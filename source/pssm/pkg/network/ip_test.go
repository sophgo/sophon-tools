package network

import (
	"errors"
	"os/exec"
	"testing"
)

// 使用 "ip addr" 真实输出作为测试夹具
const ipAddrOutput = `
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::211:22ff:fe33:4455/64 scope link
       valid_lft forever preferred_lft forever
3: eth1: <BROADCAST,MULTICAST,DOWN> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/ether 00:11:22:33:44:66 brd ff:ff:ff:ff:ff:ff
4: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default
    link/ether 02:42:ac:11:00:01 brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
       valid_lft forever preferred_lft forever
`

func TestParseIPAddr(t *testing.T) {
	cards := parseIPAddr(ipAddrOutput)

	if len(cards) != 4 {
		t.Fatalf("expected 4 interfaces, got %d", len(cards))
	}

	// lo
	if cards[0].Name != "lo" {
		t.Fatalf("expected lo, got %s", cards[0].Name)
	}
	if !cards[0].IsLoopback {
		t.Fatal("lo should be loopback")
	}
	if cards[0].State != "UP" {
		t.Fatalf("lo state expected UP, got %s", cards[0].State)
	}
	if len(cards[0].IPs) < 1 {
		t.Fatal("lo should have IP")
	}

	// eth0
	if cards[1].Name != "eth0" {
		t.Fatalf("expected eth0, got %s", cards[1].Name)
	}
	if cards[1].MAC != "00:11:22:33:44:55" {
		t.Fatalf("eth0 MAC expected 00:11:22:33:44:55, got %s", cards[1].MAC)
	}
	if cards[1].State != "UP" {
		t.Fatalf("eth0 state expected UP, got %s", cards[1].State)
	}
	if len(cards[1].IPs) != 2 {
		t.Fatalf("eth0 should have 2 IPs (v4+v6), got %d", len(cards[1].IPs))
	}
	foundIPv4 := false
	for _, ip := range cards[1].IPs {
		if ip == "192.168.1.100/24" {
			foundIPv4 = true
		}
	}
	if !foundIPv4 {
		t.Fatalf("eth0 should have 192.168.1.100/24, got %v", cards[1].IPs)
	}

	// eth1 (DOWN, no IP)
	if cards[2].Name != "eth1" {
		t.Fatalf("expected eth1, got %s", cards[2].Name)
	}
	if cards[2].State != "DOWN" {
		t.Fatalf("eth1 state expected DOWN, got %s", cards[2].State)
	}
	if len(cards[2].IPs) != 0 {
		t.Fatalf("eth1 should have no IPs, got %d", len(cards[2].IPs))
	}

	// docker0
	if cards[3].Name != "docker0" {
		t.Fatalf("expected docker0, got %s", cards[3].Name)
	}
	if cards[3].State != "UP" {
		t.Fatalf("docker0 state expected UP, got %s", cards[3].State)
	}
}

func TestParseEmptyOutput(t *testing.T) {
	cards := parseIPAddr("")
	if len(cards) != 0 {
		t.Fatalf("expected 0 interfaces, got %d", len(cards))
	}
}

func TestClassifyState(t *testing.T) {
	tests := []struct {
		flags string
		want  string
	}{
		{"UP,LOWER_UP", "UP"},
		{"DOWN", "DOWN"},
		{"BROADCAST,MULTICAST", "UNKNOWN"},
		{"NO-CARRIER,BROADCAST,MULTICAST,UP", "UP"},
	}
	for _, tt := range tests {
		got := classifyState(tt.flags)
		if got != tt.want {
			t.Errorf("classifyState(%q) = %q, want %q", tt.flags, got, tt.want)
		}
	}
}

// 虚拟/环回接口 ip addr 输出夹具（含 eth0/eth1 物理网卡和 dummy0/lo/sit0/wlan0/docker0）
const ipAddrWithVirtual = `
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
3: eth1: <BROADCAST,MULTICAST,DOWN> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/ether 00:11:22:33:44:66 brd ff:ff:ff:ff:ff:ff
4: dummy0: <BROADCAST,NOARP> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/ether 00:00:00:00:00:00 brd ff:ff:ff:ff:ff:ff
5: sit0@NONE: <NOARP> mtu 1480 qdisc noop state DOWN group default qlen 1000
    link/sit 0.0.0.0 brd 0.0.0.0
6: wlan0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/ether 00:00:00:00:00:00 brd ff:ff:ff:ff:ff:ff
7: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default
    link/ether 02:42:ac:11:00:01 brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
`

func TestFilterPhysicalNetCards(t *testing.T) {
	allCards := parseIPAddr(ipAddrWithVirtual)
	if len(allCards) != 7 {
		t.Fatalf("expected 7 total interfaces, got %d", len(allCards))
	}

	filtered := filterPhysicalNetCards(allCards)
	if len(filtered) != 2 {
		t.Fatalf("expected 2 physical interfaces, got %d: %v", len(filtered), names(filtered))
	}

	namesMap := make(map[string]bool)
	for _, c := range filtered {
		namesMap[c.Name] = true
	}

	if !namesMap["eth0"] {
		t.Fatal("expected eth0 in filtered result")
	}
	if !namesMap["eth1"] {
		t.Fatal("expected eth1 in filtered result")
	}

	// 确认虚拟/环回接口全部被排除
	virtualNames := []string{"lo", "dummy0", "sit0", "wlan0", "docker0"}
	for _, name := range virtualNames {
		if namesMap[name] {
			t.Fatalf("virtual interface %q should be filtered out", name)
		}
	}
}

func TestIsPhysicalIf(t *testing.T) {
	tests := []struct {
		name string
		want bool
	}{
		{"eth0", true},
		{"eth1", true},
		{"enp0s3", true},
		{"enp4s0", true},
		{"bond0", true},
		{"em1", true},
		{"p6p1", true},
		{"lo", false},
		{"dummy0", false},
		{"sit0", false},
		{"wlan0", false},
		{"docker0", false},
		{"veth12345", false},
		{"tun0", false},
		{"br-abc", false},
	}
	for _, tt := range tests {
		got := isPhysicalIf(tt.name)
		if got != tt.want {
			t.Errorf("isPhysicalIf(%q) = %v, want %v", tt.name, got, tt.want)
		}
	}
}

func TestFilterPhysicalNetCardsEmpty(t *testing.T) {
	// 全虚拟接口列表应返回空切片
	cards := []NetCard{
		{Name: "lo"},
		{Name: "dummy0"},
		{Name: "docker0"},
	}
	filtered := filterPhysicalNetCards(cards)
	if len(filtered) != 0 {
		t.Fatalf("expected empty, got %d", len(filtered))
	}
}

func TestFilterPhysicalNetCardsNilInput(t *testing.T) {
	filtered := filterPhysicalNetCards(nil)
	if filtered == nil {
		t.Fatal("expected empty slice, got nil")
	}
	if len(filtered) != 0 {
		t.Fatalf("expected empty, got %d", len(filtered))
	}
}

// names 辅助函数：提取网卡名称列表便于测试输出。
func names(cards []NetCard) []string {
	out := make([]string, len(cards))
	for i, c := range cards {
		out[i] = c.Name
	}
	return out
}

// ============================================================================
// bm_set_ip 相关测试
// ============================================================================

// capturedArgs 记录 runCmd 被调用时传入的参数。
type capturedArgs struct {
	name string
	args []string
}

// saveAndRestore 保存并返回恢复函数，用于测试中替换包级变量。
func saveAndRestore() func() {
	origLookPath := lookPath
	origRunCmd := runCmd
	return func() {
		lookPath = origLookPath
		runCmd = origRunCmd
	}
}

func TestSetStaticIPCallsBmSetIp(t *testing.T) {
	defer saveAndRestore()()

	var captured capturedArgs

	// 模拟 bm_set_ip 存在
	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	// 模拟执行成功，捕获参数
	runCmd = func(name string, args ...string) (string, string, error) {
		captured = capturedArgs{name: name, args: args}
		return "", "", nil
	}

	err := SetStaticIP("eth0", "192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if captured.name != "/usr/sbin/bm_set_ip" {
		t.Errorf("expected bm_set_ip path, got %q", captured.name)
	}
	if len(captured.args) != 5 {
		t.Fatalf("expected 5 args, got %d: %v", len(captured.args), captured.args)
	}
	if captured.args[0] != "eth0" {
		t.Errorf("arg[0] device = %q, want eth0", captured.args[0])
	}
	if captured.args[1] != "192.168.1.100" {
		t.Errorf("arg[1] ip = %q, want 192.168.1.100", captured.args[1])
	}
	if captured.args[2] != "255.255.255.0" {
		t.Errorf("arg[2] mask = %q, want 255.255.255.0", captured.args[2])
	}
	if captured.args[3] != "192.168.1.1" {
		t.Errorf("arg[3] gateway = %q, want 192.168.1.1", captured.args[3])
	}
	if captured.args[4] != "8.8.8.8" {
		t.Errorf("arg[4] dns = %q, want 8.8.8.8", captured.args[4])
	}
}

func TestSetStaticIPCallsBmSetIpEmptyGatewayDNS(t *testing.T) {
	defer saveAndRestore()()

	var captured capturedArgs

	lookPath = func(name string) (string, error) {
		return "/usr/local/bin/bm_set_ip", nil
	}
	runCmd = func(name string, args ...string) (string, string, error) {
		captured = capturedArgs{name: name, args: args}
		return "", "", nil
	}

	// gateway 和 dns 为空字符串
	err := SetStaticIP("eth0", "10.0.0.1", "255.0.0.0", "", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if captured.args[3] != "" {
		t.Errorf("arg[3] gateway = %q, want empty", captured.args[3])
	}
	if captured.args[4] != "" {
		t.Errorf("arg[4] dns = %q, want empty", captured.args[4])
	}
}

func TestSetDynamicIPCallsBmSetIp(t *testing.T) {
	defer saveAndRestore()()

	var captured capturedArgs

	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	runCmd = func(name string, args ...string) (string, string, error) {
		captured = capturedArgs{name: name, args: args}
		return "", "", nil
	}

	err := SetDynamicIP("eth0")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if captured.name != "/usr/sbin/bm_set_ip" {
		t.Errorf("expected bm_set_ip path, got %q", captured.name)
	}
	if len(captured.args) != 3 {
		t.Fatalf("expected 3 args, got %d: %v", len(captured.args), captured.args)
	}
	if captured.args[0] != "eth0" {
		t.Errorf("arg[0] device = %q, want eth0", captured.args[0])
	}
	if captured.args[1] != "dhcp" {
		t.Errorf("arg[1] = %q, want dhcp", captured.args[1])
	}
	if captured.args[2] != "" {
		t.Errorf("arg[2] = %q, want empty", captured.args[2])
	}
}

func TestSetStaticIPToolNotFound(t *testing.T) {
	defer saveAndRestore()()

	// 模拟 bm_set_ip 不存在
	lookPath = func(name string) (string, error) {
		return "", exec.ErrNotFound
	}
	// runCmd 不应被调用
	runCmdCalled := false
	runCmd = func(name string, args ...string) (string, string, error) {
		runCmdCalled = true
		return "", "", nil
	}

	err := SetStaticIP("eth0", "192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8")
	if err == nil {
		t.Fatal("expected error for tool not found")
	}
	if err.Error() != "bm_set_ip tool not found, please install pbm_set_ip" {
		t.Errorf("error = %q, want 'bm_set_ip tool not found, please install pbm_set_ip'", err.Error())
	}
	if runCmdCalled {
		t.Error("runCmd should not be called when tool not found")
	}
}

func TestSetDynamicIPToolNotFound(t *testing.T) {
	defer saveAndRestore()()

	lookPath = func(name string) (string, error) {
		return "", exec.ErrNotFound
	}
	runCmdCalled := false
	runCmd = func(name string, args ...string) (string, string, error) {
		runCmdCalled = true
		return "", "", nil
	}

	err := SetDynamicIP("eth0")
	if err == nil {
		t.Fatal("expected error for tool not found")
	}
	if err.Error() != "bm_set_ip tool not found, please install pbm_set_ip" {
		t.Errorf("error = %q, want 'bm_set_ip tool not found, please install pbm_set_ip'", err.Error())
	}
	if runCmdCalled {
		t.Error("runCmd should not be called when tool not found")
	}
}

func TestSetStaticIPInvalidInput(t *testing.T) {
	defer saveAndRestore()()

	// 确保 bm_set_ip 存在，但不应被调用（输入校验在前）
	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	runCmdCalled := false
	runCmd = func(name string, args ...string) (string, string, error) {
		runCmdCalled = true
		return "", "", nil
	}

	tests := []struct {
		name    string
		device  string
		ip      string
		mask    string
		gateway string
		dns     string
		wantErr string
	}{
		{"invalid device name", "eth0; rm -rf /", "192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8", "invalid device name"},
		{"invalid device with spaces", "eth0 foo", "192.168.1.100", "255.255.255.0", "", "", "invalid device name"},
		{"invalid ip", "eth0", "not-an-ip", "255.255.255.0", "", "", "invalid ip address"},
		{"invalid mask", "eth0", "192.168.1.100", "not-a-mask", "", "", "invalid netmask"},
		{"invalid gateway", "eth0", "192.168.1.100", "255.255.255.0", "bad-gw", "", "invalid gateway"},
		{"invalid dns", "eth0", "192.168.1.100", "255.255.255.0", "", "bad-dns", "invalid dns address"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runCmdCalled = false
			err := SetStaticIP(tt.device, tt.ip, tt.mask, tt.gateway, tt.dns)
			if err == nil {
				t.Fatal("expected error")
			}
			if err.Error() != tt.wantErr {
				t.Errorf("error = %q, want %q", err.Error(), tt.wantErr)
			}
			if runCmdCalled {
				t.Error("runCmd should not be called for invalid input")
			}
		})
	}
}

func TestSetDynamicIPInvalidInput(t *testing.T) {
	defer saveAndRestore()()

	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	runCmdCalled := false
	runCmd = func(name string, args ...string) (string, string, error) {
		runCmdCalled = true
		return "", "", nil
	}

	err := SetDynamicIP("eth0; rm -rf /")
	if err == nil {
		t.Fatal("expected error for invalid device")
	}
	if err.Error() != "invalid device name" {
		t.Errorf("error = %q, want 'invalid device name'", err.Error())
	}
	if runCmdCalled {
		t.Error("runCmd should not be called for invalid input")
	}
}

func TestSetStaticIPRunCmdError(t *testing.T) {
	defer saveAndRestore()()

	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	runCmd = func(name string, args ...string) (string, string, error) {
		return "", "no such device", errors.New("exit status 1")
	}

	err := SetStaticIP("eth99", "192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8")
	if err == nil {
		t.Fatal("expected error from bm_set_ip")
	}
	// 错误信息应包含 bm_set_ip 的 stderr 和 err
	if err.Error() != "no such device: exit status 1" {
		t.Errorf("error = %q, want 'no such device: exit status 1'", err.Error())
	}
}

func TestSetDynamicIPRunCmdError(t *testing.T) {
	defer saveAndRestore()()

	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	runCmd = func(name string, args ...string) (string, string, error) {
		return "", "no such device", errors.New("exit status 1")
	}

	err := SetDynamicIP("eth99")
	if err == nil {
		t.Fatal("expected error from bm_set_ip")
	}
	if err.Error() != "no such device: exit status 1" {
		t.Errorf("error = %q, want 'no such device: exit status 1'", err.Error())
	}
}

func TestSetStaticIPRunCmdErrStrOnly(t *testing.T) {
	defer saveAndRestore()()

	lookPath = func(name string) (string, error) {
		return "/usr/sbin/bm_set_ip", nil
	}
	// errStr 非空，err 为 nil 的情况
	runCmd = func(name string, args ...string) (string, string, error) {
		return "", "some warning", nil
	}

	err := SetStaticIP("eth0", "192.168.1.100", "255.255.255.0", "", "")
	if err == nil {
		t.Fatal("expected error from bm_set_ip stderr")
	}
	if err.Error() != "some warning" {
		t.Errorf("error = %q, want 'some warning'", err.Error())
	}
}