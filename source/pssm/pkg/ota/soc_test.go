package ota

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// createOTAFixture 创建一个含刷机包标记文件的 .tgz，返回路径。
func createOTAFixture(t *testing.T, dir, name string, files map[string]string) string {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir fixture dir: %v", err)
	}
	path := filepath.Join(dir, name)
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create fixture: %v", err)
	}
	defer f.Close()

	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)
	for name, content := range files {
		hdr := &tar.Header{Name: name, Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}
		if strings.HasSuffix(name, "/") {
			hdr.Typeflag = tar.TypeDir
			hdr.Size = 0
		}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatalf("tar header %s: %v", name, err)
		}
		if !strings.HasSuffix(name, "/") {
			if _, err := tw.Write([]byte(content)); err != nil {
				t.Fatalf("tar write %s: %v", name, err)
			}
		}
	}
	tw.Close()
	gw.Close()
	return path
}

// ---------------------------------------------------------------
// PrepareSOC
// ---------------------------------------------------------------

func TestPrepareSOC(t *testing.T) {
	otaDir := t.TempDir()
	workRoot := t.TempDir()
	pkg := createOTAFixture(t, otaDir, "fw.tgz", map[string]string{
		"BOOT/boot.img": "boot-image-data",
		"md5.txt":       "abc123 boot.img\n",
	})

	workDir := filepath.Join(workRoot, "wf-123")
	if err := PrepareSOC(workDir, pkg); err != nil {
		t.Fatalf("PrepareSOC: %v", err)
	}

	// 刷机包文件已解压
	if data, err := os.ReadFile(filepath.Join(workDir, "BOOT", "boot.img")); err != nil {
		t.Fatalf("read extracted boot.img: %v", err)
	} else if string(data) != "boot-image-data" {
		t.Errorf("boot.img content mismatch: %s", string(data))
	}
	if _, err := os.Stat(filepath.Join(workDir, "md5.txt")); err != nil {
		t.Errorf("md5.txt missing: %v", err)
	}
	// ota.sh + bc 已写入
	if _, err := os.Stat(filepath.Join(workDir, "ota.sh")); err != nil {
		t.Errorf("ota.sh missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(workDir, "arm64_bin", "bc")); err != nil {
		t.Errorf("arm64_bin/bc missing: %v", err)
	}
}

func TestPrepareSOCZipSlip(t *testing.T) {
	otaDir := t.TempDir()
	workRoot := t.TempDir()
	// 构造含路径穿越的 tar.gz
	path := filepath.Join(otaDir, "evil.tgz")
	f, _ := os.Create(path)
	defer f.Close()
	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)
	tw.WriteHeader(&tar.Header{Name: "../../etc/passwd", Mode: 0o644, Size: 5, Typeflag: tar.TypeReg})
	tw.Write([]byte("evil"))
	tw.Close()
	gw.Close()

	if err := PrepareSOC(filepath.Join(workRoot, "wf-evil"), path); err == nil {
		t.Fatal("expected zip-slip error, got nil")
	} else if !strings.Contains(err.Error(), "zip-slip") {
		t.Errorf("expected zip-slip in error, got: %v", err)
	}
}

func TestPrepareSOCMissingPkg(t *testing.T) {
	err := PrepareSOC(filepath.Join(t.TempDir(), "wf"), "/nonexistent/pkg.tgz")
	if err == nil {
		t.Fatal("expected error for missing package")
	}
}

// ---------------------------------------------------------------
// RunSOC（mock runner 断言命令）
// ---------------------------------------------------------------

func TestRunSOCDefaultKeepsData(t *testing.T) {
	e, runner, _, paths := newTestEngine(t, false)
	workDir := filepath.Join(paths.SOCWorkRoot, "wf-run")
	_ = os.MkdirAll(workDir, 0o755)
	_ = os.WriteFile(filepath.Join(workDir, "ota.sh"), []byte("#!/bin/bash\n"), 0o755)

	if err := e.RunSOC(workDir, true); err != nil {
		t.Fatalf("RunSOC: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("expected 1 runner call, got %d", len(calls))
	}
	if calls[0].Name != "sudo" {
		t.Errorf("runner name = %q, want sudo", calls[0].Name)
	}
	if len(calls[0].Args) != 2 || calls[0].Args[0] != "bash" {
		t.Errorf("args = %+v, want [bash <script>]", calls[0].Args)
	}
	if calls[0].Args[1] != filepath.Join(workDir, "ota.sh") {
		t.Errorf("script path = %q", calls[0].Args[1])
	}
	// 默认保留 data，不传 LAST_PART_NOT_FLASH=0
	for _, a := range calls[0].Args {
		if strings.Contains(a, "LAST_PART_NOT_FLASH") {
			t.Errorf("should not pass LAST_PART_NOT_FLASH arg by default, got %q", a)
		}
	}
}

func TestRunSOCFlashAllPartitions(t *testing.T) {
	e, runner, _, paths := newTestEngine(t, false)
	workDir := filepath.Join(paths.SOCWorkRoot, "wf-flash")
	_ = os.MkdirAll(workDir, 0o755)
	_ = os.WriteFile(filepath.Join(workDir, "ota.sh"), []byte("#!/bin/bash\n"), 0o755)

	if err := e.RunSOC(workDir, false); err != nil {
		t.Fatalf("RunSOC: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("expected 1 call, got %d", len(calls))
	}
	if len(calls[0].Args) != 3 {
		t.Fatalf("expected 3 args, got %d: %+v", len(calls[0].Args), calls[0].Args)
	}
	if calls[0].Args[2] != "LAST_PART_NOT_FLASH=0" {
		t.Errorf("3rd arg = %q, want LAST_PART_NOT_FLASH=0", calls[0].Args[2])
	}
}

func TestRunSOCRunnerFails(t *testing.T) {
	e, runner, _, paths := newTestEngine(t, false)
	runner.fail = true
	workDir := filepath.Join(paths.SOCWorkRoot, "wf-fail")
	_ = os.MkdirAll(workDir, 0o755)
	_ = os.WriteFile(filepath.Join(workDir, "ota.sh"), []byte("#!/bin/bash\n"), 0o755)

	if err := e.RunSOC(workDir, true); err == nil {
		t.Fatal("expected error when runner fails")
	}
}

// ---------------------------------------------------------------
// StatusSOC（mock flags）
// ---------------------------------------------------------------

func TestStatusSOCNoneRunning(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	flags.success = false
	flags.error = false
	st, _ := e.StatusSOC()
	if st != StatusRunning {
		t.Errorf("status = %d, want %d (Running)", st, StatusRunning)
	}
}

func TestStatusSOCSuccess(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	flags.success = true
	st, info := e.StatusSOC()
	if st != StatusSuccess {
		t.Errorf("status = %d, want %d", st, StatusSuccess)
	}
	if info != "" {
		t.Errorf("success info should be empty, got %q", info)
	}
}

func TestStatusSOCFail(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	flags.error = true
	flags.panicLine = "LAST_PART_NOT_FLASH mode, check last part start [28602368] != [49573888]"
	st, info := e.StatusSOC()
	if st != StatusFail {
		t.Errorf("status = %d, want %d", st, StatusFail)
	}
	if !strings.Contains(info, "LAST_PART_NOT_FLASH") {
		t.Errorf("info should contain panic line, got %q", info)
	}
}

func TestStatusSOCDryRun(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	st, _ := e.StatusSOC()
	if st != StatusSuccess {
		t.Errorf("dryRun status = %d, want %d", st, StatusSuccess)
	}
}

// ---------------------------------------------------------------
// extractPanicLine
// ---------------------------------------------------------------

func TestExtractPanicLine(t *testing.T) {
	cases := []struct {
		name    string
		log     string
		want    string
	}{
		{
			name: "last panic line extracted with prefix stripped",
			log: `+ echo "Starting flash..."
+ check_partition
+ [ 28602368 -ne 49573888 ]
+ panic "LAST_PART_NOT_FLASH mode, check last part start [28602368] != [49573888]"
+ /usr/sbin/ota.sh: line 167:  panicked_func
[PANIC] LAST_PART_NOT_FLASH mode, check last part start [28602368] != [49573888]
+ cleanup_temp_files
+ exit 1`,
			want: "LAST_PART_NOT_FLASH mode, check last part start [28602368] != [49573888]",
		},
		{
			name: "no panic line returns last non-empty line",
			log: `line one
line two
last line of output`,
			want: "last line of output",
		},
		{
			name:    "empty log returns empty",
			log:     "",
			want:    "",
		},
		{
			name: "multiple panic lines returns last one",
			log: `[PANIC] first error
some noise
[PANIC] second error
more noise`,
			want: "second error",
		},
		{
			name: "panic line without space after prefix",
			log: `[PANIC]disk full error`,
			want: "disk full error",
		},
		{
			name: "last non-empty line truncated to 200 chars",
			log:  strings.Repeat("x", 250),
			want: strings.Repeat("x", 200),
		},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			got := extractPanicLine(tt.log)
			if got != tt.want {
				t.Errorf("extractPanicLine() = %q, want %q", got, tt.want)
			}
		})
	}
}

// ---------------------------------------------------------------
// parseLastPartNotFlash
// ---------------------------------------------------------------

func TestParseLastPartNotFlash(t *testing.T) {
	cases := []struct {
		cmd  string
		want bool
	}{
		{"", true},
		{"LAST_PART_NOT_FLASH=0", false},
		{"foo=1;LAST_PART_NOT_FLASH=0", false},
		{"some other flag", true},
	}
	for _, tt := range cases {
		if got := parseLastPartNotFlash(tt.cmd); got != tt.want {
			t.Errorf("parseLastPartNotFlash(%q) = %v, want %v", tt.cmd, got, tt.want)
		}
	}
}

// ---------------------------------------------------------------
// runSOC 端到端（非干跑，mock runner + 预置 success 标志 → poll → Success）
// ---------------------------------------------------------------

func TestRunSOCFlowSuccess(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()

	// 预置 .tgz 刷机包
	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{
		"BOOT/boot.img": "boot-data",
		"md5.txt":       "deadbeef boot.img\n",
	})
	// 预置 success 标志，pollOnce 首次即命中
	flags.success = true

	flow := Workflow{Product: "SE7", FileName: "fw.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)

	// 断言解压 + ota.sh 写入工作目录
	workDir := filepath.Join(e.paths.SOCWorkRoot, flow.WorkflowID)
	if _, err := os.Stat(filepath.Join(workDir, "ota.sh")); err != nil {
		t.Errorf("ota.sh missing in workDir %s: %v", workDir, err)
	}
	if data, err := os.ReadFile(filepath.Join(workDir, "BOOT", "boot.img")); err != nil {
		t.Errorf("extracted boot.img missing: %v", err)
	} else if string(data) != "boot-data" {
		t.Errorf("boot.img content: %s", string(data))
	}
}

func TestRunSOCFlowFail(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()

	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{"md5.txt": "x\n"})
	// 预置 error 标志，poll 命中 Fail
	flags.error = true
	flags.panicLine = "ota failed: gpt corrupt"

	flow := Workflow{Product: "se9", FileName: "fw.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusFail, 3*time.Second)
	wf, _ := e.Query(flow.WorkflowID)
	if !strings.Contains(wf.Info, "gpt corrupt") {
		t.Errorf("Info = %q, want contain log tail", wf.Info)
	}
}

// runSOC 解压失败（包不存在）→ Fail
func TestRunSOCFlowPrepareFail(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir() // 空，无 fw.tgz
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SE7", FileName: "missing.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusFail, 3*time.Second)
}

// ---------------------------------------------------------------
// runSOC FlashData 端到端（mock runner 断言命令）
// ---------------------------------------------------------------

func TestRunSOCWithFlashData(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()

	// 预置 .tgz 刷机包
	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{
		"BOOT/boot.img": "boot-data",
		"md5.txt":       "abc\n",
	})

	flow := Workflow{
		Product:   "SE7",
		FileName:  "fw.tgz",
		FlashData: true,
	}
	if err := e.runSOC(flow); err != nil {
		t.Fatalf("runSOC: %v", err)
	}
	calls := runner.calls_()
	if len(calls) == 0 {
		t.Fatal("expected at least 1 runner call")
	}
	// 最后一个调用是 RunSOC（sudo bash ...）
	last := calls[len(calls)-1]
	foundFlash0 := false
	for _, a := range last.Args {
		if a == "LAST_PART_NOT_FLASH=0" {
			foundFlash0 = true
		}
	}
	if !foundFlash0 {
		t.Errorf("FlashData=true should pass LAST_PART_NOT_FLASH=0, got args=%v", last.Args)
	}
}

func TestRunSOCWithoutFlashData(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()

	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{
		"BOOT/boot.img": "boot-data",
		"md5.txt":       "abc\n",
	})

	flow := Workflow{
		Product:   "SE7",
		FileName:  "fw.tgz",
		FlashData: false,
	}
	if err := e.runSOC(flow); err != nil {
		t.Fatalf("runSOC: %v", err)
	}
	calls := runner.calls_()
	if len(calls) == 0 {
		t.Fatal("expected at least 1 runner call")
	}
	last := calls[len(calls)-1]
	for _, a := range last.Args {
		if strings.Contains(a, "LAST_PART_NOT_FLASH") {
			t.Errorf("FlashData=false should NOT pass LAST_PART_NOT_FLASH, got args=%v", last.Args)
		}
	}
}
