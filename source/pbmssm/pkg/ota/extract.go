package ota

import (
	"archive/tar"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// errZipSlip zip-slip / 路径穿越检测。
var errZipSlip = errors.New("zip-slip detected: entry path escapes destination directory")

// maxExtractSize 单个解压条目大小上限（1GiB），防解压炸弹。
const maxExtractSize = 1 << 30

// isSafeEntry 检查 tar 条目路径是否安全（解析后仍在 destDir 内）。
func isSafeEntry(destDir, entryPath string) bool {
	if strings.Contains(entryPath, "..") {
		return false
	}
	cleaned := filepath.Clean(entryPath)
	if strings.Contains(cleaned, "..") {
		return false
	}
	absDest, err := filepath.Abs(destDir)
	if err != nil {
		return false
	}
	absResolved, err := filepath.Abs(filepath.Join(destDir, cleaned))
	if err != nil {
		return false
	}
	return strings.HasPrefix(absResolved, absDest+string(filepath.Separator)) || absResolved == absDest
}

// extractTarGz 解压 tar.gz 到 destDir，含 zip-slip 防护、拒绝符号链接、解压大小上限。
func extractTarGz(filePath, destDir string) error {
	f, err := os.Open(filePath)
	if err != nil {
		return err
	}
	defer f.Close()

	gzReader, err := gzip.NewReader(f)
	if err != nil {
		return fmt.Errorf("gzip reader: %w", err)
	}
	defer gzReader.Close()

	tarReader := tar.NewReader(gzReader)
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}
		if !isSafeEntry(destDir, header.Name) {
			return fmt.Errorf("%w: %s", errZipSlip, header.Name)
		}
		target := filepath.Join(destDir, filepath.Clean(header.Name))

		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			out, err := os.Create(target)
			if err != nil {
				return err
			}
			if _, err := io.CopyN(out, tarReader, maxExtractSize); err != nil && err != io.EOF {
				out.Close()
				return err
			}
			out.Close()
		case tar.TypeSymlink:
			// 拒绝符号链接（安全考虑）
			continue
		}
	}
	return nil
}
