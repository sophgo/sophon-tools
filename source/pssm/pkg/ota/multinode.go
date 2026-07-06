package ota

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"ssm/logger"
)

// runMultiNode 执行多节点（SE6/SE8）升级，对齐 bmssm runSE6Cmd。
//
//	controller/ctrl → UpgradeCtrl（local_update.sh）
//	core            → UpgradeAllCores/UpgradeSingleCore（远程 ssh）
func (e *Engine) runMultiNode(flow Workflow) error {
	switch strings.ToLower(strings.TrimSpace(flow.ModuleName)) {
	case "controller", "ctrl":
		return e.runMultiNodeCtrl(flow)
	case "core":
		return e.runMultiNodeCore(flow)
	default:
		return fmt.Errorf("multinode: unknown module %q (want core/controller)", flow.ModuleName)
	}
}

// runMultiNodeCtrl 对齐 bmssm UpgradeCtrl：df 查根盘不满，chmod +x local_update.sh，
// 跑 cmd（默认 /data/ota/local_update.sh md5.txt 0）。
func (e *Engine) runMultiNodeCtrl(flow Workflow) error {
	used, err := e.diskUsageFn(e.paths.DiskCheckPath)
	if err != nil {
		return fmt.Errorf("disk usage check: %w", err)
	}
	if used > 0.95 {
		return fmt.Errorf("root disk nearly full (%.0f%%), abort upgrade", used*100)
	}

	localSh := filepath.Join(e.paths.CtrlOTADir, "local_update.sh")
	if err := os.Chmod(localSh, 0o755); err != nil {
		// 文件可能尚未就绪，best-effort 警告
		logger.Warn("ota: chmod %s failed: %v", localSh, err)
	}

	cmd := flow.CmdFlag
	if cmd == "" {
		cmd = localSh + " md5.txt 0"
	} else {
		if err := validateCmdFlag(cmd); err != nil {
			return fmt.Errorf("ctrl cmdFlag: %w", err)
		}
	}
	logger.Info("ota: run multinode ctrl upgrade: %s", cmd)
	_, stderr, err := e.runner("bash", "-c", cmd)
	if err != nil {
		return fmt.Errorf("local_update.sh failed: %v: %s", err, stderr)
	}
	return nil
}

// runMultiNodeCore 对齐 bmssm UpgradeAllCores：经 ssh_anycmd.exp 远程跑 mk_bootscr.sh。
// CmdFlag 经白名单校验后执行；为空则跑默认 /data/ota/local_update.sh md5.txt 0（对齐 bmssm）。
func (e *Engine) runMultiNodeCore(flow Workflow) error {
	cmd := flow.CmdFlag
	if cmd == "" {
		cmd = "/data/ota/local_update.sh md5.txt 0"
	} else {
		if err := validateCmdFlag(cmd); err != nil {
			return fmt.Errorf("core cmdFlag: %w", err)
		}
	}
	logger.Info("ota: run multinode core upgrade: %s", cmd)
	_, stderr, err := e.runner("bash", "-c", cmd)
	if err != nil {
		return fmt.Errorf("core upgrade failed: %v: %s", err, stderr)
	}
	return nil
}

// diskUsage 返回路径的已用空间比例（0..1），基于 syscall.Statfs。
func diskUsage(path string) (float64, error) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(path, &stat); err != nil {
		return 0, err
	}
	if stat.Blocks == 0 {
		return 0, nil
	}
	used := float64(stat.Blocks-stat.Bfree) / float64(stat.Blocks)
	return used, nil
}
