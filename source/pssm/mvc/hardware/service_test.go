package hardware

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

// --- Fake 实现 ---

// fakeCmdRunner 用于模拟 shell 命令执行。
type fakeCmdRunner struct {
	output string
	err    error
}

func (f *fakeCmdRunner) Run(name string, args ...string) (string, error) {
	return f.output, f.err
}

// fakeFileReader 用于模拟文件读取（sysfs 夹具）。
type fakeFileReader struct {
	files map[string]string // path -> content
}

func newFakeFileReader() *fakeFileReader {
	return &fakeFileReader{files: make(map[string]string)}
}

func (f *fakeFileReader) Add(path, content string) {
	f.files[path] = content
}

func (f *fakeFileReader) ReadFile(path string) ([]byte, error) {
	content, ok := f.files[path]
	if !ok {
		return nil, os.ErrNotExist
	}
	return []byte(content), nil
}

// fakeRebooter 记录调用次数，绝不真重启。
type fakeRebooter struct {
	calls atomic.Int32
	lastErr error
}

func (f *fakeRebooter) Reboot() error {
	f.calls.Add(1)
	return f.lastErr
}

// --- 测试辅助 ---

func makeTestService() (*HardwareService, *fakeFileReader, *fakeRebooter) {
	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	cmd := &fakeCmdRunner{}
	svc := NewService(cmd, fr, rb)
	return svc, fr, rb
}

// ========== Health ==========

func TestGetHealthUptimeNotEmpty(t *testing.T) {
	svc, _, _ := makeTestService()
	resp := svc.GetHealth()
	if resp.Uptime == "" {
		t.Fatal("expected non-empty uptime")
	}
}

func TestGetHealthTempFromSysfs(t *testing.T) {
	svc, fr, _ := makeTestService()

	// thermal_zone0/temp 值 45678 → 45.7C
	fr.Add("/sys/class/thermal/thermal_zone0/temp", "45678\n")

	resp := svc.GetHealth()
	if resp.CPUTemp != "45.7C" {
		t.Fatalf("expected 45.7C, got %s", resp.CPUTemp)
	}
}

func TestGetHealthTempNoSysfs(t *testing.T) {
	// 无 sysfs 温度文件时，CPUTemp 为空（降级）
	svc, fr, _ := makeTestService()

	// 故意不放任何 thermal_zone 文件
	fr.Add("/sys/class/thermal/thermal_zone99/temp", "invalid")
	// zone99 不会被遍历到（只遍历 0-9）

	resp := svc.GetHealth()
	if resp.CPUTemp != "" {
		t.Fatalf("expected empty CPUTemp when no sysfs, got %s", resp.CPUTemp)
	}
	if resp.Uptime == "" {
		t.Fatal("uptime should still be present")
	}
}

func TestGetHealthTempSecondZone(t *testing.T) {
	svc, fr, _ := makeTestService()

	// zone0 不存在，zone1 有值
	fr.Add("/sys/class/thermal/thermal_zone1/temp", "33128\n")

	resp := svc.GetHealth()
	if resp.CPUTemp != "33.1C" {
		t.Fatalf("expected 33.1C from zone1, got %s", resp.CPUTemp)
	}
}

func TestGetHealthTempInvalidValue(t *testing.T) {
	svc, fr, _ := makeTestService()

	// zone0 有文件但值非法
	fr.Add("/sys/class/thermal/thermal_zone0/temp", "not-a-number\n")

	resp := svc.GetHealth()
	if resp.CPUTemp != "" {
		t.Fatalf("expected empty CPUTemp for invalid value, got %s", resp.CPUTemp)
	}
}

// ========== Reboot ==========

func TestRebootNoDelay(t *testing.T) {
	svc, _, rb := makeTestService()

	err := svc.Reboot(0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rb.calls.Load() != 1 {
		t.Fatalf("expected 1 reboot call, got %d", rb.calls.Load())
	}
}

func TestRebootWithDelay(t *testing.T) {
	// delay 在测试中无害——rebooter 是 fake，不会真调用 /sbin/reboot
	svc, _, rb := makeTestService()

	// 1 秒延迟，fake rebooter 不真重启
	err := svc.Reboot(1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rb.calls.Load() != 1 {
		t.Fatalf("expected 1 reboot call, got %d", rb.calls.Load())
	}
}

func TestRebootDelayTooLarge(t *testing.T) {
	svc, _, _ := makeTestService()

	err := svc.Reboot(301)
	if err == nil {
		t.Fatal("expected error for delay > 300")
	}
	if !strings.Contains(err.Error(), "300") {
		t.Fatalf("error should mention 300 max, got: %v", err)
	}
}

func TestRebootDelayNegative(t *testing.T) {
	svc, _, _ := makeTestService()

	err := svc.Reboot(-1)
	if err == nil {
		t.Fatal("expected error for negative delay")
	}
}

func TestRebootFakeDoesNotReallyReboot(t *testing.T) {
	// 核心约束：测试绝不能真重启。
	// fakeRebooter 只记录计数，不调用 /sbin/reboot
	svc, _, rb := makeTestService()
	rb.lastErr = fmt.Errorf("simulated failure")

	err := svc.Reboot(0)
	if err == nil {
		t.Fatal("expected simulated error")
	}
	if rb.calls.Load() != 1 {
		t.Fatalf("expected 1 call, got %d", rb.calls.Load())
	}
}

// ========== LED ==========

func TestGetLEDNotAvailable(t *testing.T) {
	svc, _, _ := makeTestService()
	resp := svc.GetLED()
	if resp.Available {
		t.Fatal("expected LED not available")
	}
	if resp.Reason == "" {
		t.Fatal("expected reason for LED unavailability")
	}
}

func TestSetLEDValidStates(t *testing.T) {
	svc, _, _ := makeTestService()

	// 所有有效 state 应通过参数校验（但返回"不可用"错误——降级）
	for _, state := range []string{"on", "off", "blink"} {
		err := svc.SetLED(state)
		if err == nil {
			t.Fatalf("expected error for LED state %s (not available without bmlib)", state)
		}
		// 不可用错误（非参数校验错误）
		if strings.HasPrefix(err.Error(), "invalid LED state") {
			t.Fatalf("state %s should be valid, but got validation error: %v", state, err)
		}
	}
}

func TestSetLEDInvalidState(t *testing.T) {
	svc, _, _ := makeTestService()

	err := svc.SetLED("flashing")
	if err == nil {
		t.Fatal("expected error for invalid LED state")
	}
	if !strings.Contains(err.Error(), "invalid LED state") {
		t.Fatalf("expected validation error, got: %v", err)
	}
}

func TestSetLEDInvalidStateEmpty(t *testing.T) {
	svc, _, _ := makeTestService()

	err := svc.SetLED("")
	if err == nil {
		t.Fatal("expected error for empty LED state")
	}
}

// ========== Card ==========

func TestGetCardPlaceholder(t *testing.T) {
	svc, _, _ := makeTestService()
	resp := svc.GetCard()

	if resp.Available {
		t.Fatal("expected card not available (bmlib not integrated)")
	}
	if resp.Reason != "bmlib not integrated" {
		t.Fatalf("expected reason 'bmlib not integrated', got %s", resp.Reason)
	}
}

// ========== 集成：使用真实 sysfs 夹具（os 文件） ==========

func TestGetHealthTempFromWrittenFileFixture(t *testing.T) {
	// 在 tempdir 中创建伪 sysfs 文件，然后用 osFileReader 加载。
	// 用 fakeFileReader 将标准 sysfs 路径映射到 tempdir 文件。
	dir := t.TempDir()
	zoneDir := filepath.Join(dir, "sys", "class", "thermal", "thermal_zone0")
	os.MkdirAll(zoneDir, 0o755)
	realPath := filepath.Join(zoneDir, "temp")
	os.WriteFile(realPath, []byte("52100\n"), 0o644)

	// 将真实文件内容注入到 fakeFileReader 的标准 sysfs 路径下
	fr := newFakeFileReader()
	data, _ := os.ReadFile(realPath)
	fr.Add("/sys/class/thermal/thermal_zone0/temp", string(data))

	svc := NewService(&fakeCmdRunner{}, fr, &fakeRebooter{})
	resp := svc.GetHealth()

	if resp.CPUTemp != "52.1C" {
		t.Fatalf("expected 52.1C, got %s", resp.CPUTemp)
	}
}
