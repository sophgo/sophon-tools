package systemd

import (
	"fmt"
	"path"
	"regexp"
	"strconv"
	"strings"

	"bmssm/config"
)

// ErrProtected 操作被关键服务保护拒绝。
var ErrProtected = fmt.Errorf("service is protected")

// ErrInvalidUnitName 表示 unit 名称格式不合法。
var ErrInvalidUnitName = fmt.Errorf("invalid unit name")

// ErrInvalidAction 表示 action 不在允许列表中。
var ErrInvalidAction = fmt.Errorf("invalid action")

var unitNameRe = regexp.MustCompile(`^[a-zA-Z0-9@:_.-]+$`)

// ValidateUnitName 校验 unit 名（防注入）；允许字母数字 @ : _ . - *。
func ValidateUnitName(name string) error {
	if !unitNameRe.MatchString(name) {
		return fmt.Errorf("%w: %q", ErrInvalidUnitName, name)
	}
	return nil
}

// ProtectedMatch 判断 unit 是否命中保护名单（支持 * 和 ? glob，按 path.Match）。
func ProtectedMatch(name string, patterns []string) bool {
	for _, p := range patterns {
		if ok, err := path.Match(p, name); err == nil && ok {
			return true
		}
	}
	return false
}

// DefaultProtectedServices 默认关键服务名单（设备实证 .185/.57 确认）。
var DefaultProtectedServices = []string{
	"bmssm.service",
	"sophliteos.service",
	"nginx.service",
	"ssh.service",
	"sshd.service",
	"networking.service",
	"systemd-networkd.service",
	"systemd-resolved.service",
	"networkd-dispatcher.service",
	"dbus.service",
	"systemd-journald.service",
	"systemd-logind.service",
	"systemd-udevd.service",
	"systemd-timesyncd.service",
	"getty@*.service",
	"serial-getty@*.service",
	// 功能关键（禁用虽不开机失败，但会让设备失去核心功能）：
	"docker.service",           // 容器化 AI 推理负载
	"containerd.service",       // docker 依赖
	"upd72020x-fwload.service", // USB3 主控固件
	"apparmor.service",         // 安全框架，snap/AppArmor 依赖
	"ubuntu-fan.service",       // Fan overlay 网络
	// Sophon 厂商硬件/运行时（一个通配覆盖全部 bm 开头服务）
	"bm*.service",
}

// ProtectedList 从配置读取保护名单；配置缺省时用 DefaultProtectedServices。
// 用户可在 bmssm.yaml 加 systemd.protected: [...] 覆盖。
func ProtectedList() []string {
	config.Conf.RLock()
	defer config.Conf.RUnlock()
	v := config.Conf.GetViper()
	if v == nil {
		return DefaultProtectedServices
	}
	list := v.GetStringSlice("systemd.protected")
	if len(list) == 0 {
		return DefaultProtectedServices
	}
	return list
}

// listUnitRow is a parsed row of `systemctl list-units --plain` text output.
type listUnitRow struct {
	Unit        string
	Load        string
	Active      string
	Sub         string
	Description string
}

// ParseListUnits 解析 `systemctl list-units --type=service --all --no-pager --plain` 文本输出。
// 跳过表头("UNIT ...")与页脚("N loaded units listed.")：它们的首字段不以 .service 结尾。
func ParseListUnits(content string) []listUnitRow {
	var out []listUnitRow
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}
		unit := fields[0]
		if !strings.HasSuffix(unit, ".service") {
			continue
		}
		row := listUnitRow{
			Unit:   unit,
			Load:   fields[1],
			Active: fields[2],
			Sub:    fields[3],
		}
		if len(fields) > 4 {
			row.Description = strings.Join(fields[4:], " ")
		}
		out = append(out, row)
	}
	return out
}

// ParseListUnitFiles 解析 `systemctl list-unit-files --type=service --no-pager --plain` 输出，
// 返回 unit 名 → enabled 状态（enabled/disabled/static/masked）。
func ParseListUnitFiles(content string) map[string]string {
	out := make(map[string]string)
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		unit := fields[0]
		if !strings.HasSuffix(unit, ".service") {
			continue // 跳过表头/页脚（"UNIT FILE ..."、"N unit files listed."）
		}
		out[unit] = fields[1]
	}
	return out
}

// ParseBlame 解析 `systemd-analyze blame` 输出（行如 "8.123s foo.service"），限 200 项。
func ParseBlame(content string) []BlameItem {
	var out []BlameItem
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		t := strings.TrimSuffix(fields[0], "s")
		secs, err := strconv.ParseFloat(t, 64)
		if err != nil {
			continue
		}
		out = append(out, BlameItem{Time: secs, Unit: fields[1]})
		if len(out) >= 200 {
			break
		}
	}
	return out
}

var (
	kernelRe = regexp.MustCompile(`(\d+\.?\d*)s\s*\(kernel\)`)
	userRe   = regexp.MustCompile(`(\d+\.?\d*)s\s*\(userspace\)`)
	totalRe  = regexp.MustCompile(`=\s*(\d+\.?\d*)s`)
)

// ParseAnalyzeTime 解析 `systemd-analyze time` 输出，返回 kernel/userspace/total 秒。
func ParseAnalyzeTime(content string) (kernel, userspace, total float64) {
	if m := kernelRe.FindStringSubmatch(content); m != nil {
		kernel, _ = strconv.ParseFloat(m[1], 64)
	}
	if m := userRe.FindStringSubmatch(content); m != nil {
		userspace, _ = strconv.ParseFloat(m[1], 64)
	}
	if m := totalRe.FindStringSubmatch(content); m != nil {
		total, _ = strconv.ParseFloat(m[1], 64)
	}
	return
}
