package system

import (
	"os"
	"path/filepath"
	"testing"
)

const cpuinfoBm1688 = `processor	: 0
model name	: bm1688
CPU part	: 0xd03
`

const cpuinfoCv84x6PartD05 = `processor	: 0
model name	: bm1688
CPU part	: 0xd05
`

const cpuinfoCv84x6 = `processor	: 0
model name	: cv84x6
CPU part	: 0xd05
`

const cpuinfoBm1684x = `processor	: 0
model name	: bm1684x
CPU part	: 0xd03
`

// TestDetectCpuModelModelName model name 可靠时直接返回（小写归一）。
func TestDetectCpuModelModelName(t *testing.T) {
	cases := []struct {
		name, content, want string
	}{
		{"bm1684x", cpuinfoBm1684x, "bm1684x"},
		{"cv84x6", cpuinfoCv84x6, "cv84x6"},
		{"empty", "", ""},
		{"missing part", "model name\t: bm1688\n", "bm1688"},
	}
	for _, tc := range cases {
		if got := DetectCpuModel(tc.content, ""); got != tc.want {
			t.Errorf("%s: DetectCpuModel() = %q, want %q", tc.name, got, tc.want)
		}
	}
}

// TestDetectCpuModelPartD05Override CPU part 0xd05（Cortex-A55，仅 CV84X2/CV84X6）
// 优先于 model name——CV84X2 内核可能输出 bm1688/cv186ah/null，model name 不可靠。
// 对齐 get_info.sh CPU part 两级识别。
func TestDetectCpuModelPartD05Override(t *testing.T) {
	if got := DetectCpuModel(cpuinfoCv84x6PartD05, ""); got != "cv84x6" {
		t.Errorf("DetectCpuModel(part=0xd05) = %q, want cv84x6", got)
	}
	// d05 大写十六进制同样命中
	upper := "model name\t: bm1688\nCPU part\t: 0xD05\n"
	if got := DetectCpuModel(upper, ""); got != "cv84x6" {
		t.Errorf("DetectCpuModel(part=0xD05) = %q, want cv84x6", got)
	}
}

// TestDetectCpuModelDtsFallback model name 非 cv84x6 且无 d05 时，
// 扫描 dts compatible 含 "cvitek,cv84x6-" 的节点兜底升级为 cv84x6。
func TestDetectCpuModelDtsFallback(t *testing.T) {
	dts := t.TempDir()
	node := filepath.Join(dts, "soc@0")
	if err := os.MkdirAll(node, 0o755); err != nil {
		t.Fatal(err)
	}
	// compatible 文件为 NUL 分隔字符串，与真机设备树一致
	compat := "cvitek,cv84x6-clk\x00cvitek,syscon\x00"
	if err := os.WriteFile(filepath.Join(node, "compatible"), []byte(compat), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := DetectCpuModel(cpuinfoBm1688, dts); got != "cv84x6" {
		t.Errorf("DetectCpuModel(dts cv84x6 compat) = %q, want cv84x6", got)
	}
	// 无匹配 compatible 的 dts 不升级
	other := t.TempDir()
	if err := os.MkdirAll(filepath.Join(other, "soc@0"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(other, "soc@0", "compatible"), []byte("cvitek,bm1688\x00"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := DetectCpuModel(cpuinfoBm1688, other); got != "bm1688" {
		t.Errorf("DetectCpuModel(dts no match) = %q, want bm1688", got)
	}
	// dtsRoot 不存在（空串）不升级
	if got := DetectCpuModel(cpuinfoBm1688, ""); got != "bm1688" {
		t.Errorf("DetectCpuModel(no dts) = %q, want bm1688", got)
	}
}

// TestDetectCpuModelDtsNotScannedWhenPartMatched model name 已是 cv84x6 或
// part 命中 d05 时不再扫 dts（短路，避免每次采集都走目录树）。
func TestDetectCpuModelDtsNotScannedWhenPartMatched(t *testing.T) {
	// d05 命中 + dtsRoot 不存在：仍应返回 cv84x6（不依赖 dts）
	if got := DetectCpuModel(cpuinfoCv84x6PartD05, "/nonexistent-dts-root"); got != "cv84x6" {
		t.Errorf("DetectCpuModel(d05, bad dts root) = %q, want cv84x6", got)
	}
}
