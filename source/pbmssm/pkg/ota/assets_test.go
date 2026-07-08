package ota

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWriteAssets(t *testing.T) {
	dir := t.TempDir()
	if err := WriteAssets(dir); err != nil {
		t.Fatalf("WriteAssets: %v", err)
	}

	// ota.sh written, executable, non-empty, shebang
	otaPath := filepath.Join(dir, "ota.sh")
	info, err := os.Stat(otaPath)
	if err != nil {
		t.Fatalf("stat ota.sh: %v", err)
	}
	if info.Size() == 0 {
		t.Fatal("ota.sh is empty")
	}
	if info.Mode().Perm()&0o111 == 0 {
		t.Errorf("ota.sh not executable, mode=%v", info.Mode().Perm())
	}
	data, err := os.ReadFile(otaPath)
	if err != nil {
		t.Fatalf("read ota.sh: %v", err)
	}
	if !strings.HasPrefix(string(data), "#!") {
		t.Error("ota.sh should start with shebang")
	}

	// bc written under arm64_bin/, executable, ELF
	bcPath := filepath.Join(dir, "arm64_bin", "bc")
	bcInfo, err := os.Stat(bcPath)
	if err != nil {
		t.Fatalf("stat bc: %v", err)
	}
	if bcInfo.Size() == 0 {
		t.Fatal("bc is empty")
	}
	if bcInfo.Mode().Perm()&0o111 == 0 {
		t.Errorf("bc not executable, mode=%v", bcInfo.Mode().Perm())
	}
	bcData, err := os.ReadFile(bcPath)
	if err != nil {
		t.Fatalf("read bc: %v", err)
	}
	if len(bcData) < 4 || bcData[0] != 0x7f || bcData[1] != 'E' || bcData[2] != 'L' || bcData[3] != 'F' {
		t.Error("bc should be an ELF binary")
	}
}

func TestWriteAssetsIdempotent(t *testing.T) {
	dir := t.TempDir()
	if err := WriteAssets(dir); err != nil {
		t.Fatalf("first WriteAssets: %v", err)
	}
	// second call should not error (overwrite)
	if err := WriteAssets(dir); err != nil {
		t.Fatalf("second WriteAssets: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, "ota.sh")); err != nil {
		t.Errorf("ota.sh missing after second write: %v", err)
	}
}

func TestWriteAssetsMkdirFails(t *testing.T) {
	// pointing at an unreachable path under a file should fail
	dir := t.TempDir()
	filePath := filepath.Join(dir, "afile")
	if err := os.WriteFile(filePath, []byte("x"), 0o644); err != nil {
		t.Fatalf("setup: %v", err)
	}
	if err := WriteAssets(filepath.Join(filePath, "sub")); err == nil {
		t.Fatal("expected error when mkdir fails")
	}
}
