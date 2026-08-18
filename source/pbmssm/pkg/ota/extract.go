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

// 解压上限（var 便于测试注入小值，生产常量等价）：
//   - maxExtractSize      单个解压条目大小上限（1GiB）
//   - maxExtractTotalBytes 单次解包累计解压上限（与 software 侧同口径 2GiB），
//     防大量条目累计撑爆磁盘（MYS-389）
//   - maxExtractEntries   单次解包条目数上限，防"百万小文件"耗尽 inode（MYS-389）
var (
	maxExtractSize       = int64(1 << 30)
	maxExtractTotalBytes = int64(2 << 30)
	maxExtractEntries    = 8192
)

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
	var totalBytes int64
	var entries int
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
			// 单条目限制 + 累计总量限制（防 tar 炸弹）。
			// CopyN 上限取 maxExtractSize+1：条目超过单条目上限时复制量恰好
			// 超过上限并返回 nil（达到 limit），据此报错而非静默截断为 1GiB
			// （旧实现还会把剩余数据吞掉导致后续条目解析错乱）。
			n, err := io.CopyN(out, tarReader, maxExtractSize+1)
			out.Close()
			if err != nil && err != io.EOF {
				return err
			}
			if n > maxExtractSize {
				return fmt.Errorf("entry %s exceeds size limit (%d bytes)", header.Name, int64(maxExtractSize))
			}
			totalBytes += n
			if totalBytes > maxExtractTotalBytes {
				return fmt.Errorf("extraction exceeds total size limit (%d bytes)", maxExtractTotalBytes)
			}
		case tar.TypeSymlink:
			// 拒绝符号链接（安全考虑）
			continue
		}
		entries++
		if entries > maxExtractEntries {
			return fmt.Errorf("extraction exceeds entry count limit (%d)", maxExtractEntries)
		}
	}
	return nil
}
