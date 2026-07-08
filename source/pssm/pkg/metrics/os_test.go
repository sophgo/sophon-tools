package metrics

import (
	"errors"
	"testing"
)

// ---------------------------------------------------------------
// OSVersion — /etc/os-release PRETTY_NAME
// ---------------------------------------------------------------

func TestOSVersion(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/etc/os-release": "NAME=\"Ubuntu\"\nPRETTY_NAME=\"Ubuntu 20.04 LTS\"\nID=ubuntu\nVERSION_CODENAME=focal\n",
	}}
	c := NewCollector(fr, nil)
	got := c.OSVersion()
	want := "Ubuntu 20.04 LTS"
	if got != want {
		t.Errorf("OSVersion() = %q, want %q", got, want)
	}
}

func TestOSVersionMissingPrettyName(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/etc/os-release": "NAME=ubuntu\nID=ubuntu\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.OSVersion(); got != "" {
		t.Errorf("OSVersion() = %q, want empty when PRETTY_NAME absent", got)
	}
}

func TestOSVersionFileMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.OSVersion(); got != "" {
		t.Errorf("OSVersion() = %q, want empty when file missing", got)
	}
}

// ---------------------------------------------------------------
// Runtime — /proc/uptime -> "H:MM:SS"（H 不补零，MM/SS 补零）
// ---------------------------------------------------------------

func TestRuntime(t *testing.T) {
	// 330341.40 s = 91:45:41
	fr := &fakeFileReader{files: map[string]string{
		"/proc/uptime": "330341.40 2627182.68\n",
	}}
	c := NewCollector(fr, nil)
	got := c.Runtime()
	want := "91:45:41"
	if got != want {
		t.Errorf("Runtime() = %q, want %q", got, want)
	}
}

func TestRuntimeSingleDigitPadding(t *testing.T) {
	// 3661 s = 1:01:01 —— 验证小时不补零、分秒补零
	fr := &fakeFileReader{files: map[string]string{
		"/proc/uptime": "3661.00 0.0\n",
	}}
	c := NewCollector(fr, nil)
	got := c.Runtime()
	want := "1:01:01"
	if got != want {
		t.Errorf("Runtime() = %q, want %q (H:MM:SS padding)", got, want)
	}
}

func TestRuntimeFileMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.Runtime(); got != "" {
		t.Errorf("Runtime() = %q, want empty when file missing", got)
	}
}

// ---------------------------------------------------------------
// SdkVersion — 对齐 pget_info 决策树：CPU_MODEL × KERNEL × WORK_MODE
// ---------------------------------------------------------------

// cpuinfo1684x  bm1684x SOC 设备的 /proc/cpuinfo 片段。
const cpuinfo1684x = "processor : 0\nmodel name : bm1684x\nBogoMIPS : 200.00\n"

func TestSdkVersionSOC1684xKernel54(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.4.217-bm1684-g538a73e\n", nil},
		"/usr/sbin/bm_version": {"SophonSDK version: v23.09 LTS-SP5\nsophon-soc-libsophon : 0.5.1\nBL2 v2.8\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "v23.09 LTS-SP5"
	if got != want {
		t.Errorf("SdkVersion() = %q, want %q", got, want)
	}
}

// TestSdkVersionSOC1684Kernel54 锁定 bm1684（非 x）路由：socModels["bm1684"] + case "bm1684"。
// 若任一条目被误删，真实 bm1684 设备会被误判 PCIE 返空/错误，而所有 bm1684x 测试仍过。
func TestSdkVersionSOC1684Kernel54(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": "model name : bm1684\n"}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.4.217-bm1684\n", nil},
		"/usr/sbin/bm_version": {"SophonSDK version: v23.09 LTS\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "v23.09 LTS"
	if got != want {
		t.Errorf("SdkVersion() bm1684 = %q, want %q", got, want)
	}
}

func TestSdkVersionSOC1684xKernel49(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":            cpuinfo1684x,
		"/system/data/buildinfo.txt": "VERSION 2.7.0\nKERNEL_VERSION 4.9.218\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname": {"4.9.218\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "2.7.0"
	if got != want {
		t.Errorf("SdkVersion() 4.9 = %q, want %q", got, want)
	}
}

// TestSdkVersionBuildInfoKernelVersionFirst 验证行首精确匹配：KERNEL_VERSION 行在前
// 时跳过它，取真正 VERSION 行的第 2 字段（修复子串 Contains 误匹配 KERNEL_VERSION 的缺陷）。
func TestSdkVersionBuildInfoKernelVersionFirst(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":              cpuinfo1684x,
		"/system/data/buildinfo.txt": "KERNEL_VERSION 4.9.218\nVERSION 2.7.0\nLIBSOPHON_VERSION 0.4.9\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"4.9.218\n", nil}}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "2.7.0"
	if got != want {
		t.Errorf("SdkVersion() buildinfo KERNEL_VERSION-first = %q, want %q", got, want)
	}
}

// TestSdkVersionBuildInfoOnlyKernelVersion buildinfo 仅含 KERNEL_VERSION 行（无 VERSION 行）
// 时应返空串，而非把内核版本号 4.9.218 当 SDK 版本返回。
func TestSdkVersionBuildInfoOnlyKernelVersion(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":              cpuinfo1684x,
		"/system/data/buildinfo.txt": "KERNEL_VERSION 4.9.218\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"4.9.218\n", nil}}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() only-KERNEL_VERSION = %q, want empty", got)
	}
}

func TestSdkVersionSOC1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name : bm1688\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.10.5\n", nil},
		"/usr/sbin/bm_version": {"Gemini_SDK: v1.5.0\nlibsophon : 0.5.0\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "v1.5.0"
	if got != want {
		t.Errorf("SdkVersion() bm1688 = %q, want %q", got, want)
	}
}

func TestSdkVersionSOC186ah(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name : cv186ah\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.10.5\n", nil},
		"/usr/sbin/bm_version": {"Gemini_SDK: v1.5.1\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "v1.5.1"
	if got != want {
		t.Errorf("SdkVersion() cv186ah = %q, want %q", got, want)
	}
}

// TestSdkVersionSOC1688NewFormat 锁定新格式 bm_version 首行 "SophonSDK(BM1688) 2.1"。
// SE9 实测 bm_version 输出此格式（无 Gemini_SDK 行），SDK 版本取 ')' 之后的 "2.1"。
func TestSdkVersionSOC1688NewFormat(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name : bm1688\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname": {"5.10.4-7bc3705129ea-sophon-custom\n", nil},
		"/usr/sbin/bm_version": {
			"SophonSDK(BM1688) 2.1\n" +
				"sophon-soc-libsophon : 0.4.13\n" +
				"sophon-soc-libsophon-dev : 0.4.13\n" +
				"sophon-media-soc-sophon-ffmpeg : 2.1.0\n" +
				"sophon-media-soc-sophon-opencv : 2.1.0\n" +
				"BL2 bm1688:gf53dd39-dirty 2025-11-18T16:50:31+08:00\n",
			nil,
		},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "2.1"
	if got != want {
		t.Errorf("SdkVersion() bm1688 new-format = %q, want %q", got, want)
	}
}

// TestSdkVersionSOC1688NewFormatNoSDKLine 新格式 bm_version 无 "SophonSDK(" 首行也无
// Gemini_SDK 行（异常输出），SDK 版本返空（libsophon 回退依赖真实软链，单测环境无）。
func TestSdkVersionSOC1688NewFormatNoSDKLine(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name : bm1688\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.10.4\n", nil},
		"/usr/sbin/bm_version": {"sophon-soc-libsophon : 0.4.13\n", nil},
	}}
	c := NewCollector(fr, cmd)
	// 单测环境无 /opt/sophon/libsophon-current 软链，libsophon 回退返空
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() bm1688 no-sdk-line = %q, want empty", got)
	}
}

func TestSdkVersionPCIE(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":                 "model name : Intel(R) Xeon(R) CPU\n",
		"/proc/bmsophon/driver_version": "driver_version: 2.7.0 : 2023-08-01 : build123\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname": {"5.15.0\n", nil},
	}}
	c := NewCollector(fr, cmd)
	got := c.SdkVersion()
	want := "2.7.0"
	if got != want {
		t.Errorf("SdkVersion() PCIE = %q, want %q", got, want)
	}
}

// TestSdkVersionPCIEDriverNoColon driver_version 无冒号时返空串（降级安全）。
func TestSdkVersionPCIEDriverNoColon(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":                 "model name : Intel(R) Xeon(R) CPU\n",
		"/proc/bmsophon/driver_version": "no_colon_here\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"5.15.0\n", nil}}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() PCIE no-colon = %q, want empty", got)
	}
}

// TestSdkVersionSOC1684xBmVersionFail SOC+bm1684x+5.4 但 bm_version 失败——主分支返空串
// （严格对齐 pget_info，不返回 libsophon 版本，二者语义不同）。
func TestSdkVersionSOC1684xBmVersionFail(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.4.217\n", nil},
		"/usr/sbin/bm_version": {"", errors.New("not found")},
	}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() bm_version fail = %q, want empty", got)
	}
}

// TestSdkVersionBmVersionNoPrefixLine bm_version 成功但输出不含目标 prefix 行——返空串
// （bmVersionLine 循环完无匹配的 return "" 路径）。
func TestSdkVersionBmVersionNoPrefixLine(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"uname":                {"5.4.217\n", nil},
		"/usr/sbin/bm_version": {"sophon-soc-libsophon : 0.5.1\nBL2 v2.8\n", nil},
	}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() no-prefix = %q, want empty", got)
	}
}

// TestSdkVersionSOC1684xKernel49NoBuildinfo SOC+4.9 但 buildinfo.txt 缺失——返空串。
func TestSdkVersionSOC1684xKernel49NoBuildinfo(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"4.9.218\n", nil}}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() 4.9 no-buildinfo = %q, want empty", got)
	}
}

// TestSdkVersionSOC1684xKernelOther SOC+bm1684x 但内核既非 5.4 也非 4.9（如 5.10/6.x）
// ——两个 elif 都不命中，穿透返空串（对齐 pget_info：未知内核不设 SDK_VERSION）。
func TestSdkVersionSOC1684xKernelOther(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"6.1.0\n", nil}}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() kernel-other = %q, want empty", got)
	}
}

// TestSdkVersionNoCpuinfo /proc/cpuinfo 缺失 → cpuModel 空 → 非 SOC → PCIE 分支
// → driver_version 也无 → 返空串（不兜底 libsophon）。
func TestSdkVersionNoCpuinfo(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"uname": {"5.4.217\n", nil}}}
	c := NewCollector(fr, cmd)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() no-cpuinfo = %q, want empty", got)
	}
}

// TestSdkVersionCmdNil cmd 为 nil（uname/bm_version 都不可用）——不 panic，返空串。
func TestSdkVersionCmdNil(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/cpuinfo": cpuinfo1684x}}
	c := NewCollector(fr, nil)
	if got := c.SdkVersion(); got != "" {
		t.Errorf("SdkVersion() cmd-nil = %q, want empty", got)
	}
}

// TestParseLibsophonVersion 对齐 get_info awk -F'-' '{print $2}'。
func TestParseLibsophonVersion(t *testing.T) {
	cases := []struct{ in, want string }{
		{"libsophon-0.4.13", "0.4.13"},
		{"/opt/sophon/libsophon-0.4.13", "0.4.13"},
		{"libsophon-0.5.3", "0.5.3"},
		{"no-dash-here", "dash"}, // split by -: ["no","dash","here"] -> 第2段 "dash"
		{"nodash", ""},
		{"", ""},
	}
	for _, tt := range cases {
		if got := parseLibsophonVersion(tt.in); got != tt.want {
			t.Errorf("parseLibsophonVersion(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}
