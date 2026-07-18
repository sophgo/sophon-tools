// detect.go
package firewall

import (
	"regexp"
	"sort"
	"strconv"
	"strings"

	"bmssm/logger"
)

// EnvIssue 单个环境问题 + 修复指引。
type EnvIssue struct {
	Check   string `json:"check"`
	Message string `json:"message"`
	FixCmd  string `json:"fix_cmd"`
}

// EnvResult 环境检查结果。
type EnvResult struct {
	OK     bool       `json:"ok"`
	Issues []EnvIssue `json:"issues"`
}

// CheckEnvironment 检查防火墙功能所需环境。任一不满足返 OK=false。绝不 panic。
func CheckEnvironment(r CommandRunner) EnvResult {
	res := EnvResult{OK: true}

	// iptables 本体
	if _, _, err := r.Run("iptables", "-V"); err != nil {
		res.OK = false
		res.Issues = append(res.Issues, EnvIssue{
			Check:   "iptables",
			Message: "未找到 iptables 命令",
			FixCmd:  "apt-get install -y iptables",
		})
	}
	// iptables-save / iptables-restore（iptables-persistent 提供）
	if _, _, err := r.Run("iptables-save", "-V"); err != nil {
		res.OK = false
		res.Issues = append(res.Issues, EnvIssue{
			Check:   "iptables-save",
			Message: "未找到 iptables-save，缺少 iptables-persistent",
			FixCmd:  "apt-get install -y iptables-persistent",
		})
	}
	if _, _, err := r.Run("iptables-restore", "-V"); err != nil {
		res.OK = false
		res.Issues = append(res.Issues, EnvIssue{
			Check:   "iptables-restore",
			Message: "未找到 iptables-restore，缺少 iptables-persistent",
			FixCmd:  "apt-get install -y iptables-persistent",
		})
	}
	// ufw：installed 且 active → 拒绝
	if out, _, err := r.Run("ufw", "status"); err == nil {
		if strings.Contains(out, "Status: active") {
			res.OK = false
			res.Issues = append(res.Issues, EnvIssue{
				Check:   "ufw",
				Message: "检测到 ufw 已启用，会与防火墙 filter 规则冲突。请先禁用 ufw 或卸载；若用 ufw 管理防火墙，请勿使用本功能。",
				FixCmd:  "ufw disable",
			})
		}
	}
	// rules.v4 可写
	_, persistPath, _, _ := FirewallConfig()
	if persistPath != "" {
		if _, _, err := r.Run("test", "-w", persistPath); err != nil {
			// test -w 退出码非零=不可写；但目录可能不存在也算不可写
			res.OK = false
			res.Issues = append(res.Issues, EnvIssue{
				Check:   "rules_v4",
				Message: "持久化文件 " + persistPath + " 不可写",
				FixCmd:  "mkdir -p /etc/iptables && touch " + persistPath,
			})
		}
	}
	if !res.OK {
		logger.Warn("firewall environment check failed: %d issues", len(res.Issues))
	}
	return res
}

// ss 行正则：捕获 Local Address:Port 和 Process 名
var ssLineRe = regexp.MustCompile(`LISTEN\s+\d+\s+\d+\s+\S+:(\d+)\s+\S+\s+users:\(\(\"(\w+)\"`)

// netstat 行正则：捕获 Local Address:Port 和 PID/Process 名
// netstat -tlnp 输出格式：tcp  0  0 0.0.0.0:22  0.0.0.0:*  LISTEN  1234/sshd
var netstatLineRe = regexp.MustCompile(`^tcp6?\s+\d+\s+\d+\s+\S+:(\d+)\s+\S+\s+LISTEN\s+\d+/(\S+)`)

// parseListenPorts 用给定正则解析监听输出，筛选进程名通过 nameFilter 的端口，去重排序。
func parseListenPorts(out string, re *regexp.Regexp, nameFilter func(string) bool) []int {
	var ports []int
	for _, line := range strings.Split(out, "\n") {
		m := re.FindStringSubmatch(line)
		if len(m) != 3 {
			continue
		}
		if !nameFilter(m[2]) {
			continue
		}
		p, e := strconv.Atoi(m[1])
		if e == nil && p > 0 && p < 65536 {
			ports = append(ports, p)
		}
	}
	return dedupSortPorts(ports)
}

// DetectSSHPorts 动态探测 sshd 监听的所有端口（可能多端口）。ss 不可用回退 netstat。不硬编码。
func DetectSSHPorts(r CommandRunner) []int {
	out, _, err := r.Run("ss", "-tlnpH")
	re := ssLineRe
	if err != nil {
		// 回退 netstat
		out, _, err = r.Run("netstat", "-tlnp")
		if err != nil {
			return nil
		}
		re = netstatLineRe
	}
	return parseListenPorts(out, re, func(name string) bool { return name == "sshd" })
}

// DetectSophliteosPorts 探测 sophliteos 进程监听端口（可被 config 覆盖，此处探测）。
func DetectSophliteosPorts(r CommandRunner) []int {
	out, _, err := r.Run("ss", "-tlnpH")
	re := ssLineRe
	if err != nil {
		out, _, err = r.Run("netstat", "-tlnp")
		if err != nil {
			return nil
		}
		re = netstatLineRe
	}
	return parseListenPorts(out, re, func(name string) bool { return strings.Contains(name, "sophliteos") })
}

// ProtectPorts 合并 SSH + sophliteos + config 额外端口，去重排序。每次 apply 前调。
func ProtectPorts(r CommandRunner) []int {
	ssh := DetectSSHPorts(r)
	soph := DetectSophliteosPorts(r)
	_, _, _, extra := FirewallConfig()
	all := append(append(ssh, soph...), extra...)
	return dedupSortPorts(all)
}

func dedupSortPorts(ports []int) []int {
	seen := map[int]bool{}
	var out []int
	for _, p := range ports {
		if !seen[p] {
			seen[p] = true
			out = append(out, p)
		}
	}
	sort.Ints(out)
	return out
}
