package ota

import (
	"fmt"
	"path/filepath"
	"strings"

	"bmssm/logger"
)

// runPCIE 执行 PCIE（SC5/SC7）bm_firmware_update 刷机，对齐 bmssm runSC5Cmd。
// 命令：bm_firmware_update --dev=0xff --file=<pkgPath> --target=a53|mcu [--full]。
// file 路径：回滚用 backup/，升级用 bootrom/(a53) 或 firmware/(mcu)。
// 刷机成功后由 handleFlash 推进到 reboot 步骤（Strategy|=reboot）。
func (e *Engine) runPCIE(flow Workflow) error {
	if err := validatePCIECmdFlag(flow.CmdFlag); err != nil {
		return fmt.Errorf("pcie cmdFlag: %w", err)
	}

	target := pcieTarget(flow.ModuleName)
	pkgPath, err := e.pcieFilePath(flow, target)
	if err != nil {
		return fmt.Errorf("pcie file path: %w", err)
	}

	args := []string{"--dev=0xff", "--file=" + pkgPath, "--target=" + target}
	if pcieFull(flow.CmdFlag) {
		args = append(args, "--full")
	}
	logger.Info("ota: run pcie bm_firmware_update %v", args)
	_, stderr, err := e.runner("bm_firmware_update", args...)
	if err != nil {
		return fmt.Errorf("bm_firmware_update failed: %v: %s", err, stderr)
	}
	return nil
}

// pcieTarget 从 ModuleName 解析刷写目标，默认 a53。
func pcieTarget(moduleName string) string {
	switch strings.ToLower(strings.TrimSpace(moduleName)) {
	case "mcu":
		return "mcu"
	}
	return "a53"
}

// pcieFilePath 按 类型(回滚/升级) 与 target 选择包路径，对齐 bmssm 目录布局。
// 返回前对 FileName 做 sanitize 防路径穿越。
func (e *Engine) pcieFilePath(flow Workflow, target string) (string, error) {
	safe := sanitizeFileName(flow.FileName)
	if safe == "" {
		return "", fmt.Errorf("invalid file name: %q", flow.FileName)
	}
	if flow.Type == TypeRollback {
		return filepath.Join(e.paths.PCIEBackupDir, safe), nil
	}
	if target == "mcu" {
		return filepath.Join(e.paths.PCIEFirmwareDir, safe), nil
	}
	return filepath.Join(e.paths.PCIEBootromDir, safe), nil
}

// pcieFull 当 CmdFlag 含 "full" 时追加 --full（对齐 bmssm 全量刷写标志）。
func pcieFull(cmdFlag string) bool {
	return strings.Contains(strings.ToLower(cmdFlag), "full")
}
