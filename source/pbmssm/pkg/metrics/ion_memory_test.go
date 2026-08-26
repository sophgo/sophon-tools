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

func TestChipTypeCv84x6(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: cv84x6\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "cv84x6" {
		t.Errorf("ChipType() = %q, want cv84x6", got)
	}
}

func TestChipTypeCv84x6Uppercase(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: CV84X6\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "cv84x6" {
		t.Errorf("ChipType() = %q, want cv84x6 (case-insensitive)", got)
	}
}

func TestChipFamily(t *testing.T) {
	cases := []struct{ chip, want string }{
		{"bm1684x", "bm1684"},
		{"bm1684", "bm1684"},
		{"bm1688", "cv"},
		{"cv186ah", "cv"},
		{"cv84x6", "cv"},
		{"", ""},
	}
	for _, tt := range cases {
		if got := chipFamily(tt.chip); got != tt.want {
			t.Errorf("chipFamily(%q) = %q, want %q", tt.chip, got, tt.want)
		}
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

// TestChipTypePartD05Override 真机场景：CV84X2 上 model name 误报 bm1688，
// CPU part 0xd05（Cortex-A55，仅 CV84X2/CV84X6）应把 ChipType 修正为 cv84x6，
// 使时钟（clk_ap_ca55 等）/ion heap（cvi_）/SDK 版本走 cv84x6 路径。
func TestChipTypePartD05Override(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1688\nCPU part	: 0xd05\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.ChipType(); got != "cv84x6" {
		t.Errorf("ChipType() = %q, want cv84x6 (part 0xd05 优先于误报的 model name)", got)
	}
}

// TestChipDisplayName 芯片显示名映射（一处定义）：cv84x6 → CV84X2，
// 其余芯片大写。空串保持空串（前端显示 '-'）。
func TestChipDisplayName(t *testing.T) {
	cases := []struct{ chip, want string }{
		{"cv84x6", "CV84X2"},
		{"bm1684x", "BM1684X"},
		{"bm1688", "BM1688"},
		{"cv186ah", "CV186AH"},
		{"", ""},
	}
	for _, tt := range cases {
		if got := ChipDisplayName(tt.chip); got != tt.want {
			t.Errorf("ChipDisplayName(%q) = %q, want %q", tt.chip, got, tt.want)
		}
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

func TestVppMemoryCv84x6(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 419430400, 209715200),
	}}
	c := NewCollector(fr, nil)
	total, used := c.VppMemory("cv84x6")
	if total != 419430400 || used != 209715200 {
		t.Errorf("VppMemory() = (%d, %d), want (419430400, 209715200)", total, used)
	}
}

func TestTpuMemoryCv84x6(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/cvi_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 4141875200, 2070937600),
	}}
	c := NewCollector(fr, nil)
	total, used := c.TpuMemory("cv84x6")
	if total != 4141875200 || used != 2070937600 {
		t.Errorf("TpuMemory() = (%d, %d), want (4141875200, 2070937600)", total, used)
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

// TestVpuMemoryBM1684X 覆盖真机 BM1684X 的 vpu heap（[2] 行）。曾误读 vpp heap，已修。
func TestVpuMemoryBM1684X(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/sys/kernel/debug/ion/bm_vpu_heap_dump/summary": realDeviceIonSummary("[2]", "vpu", 3085959168, 28262400),
	}}
	c := NewCollector(fr, nil)
	total, used := c.VpuMemory("bm1684x")
	if total != 3085959168 || used != 28262400 {
		t.Errorf("VpuMemory() = (%d, %d), want (3085959168, 28262400)", total, used)
	}
}

// TestVpuMemoryBM1688 BM1688 无 vpu heap → 0,0（前端据此隐藏 VPU 行）。
func TestVpuMemoryBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if total, used := c.VpuMemory("bm1688"); total != 0 || used != 0 {
		t.Errorf("VpuMemory(bm1688) = (%d,%d), want (0,0)", total, used)
	}
}

// approxEqual 浮点近似比较（MB/百分比容差）。
func approxEqual(a, b, tol float64) bool {
	d := a - b
	if d < 0 {
		d = -d
	}
	return d <= tol
}

// TestMemoryLayoutBM1684X 组合：系统(/proc/meminfo) + TPU/VPU/VPP 三 ion heap → MB+使用率。
func TestMemoryLayoutBM1684X(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name\t: bm1684x\n",
		"/proc/meminfo": "MemTotal:       6427708 kB\n" +
			"MemFree:        3672508 kB\n" +
			"MemAvailable:   5920400 kB\n",
		"/sys/kernel/debug/ion/bm_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 2531262464, 0),
		"/sys/kernel/debug/ion/bm_vpu_heap_dump/summary": realDeviceIonSummary("[2]", "vpu", 3085959168, 28262400),
		"/sys/kernel/debug/ion/bm_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 3221225472, 536870912),
	}}
	c := NewCollector(fr, nil)
	lay := c.MemoryLayout()

	if lay.ChipType != "BM1684X" {
		t.Fatalf("ChipType = %q, want BM1684X (显示名)", lay.ChipType)
	}
	// 系统：6277 MB total，used = 6277-5781(available) = 496，使用率 ~7.90%
	// （buff/cache 可回收不计入，available 口径）
	if !approxEqual(lay.System.TotalMB, 6277, 1) {
		t.Errorf("System.TotalMB = %v, want ~6277", lay.System.TotalMB)
	}
	if !approxEqual(lay.System.UsedMB, 496, 1) {
		t.Errorf("System.UsedMB = %v, want ~496", lay.System.UsedMB)
	}
	if !approxEqual(lay.System.UsagePct, 7.90, 0.1) {
		t.Errorf("System.UsagePct = %v, want ~7.90", lay.System.UsagePct)
	}
	// TPU：2531262464 B = 2414 MB 整；used 0
	if !approxEqual(lay.TPU.TotalMB, 2414, 0.01) || !approxEqual(lay.TPU.UsagePct, 0, 0.01) {
		t.Errorf("TPU = %+v, want TotalMB~2414 UsagePct~0", lay.TPU)
	}
	// VPP：3221225472 B = 3072 MB 整；used 536870912 B = 512 MB；使用率 16.667%
	if !approxEqual(lay.VPP.TotalMB, 3072, 0.01) {
		t.Errorf("VPP.TotalMB = %v, want 3072", lay.VPP.TotalMB)
	}
	if !approxEqual(lay.VPP.UsedMB, 512, 0.01) {
		t.Errorf("VPP.UsedMB = %v, want 512", lay.VPP.UsedMB)
	}
	if !approxEqual(lay.VPP.UsagePct, 16.6667, 0.01) {
		t.Errorf("VPP.UsagePct = %v, want ~16.667", lay.VPP.UsagePct)
	}
	// VPU：3085959168 B ≈ 2942.96 MB，used>0 → 使用率>0
	if !approxEqual(lay.VPU.TotalMB, 2942.96, 0.1) {
		t.Errorf("VPU.TotalMB = %v, want ~2942.96", lay.VPU.TotalMB)
	}
	if lay.VPU.UsedMB <= 0 || lay.VPU.UsagePct <= 0 {
		t.Errorf("VPU = %+v, want used>0 usage>0", lay.VPU)
	}
	// 关键：VPU 与 VPP 不再相同（曾 bug）
	if lay.VPU.TotalMB == lay.VPP.TotalMB {
		t.Errorf("VPU.TotalMB (%v) == VPP.TotalMB (%v): vpu heap not distinct from vpp", lay.VPU.TotalMB, lay.VPP.TotalMB)
	}
}

// TestMemoryLayoutBM1688 SE9(BM1688)：无 VPU heap → VPU 全 0；VPP 走 cvi_ heap。
func TestMemoryLayoutBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name\t: BM1688\n",
		"/proc/meminfo": "MemTotal:       4096000 kB\nMemFree:        2048000 kB\nMemAvailable:   3000000 kB\n",
		"/sys/kernel/debug/ion/cvi_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 1610612736, 0),
		"/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 4290772992, 0),
	}}
	c := NewCollector(fr, nil)
	lay := c.MemoryLayout()

	if lay.ChipType != "BM1688" {
		t.Fatalf("ChipType = %q, want BM1688 (显示名)", lay.ChipType)
	}
	if !approxEqual(lay.TPU.TotalMB, 1536, 0.01) {
		t.Errorf("TPU.TotalMB = %v, want 1536", lay.TPU.TotalMB)
	}
	if !approxEqual(lay.VPP.TotalMB, 4092, 0.5) {
		t.Errorf("VPP.TotalMB = %v, want ~4092", lay.VPP.TotalMB)
	}
	if lay.VPU.TotalMB != 0 || lay.VPU.UsedMB != 0 || lay.VPU.UsagePct != 0 {
		t.Errorf("VPU = %+v, want all 0 on BM1688", lay.VPU)
	}
}

// TestMemoryLayoutCv84x6 CV84X2 内存布局：cvi_ ion heap + chipType 输出显示名 CV84X2
// （cv84x6 → CV84X2 映射在 bmssm 一处定义，sophliteos 前端透传显示"芯片名称"）。
func TestMemoryLayoutCv84x6(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name\t: cv84x6\n",
		"/proc/meminfo": "MemTotal:       4096000 kB\nMemFree:        2048000 kB\nMemAvailable:   3000000 kB\n",
		"/sys/kernel/debug/ion/cvi_npu_heap_dump/summary": realDeviceIonSummary("[0]", "npu", 1610612736, 0),
		"/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary": realDeviceIonSummary("[1]", "vpp", 4290772992, 0),
	}}
	c := NewCollector(fr, nil)
	lay := c.MemoryLayout()

	if lay.ChipType != "CV84X2" {
		t.Fatalf("ChipType = %q, want CV84X2 (显示名)", lay.ChipType)
	}
	if !approxEqual(lay.TPU.TotalMB, 1536, 0.01) {
		t.Errorf("TPU.TotalMB = %v, want 1536", lay.TPU.TotalMB)
	}
	if !approxEqual(lay.VPP.TotalMB, 4092, 0.5) {
		t.Errorf("VPP.TotalMB = %v, want ~4092", lay.VPP.TotalMB)
	}
	if lay.VPU.TotalMB != 0 || lay.VPU.UsedMB != 0 || lay.VPU.UsagePct != 0 {
		t.Errorf("VPU = %+v, want all 0 on CV84X2", lay.VPU)
	}
}
