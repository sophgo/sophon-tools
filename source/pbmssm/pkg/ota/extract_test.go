package ota

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ---------------------------------------------------------------
// 解压上限测试（MYS-389）：累计总量 / 条目数 / 单条目
// 通过临时调小包级上限变量构造小额触发用例，避免写真实 2GiB 数据。
// ---------------------------------------------------------------

// makeTarGz 构造含 entries（name -> content）的 tar.gz 并落盘。
func makeTarGz(t *testing.T, files map[string][]byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "pkg.tar.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()

	gw := gzip.NewWriter(f)
	tw := tar.NewWriter(gw)
	for name, content := range files {
		hdr := &tar.Header{Name: name, Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(content); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gw.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

// withExtractLimits 临时覆盖解压上限，用例结束后恢复。
func withExtractLimits(t *testing.T, size, total, entries int64) {
	t.Helper()
	oldSize, oldTotal, oldEntries := maxExtractSize, maxExtractTotal, maxExtractEntries
	maxExtractSize, maxExtractTotal, maxExtractEntries = size, total, int(entries)
	t.Cleanup(func() {
		maxExtractSize, maxExtractTotal, maxExtractEntries = oldSize, oldTotal, oldEntries
	})
}

func TestExtractNormalWithinLimits(t *testing.T) {
	src := makeTarGz(t, map[string][]byte{
		"a.txt": []byte("aaa"),
		"b.txt": []byte("bbbb"),
	})
	dest := t.TempDir()
	if err := extractTarGz(src, dest); err != nil {
		t.Fatalf("extractTarGz: %v", err)
	}
	if data, err := os.ReadFile(filepath.Join(dest, "a.txt")); err != nil || string(data) != "aaa" {
		t.Fatalf("a.txt: %q err=%v", data, err)
	}
	if data, err := os.ReadFile(filepath.Join(dest, "b.txt")); err != nil || string(data) != "bbbb" {
		t.Fatalf("b.txt: %q err=%v", data, err)
	}
}

func TestExtractTotalSizeLimit(t *testing.T) {
	// 累计上限 100 字节：两个 60 字节文件累计 120 超限
	withExtractLimits(t, 1<<20, 100, 10000)
	dest := t.TempDir()
	path := makeTarGz(t, map[string][]byte{
		"one.txt":   make([]byte, 60),
		"two/f.txt": make([]byte, 60),
	})
	if err := extractTarGz(path, dest); err == nil {
		t.Fatal("expected total size limit error, got nil")
	} else if !strings.Contains(err.Error(), "total size limit") {
		t.Errorf("expected 'total size limit' in error, got: %v", err)
	}
}

func TestExtractEntryCountLimit(t *testing.T) {
	withExtractLimits(t, 1<<20, 1<<20, 3)
	path := makeTarGz(t, map[string][]byte{
		"1.txt": []byte("1"),
		"2.txt": []byte("2"),
		"3.txt": []byte("3"),
		"4.txt": []byte("4"),
	})
	dest := t.TempDir()
	if err := extractTarGz(path, dest); err == nil {
		t.Fatal("expected entry count limit error, got nil")
	} else if !strings.Contains(err.Error(), "entry count limit") {
		t.Errorf("expected 'entry count limit' in error, got: %v", err)
	}
}

func TestExtractSingleEntrySizeLimit(t *testing.T) {
	// 单条目上限 100 字节：一条 200 字节文件超限（旧实现会静默截断为 100，不报错）
	withExtractLimits(t, 100, 1<<20, 10000)
	path := makeTarGz(t, map[string][]byte{
		"big.bin": make([]byte, 200),
	})
	dest := t.TempDir()
	if err := extractTarGz(path, dest); err == nil {
		t.Fatal("expected single entry size limit error, got nil")
	} else if !strings.Contains(err.Error(), "exceeds size limit") {
		t.Errorf("expected 'exceeds size limit' in error, got: %v", err)
	}
}
