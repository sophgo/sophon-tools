package main

// 局域网设备发现（ARP 扫描）。
//
// 为什么用 ARP 而不是 ICMP / TCP 端口探测：
//   * ARP 是二层协议，请求由网卡直接发出，**不经过主机防火墙**——目标机的
//     iptables/firewalld/Windows 防火墙都不会拦，这是"不容易触发防火墙"的关键；
//   * 只有 ARP 能拿到 MAC 地址，而"按 MAC 前缀筛选"是本功能的硬需求；
//   * 不需要目标机开放任何端口、不需要它响应 ICMP。
//
// 代价：ARP 只在本网段（广播域）内有效，且需要 CAP_NET_RAW 权限。
// 权限不足时退化为读 /proc/net/arp（只能看到本机最近通信过的邻居）。

import (
	"context"
	"errors"
	"fmt"
	"net"
	"sort"
	"strings"
	"time"
)

// ScanOptions 一次扫描的参数。
type ScanOptions struct {
	// Interface 指定网口名，例如 eno1；空表示按网段自动挑选。
	Interface string
	// CIDR 目标网段，例如 192.168.1.0/24。也接受单个 IP。
	CIDR string
	// MACPrefix 只保留以此开头的 MAC；长度任意，空表示不过滤。
	// 支持 00:1a:、00:1a:2b、001a2b、00-1A-2B 等写法。
	MACPrefix string
	// Timeout 等待 ARP 应答的总时长，默认 3 秒。
	Timeout time.Duration
	// Workers 并发发送数，默认 64。
	Workers int
}

// ScanResult 一台被发现的主机。
type ScanResult struct {
	IP  string `json:"ip"`
	MAC string `json:"mac"`
}

// ScanSummary 扫描结果的汇总，供界面展示。
type ScanSummary struct {
	Results []ScanResult `json:"results"`
	// Total 网段内被探测的地址数
	Total int `json:"total"`
	// Method 实际使用的发现方式：arp / arp-cache
	Method string `json:"method"`
	// Interface 实际使用的网口
	Interface string `json:"interface"`
	// Elapsed 耗时
	Elapsed time.Duration `json:"elapsed"`
	// Note 给用户的说明（例如权限不足时的降级提示）
	Note string `json:"note,omitempty"`
}

// NormalizeMACPrefix 把各种写法的 MAC 前缀统一成小写、无分隔符的形式。
// 返回规范化前缀与错误；空前缀合法（表示不过滤）。
func NormalizeMACPrefix(s string) (string, error) {
	clean := strings.ToLower(strings.TrimSpace(s))
	clean = strings.NewReplacer(":", "", "-", "", ".", "", " ", "").Replace(clean)
	if clean == "" {
		return "", nil
	}
	if len(clean) > 12 {
		return "", fmt.Errorf("MAC 前缀过长（%d 个十六进制字符，最多 12）", len(clean))
	}
	for _, r := range clean {
		isHex := (r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')
		if !isHex {
			return "", fmt.Errorf("MAC 前缀含非法字符 %q（只允许 0-9 a-f 与分隔符 : - .）", r)
		}
	}
	return clean, nil
}

// NormalizeMAC 把 MAC 规范化成 aa:bb:cc:dd:ee:ff。
func NormalizeMAC(s string) string {
	h, err := NormalizeMACPrefix(s)
	if err != nil || len(h) != 12 {
		return strings.ToLower(strings.TrimSpace(s))
	}
	parts := make([]string, 6)
	for i := 0; i < 6; i++ {
		parts[i] = h[i*2 : i*2+2]
	}
	return strings.Join(parts, ":")
}

// macHasPrefix 判断 MAC 是否匹配已规范化的前缀。
func macHasPrefix(mac, prefix string) bool {
	if prefix == "" {
		return true
	}
	h, err := NormalizeMACPrefix(mac)
	if err != nil {
		return false
	}
	return strings.HasPrefix(h, prefix)
}

// parseScanCIDR 解析目标网段，返回网段内所有可用主机地址。
//
// 跳过网络地址与广播地址；/31、/32 这类没有"可用主机"概念的网段按原样保留
// （点对点链路上两端都可用）。
func parseScanCIDR(s string) ([]net.IP, *net.IPNet, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, nil, errors.New("网段不能为空，例如 192.168.1.0/24")
	}
	if !strings.Contains(s, "/") {
		// 允许直接写单个 IP
		ip := net.ParseIP(s)
		if ip == nil || ip.To4() == nil {
			return nil, nil, fmt.Errorf("无法解析网段 %q，应形如 192.168.1.0/24", s)
		}
		return []net.IP{ip.To4()}, &net.IPNet{IP: ip.To4(), Mask: net.CIDRMask(32, 32)}, nil
	}
	_, ipnet, err := net.ParseCIDR(s)
	if err != nil {
		return nil, nil, fmt.Errorf("无法解析网段 %q: %w", s, err)
	}
	v4 := ipnet.IP.To4()
	if v4 == nil {
		return nil, nil, fmt.Errorf("只支持 IPv4 网段，得到 %q", s)
	}
	ones, bits := ipnet.Mask.Size()
	if bits != 32 {
		return nil, nil, fmt.Errorf("只支持 IPv4 网段，得到 %q", s)
	}
	// 上限保护：/8 这样的网段有 1600 万地址，扫完会很久且刷爆网络。
	const maxHosts = 1 << 16
	if ones < 16 {
		return nil, nil, fmt.Errorf("网段过大（/%d，%d 个地址），请缩小到 /16 或更小", ones, 1<<(32-ones))
	}
	total := 1 << (32 - ones)
	if total > maxHosts {
		return nil, nil, fmt.Errorf("网段过大（%d 个地址），最多支持 %d", total, maxHosts)
	}

	base := make(net.IP, 4)
	copy(base, v4)
	var out []net.IP
	for i := 0; i < total; i++ {
		ip := make(net.IP, 4)
		v := uint32(base[0])<<24 | uint32(base[1])<<16 | uint32(base[2])<<8 | uint32(base[3])
		v += uint32(i)
		ip[0], ip[1], ip[2], ip[3] = byte(v>>24), byte(v>>16), byte(v>>8), byte(v)
		// 跳过网络地址与广播地址（/31 与 /32 例外：没有这个概念）
		if ones < 31 {
			if i == 0 || i == total-1 {
				continue
			}
		}
		out = append(out, ip)
	}
	return out, ipnet, nil
}

// ScanLAN 执行一次局域网扫描。
func ScanLAN(ctx context.Context, opts ScanOptions) (*ScanSummary, error) {
	prefix, err := NormalizeMACPrefix(opts.MACPrefix)
	if err != nil {
		return nil, err
	}
	hosts, ipnet, err := parseScanCIDR(opts.CIDR)
	if err != nil {
		return nil, err
	}
	timeout := opts.Timeout
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	workers := opts.Workers
	if workers <= 0 {
		workers = 64
	}

	iface, err := pickInterface(opts.Interface, ipnet, hosts)
	if err != nil {
		return nil, err
	}

	start := time.Now()
	summary := &ScanSummary{Total: len(hosts), Interface: iface.Name}

	found, scanErr := arpScan(ctx, iface, hosts, timeout, workers)
	if scanErr == nil {
		summary.Method = "arp"
	} else {
		// 权限不足等情况下退化为读邻居表。
		cached, cacheErr := readARPTable()
		if cacheErr != nil {
			return nil, fmt.Errorf("ARP 扫描失败(%v)，且读取本机邻居表也失败: %w", scanErr, cacheErr)
		}
		summary.Method = "arp-cache"
		summary.Note = fmt.Sprintf("无法主动发送 ARP（%v）。已改为读取本机 ARP 缓存，只能看到最近通信过的设备;"+
			"要扫描整个网段，请用 root 运行，或执行:sudo setcap cap_net_raw+ep <程序路径>", scanErr)
		found = map[string]string{}
		for ip, mac := range cached {
			if ipnet.Contains(net.ParseIP(ip)) {
				found[ip] = mac
			}
		}
	}

	for ip, mac := range found {
		if !macHasPrefix(mac, prefix) {
			continue
		}
		summary.Results = append(summary.Results, ScanResult{IP: ip, MAC: NormalizeMAC(mac)})
	}
	sort.Slice(summary.Results, func(i, j int) bool {
		return ipLess(summary.Results[i].IP, summary.Results[j].IP)
	})
	summary.Elapsed = time.Since(start)
	return summary, nil
}

// ipLess 按数值比较两个 IPv4 地址。
func ipLess(a, b string) bool {
	x, y := net.ParseIP(a).To4(), net.ParseIP(b).To4()
	if x == nil || y == nil {
		return a < b
	}
	for i := 0; i < 4; i++ {
		if x[i] != y[i] {
			return x[i] < y[i]
		}
	}
	return false
}

// readARPTable 读取本机 ARP 邻居表（Linux 的 /proc/net/arp）。
func readARPTable() (map[string]string, error) {
	return readARPTablePlatform()
}
