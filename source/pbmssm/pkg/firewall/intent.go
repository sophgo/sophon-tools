package firewall

import (
	"encoding/json"
	"fmt"
	"net"
	"strconv"
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
	Table   string   // 默认 "filter"
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
			if _, n, err := net.ParseCIDR(p.Src); err != nil || n == nil {
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
		r2 := []string{"-p", "tcp", "--dport", strconv.Itoa(p.Port), "-m", "recent", "--update", "--seconds", strconv.Itoa(sec), "--hitcount", strconv.Itoa(p.Rate+1), "--name", rn, "-j", "DROP", "-m", "comment", "--comment", c}
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
		args := []string{"-p", "icmp", "-j", j, "-m", "comment", "--comment", c}
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
	return n, nil
}

func wrapInvalid(e error) error { return fmt.Errorf("%w: %v", ErrInvalidInput, e) }
