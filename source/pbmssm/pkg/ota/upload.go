package ota

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"bmssm/logger"
)

// OTAUpload 校验并保存 OTA 刷机包到 module 对应目录。
//
//	module: soc/core/ctrl(controller) —— soc/ctrl→/data/ota，core→/recovery/tftp
//	origName: 原始文件名（仅 .tgz/.tar.gz 白名单）
//	srcPath: multipart 已落盘的临时文件路径
//	size: 文件大小（字节）
//
// 返回保存后的绝对路径。执行 .tgz 白名单、磁盘空间预检、mkdir、复制。
func (e *Engine) OTAUpload(module, origName, srcPath string, size int64) (string, error) {
	destDir, err := e.moduleDestDir(module)
	if err != nil {
		return "", err
	}
	if !isValidOTAPkg(origName) {
		return "", fmt.Errorf("invalid ota package: %s (allowed: .tgz, .tar.gz)", origName)
	}

	// 磁盘空间预检：优先检查目标目录所在分区，失败回退到配置的检查路径。
	used, err := e.diskUsageFn(destDir)
	if err != nil {
		used, _ = e.diskUsageFn(e.paths.DiskCheckPath)
	}
	if used > 0.95 {
		return "", fmt.Errorf("destination disk nearly full (%.0f%%), abort upload", used*100)
	}

	if err := os.MkdirAll(destDir, 0o755); err != nil {
		return "", fmt.Errorf("mkdir dest %s: %w", destDir, err)
	}
	dest := filepath.Join(destDir, filepath.Base(origName))
	if err := copyFileOta(srcPath, dest); err != nil {
		return "", fmt.Errorf("save package: %w", err)
	}
	logger.Info("ota: uploaded package %s (%d bytes) → %s", origName, size, dest)
	return dest, nil
}

// moduleDestDir 将 module 映射到目标目录。
func (e *Engine) moduleDestDir(module string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(module)) {
	case "soc":
		return e.paths.SOCOTADir, nil
	case "ctrl", "controller":
		return e.paths.CtrlOTADir, nil
	case "core":
		return e.paths.CoreTftpDir, nil
	}
	return "", fmt.Errorf("invalid module %q (want soc/core/ctrl)", module)
}

// isValidOTAPkg 校验 OTA 包文件名：仅 .tgz/.tar.gz，basename，无路径穿越。
func isValidOTAPkg(name string) bool {
	base := filepath.Base(name)
	if base != name || base == "" || base == "." || base == ".." {
		return false
	}
	lower := strings.ToLower(base)
	if !strings.HasSuffix(lower, ".tgz") && !strings.HasSuffix(lower, ".tar.gz") {
		return false
	}
	// 至少有一个字符在扩展名前
	return len(base) > 4 && !strings.HasPrefix(lower, ".tgz") && !strings.HasPrefix(lower, ".tar.gz")
}

// copyFileOta 复制文件。
func copyFileOta(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
