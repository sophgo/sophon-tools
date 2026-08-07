package firewall

import (
	"encoding/json"
	"fmt"
	"net"
	"strconv"
	"strings"
)

type IntentType string

const (
	IntentPortAllow   IntentType = "port_allow"
	IntentPortDeny    IntentType = "port_deny"
	IntentRateLimit   IntentType = "rate_limit"
	IntentIPWhitelist IntentType = "ip_whitelist"
	IntentIPBlacklist IntentType = "ip_blacklist"
	IntentICMP        IntentType = "icmp"
)

// Intent 高层意图（存 SQLite 的期望状态）。
type Intent struct {
	ID      int64      `json:"id"`
	Type    IntentType `json:"type"`
	Params  string     `json:"params"` // JSON
	Enabled bool       `json:"enabled"`
}

// IptablesRule 一条 iptables 规则的参数化表示（不经 shell）。
type IptablesRule struct {
	Table   string // 默认 "filter"
	Chain   string
	Args    []string // 完整参数（含 -m comment --comment）
	Comment string   // 注释值（便于 rebuild 按注释定位）
}

func (it Intent) comment() string { return fmt.Sprintf("%s %d", CommentIntentPrefix, it.ID) }

func (it Intent) recentName() string { return fmt.Sprintf("fw%dl%d", len(CommentIntentPrefix), it.ID) }

func (it Intent) Validate() error {
	switch it.Type {
	case IntentPortAllow, IntentPortDeny:
		var p struct {
			Proto string `json:"proto"`
			Port  int    `json:"port"`
			Src   string `json:"src"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return wrapInvalid(err)
		}
		if p.Proto != "tcp" && p.Proto != "udp" {
			return wrapInvalid(fmt.Errorf("proto must be tcp/udp"))
		}
		if p.Port < 1 || p.Port > 65535 {
			return wrapInvalid(fmt.Errorf("port out of range"))
		}
		if p.Src != "" {
			if _, err := parseIPv4CIDR(p.Src); err != nil {
				return wrapInvalid(fmt.Errorf("bad src cidr"))
			}
		}
	case IntentRateLimit:
		var p struct {
			Port int    `json:"port"`
			Rate int    `json:"rate"`
			Per  string `json:"per"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return wrapInvalid(err)
		}
		if p.Port < 1 || p.Port > 65535 {
			return wrapInvalid(fmt.Errorf("port out of range"))
		}
		if p.Rate < 1 {
			return wrapInvalid(fmt.Errorf("rate must >=1"))
		}
		if p.Per != "second" && p.Per != "minute" {
			return wrapInvalid(fmt.Errorf("per must be second/minute"))
		}
	case IntentIPWhitelist, IntentIPBlacklist:
		var p struct {
			CIDR string `json:"cidr"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return wrapInvalid(err)
		}
		if _, err := parseIPv4CIDR(p.CIDR); err != nil {
			return wrapInvalid(err)
		}
	case IntentICMP:
		var p struct {
			Allow bool `json:"allow"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return wrapInvalid(err)
		}
	default:
		return wrapInvalid(fmt.Errorf("unknown intent type: %s", it.Type))
	}
	return nil
}

func (it Intent) Translate() ([]IptablesRule, error) {
	if err := it.Validate(); err != nil {
		return nil, err
	}
	c := it.comment()
	switch it.Type {
	case IntentPortAllow, IntentPortDeny:
		var p struct {
			Proto string `json:"proto"`
			Port  int    `json:"port"`
			Src   string `json:"src"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		args := []string{"-p", p.Proto}
		if p.Src != "" {
			args = append(args, "-s", p.Src)
		}
		args = append(args, "--dport", strconv.Itoa(p.Port), "-j")
		if it.Type == IntentPortAllow {
			args = append(args, "ACCEPT")
		} else {
			args = append(args, "DROP")
		}
		args = append(args, "-m", "comment", "--comment", c)
		return []IptablesRule{{Table: "filter", Chain: "INPUT", Args: args, Comment: c}}, nil
	case IntentRateLimit:
		var p struct {
			Port int    `json:"port"`
			Rate int    `json:"rate"`
			Per  string `json:"per"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		sec := 1
		if p.Per == "minute" {
			sec = 60
		}
		rn := it.recentName()
		r1 := []string{"-p", "tcp", "--dport", strconv.Itoa(p.Port), "-m", "recent", "--set", "--name", rn, "-m", "comment", "--comment", c}
		r2 := []string{"-p", "tcp", "--dport", strconv.Itoa(p.Port), "-m", "recent", "--update", "--seconds", strconv.Itoa(sec), "--hitcount", strconv.Itoa(p.Rate + 1), "--name", rn, "-j", "DROP", "-m", "comment", "--comment", c}
		return []IptablesRule{
			{Table: "filter", Chain: "INPUT", Args: r1, Comment: c},
			{Table: "filter", Chain: "INPUT", Args: r2, Comment: c},
		}, nil
	case IntentIPWhitelist, IntentIPBlacklist:
		var p struct {
			CIDR string `json:"cidr"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		j := "ACCEPT"
		if it.Type == IntentIPBlacklist {
			j = "DROP"
		}
		args := []string{"-s", p.CIDR, "-j", j, "-m", "comment", "--comment", c}
		return []IptablesRule{{Table: "filter", Chain: "INPUT", Args: args, Comment: c}}, nil
	case IntentICMP:
		var p struct {
			Allow bool `json:"allow"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		j := "DROP"
		if p.Allow {
			j = "ACCEPT"
		}
		// 只作用于 ICMP 回显（echo request/reply），不误伤 SSH/PMTU 依赖的
		// 分片、destination-unreachable 等"非回显"ICMP——那些类型不携带
		// 完整传输头，不受 -p icmp 外的端口规则约束，被 DROP 会挂起 SSH 大块。
		args := []string{"-p", "icmp", "--icmp-type", "8", "-j", j, "-m", "comment", "--comment", c}
		return []IptablesRule{{Table: "filter", Chain: "INPUT", Args: args, Comment: c}}, nil
	}
	return nil, wrapInvalid(fmt.Errorf("unreachable"))
}

func parseIPv4CIDR(s string) (*net.IPNet, error) {
	ip, n, err := net.ParseCIDR(s)
	if err != nil || n == nil {
		return nil, fmt.Errorf("bad cidr")
	}
	if ip.To4() == nil {
		return nil, fmt.Errorf("only ipv4 supported")
	}
	// 拒绝 IPv4-mapped IPv6（::ffff:x.x.x.x/x）：To4() 非 nil 但语义上是 IPv6 语法，
	// iptables 上的行为不确定，且会绕过 isBroadMatch 的 bits==32 判定（F1 绕过）。
	if strings.Contains(s, ":") {
		return nil, fmt.Errorf("only ipv4 supported")
	}
	return n, nil
}

// isBroadMatch 判断 src 是否覆盖所有 IPv4 源：空（缺省=匹配全部）、0.0.0.0/0、0.0.0.0。
// 空字符串必须视为全网段——Translate 对空 src 不输出 -s 参数，等价 -s 0.0.0.0/0。
// 前缀 /0 与 /1 均视为危险（/1 覆盖半个地址空间，几乎必含管理机/运维终端）。
func isBroadMatch(src string) bool {
	if src == "" || src == "0.0.0.0/0" || src == "0.0.0.0" {
		return true
	}
	// 归一化后比较：0.0.0.0/0 的 IPNet 掩码位为 0，覆盖全部。
	if ip, n, err := net.ParseCIDR(src); err == nil && n != nil {
		ones, bits := n.Mask.Size()
		if ip.To4() != nil && bits == 32 && ones <= 1 {
			return true
		}
		// IPv4-mapped IPv6（::ffff:x.x.x.x/x）：ip.To4() 非 nil 但 bits=128。
		// 归一化后按 IPv4 判定：mapped 的 /0、/1 同样覆盖全网段（F1 绕过）。
		if ip4 := ip.To4(); ip4 != nil {
			return ones <= 1
		}
	}
	return false
}

// isBroadCidr 判断 CIDR 是否覆盖全部或近乎全部 IPv4（用于 ip_blacklist 等无端口维度意图）。
// 与 isBroadMatch 语义一致，单独命名以强调其适用范围。
func isBroadCidr(cidr string) bool { return isBroadMatch(cidr) }

// CheckProtectDeny 拒绝屏蔽保护端口/全网段保护主机的意图。返回 ErrInvalidInput。
// 覆盖三种绕过路径：
//  1. port_deny + 全网段 src（空/0.0.0.0/0/0.0.0.0）且端口命中 protect → 拒绝
//  2. ip_blacklist + 全网段 cidr → 拒绝（黑名单无端口维度，全内网封禁即锁死保护主机）
//  3. rate_limit 作用于保护端口 → 拒绝（recent+DROP 超限丢弃，等效拒绝）
//
// 与 Translate 语义对齐：src 缺省即匹配所有源，绝非"仅匹配自己"。
//
// 已知边界（S1/S2，前端已有提示）：特定源网段（如 10/8、172.16/12、192.168/16）的拒绝
// 仍会合法通过守卫——企业内网管理机常落这些网段，可能锁死管理通道；且 protect 端口依赖
// 实时探测（ss/netstat），探测不到时（如 sshd 以非标准进程名运行、systemd socket 激活）
// 危险规则会被放行。Rebuild 不再有旧 Apply 的"临时放行 + 回滚计时器"兜底，配置需谨慎。
func CheckProtectDeny(it *Intent, protect []int) error {
	if len(protect) == 0 {
		return nil
	}
	switch it.Type {
	case IntentPortDeny:
		var p struct {
			Port int    `json:"port"`
			Src  string `json:"src"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil // params 格式不匹配，由 Validate 负责报错
		}
		if isBroadMatch(p.Src) {
			for _, port := range protect {
				if p.Port == port {
					return fmt.Errorf("%w: 不能拒绝保护端口 %d 的全网段流量", ErrInvalidInput, port)
				}
			}
		}
	case IntentIPBlacklist:
		var p struct {
			CIDR string `json:"cidr"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil
		}
		if isBroadMatch(p.CIDR) {
			return fmt.Errorf("%w: 不能将保护主机加入全网段黑名单", ErrInvalidInput)
		}
	case IntentRateLimit:
		var p struct {
			Port int `json:"port"`
		}
		if err := json.Unmarshal([]byte(it.Params), &p); err != nil {
			return nil
		}
		for _, port := range protect {
			if p.Port == port {
				return fmt.Errorf("%w: 不能对保护端口 %d 设置速率限制（可能丢弃管理连接）", ErrInvalidInput, port)
			}
		}
	}
	return nil
}

func wrapInvalid(e error) error { return fmt.Errorf("%w: %v", ErrInvalidInput, e) }
