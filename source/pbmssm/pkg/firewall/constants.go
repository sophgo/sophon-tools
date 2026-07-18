package firewall

import (
	"errors"
	"regexp"

	"bmssm/config"
)

// 注释标记前缀（rebuild 只删带这些前缀的规则，绝不误删用户手写/NAT/docker 自管规则）。
const (
	CommentIntentPrefix  = "bmssm-fw-intent"
	CommentDockerPrefix  = "bmssm-fw-docker"
	CommentProtectPrefix = "bmssm-fw-protect"
)

// safeTokenRe 白名单：字母数字下划线点冒号短横斜杠。用于链名/目标名/表名/协议/CIDR等 iptables 标识符。
var safeTokenRe = regexp.MustCompile(`^[A-Za-z0-9_.:\/-]+$`)

// sentinel errors，controller 用 errors.Is 区分。
var (
	ErrInvalidInput = errors.New("invalid input")
	ErrEnvironment  = errors.New("environment not satisfied")
	ErrRiskDetected = errors.New("risk detected")
	ErrPendingApply = errors.New("pending apply exists")
)

// FirewallConfig 读取 firewall 配置节，未加载时返默认值（绝不 panic）。
func FirewallConfig() (enabled bool, persistPath string, rollbackSec int, extraProtect []int) {
	enabled = true
	persistPath = "/etc/iptables/rules.v4"
	rollbackSec = 300
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()
	if v == nil {
		return
	}
	if v.IsSet("firewall.enabled") {
		enabled = v.GetBool("firewall.enabled")
	}
	if v.IsSet("firewall.persistPath") {
		persistPath = v.GetString("firewall.persistPath")
	}
	if v.IsSet("firewall.rollbackSeconds") {
		rollbackSec = v.GetInt("firewall.rollbackSeconds")
	}
	if v.IsSet("firewall.protectPorts") {
		for _, p := range v.GetIntSlice("firewall.protectPorts") {
			extraProtect = append(extraProtect, p)
		}
	}
	return
}
