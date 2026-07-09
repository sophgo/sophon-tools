package metrics

import (
	"os"
	"strconv"
	"testing"
)

func TestChipTypeBM1684X(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "bm1684x" {
		t.Errorf("ChipType() = %q, want bm1684x", got)
	}
}

func TestChipTypeBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: BM1688\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "bm1688" {
		t.Errorf("ChipType() = %q, want bm1688", got)
	}
}

func TestChipTypeUnknown(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: Intel(R) Xeon(R)\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "" {
		t.Errorf("ChipType() = %q, want empty for unknown", got)
	}
}

func TestChipTypeMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "" {
		t.Errorf("ChipType() = %q, want empty when missing", got)
	}
}

// realDeviceIonSummary 是真机 BM1684X 上 cat summary 的实际输出格式：
//
//	Summary:\n
//	[0] npu heap size:2531262464 bytes, used:0 bytes\tusage rate:0%, memory usage peak 456974336 bytes\n
//
// 注意 total 字段名是 `size:` 而非 `total:`，且后跟 `bytes,`。
// Rust 原版用 awk 取 $4/$6 再剥前缀；Go 端须同时识别 size:/total:。
func realDeviceIonSummary(prefix, name string, total, used int64) string {
	return "Summary:\n" +
		prefix + " " + name + " heap size:" + strconv.FormatInt(total, 10) +
		" bytes, used:" + strconv.FormatInt(used, 10) +
		" bytes\tusage rate:0%, memory usage peak 0 bytes\n\nDetails:\n"
}

func TestVppMemoryBM1684X(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/bm_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 3221225472, 536870912),
	}}
	c := NewCollector(fr, nil)
	total, used := c.VppMemory("bm1684x")
	if total != 3221225472 || used != 536870912 {
		t.Errorf("VppMemory() = (%d, %d), want (3221225472, 536870912)", total, used)
	}
}

func TestVppMemoryBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 419430400, 209715200),
	}}
	c := NewCollector(fr, nil)
	total, used := c.VppMemory("bm1688")
	if total != 419430400 || used != 209715200 {
		t.Errorf("VppMemory() = (%d, %d), want (419430400, 209715200)", total, used)
	}
}

func TestVppMemoryMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	total, used := c.VppMemory("bm1684x")
	if total != 0 || used != 0 {
		t.Errorf("VppMemory() = (%d, %d), want (0,0) when missing", total, used)
	}
}

func TestTpuMemoryBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/cvi_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 4141875200, 2070937600),
	}}
	c := NewCollector(fr, nil)
	total, used := c.TpuMemory("bm1688")
	if total != 4141875200 || used != 2070937600 {
		t.Errorf("TpuMemory() = (%d, %d), want (4141875200, 2070937600)", total, used)
	}
}

// TestTpuMemoryBM1684XRealFormat 覆盖真机 BM1684X 的 npu heap（[0] 行，size: 前缀）。
func TestTpuMemoryBM1684XRealFormat(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/bm_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 2531262464, 0),
	}}
	c := NewCollector(fr, nil)
	total, used := c.TpuMemory("bm1684x")
	if total != 2531262464 || used != 0 {
		t.Errorf("TpuMemory() = (%d, %d), want (2531262464, 0)", total, used)
	}
}

func TestIonMemoryFilesExist(t *testing.T) {
	// smoke: ensure no panic on nil-safe paths
	c := NewCollector(&fakeFileReader{files: map[string]string{}, err: os.ErrNotExist}, nil)
	if total, used := c.VppMemory("unknown"); total != 0 || used != 0 {
		t.Errorf("VppMemory(unknown) = (%d,%d), want (0,0)", total, used)
	}
}
