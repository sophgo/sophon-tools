// Package network 提供网卡 IP 查询/配置与 NAT 规则管理。
package network

import (
	"errors"
	"net"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	"bmssm/pkg/system"
)

// deviceNameRe 限定网卡名为字母数字加 .:_- 的常见 Linux 接口名。
var deviceNameRe = regexp.MustCompile(`^[A-Za-z0-9._:-]+$`)

// DNS 解析来源：
//   - resolvConfUpstreamPath：systemd-resolved 的真实上游 DNS（Ubuntu 等系统
//     /etc/resolv.conf 指向 stub 127.0.0.53，不是真实 DNS，需读此文件取上游）。
//   - resolvConfPath：传统 /etc/resolv.conf 回退（非 systemd-resolved 系统）。
const (
	resolvConfUpstreamPath = "/run/systemd/resolve/resolv.conf"
	resolvConfPath         = "/etc/resolv.conf"
)

// lookPath / runCmd / readFile 为包级变量，便于测试注入。
var (
	lookPath = exec.LookPath
	runCmd   = system.RunCommandArgs
	readFile = os.ReadFile
)

// NetCard 网卡信息。
//
// IPs 保留原始 "ip/prefix" 列表（兼容旧调用方）；IP/NetMask/Gateway/DNS/Dynamic
// 为 networkSetting 页面所需的扁平字段：
//   - IP/NetMask：取首个 IPv4 地址与点分掩码（解析自 ip addr）
//   - Gateway：默认路由网关（解析自 ip route，按 dev 映射）
//   - DNS：首个 nameserver（解析自 /etc/resolv.conf）
//   - Dynamic：1 表示该网卡由 dhcp 客户端托管（dhclient/udhcpc/dhcpcd 进程匹配）
type NetCard struct {
	Name       string   `json:"name"`
	IPs        []string `json:"ips"`
	MAC        string   `json:"mac"`
	State      string   `json:"state"`
	IsLoopback bool     `json:"isLoopback"`
	IP         string   `json:"ip"`
	NetMask    string   `json:"netMask"`
	Gateway    string   `json:"gateway"`
	DNS        string   `json:"dns"`
	Dynamic    int      `json:"dynamic"`
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
	cards := filterPhysicalNetCards(parseIPAddr(outStr))
	enrichNetCards(cards)
	return cards, nil
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
			ipStr := strings.TrimSpace(m[1])
			prefix := strings.TrimSpace(m[2])
			current.IPs = append(current.IPs, ipStr+"/"+prefix)
			// 取首个 IPv4 作为扁平 IP/NetMask（networkSetting 页面用）
			if current.IP == "" {
				current.IP = ipStr
				current.NetMask = prefixToNetMask(prefix)
			}
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

// prefixToNetMask 将 CIDR 前缀长度（"24"）转为点分掩码（"255.255.255.0"）。
// 非法前缀返回空串。
func prefixToNetMask(prefix string) string {
	prefixIface, err := strconv.Atoi(prefix)
	if err != nil || prefixIface < 0 || prefixIface > 32 {
		return ""
	}
	_, ipnet, err := net.ParseCIDR("0.0.0.0/" + prefix)
	if err != nil || ipnet == nil {
		return ""
	}
	return net.IP(ipnet.Mask).String()
}

// ---------------------------------------------------------------
// 网卡字段补全：gateway / dns / dynamic
// ---------------------------------------------------------------

// enrichNetCards 为每张物理网卡填充 Gateway/DNS/Dynamic（best-effort，失败留空/0）。
// loopback 不补全。所有外部命令均通过可注入的包级变量执行，便于测试。
func enrichNetCards(cards []NetCard) []NetCard {
	if len(cards) == 0 {
		return cards
	}
	gwByDev := parseDefaultGateways()
	dns := parseResolvDNS()
	dhcpLines := parseDhcpProcessLines()
	for i := range cards {
		if cards[i].IsLoopback {
			continue
		}
		if gw, ok := gwByDev[cards[i].Name]; ok {
			cards[i].Gateway = gw
		}
		// 仅对已分配 IP 的网卡填 DNS（未启用的网卡不展示 DNS）
		if dns != "" && cards[i].IP != "" {
			cards[i].DNS = dns
		}
		if isDhcpInterface(cards[i].Name, dhcpLines) {
			cards[i].Dynamic = 1
		}
	}
	return cards
}

// parseDefaultGateways 运行 "ip route"，返回 dev→默认网关 映射。
// 命令失败时返回空 map（不阻断查询）。
func parseDefaultGateways() map[string]string {
	out, _, err := runCmd("ip", "route")
	if err != nil {
		return map[string]string{}
	}
	return parseDefaultRoutes(out)
}

// parseDefaultRoutes 解析 "ip route" 输出中的 default 路由，返回 dev→gateway 映射。
// 兼容 "default via X dev Y" 与 "default dev Y"（无 via，网关留空）两种形式。
func parseDefaultRoutes(output string) map[string]string {
	out := make(map[string]string)
	re := regexp.MustCompile(`^default(?:\s+via\s+([0-9.]+))?\s+dev\s+(\S+)`)
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if m := re.FindStringSubmatch(line); m != nil {
			out[m[2]] = m[1]
		}
	}
	return out
}

// parseResolvDNS 取首个有效 nameserver。
// 优先 /run/systemd/resolve/resolv.conf（systemd-resolved 真实上游；/etc/resolv.conf
// 在 systemd-resolved 系统上是 stub 127.0.0.53，非真实 DNS），回退 /etc/resolv.conf。
func parseResolvDNS() string {
	if data, err := readFile(resolvConfUpstreamPath); err == nil {
		if dns := parseResolvConfDNS(string(data)); dns != "" {
			return dns
		}
	}
	data, err := readFile(resolvConfPath)
	if err != nil {
		return ""
	}
	return parseResolvConfDNS(string(data))
}

// parseResolvConfDNS 解析 /etc/resolv.conf 内容，返回首个 nameserver IP。
func parseResolvConfDNS(content string) string {
	re := regexp.MustCompile(`^\s*nameserver\s+([0-9.]+)`)
	for _, line := range strings.Split(content, "\n") {
		if m := re.FindStringSubmatch(line); m != nil {
			return m[1]
		}
	}
	return ""
}

// parseDhcpProcessLines 运行 "ps -eo args="，筛选出 dhcp 客户端进程行。
// 用于判断某网卡是否由 dhcp 客户端托管。命令失败返回 nil。
func parseDhcpProcessLines() []string {
	out, _, err := runCmd("ps", "-eo", "args=")
	if err != nil {
		return nil
	}
	return filterDhcpLines(out)
}

// filterDhcpLines 从 ps 输出中筛出 dhclient/udhcpc/dhcpcd 进程行。
func filterDhcpLines(output string) []string {
	var lines []string
	for _, line := range strings.Split(output, "\n") {
		if strings.Contains(line, "dhclient") ||
			strings.Contains(line, "udhcpc") ||
			strings.Contains(line, "dhcpcd") {
			lines = append(lines, line)
		}
	}
	return lines
}

// isDhcpInterface 判断 dev 是否出现在任一 dhcp 客户端进程行的参数中（整词匹配）。
func isDhcpInterface(dev string, dhcpLines []string) bool {
	if len(dhcpLines) == 0 || dev == "" {
		return false
	}
	re := regexp.MustCompile(`\b` + regexp.QuoteMeta(dev) + `\b`)
	for _, line := range dhcpLines {
		if re.MatchString(line) {
			return true
		}
	}
	return false
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

	// bm_set_ip 成功时也可能往 stderr 输出 netplan 警告（如 "gateway4 has been
	// deprecated"、"Permissions for /etc/netplan/... are too open"），这些不是错误。
	// 仅当命令非零退出（err != nil）才视为失败；exit 0 时的 stderr 警告忽略。
	_, errStr, err := runCmd(bmPath, device, ip, mask, gw, ds)
	if err != nil {
		if errStr != "" {
			return errors.New(errStr)
		}
		return err
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
		if errStr != "" {
			return errors.New(errStr)
		}
		return err
	}
	return nil
}

// IPConfig 网卡 IP 配置（IPv4 + 可选 IPv6），对应前端 IPSettings。
//   - IPType 1=静态 2=DHCP；IPv6Type 0=不配置 1=静态 2=DHCP
//   - Mask/Prefix6 为 CIDR 或点分掩码（bm_set_ip 两者皆收）
type IPConfig struct {
	Device   string
	IPType   int
	IP       string
	Mask     string
	Gateway  string
	DNS      string
	IPv6Type int
	IPv6     string
	Prefix6  string
	Gateway6 string
	DNS6     string
}

// buildBmSetIPArgs 按 bm_set_ip 用法构造位置参数（设备 + IPv4 段 + 可选 IPv6 段）。
// bm_set_ip 按特征自动分组（含 ":" 为 IPv6、dhcp 为 DHCP），故无需空位占位；
// 但 DHCP4 + IPv6 时需补 gw/dns 空位以到达 IPv6 槽（对齐 readme "dhcp ” ” ” ipv6…"）。
//
//	静态4        → device ip mask gw dns
//	DHCP4        → device dhcp ''
//	静态4+静态6  → device ip mask gw dns ipv6 prefix6 gw6 dns6
//	DHCP4+静态6  → device dhcp '' '' '' ipv6 prefix6 gw6 dns6
//	静态4+DHCP6  → device ip mask gw dns dhcp
//	DHCP4+DHCP6  → device dhcp '' '' '' dhcp
func buildBmSetIPArgs(c IPConfig) []string {
	args := []string{c.Device}
	// IPv4 段
	if c.IPType == 2 { // DHCP4
		args = append(args, "dhcp", "")
		if c.IPv6Type != 0 { // 需补 gw/dns 空位以达 IPv6 槽
			args = append(args, "", "")
		}
	} else { // 静态4
		args = append(args, c.IP, c.Mask, c.Gateway, c.DNS)
	}
	// IPv6 段（可选）
	if c.IPv6Type != 0 {
		if c.IPv6Type == 2 { // DHCP6
			args = append(args, "dhcp")
		} else { // 静态6
			args = append(args, c.IPv6, c.Prefix6, c.Gateway6, c.DNS6)
		}
	}
	return args
}

// SetIP 配置网卡 IP（IPv4 + 可选 IPv6），调用 bm_set_ip。
// 校验设备名 + 静态地址合法性（IPv4/IPv6 用 net.ParseIP；掩码/前缀透传给 bm_set_ip）。
// DHCP 模式跳过地址校验。bm_set_ip 成功时 stderr 的 netplan 弃用警告忽略（仅非零退出为失败）。
func SetIP(c IPConfig) error {
	if !deviceNameRe.MatchString(c.Device) {
		return errors.New("invalid device name")
	}
	if c.IPType == 1 { // 静态4 校验
		if net.ParseIP(c.IP) == nil {
			return errors.New("invalid ip address")
		}
	}
	if c.IPv6Type == 1 { // 静态6 校验
		if net.ParseIP(c.IPv6) == nil {
			return errors.New("invalid ipv6 address")
		}
	}
	// 网关/DNS 若提供则校验为合法 IP（v4/v6 皆可）
	for _, g := range []string{c.Gateway, c.DNS, c.Gateway6, c.DNS6} {
		if g != "" && net.ParseIP(g) == nil {
			return errors.New("invalid gateway/dns address: " + g)
		}
	}

	bmPath, err := findBmSetIp()
	if err != nil {
		return err
	}
	args := buildBmSetIPArgs(c)
	_, errStr, err := runCmd(bmPath, args...)
	if err != nil {
		if errStr != "" {
			return errors.New(errStr)
		}
		return err
	}
	return nil
}
