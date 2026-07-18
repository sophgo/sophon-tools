// docker_user.go
package firewall

import (
	"encoding/json"
	"fmt"
	"strconv"
)

type DockerScene string

const (
	DockerExtToContainer DockerScene = "ext_to_container"
	DockerContainerToExt DockerScene = "container_to_ext"
)

type DockerRule struct {
	ID      int64       `json:"id"`
	Scene   DockerScene `json:"scene"`
	Params  string      `json:"params"`
	Enabled bool        `json:"enabled"`
}

func (d DockerRule) comment() string { return fmt.Sprintf("%s %d", CommentDockerPrefix, d.ID) }

func (d DockerRule) Validate() error {
	switch d.Scene {
	case DockerExtToContainer:
		var p struct {
			ContainerPort int    `json:"container_port"`
			Proto         string `json:"proto"`
			Src           string `json:"src"`
			Action        string `json:"action"`
		}
		if err := json.Unmarshal([]byte(d.Params), &p); err != nil {
			return wrapInvalid(err)
		}
		if p.ContainerPort < 1 || p.ContainerPort > 65535 {
			return wrapInvalid(fmt.Errorf("bad port"))
		}
		if p.Proto != "tcp" && p.Proto != "udp" {
			return wrapInvalid(fmt.Errorf("proto must tcp/udp"))
		}
		if p.Src != "" {
			if _, err := parseIPv4CIDR(p.Src); err != nil {
				return wrapInvalid(err)
			}
		}
		if p.Action != "allow" && p.Action != "deny" {
			return wrapInvalid(fmt.Errorf("action must allow/deny"))
		}
	case DockerContainerToExt:
		var p struct {
			ContainerCIDR string `json:"container_cidr"`
			DstExcept     string `json:"dst_except"`
			Action        string `json:"action"`
		}
		if err := json.Unmarshal([]byte(d.Params), &p); err != nil {
			return wrapInvalid(err)
		}
		if _, err := parseIPv4CIDR(p.ContainerCIDR); err != nil {
			return wrapInvalid(err)
		}
		if p.DstExcept != "" {
			if _, err := parseIPv4CIDR(p.DstExcept); err != nil {
				return wrapInvalid(err)
			}
		}
		if p.Action != "allow" && p.Action != "deny" {
			return wrapInvalid(fmt.Errorf("action must allow/deny"))
		}
	default:
		return wrapInvalid(fmt.Errorf("unknown scene: %s", d.Scene))
	}
	return nil
}

func (d DockerRule) Translate() ([]IptablesRule, error) {
	if err := d.Validate(); err != nil {
		return nil, err
	}
	c := d.comment()
	switch d.Scene {
	case DockerExtToContainer:
		var p struct {
			ContainerPort int    `json:"container_port"`
			Proto         string `json:"proto"`
			Src           string `json:"src"`
			Action        string `json:"action"`
		}
		if err := json.Unmarshal([]byte(d.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		port := strconv.Itoa(p.ContainerPort)
		if p.Action == "allow" {
			// 放行指定源 RETURN，拒绝其他源 DROP（两条，按顺序）
			r1 := []string{"-p", p.Proto, "--dport", port, "-s", p.Src, "-j", "RETURN", "-m", "comment", "--comment", c}
			r2 := []string{"-p", p.Proto, "--dport", port, "-j", "DROP", "-m", "comment", "--comment", c}
			return []IptablesRule{
				{Table: "filter", Chain: "DOCKER-USER", Args: r1, Comment: c},
				{Table: "filter", Chain: "DOCKER-USER", Args: r2, Comment: c},
			}, nil
		}
		// deny: 拒绝指定源
		r := []string{"-p", p.Proto, "--dport", port, "-s", p.Src, "-j", "DROP", "-m", "comment", "--comment", c}
		return []IptablesRule{{Table: "filter", Chain: "DOCKER-USER", Args: r, Comment: c}}, nil
	case DockerContainerToExt:
		var p struct {
			ContainerCIDR string `json:"container_cidr"`
			DstExcept     string `json:"dst_except"`
			Action        string `json:"action"`
		}
		if err := json.Unmarshal([]byte(d.Params), &p); err != nil {
			return nil, wrapInvalid(err)
		}
		j := "DROP"
		if p.Action == "allow" {
			j = "RETURN"
		}
		args := []string{"-s", p.ContainerCIDR}
		if p.DstExcept != "" {
			// iptables negation: `!` 必须作为独立 token 在 -d 之前（nft_tables 后端不接受 -d !value 的 legacy 写法）
			args = append(args, "!", "-d", p.DstExcept)
		}
		args = append(args, "-j", j, "-m", "comment", "--comment", c)
		return []IptablesRule{{Table: "filter", Chain: "DOCKER-USER", Args: args, Comment: c}}, nil
	}
	return nil, wrapInvalid(fmt.Errorf("unreachable"))
}
