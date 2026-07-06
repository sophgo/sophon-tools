package software

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ----------------------------------------------------------------
// ListSoftware
// ----------------------------------------------------------------

func TestListSoftwareEmpty(t *testing.T) {
	dir := t.TempDir()
	svc := NewSoftwareService(dir, t.TempDir(), t.TempDir(), DefaultMaxSize)

	result, err := svc.ListSoftware()
	if err != nil {
		t.Fatalf("ListSoftware: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected 0, got %d", len(result))
	}
}

func TestListSoftwareNonExistent(t *testing.T) {
	svc := NewSoftwareService("/nonexistent/path/12345", t.TempDir(), t.TempDir(), DefaultMaxSize)

	result, err := svc.ListSoftware()
	if err != nil {
		t.Fatalf("ListSoftware on non-existent should return empty, not error: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected 0, got %d", len(result))
	}
}

func TestListSoftwareWithModules(t *testing.T) {
	root := t.TempDir()

	// 创建模块目录
	modA := filepath.Join(root, "module-a")
	modB := filepath.Join(root, "module-b")
	modC := filepath.Join(root, "module-c")
	os.MkdirAll(modA, 0o755)
	os.MkdirAll(modB, 0o755)
	os.MkdirAll(modC, 0o755)

	// 模块 A 有 VERSION 文件
	os.WriteFile(filepath.Join(modA, "VERSION"), []byte("1.2.3\n"), 0o644)
	// 模块 B 有 version 文件（多行）
	os.WriteFile(filepath.Join(modB, "version"), []byte("2.0.0\nbeta\n"), 0o644)
	// 模块 C 无版本文件

	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)
	result, err := svc.ListSoftware()
	if err != nil {
		t.Fatalf("ListSoftware: %v", err)
	}
	if len(result) != 3 {
		t.Fatalf("expected 3, got %d", len(result))
	}

	// 验证
	found := make(map[string]SoftwareInfo)
	for _, s := range result {
		found[s.Name] = s
	}

	if found["module-a"].Version != "1.2.3" {
		t.Errorf("module-a version: %s", found["module-a"].Version)
	}
	if found["module-b"].Version != "2.0.0" {
		t.Errorf("module-b version: %s", found["module-b"].Version)
	}
	if found["module-c"].Version != "unknown" {
		t.Errorf("module-c version: %s", found["module-c"].Version)
	}
}

func TestListSoftwareSkipsHiddenDirs(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, ".hidden"), 0o755)
	os.MkdirAll(filepath.Join(root, "visible"), 0o755)
	os.WriteFile(filepath.Join(root, "visible", "VERSION"), []byte("1.0\n"), 0o644)

	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)
	result, err := svc.ListSoftware()
	if err != nil {
		t.Fatalf("ListSoftware: %v", err)
	}
	if len(result) != 1 {
		t.Fatalf("expected 1 (hidden skipped), got %d", len(result))
	}
	if result[0].Name != "visible" {
		t.Errorf("expected 'visible', got '%s'", result[0].Name)
	}
}

func TestListSoftwareVersionFileVariants(t *testing.T) {
	root := t.TempDir()

	tests := []struct {
		dirName string
		verFile string
		content string
		expect  string
	}{
		{"p1", "VERSION", "1.0.0\n", "1.0.0"},
		{"p2", "version", "2.0.0", "2.0.0"},
		{"p3", "version.txt", "3.0.0\n", "3.0.0"},
		{"p4", ".version", "4.0.0", "4.0.0"},
		{"p5", "version.json", `{"version": "5.0.0"}`, `{"version": "5.0.0"}`},
	}

	for _, tt := range tests {
		os.MkdirAll(filepath.Join(root, tt.dirName), 0o755)
		os.WriteFile(filepath.Join(root, tt.dirName, tt.verFile), []byte(tt.content), 0o644)
	}

	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)
	result, err := svc.ListSoftware()
	if err != nil {
		t.Fatalf("ListSoftware: %v", err)
	}

	found := make(map[string]string)
	for _, s := range result {
		found[s.Name] = s.Version
	}

	for _, tt := range tests {
		if found[tt.dirName] != tt.expect {
			t.Errorf("%s: expected version '%s', got '%s'", tt.dirName, tt.expect, found[tt.dirName])
		}
	}
}

// ----------------------------------------------------------------
// 构建测试 tar.gz / zip
// ----------------------------------------------------------------

// createTestTarGz 创建含指定文件的 tar.gz。
func createTestTarGz(t *testing.T, files map[string]string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.tar.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create tar.gz: %v", err)
	}
	defer f.Close()

	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)

	for name, content := range files {
		hdr := &tar.Header{
			Name: name,
			Mode: 0o644,
			Size: int64(len(content)),
		}
		if strings.HasSuffix(name, "/") {
			hdr.Typeflag = tar.TypeDir
			hdr.Size = 0
		} else {
			hdr.Typeflag = tar.TypeReg
		}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatalf("tar write header %s: %v", name, err)
		}
		if !strings.HasSuffix(name, "/") {
			if _, err := tw.Write([]byte(content)); err != nil {
				t.Fatalf("tar write body %s: %v", name, err)
			}
		}
	}

	if err := tw.Close(); err != nil {
		t.Fatalf("tar close: %v", err)
	}
	if err := gw.Close(); err != nil {
		t.Fatalf("gzip close: %v", err)
	}
	return path
}

// createTestZip 创建含指定文件的 zip。
func createTestZip(t *testing.T, files map[string]string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.zip")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create zip: %v", err)
	}
	defer f.Close()

	zw := zip.NewWriter(f)
	for name, content := range files {
		if strings.HasSuffix(name, "/") {
			_, err := zw.Create(name)
			if err != nil {
				t.Fatalf("zip create dir %s: %v", name, err)
			}
		} else {
			w, err := zw.Create(name)
			if err != nil {
				t.Fatalf("zip create %s: %v", name, err)
			}
			if _, err := w.Write([]byte(content)); err != nil {
				t.Fatalf("zip write %s: %v", name, err)
			}
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("zip close: %v", err)
	}
	return path
}

// createMaliciousTarGz 创建含路径穿越的 tar.gz。
func createMaliciousTarGz(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "evil.tar.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create evil tar: %v", err)
	}
	defer f.Close()

	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)

	// 第一个条目：正常文件
	hdr := &tar.Header{
		Name:     "safe.txt",
		Mode:     0o644,
		Size:     5,
		Typeflag: tar.TypeReg,
	}
	tw.WriteHeader(hdr)
	tw.Write([]byte("hello"))

	// 第二个条目：路径穿越
	hdr2 := &tar.Header{
		Name:     "../../etc/passwd",
		Mode:     0o644,
		Size:     10,
		Typeflag: tar.TypeReg,
	}
	tw.WriteHeader(hdr2)
	tw.Write([]byte("hacked!!!"))

	tw.Close()
	gw.Close()
	return path
}

// ----------------------------------------------------------------
// 解包测试
// ----------------------------------------------------------------

func TestExtractTarGz(t *testing.T) {
	src := createTestTarGz(t, map[string]string{
		"app/":            "",
		"app/main":        "binary content",
		"app/config.json": `{"port": 8080}`,
	})
	dest := t.TempDir()

	if err := extractTarGz(src, dest); err != nil {
		t.Fatalf("extractTarGz: %v", err)
	}

	// 验证文件存在
	if data, err := os.ReadFile(filepath.Join(dest, "app", "main")); err != nil {
		t.Fatalf("read extracted main: %v", err)
	} else if string(data) != "binary content" {
		t.Errorf("expected 'binary content', got '%s'", string(data))
	}

	if data, err := os.ReadFile(filepath.Join(dest, "app", "config.json")); err != nil {
		t.Fatalf("read extracted config: %v", err)
	} else if string(data) != `{"port": 8080}` {
		t.Errorf("config mismatch: %s", string(data))
	}
}

func TestExtractZip(t *testing.T) {
	src := createTestZip(t, map[string]string{
		"app/":            "",
		"app/main":        "binary content",
		"app/config.json": `{"port": 8080}`,
	})
	dest := t.TempDir()

	if err := extractZip(src, dest); err != nil {
		t.Fatalf("extractZip: %v", err)
	}

	if data, err := os.ReadFile(filepath.Join(dest, "app", "main")); err != nil {
		t.Fatalf("read extracted main: %v", err)
	} else if string(data) != "binary content" {
		t.Errorf("expected 'binary content', got '%s'", string(data))
	}
}

// ----------------------------------------------------------------
// Zip-slip 防护
// ----------------------------------------------------------------

func TestExtractTarGzZipSlip(t *testing.T) {
	src := createMaliciousTarGz(t)
	dest := t.TempDir()

	err := extractTarGz(src, dest)
	if err == nil {
		t.Fatal("expected zip-slip error, got nil")
	}
	if !strings.Contains(err.Error(), "zip-slip") {
		t.Errorf("expected 'zip-slip' in error, got: %v", err)
	}
}

func TestExtractTarGzRejectsSymlink(t *testing.T) {
	// 创建含符号链接的 tar（symlink 条目应被跳过）
	path := filepath.Join(t.TempDir(), "symlink.tar.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	defer f.Close()

	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)

	hdr := &tar.Header{
		Name:     "link_to_passwd",
		Mode:     0o777,
		Size:     0,
		Typeflag: tar.TypeSymlink,
		Linkname: "/etc/passwd",
	}
	tw.WriteHeader(hdr)

	tw.Close()
	gw.Close()

	dest := t.TempDir()
	if err := extractTarGz(path, dest); err != nil {
		t.Fatalf("extractTarGz should not fail on symlink: %v", err)
	}
	// 符号链接不应被创建
	if _, err := os.Lstat(filepath.Join(dest, "link_to_passwd")); !os.IsNotExist(err) {
		t.Fatal("symlink should not be created")
	}
}

// ----------------------------------------------------------------
// InstallPackage（集成测试）
// ----------------------------------------------------------------

func TestInstallPackageTarGz(t *testing.T) {
	src := createTestTarGz(t, map[string]string{
		"bin/":     "",
		"bin/app":  "#!/bin/sh\necho hello",
		"VERSION":  "1.0.0\n",
	})
	root := t.TempDir()
	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)

	resp, err := svc.InstallPackage(src, "myapp-1.0.0.tar.gz")
	if err != nil {
		t.Fatalf("InstallPackage: %v", err)
	}
	if !resp.Success {
		t.Fatalf("expected success, got %+v", resp)
	}

	// 验证目录创建并解包
	if data, err := os.ReadFile(filepath.Join(root, "myapp-1.0.0", "VERSION")); err != nil {
		t.Fatalf("read VERSION: %v", err)
	} else if string(data) != "1.0.0\n" {
		t.Errorf("VERSION mismatch: %s", string(data))
	}

	// 验证软件列表中可见
	sw, _ := svc.ListSoftware()
	found := false
	for _, s := range sw {
		if s.Name == "myapp-1.0.0" && s.Version == "1.0.0" {
			found = true
		}
	}
	if !found {
		t.Error("installed package not found in software list")
	}
}

func TestInstallPackageTarGzWithInstallScript(t *testing.T) {
	src := createTestTarGz(t, map[string]string{
		"install.sh": "#!/bin/sh\necho 'install script ran'",
	})
	root := t.TempDir()
	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)

	resp, err := svc.InstallPackage(src, "scriptpkg.tar.gz")
	if err != nil {
		t.Fatalf("InstallPackage: %v", err)
	}
	if !resp.Success {
		t.Fatalf("expected success, got %+v", resp)
	}
	if !strings.Contains(resp.Output, "install script ran") {
		t.Errorf("expected 'install script ran' in output, got: %s", resp.Output)
	}
}

func TestInstallPackageZip(t *testing.T) {
	src := createTestZip(t, map[string]string{
		"data/":         "",
		"data/info.txt": "package info here",
	})
	root := t.TempDir()
	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)

	resp, err := svc.InstallPackage(src, "data-pkg.zip")
	if err != nil {
		t.Fatalf("InstallPackage: %v", err)
	}
	if !resp.Success {
		t.Fatalf("expected success, got %+v", resp)
	}

	if data, err := os.ReadFile(filepath.Join(root, "data-pkg", "data", "info.txt")); err != nil {
		t.Fatalf("read info.txt: %v", err)
	} else if string(data) != "package info here" {
		t.Errorf("content mismatch: %s", string(data))
	}
}

func TestInstallPackageUnsupportedFormat(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	_, err := svc.InstallPackage("/tmp/test.rar", "test.rar")
	if err == nil {
		t.Fatal("expected error for unsupported format")
	}
	if !strings.Contains(err.Error(), "unsupported") {
		t.Errorf("expected 'unsupported' in error, got: %v", err)
	}
}

func TestUpgradePackageSameAsInstall(t *testing.T) {
	src := createTestTarGz(t, map[string]string{
		"VERSION": "2.0.0\n",
	})
	root := t.TempDir()
	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)

	resp, err := svc.UpgradePackage(src, "upgrade-test.tar.gz")
	if err != nil {
		t.Fatalf("UpgradePackage: %v", err)
	}
	if !resp.Success {
		t.Fatalf("expected success, got %+v", resp)
	}
}

// ----------------------------------------------------------------
// OTA 固件
// ----------------------------------------------------------------

func TestUploadFirmwareSuccess(t *testing.T) {
	otaDir := t.TempDir()
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), otaDir, DefaultMaxSize)

	// 创建测试固件文件
	fwPath := filepath.Join(t.TempDir(), "firmware_v1.0.tgz")
	os.WriteFile(fwPath, []byte("dummy firmware"), 0o644)

	resp, err := svc.UploadFirmware(fwPath, "firmware_v1.0.tgz", 14)
	if err != nil {
		t.Fatalf("UploadFirmware: %v", err)
	}
	if resp.UploadID == "" {
		t.Fatal("uploadId should not be empty")
	}
	if resp.FileName != "firmware_v1.0.tgz" {
		t.Errorf("fileName: %s", resp.FileName)
	}
	if resp.FileSize != 14 {
		t.Errorf("fileSize: %d", resp.FileSize)
	}
	if resp.UploadID == "" {
		t.Fatal("uploadId should not be empty")
	}
}

func TestUploadFirmwareInvalidName(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	fwPath := filepath.Join(t.TempDir(), "evil.exe")
	os.WriteFile(fwPath, []byte("bad"), 0o644)

	_, err := svc.UploadFirmware(fwPath, "evil.exe", 3)
	if err == nil {
		t.Fatal("expected error for .exe firmware")
	}
	if !strings.Contains(err.Error(), "invalid firmware") {
		t.Errorf("expected 'invalid firmware', got: %v", err)
	}
}

func TestUploadFirmwarePathTraversal(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	fwPath := filepath.Join(t.TempDir(), "legit.tgz")
	os.WriteFile(fwPath, []byte("ok"), 0o644)

	_, err := svc.UploadFirmware(fwPath, "../../etc/passwd.tgz", 2)
	if err == nil {
		t.Fatal("expected error for path traversal firmware name")
	}
}

func TestGetFirmwareInfoFound(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	fwPath := filepath.Join(t.TempDir(), "testfw.tgz")
	os.WriteFile(fwPath, []byte("test firmware"), 0o644)

	uploadResp, _ := svc.UploadFirmware(fwPath, "testfw.tgz", 13)

	resp, err := svc.GetFirmwareInfo(uploadResp.UploadID)
	if err != nil {
		t.Fatalf("GetFirmwareInfo: %v", err)
	}
	if resp.Status != "uploaded" {
		t.Errorf("expected status 'uploaded', got '%s'", resp.Status)
	}
	if resp.FileName != "testfw.tgz" {
		t.Errorf("fileName: %s", resp.FileName)
	}
}

func TestGetFirmwareInfoNotFound(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	_, err := svc.GetFirmwareInfo("nonexistent")
	if err == nil {
		t.Fatal("expected error for nonexistent uploadId")
	}
}

// ----------------------------------------------------------------
// OTA 升级（含降级）
// ----------------------------------------------------------------

func TestExecuteUpgradeWithScript(t *testing.T) {
	// 创建含 upgrade.sh 的固件 tar.gz
	fwContent := map[string]string{
		"upgrade.sh": "#!/bin/sh\necho 'upgrade done'",
	}
	fwPath := createTestTarGz(t, fwContent)
	otaDir := t.TempDir()
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), otaDir, DefaultMaxSize)

	// 上传固件
	uploadResp, err := svc.UploadFirmware(fwPath, "fw_with_script.tgz", 100)
	if err != nil {
		t.Fatalf("UploadFirmware: %v", err)
	}

	// 执行升级
	resp, err := svc.ExecuteUpgrade(uploadResp.UploadID)
	if err != nil {
		t.Fatalf("ExecuteUpgrade: %v", err)
	}
	if !resp.Success {
		t.Errorf("expected success, got %+v", resp)
	}
	if !resp.Available {
		t.Errorf("expected available=true, got false")
	}
	if !strings.Contains(resp.Output, "upgrade done") {
		t.Errorf("expected 'upgrade done' in output, got: %s", resp.Output)
	}

	// 验证状态变为 completed
	info, _ := svc.GetFirmwareInfo(uploadResp.UploadID)
	if info.Status != "completed" {
		t.Errorf("expected status 'completed', got '%s'", info.Status)
	}
}

func TestExecuteUpgradeNoScriptDegraded(t *testing.T) {
	// 创建不含升级脚本的固件
	fwContent := map[string]string{
		"firmware.bin": "raw binary data",
	}
	fwPath := createTestTarGz(t, fwContent)
	otaDir := t.TempDir()
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), otaDir, DefaultMaxSize)

	uploadResp, err := svc.UploadFirmware(fwPath, "fw_no_script.tgz", 100)
	if err != nil {
		t.Fatalf("UploadFirmware: %v", err)
	}

	resp, err := svc.ExecuteUpgrade(uploadResp.UploadID)
	if err != nil {
		t.Fatalf("ExecuteUpgrade should not error on degraded: %v", err)
	}
	if resp.Available {
		t.Fatal("expected available=false for firmware without upgrade script")
	}
	if resp.Success {
		t.Fatal("expected success=false")
	}
}

func TestExecuteUpgradeWithInstallShInSubdir(t *testing.T) {
	// 固件包中 install.sh 在子目录中
	fwContent := map[string]string{
		"bootloader/":          "",
		"bootloader/install.sh": "#!/bin/sh\necho 'bootloader install ok'",
	}
	fwPath := createTestTarGz(t, fwContent)
	otaDir := t.TempDir()
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), otaDir, DefaultMaxSize)

	uploadResp, _ := svc.UploadFirmware(fwPath, "fw_subdir.tgz", 100)

	resp, err := svc.ExecuteUpgrade(uploadResp.UploadID)
	if err != nil {
		t.Fatalf("ExecuteUpgrade: %v", err)
	}
	if !resp.Available {
		t.Fatal("expected available=true for firmware with install.sh in subdir")
	}
	if !strings.Contains(resp.Output, "bootloader install ok") {
		t.Errorf("expected 'bootloader install ok', got: %s", resp.Output)
	}
}

func TestExecuteUpgradeNotFound(t *testing.T) {
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), DefaultMaxSize)

	_, err := svc.ExecuteUpgrade("nonexistent")
	if err == nil {
		t.Fatal("expected error for nonexistent uploadId")
	}
}

// ----------------------------------------------------------------
// 文件名校验
// ----------------------------------------------------------------

func TestIsValidFirmwareName(t *testing.T) {
	tests := []struct {
		name  string
		valid bool
	}{
		{"firmware_v1.0.tgz", true},
		{"update.bin", true},
		{"Firmware.TGZ", true},
		{"a.tgz", true},
		{"evil.exe", false},
		{"", false},
		{".", false},
		{"..", false},
		{"../etc/passwd.tgz", false},
		{"script.sh", false},
		{".tgz", false},
		{".bin", false},
		{"test.tar.gz", false}, // tar.gz 不在固件白名单
	}

	for _, tt := range tests {
		got := isValidFirmwareName(tt.name)
		if got != tt.valid {
			t.Errorf("isValidFirmwareName(%q) = %v, want %v", tt.name, got, tt.valid)
		}
	}
}

func TestIsValidPackageName(t *testing.T) {
	tests := []struct {
		name  string
		valid bool
	}{
		{"myapp-1.0.0.tar.gz", true},
		{"pkg.zip", true},
		{"app.deb", true},
		{"invalid file.deb", false},     // 含空格
		{"../../etc/passwd.deb", false}, // 路径穿越
		{"", false},
		{".", false},
		{"test;rm-rf.deb", false},    // shell 注入字符
		{"test$(whoami).deb", false}, // 命令注入
		{"my_app_v1.0.tgz", true},
		{"valid-name-v1.0.tar.gz", true},
	}

	for _, tt := range tests {
		got := isValidPackageName(tt.name)
		if got != tt.valid {
			t.Errorf("isValidPackageName(%q) = %v, want %v", tt.name, got, tt.valid)
		}
	}
}

func TestSanitizeFileName(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"test.tar.gz", "test.tar.gz"},
		{"../../../etc/passwd", "passwd"},
		{"/etc/shadow", "shadow"},
		{"normal.deb", "normal.deb"},
		{"dir/file.txt", "file.txt"},
	}

	for _, tt := range tests {
		got := sanitizeFileName(tt.input)
		if got != tt.expected {
			t.Errorf("sanitizeFileName(%q) = %q, want %q", tt.input, got, tt.expected)
		}
	}
}

// ----------------------------------------------------------------
// 辅助函数
// ----------------------------------------------------------------

func TestPackageName(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"app-1.0.tar.gz", "app-1.0"},
		{"app-1.0.tgz", "app-1.0"},
		{"app-1.0.zip", "app-1.0"},
		{"app-1.0.deb", "app-1.0"},
		{"simple", "simple"},
		{"path/to/app.tar.gz", "app"},
	}

	for _, tt := range tests {
		got := packageName(tt.input)
		if got != tt.expected {
			t.Errorf("packageName(%q) = %q, want %q", tt.input, got, tt.expected)
		}
	}
}

// ----------------------------------------------------------------
// 并发安全
// ----------------------------------------------------------------

func TestOtaRecordsConcurrency(t *testing.T) {
	otaDir := t.TempDir()
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), otaDir, DefaultMaxSize)

	fwPath := filepath.Join(t.TempDir(), "concurrent_test.tgz")
	os.WriteFile(fwPath, []byte("data"), 0o644)

	// 并发上传
	const goroutines = 10
	done := make(chan struct{}, goroutines)

	for i := range goroutines {
		go func(idx int) {
			defer func() { done <- struct{}{} }()
			uploadResp, err := svc.UploadFirmware(fwPath, "concurrent_test.tgz", 4)
			if err != nil {
				t.Errorf("goroutine %d upload error: %v", idx, err)
				return
			}
			if uploadResp.UploadID == "" {
				t.Errorf("goroutine %d empty uploadId", idx)
				return
			}
			// 并发查询
			info, err := svc.GetFirmwareInfo(uploadResp.UploadID)
			if err != nil {
				t.Errorf("goroutine %d GetFirmwareInfo: %v", idx, err)
				return
			}
			if info.Status != "uploaded" {
				t.Errorf("goroutine %d expected status 'uploaded', got '%s'", idx, info.Status)
			}
		}(i)
	}

	for range goroutines {
		<-done
	}
}

// ----------------------------------------------------------------
// isSafePath
// ----------------------------------------------------------------

func TestIsSafePath(t *testing.T) {
	tests := []struct {
		entry    string
		expected bool
	}{
		{"file.txt", true},
		{"dir/file.txt", true},
		{"../../etc/passwd", false},
		{"..", false},
		{"sub/../file.txt", false}, // 含 .. 直接拒绝
	}

	for _, tt := range tests {
		got := isSafePath("/tmp/dest", tt.entry)
		if got != tt.expected {
			t.Errorf("isSafePath(%q) = %v, want %v", tt.entry, got, tt.expected)
		}
	}
}
