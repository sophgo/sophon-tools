package metrics

import "testing"

// ---------------------------------------------------------------
// ChipTemp — /sys/class/thermal/thermal_zone0/temp (milli-celsius → ℃)
// ---------------------------------------------------------------

func TestChipTemp(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/thermal/thermal_zone0/temp": "39000\n",
	}}
	c := NewCollector(fr, nil)
	got := c.ChipTemp()
	want := 39
	if got != want {
		t.Errorf("ChipTemp() = %d, want %d", got, want)
	}
}

func TestChipTempMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.ChipTemp(); got != 0 {
		t.Errorf("ChipTemp() = %d, want 0 when missing", got)
	}
}

// ---------------------------------------------------------------
// BoardTemp — /sys/class/thermal/thermal_zone1/temp (milli-celsius → ℃)
// ---------------------------------------------------------------

func TestBoardTemp(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/thermal/thermal_zone1/temp": "42000\n",
	}}
	c := NewCollector(fr, nil)
	got := c.BoardTemp()
	want := 42
	if got != want {
		t.Errorf("BoardTemp() = %d, want %d", got, want)
	}
}

func TestBoardTempMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.BoardTemp(); got != 0 {
		t.Errorf("BoardTemp() = %d, want 0 when missing", got)
	}
}

// ---------------------------------------------------------------
// TPUUsage — /sys/class/bm-tpu/bm-tpu0/device/npu_usage
// 内容形如 "usage:0 avusage:0"，取 usage: 后数字（%）
// ---------------------------------------------------------------

func TestTPUUsage(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/bm-tpu/bm-tpu0/device/npu_usage": "usage:0 avusage:0\n",
	}}
	c := NewCollector(fr, nil)
	got := c.TPUUsage()
	want := 0
	if got != want {
		t.Errorf("TPUUsage() = %d, want %d", got, want)
	}
}

func TestTPUUsageNonZero(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/bm-tpu/bm-tpu0/device/npu_usage": "usage:42 avusage:40\n",
	}}
	c := NewCollector(fr, nil)
	got := c.TPUUsage()
	want := 42
	if got != want {
		t.Errorf("TPUUsage() = %d, want %d (avusage discarded)", got, want)
	}
}

func TestTPUUsageMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.TPUUsage(); got != 0 {
		t.Errorf("TPUUsage() = %d, want 0 when missing", got)
	}
}

// ---------------------------------------------------------------
// TPUMem — /sys/kernel/debug/ion/bm_npu_heap_dump/total_mem (bytes → MB)
// 真值 4141875200 B = 3950 MiB
// ---------------------------------------------------------------

func TestTPUMem(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/bm_npu_heap_dump/total_mem": "4141875200\n",
	}}
	c := NewCollector(fr, nil)
	got := c.TPUMem()
	want := 3950.0
	if got != want {
		t.Errorf("TPUMem() = %v, want %v", got, want)
	}
}

func TestTPUMemMissing(t *testing.T) {
	// 非 root 读不到 debugfs，应降级返 0
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.TPUMem(); got != 0 {
		t.Errorf("TPUMem() = %v, want 0 when missing (non-root 降级)", got)
	}
}

// ---------------------------------------------------------------
// TPUAverageUsage — avusage: 字段
// ---------------------------------------------------------------

func TestTPUAverageUsage(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/bm-tpu/bm-tpu0/device/npu_usage": "usage:0 avusage:0\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.TPUAverageUsage(); got != 0 {
		t.Errorf("TPUAverageUsage() = %d, want 0", got)
	}
}

func TestTPUAverageUsageNonZero(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/bm-tpu/bm-tpu0/device/npu_usage": "usage:42 avusage:40\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.TPUAverageUsage(); got != 40 {
		t.Errorf("TPUAverageUsage() = %d, want 40", got)
	}
}

func TestTPUAverageUsageMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.TPUAverageUsage(); got != 0 {
		t.Errorf("TPUAverageUsage() = %d, want 0 when missing", got)
	}
}
