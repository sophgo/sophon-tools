package main

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"
)

// MAC 前缀长度任意、写法多样，都要能正确规范化与匹配。
func TestNormalizeMACPrefix(t *testing.T) {
	cases := map[string]string{
		"":                  "",
		"00":                "00",
		"00:1a":             "001a",
		"00:1A:2B":          "001a2b",
		"00-1a-2b":          "001a2b",
		"001a2b":            "001a2b",
		"00:1a:2b:3c:4d:6e": "001a2b3c4d6e",
		" 00:1a ":           "001a",
		"00.1a.2b":          "001a2b",
	}
	for in, want := range cases {
		got, err := NormalizeMACPrefix(in)
		if err != nil {
			t.Errorf("%q 应合法, got err %v", in, err)
			continue
		}
		if got != want {
			t.Errorf("%q -> %q, 期望 %q", in, got, want)
		}
	}
}

func TestNormalizeMACPrefixRejectsInvalid(t *testing.T) {
	for _, bad := range []string{"zz", "00:1g", "0011223344556", "00:1a:2b:3c:4d:6e:7f"} {
		if _, err := NormalizeMACPrefix(bad); err == nil {
			t.Errorf("%q 应被拒绝", bad)
		}
	}
}

// 前缀匹配要按"十六进制字符"匹配，而不是字符串前缀——
// 否则 "0" 会误匹配到 "a0:..." 这种。
func TestMACHasPrefix(t *testing.T) {
	cases := []struct {
		mac, prefix string
		want        bool
	}{
		{"98:a9:2d:29:e2:01", "", true},
		{"98:a9:2d:29:e2:01", "98", true},
		{"98:a9:2d:29:e2:01", "98:a9", true},
		{"98:a9:2d:29:e2:01", "98a92d", true},
		{"98:a9:2d:29:e2:01", "98:a9:2d:29:e2:01", true},
		{"98:a9:2d:29:e2:01", "99", false},
		{"98:a9:2d:29:e2:01", "a9", false}, // 不是从中间匹配
		{"f8:ed:fc:aa:6f:c0", "f8:ed", true},
		{"f8:ed:fc:aa:6f:c0", "F8:ED", true}, // 大小写不敏感
	}
	for _, c := range cases {
		p, err := NormalizeMACPrefix(c.prefix)
		if err != nil {
			t.Fatalf("%q 规范化失败: %v", c.prefix, err)
		}
		if got := macHasPrefix(c.mac, p); got != c.want {
			t.Errorf("macHasPrefix(%q, %q) = %v, 期望 %v", c.mac, c.prefix, got, c.want)
		}
	}
}

func TestNormalizeMAC(t *testing.T) {
	if got := NormalizeMAC("F8-ED-FC-AA-6F-C0"); got != "f8:ed:fc:aa:6f:c0" {
		t.Fatalf("got %q", got)
	}
	if got := NormalizeMAC("f8edfcaa6fc0"); got != "f8:ed:fc:aa:6f:c0" {
		t.Fatalf("got %q", got)
	}
}

// 网段解析：跳过网络/广播地址，过大网段直接拒绝。
func TestParseScanCIDR(t *testing.T) {
	ips, ipnet, err := parseScanCIDR("192.168.1.0/24")
	if err != nil {
		t.Fatal(err)
	}
	if len(ips) != 254 {
		t.Fatalf("/24 可用主机数 = %d, 期望 254", len(ips))
	}
	if ips[0].String() != "192.168.1.1" || ips[len(ips)-1].String() != "192.168.1.254" {
		t.Fatalf("首尾地址错误: %s .. %s", ips[0], ips[len(ips)-1])
	}
	if !ipnet.Contains(net.ParseIP("192.168.1.5")) {
		t.Fatal("网段判断错误")
	}

	// 单个 IP
	ips, _, err = parseScanCIDR("10.0.0.7")
	if err != nil || len(ips) != 1 || ips[0].String() != "10.0.0.7" {
		t.Fatalf("单 IP 解析失败: %v %v", ips, err)
	}

	// 过大
	if _, _, err := parseScanCIDR("10.0.0.0/8"); err == nil {
		t.Fatal("/8 应被拒绝")
	}
	if _, _, err := parseScanCIDR(""); err == nil {
		t.Fatal("空网段应被拒绝")
	}
	if _, _, err := parseScanCIDR("not-a-cidr"); err == nil {
		t.Fatal("非法网段应被拒绝")
	}
	if _, _, err := parseScanCIDR("fd00::/64"); err == nil {
		t.Fatal("IPv6 应被拒绝")
	}
}

// /31 与 /32 没有网络/广播地址的概念，两个地址都应保留。
func TestParseScanCIDRPointToPoint(t *testing.T) {
	ips, _, err := parseScanCIDR("10.1.1.0/31")
	if err != nil {
		t.Fatal(err)
	}
	if len(ips) != 2 {
		t.Fatalf("/31 应保留 2 个地址, got %d", len(ips))
	}
	ips, _, err = parseScanCIDR("10.1.1.9/32")
	if err != nil || len(ips) != 1 {
		t.Fatalf("/32 应保留 1 个地址, got %v %v", ips, err)
	}
}

// 权限不足时必须明确降级并给出可操作提示，而不是静默返回空结果。
func TestScanDegradesWithNote(t *testing.T) {
	if isPrivilegedForRawSocket() {
		t.Skip("当前进程有 CAP_NET_RAW，测不到降级路径")
	}
	res, err := ScanLAN(context.Background(), ScanOptions{
		CIDR:    "127.0.0.0/30",
		Timeout: 300 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("应降级而不是报错: %v", err)
	}
	if res.Method != "arp-cache" {
		t.Fatalf("方式 = %q, 期望 arp-cache", res.Method)
	}
	if !strings.Contains(res.Note, "setcap") {
		t.Fatalf("降级提示应给出解决办法, got %q", res.Note)
	}
}

// 非法参数要在扫描前就拒绝。
func TestScanRejectsBadOptions(t *testing.T) {
	if _, err := ScanLAN(context.Background(), ScanOptions{CIDR: "10.0.0.0/8"}); err == nil {
		t.Fatal("过大网段应被拒绝")
	}
	if _, err := ScanLAN(context.Background(), ScanOptions{CIDR: "192.168.1.0/24", MACPrefix: "zz"}); err == nil {
		t.Fatal("非法 MAC 前缀应被拒绝")
	}
	if _, err := ScanLAN(context.Background(), ScanOptions{CIDR: "192.168.1.0/24", Interface: "nosuchif0"}); err == nil {
		t.Fatal("不存在的网口应被拒绝")
	}
}

// 扫到结果后按 IP 数值排序（10.0.0.9 应排在 10.0.0.10 前面）。
func TestIPLess(t *testing.T) {
	if !ipLess("10.0.0.9", "10.0.0.10") {
		t.Fatal("应按数值比较而非字符串")
	}
	if ipLess("10.0.0.10", "10.0.0.9") {
		t.Fatal("顺序错误")
	}
}

// 虚拟网口要排在物理网口之后：对话框默认选中项应是接设备的那块网卡。
func TestPhysicalIfaceOrder(t *testing.T) {
	got := physicalIfaceOrder([]string{"docker0", "eno1", "virbr0", "wlp2s0", "tun0"})
	want := []string{"eno1", "wlp2s0", "docker0", "virbr0", "tun0"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("顺序 = %v, 期望 %v", got, want)
		}
	}
}

// 扫描必须在给定网段内收敛，且不因个别不可达地址卡住。
func TestScanCompletesWithinTimeout(t *testing.T) {
	start := time.Now()
	res, err := ScanLAN(context.Background(), ScanOptions{
		CIDR:    "10.99.99.0/29",
		Timeout: 600 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("扫描失败: %v", err)
	}
	if elapsed := time.Since(start); elapsed > 10*time.Second {
		t.Fatalf("扫描耗时 %s，未在超时内收敛", elapsed)
	}
	if res.Total != 6 { // /29 去掉网络与广播 = 6
		t.Fatalf("探测数 = %d, 期望 6", res.Total)
	}
}
