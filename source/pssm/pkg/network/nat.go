package network

import (
	"errors"
	"fmt"
	"net"
	"regexp"
	"strconv"
	"strings"

	"ssm/pkg/system"
)

// NatRule NAT 规则请求。
type NatRule struct {
	Direction string `json:"direction"`           // "in" (PREROUTING) or "out" (POSTROUTING)
	Operation string `json:"op"`                  // "append" or "delete"
	Src       string `json:"src"`                  // 源/目标 IP
	Dst       string `json:"dst"`                  // 目标 IP
	SrcPort   string `json:"srcPort,omitempty"`
	DstPort   string `json:"dstPort,omitempty"`
	Protocol  string `json:"protocol,omitempty"`  // tcp/udp
	Flags     string `json:"flags,omitempty"`
}

// safeTokenRe 限定白名单字符（字母数字下划线短横）。
var safeTokenRe = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// Validate 校验 NatRule 所有用户输入字段，非法返回错误。
func (rule NatRule) Validate() error {
	if rule.Direction != "in" && rule.Direction != "out" {
		return errors.New("direction must be 'in' or 'out'")
	}
	if rule.Operation != "append" && rule.Operation != "delete" {
		return errors.New("op must be 'append' or 'delete'")
	}
	if rule.Src != "" && net.ParseIP(rule.Src) == nil {
		return fmt.Errorf("invalid src ip: %s", rule.Src)
	}
	if rule.Dst != "" && net.ParseIP(rule.Dst) == nil {
		return fmt.Errorf("invalid dst ip: %s", rule.Dst)
	}
	if rule.SrcPort != "" {
		if err := validatePort(rule.SrcPort); err != nil {
			return fmt.Errorf("invalid srcPort: %w", err)
		}
	}
	if rule.DstPort != "" {
		if err := validatePort(rule.DstPort); err != nil {
			return fmt.Errorf("invalid dstPort: %w", err)
		}
	}
	if rule.Protocol != "" {
		p := rule.Protocol
		if !safeTokenRe.MatchString(p) {
			return fmt.Errorf("invalid protocol: %s", p)
		}
		// 限定为 tcp/udp 常见值
		lo := strings.ToLower(p)
		if lo != "tcp" && lo != "udp" && lo != "icmp" {
			return fmt.Errorf("unsupported protocol: %s", p)
		}
	}
	if rule.Flags != "" {
		// flags 为可选附加 iptables 参数，限定安全字符集
		if !safeTokenRe.MatchString(rule.Flags) {
			return fmt.Errorf("invalid flags: %s", rule.Flags)
		}
	}
	return nil
}

// validatePort 校验端口为 1-65535 数字。
func validatePort(s string) error {
	n, err := strconv.Atoi(s)
	if err != nil {
		return errors.New("not a number")
	}
	if n < 1 || n > 65535 {
		return errors.New("out of range 1-65535")
	}
	return nil
}

// buildArgs 构造 iptables 参数切片（不经 shell）。
func (rule NatRule) buildArgs() []string {
	chain := "PREROUTING"
	if rule.Direction == "out" {
		chain = "POSTROUTING"
	}

	op := "-A"
	if rule.Operation == "delete" {
		op = "-D"
	}

	args := []string{"-t", "nat", op, chain}

	if rule.Dst != "" {
		args = append(args, "-d", rule.Dst)
	}
	if rule.Protocol != "" {
		args = append(args, "-p", strings.ToLower(rule.Protocol))
	}
	if rule.DstPort != "" {
		args = append(args, "--dport", rule.DstPort)
	}
	if rule.Src != "" {
		args = append(args, "-j", "DNAT", "--to-destination", rule.Src)
		if rule.SrcPort != "" {
			args[len(args)-1] = rule.Src + ":" + rule.SrcPort
		}
	}
	if rule.Flags != "" {
		args = append(args, rule.Flags)
	}
	return args
}

// AddNATRule 添加或删除 NAT 规则（参数化执行，防注入）。
func AddNATRule(rule NatRule) error {
	if err := rule.Validate(); err != nil {
		return err
	}
	args := rule.buildArgs()
	_, errStr, err := system.RunCommandArgs("iptables", args...)
	if err != nil {
		if errStr != "" {
			return errors.New(errStr)
		}
		return err
	}
	return nil
}

// GetNATRules 返回当前 NAT 表规则列表。
func GetNATRules() ([]string, error) {
	outStr, _, err := system.RunCommandArgs("iptables", "-t", "nat", "-L", "-n", "--line-number")
	if err != nil {
		return nil, err
	}
	return strings.Split(outStr, "\n"), nil
}
