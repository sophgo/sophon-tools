package ota

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeTarGz 构造 tar.gz 字节流：entries 形如 map[名字]内容。
func writeTarGz(t *testing.T, entries map[string]string) []byte {
	t.Helper()
	buf := new(bytes.Buffer)
	gw := gzip.NewWriter(buf)
	tw := tar.NewWriter(gw)
	for name, content := range entries {
		hdr := &tar.Header{Name: name, Mode: 0o644, Typeflag: tar.TypeReg, Size: int64(len(content))}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatalf("header: %v", err)
		}
		if _, err := tw.Write([]byte(content)); err != nil {
			t.Fatalf("write: %v", err)
		}
	}
	tw.Close()
	gw.Close()
	return buf.Bytes()
}

func extractBytes(t *testing.T, data []byte, destDir string) error {
	t.Helper()
	filePath := filepath.Join(t.TempDir(), "pkg.tgz")
	if err := os.WriteFile(filePath, data, 0o644); err != nil {
		t.Fatalf("write tarball: %v", err)
	}
	return extractTarGz(filePath, destDir)
}

func TestExtractTotalSizeLimit(t *testing.T) {
	old := maxExtractTotalBytes
	maxExtractTotalBytes = 48 // 3×20B 内容 → 超 48 累计上限
	defer func() { maxExtractTotalBytes = old }()

	entries := map[string]string{
		"a.txt": strings.Repeat("a", 20),
		"b.txt": strings.Repeat("b", 20),
		"c.txt": strings.Repeat("c", 20),
	}
	err := extractBytes(t, writeTarGz(t, entries), t.TempDir())
	if err == nil {
		t.Fatal("expected total-size-limit error, got nil")
	}
	if !strings.Contains(err.Error(), "total size limit") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestExtractEntryCountLimit(t *testing.T) {
	old := maxExtractEntries
	maxExtractEntries = 3
	defer func() { maxExtractEntries = old }()

	entries := map[string]string{}
	for i := 0; i < 5; i++ {
		entries[fmt.Sprintf("f%d.txt", i)] = "x"
	}
	err := extractBytes(t, writeTarGz(t, entries), t.TempDir())
	if err == nil {
		t.Fatal("expected entry-count-limit error, got nil")
	}
	if !strings.Contains(err.Error(), "entry count limit") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestExtractNormalWithinLimits(t *testing.T) {
	entries := map[string]string{
		"sub/a.txt": "hello",
		"b.txt":     "world",
	}
	dest := t.TempDir()
	if err := extractBytes(t, writeTarGz(t, entries), dest); err != nil {
		t.Fatalf("normal extract failed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dest, "sub", "a.txt")); err != nil {
		t.Fatalf("a.txt missing: %v", err)
	}
	body, err := os.ReadFile(filepath.Join(dest, "b.txt"))
	if err != nil || string(body) != "world" {
		t.Fatalf("b.txt = %q err=%v", body, err)
	}
}

// TestExtractSingleEntrySizeLimit 单条目超过上限必须报错（而非静默截断为 1GiB
// 并把剩余数据吞掉——旧实现缺陷，MYS-389 一并修复）。
func TestExtractSingleEntrySizeLimit(t *testing.T) {
	old := maxExtractSize
	maxExtractSize = 100
	defer func() { maxExtractSize = old }()
	oldTotal := maxExtractTotalBytes
	maxExtractTotalBytes = 1 << 20
	defer func() { maxExtractTotalBytes = oldTotal }()

	err := extractBytes(t, writeTarGz(t, map[string]string{
		"big.bin": strings.Repeat("x", 200),
	}), t.TempDir())
	if err == nil {
		t.Fatal("expected single entry size limit error, got nil")
	}
	if !strings.Contains(err.Error(), "exceeds size limit") {
		t.Fatalf("unexpected error: %v", err)
	}
}
