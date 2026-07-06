package ota

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ---------------------------------------------------------------
// isValidOTAPkg 白名单
// ---------------------------------------------------------------

func TestIsValidOTAPkg(t *testing.T) {
	cases := []struct {
		name  string
		valid bool
	}{
		{"fw.tgz", true},
		{"fw.TGZ", true},
		{"firmware.tar.gz", true},
		{"a.tgz", true},
		{"evil.exe", false},
		{"fw.bin", false},
		{"", false},
		{".", false},
		{"..", false},
		{"../etc/passwd.tgz", false}, // 路径穿越
		{".tgz", false},              // 无主体名
		{".tar.gz", false},
		{"script.sh", false},
	}
	for _, tt := range cases {
		if got := isValidOTAPkg(tt.name); got != tt.valid {
			t.Errorf("isValidOTAPkg(%q) = %v, want %v", tt.name, got, tt.valid)
		}
	}
}

// ---------------------------------------------------------------
// moduleDestDir 分目录
// ---------------------------------------------------------------

func TestModuleDestDir(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	cases := []struct {
		module string
		want   string
	}{
		{"soc", e.paths.SOCOTADir},
		{"ctrl", e.paths.CtrlOTADir},
		{"controller", e.paths.CtrlOTADir},
		{"core", e.paths.CoreTftpDir},
		{"SOC", e.paths.SOCOTADir}, // 大小写不敏感
	}
	for _, tt := range cases {
		got, err := e.moduleDestDir(tt.module)
		if err != nil {
			t.Errorf("moduleDestDir(%q) err: %v", tt.module, err)
		}
		if got != tt.want {
			t.Errorf("moduleDestDir(%q) = %q, want %q", tt.module, got, tt.want)
		}
	}
	if _, err := e.moduleDestDir("invalid"); err == nil {
		t.Error("expected error for invalid module")
	}
}

// ---------------------------------------------------------------
// OTAUpload 端到端
// ---------------------------------------------------------------

func TestOTAUploadSOC(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()

	// 准备源文件
	srcDir := t.TempDir()
	src := filepath.Join(srcDir, "tmp_fw.tgz")
	os.WriteFile(src, []byte("package-content"), 0o644)

	dest, err := e.OTAUpload("soc", "fw.tgz", src, 15)
	if err != nil {
		t.Fatalf("OTAUpload: %v", err)
	}
	want := filepath.Join(e.paths.SOCOTADir, "fw.tgz")
	if dest != want {
		t.Errorf("dest = %q, want %q", dest, want)
	}
	data, err := os.ReadFile(dest)
	if err != nil {
		t.Fatalf("read saved: %v", err)
	}
	if string(data) != "package-content" {
		t.Errorf("saved content mismatch: %q", string(data))
	}
}

func TestOTAUploadCore(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.CoreTftpDir = t.TempDir()
	src := filepath.Join(t.TempDir(), "tmp_core.tgz")
	os.WriteFile(src, []byte("core-pkg"), 0o644)

	dest, err := e.OTAUpload("core", "core_fw.tgz", src, 8)
	if err != nil {
		t.Fatalf("OTAUpload: %v", err)
	}
	if !strings.HasSuffix(dest, "core_fw.tgz") {
		t.Errorf("dest = %q", dest)
	}
	if filepath.Dir(dest) != e.paths.CoreTftpDir {
		t.Errorf("dest dir = %q, want %q", filepath.Dir(dest), e.paths.CoreTftpDir)
	}
}

func TestOTAUploadInvalidModule(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	src := filepath.Join(t.TempDir(), "x.tgz")
	os.WriteFile(src, []byte("x"), 0o644)
	_, err := e.OTAUpload("bogus", "fw.tgz", src, 1)
	if err == nil || !strings.Contains(err.Error(), "module") {
		t.Fatalf("expected module error, got %v", err)
	}
}

func TestOTAUploadInvalidPkg(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	src := filepath.Join(t.TempDir(), "x")
	os.WriteFile(src, []byte("x"), 0o644)
	_, err := e.OTAUpload("soc", "firmware.exe", src, 1)
	if err == nil || !strings.Contains(err.Error(), "invalid ota package") {
		t.Fatalf("expected invalid pkg error, got %v", err)
	}
}

func TestOTAUploadPathTraversal(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	src := filepath.Join(t.TempDir(), "x")
	os.WriteFile(src, []byte("x"), 0o644)
	_, err := e.OTAUpload("soc", "../../etc/passwd.tgz", src, 1)
	if err == nil {
		t.Fatal("expected error for path traversal")
	}
}

func TestOTAUploadDiskFull(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.diskUsageFn = func(string) (float64, error) { return 0.99, nil }

	src := filepath.Join(t.TempDir(), "x")
	os.WriteFile(src, []byte("x"), 0o644)
	_, err := e.OTAUpload("soc", "fw.tgz", src, 1)
	if err == nil || !strings.Contains(err.Error(), "full") {
		t.Fatalf("expected disk full error, got %v", err)
	}
	// 不应落盘
	if _, err := os.Stat(filepath.Join(e.paths.SOCOTADir, "fw.tgz")); !os.IsNotExist(err) {
		t.Errorf("file should not be saved when disk full: %v", err)
	}
}

func TestOTAUploadMissingSrc(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	_, err := e.OTAUpload("soc", "fw.tgz", "/nonexistent/src.tgz", 1)
	if err == nil {
		t.Fatal("expected error for missing source")
	}
}
