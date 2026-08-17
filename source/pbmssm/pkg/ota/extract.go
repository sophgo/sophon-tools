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

// 解压上限（var 便于测试覆盖调小）：
//   - maxExtractSize    单条目大小上限（1GiB）
//   - maxExtractTotal   累计解压总量上限（2GiB，与 mvc/software maxExtractBytes 同口径）——防恶意/损坏
//     .tgz 用海量条目撑爆 /data 分区（MYS-389）
//   - maxExtractEntries 条目数上限（防海量小文件占满 inode）
var (
	maxExtractSize    = int64(1 << 30)
	maxExtractTotal   = int64(2 << 30)
	maxExtractEntries = 10000
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

// extractTarGz 解压 tar.gz 到 destDir，含 zip-slip 防护、拒绝符号链接、
// 单条目/累计总量/条目数三重上限（防解压炸弹撑爆分区）。
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
	var total, entries int64
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}
		entries++
		if entries > int64(maxExtractEntries) {
			return fmt.Errorf("extraction exceeds entry count limit (%d)", maxExtractEntries)
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
			// CopyN 上限取 maxExtractSize+1：条目超过单条目上限时复制量恰好超过
			// 上限并返回 nil（达到 limit），据此报错而非静默截断文件（旧实现把
			// 超限条目截断为 1GiB，且剩余数据被吞导致后续条目解析错乱）。
			n, err := io.CopyN(out, tarReader, maxExtractSize+1)
			out.Close()
			if err != nil && err != io.EOF {
				return err
			}
			if n > maxExtractSize {
				return fmt.Errorf("entry %s exceeds size limit (%d bytes)", header.Name, maxExtractSize)
			}
			total += n
			if total > maxExtractTotal {
				return fmt.Errorf("extraction exceeds total size limit (%d bytes)", maxExtractTotal)
			}
		case tar.TypeSymlink:
			// 拒绝符号链接（安全考虑）
			continue
		}
	}
	return nil
}
