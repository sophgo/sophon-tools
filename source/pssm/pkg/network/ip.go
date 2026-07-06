// Package network 提供网卡 IP 查询/配置与 NAT 规则管理。
package network

import (
	"errors"
	"net"
	"os/exec"
	"regexp"
	"strings"

	"ssm/pkg/system"
)

// deviceNameRe 限定网卡名为字母数字加 .:_- 的常见 Linux 接口名。
var deviceNameRe = regexp.MustCompile(`^[A-Za-z0-9._:-]+$`)

// lookPath 与 runCmd 为包级变量，便于测试注入。
var lookPath = exec.LookPath
var runCmd = system.RunCommandArgs

// NetCard 网卡信息。
type NetCard struct {
	Name       string   `json:"name"`
	IPs        []string `json:"ips"`
	MAC        string   `json:"mac"`
	State      string   `json:"state"`
	IsLoopback bool     `json:"isLoopback"`
}

// GetNetCards 通过解析 "ip addr" 输出返回网卡列表。
// 仅返回物理网卡（en/eth/bond/em/p6 前缀），排除 lo/dummy/sit/wlan/docker 等虚拟接口。
func GetNetCards() ([]NetCard, error) {
	outStr, errStr, err := system.RunCommandArgs("ip", "addr")
	if err != nil {
		return nil, err
	}
	if errStr != "" && outStr == "" {
		return nil, errors.New(errStr)
	}
	return filterPhysicalNetCards(parseIPAddr(outStr)), nil
}

// isPhysicalIf 对齐 bmssm getNetInfo：仅收 en/eth/bond/em/p6 前缀物理网卡，
// 排除 lo/dummy0/sit0/wlan0/docker0 等虚拟/环回接口。
func isPhysicalIf(name string) bool {
	return strings.HasPrefix(name, "en") ||
		strings.HasPrefix(name, "eth") ||
		strings.HasPrefix(name, "bond") ||
		strings.HasPrefix(name, "em") ||
		strings.HasPrefix(name, "p6")
}

// filterPhysicalNetCards 从网卡列表中过滤出物理网卡。
func filterPhysicalNetCards(cards []NetCard) []NetCard {
	var out []NetCard
	for _, c := range cards {
		if isPhysicalIf(c.Name) {
			out = append(out, c)
		}
	}
	if out == nil {
		out = []NetCard{}
	}
	return out
}

// parseIPAddr 解析 "ip addr" 命令输出。
// 格式示例：
// 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc ...
//
//	link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
//	inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
func parseIPAddr(output string) []NetCard {
	var cards []NetCard
	var current *NetCard

	reIface := regexp.MustCompile(`^\d+:\s+(\S+?)(@\S+)?:\s+<(.+?)>`)
	reMAC := regexp.MustCompile(`link/ether\s+([0-9a-fA-F:]+)`)
	reInet := regexp.MustCompile(`inet\s+([0-9.]+)/(\d+)`)
	reInet6 := regexp.MustCompile(`inet6\s+([0-9a-fA-F:]+)/(\d+)`)

	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		if m := reIface.FindStringSubmatch(line); m != nil {
			if current != nil {
				cards = append(cards, *current)
			}
			name := m[1]
			stateStr := m[3]
			current = &NetCard{
				Name:       name,
				State:      classifyState(stateStr),
				IsLoopback: name == "lo",
			}
			continue
		}

		if current == nil {
			continue
		}

		if m := reMAC.FindStringSubmatch(line); m != nil {
			current.MAC = m[1]
			continue
		}

		if m := reInet.FindStringSubmatch(line); m != nil {
			current.IPs = append(current.IPs, strings.TrimSpace(m[1])+"/"+m[2])
			continue
		}

		if m := reInet6.FindStringSubmatch(line); m != nil {
			current.IPs = append(current.IPs, strings.TrimSpace(m[1])+"/"+m[2])
			continue
		}
	}

	if current != nil {
		cards = append(cards, *current)
	}

	return cards
}

// classifyState 将 ip addr flags 映射为 UP/DOWN/UNKNOWN。
func classifyState(flags string) string {
	if strings.Contains(flags, "UP") {
		return "UP"
	}
	if strings.Contains(flags, "DOWN") {
		return "DOWN"
	}
	return "UNKNOWN"
}

// findBmSetIp 在常见路径中查找 bm_set_ip 工具。
// 找不到返回错误 "bm_set_ip tool not found, please install pbm_set_ip"。
func findBmSetIp() (string, error) {
	paths := []string{"bm_set_ip", "/usr/sbin/bm_set_ip", "/usr/local/bin/bm_set_ip"}
	for _, p := range paths {
		found, err := lookPath(p)
		if err == nil {
			return found, nil
		}
	}
	return "", errors.New("bm_set_ip tool not found, please install pbm_set_ip")
}

// SetStaticIP 配置静态 IP 使用 bm_set_ip 工具（参数化执行，防注入）。
func SetStaticIP(device, ip, mask, gateway, dns string) error {
	if !deviceNameRe.MatchString(device) {
		return errors.New("invalid device name")
	}
	if net.ParseIP(ip) == nil {
		return errors.New("invalid ip address")
	}
	if net.ParseIP(mask) == nil {
		return errors.New("invalid netmask")
	}
	if gateway != "" && net.ParseIP(gateway) == nil {
		return errors.New("invalid gateway")
	}
	if dns != "" && net.ParseIP(dns) == nil {
		return errors.New("invalid dns address")
	}

	bmPath, err := findBmSetIp()
	if err != nil {
		return err
	}

	// gateway/dns 为空时传空字符串
	gw := gateway
	ds := dns

	_, errStr, err := runCmd(bmPath, device, ip, mask, gw, ds)
	if err != nil {
		return errors.New(errStr + ": " + err.Error())
	}
	if errStr != "" {
		return errors.New(errStr)
	}
	return nil
}

// SetDynamicIP 配置 DHCP 使用 bm_set_ip 工具（参数化执行，防注入）。
func SetDynamicIP(device string) error {
	if !deviceNameRe.MatchString(device) {
		return errors.New("invalid device name")
	}

	bmPath, err := findBmSetIp()
	if err != nil {
		return err
	}

	_, errStr, err := runCmd(bmPath, device, "dhcp", "")
	if err != nil {
		return errors.New(errStr + ": " + err.Error())
	}
	if errStr != "" {
		return errors.New(errStr)
	}
	return nil
}