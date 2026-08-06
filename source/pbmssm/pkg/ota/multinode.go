package ota

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"bmssm/logger"
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
	var args []string
	if cmd == "" {
		// 默认命令：本机 local_update.sh（内部可信路径，已 chmod +x），参数化执行。
		args = []string{localSh, "md5.txt", "0"}
	} else {
		var err error
		args, err = splitCmdFlag(cmd)
		if err != nil {
			return fmt.Errorf("ctrl cmdFlag: %w", err)
		}
	}
	logger.Info("ota: run multinode ctrl upgrade: %v", args)
	_, stderr, err := e.runner(args[0], args[1:]...)
	if err != nil {
		return fmt.Errorf("local_update.sh failed: %v: %s", err, stderr)
	}
	return nil
}

// runMultiNodeCore 对齐 bmssm UpgradeAllCores：经 ssh 远程跑 mk_bootscr.sh。
// CmdFlag 经白名单校验后参数化执行（不经 bash -c，杜绝命令注入）；为空跑默认命令。
func (e *Engine) runMultiNodeCore(flow Workflow) error {
	cmd := flow.CmdFlag
	var args []string
	if cmd == "" {
		args = []string{"/data/ota/local_update.sh", "md5.txt", "0"}
	} else {
		var err error
		args, err = splitCmdFlag(cmd)
		if err != nil {
			return fmt.Errorf("core cmdFlag: %w", err)
		}
	}
	logger.Info("ota: run multinode core upgrade: %v", args)
	_, stderr, err := e.runner(args[0], args[1:]...)
	if err != nil {
		return fmt.Errorf("core upgrade failed: %v: %s", err, stderr)
	}
	return nil
}

// splitCmdFlag 校验并拆分 CmdFlag 为参数化命令（名称 + 参数）。
// 首 token 必须是白名单命令；其余 token 仅允许安全字符（路径/标识符/参数）。
// 返回 args[0]=命令名、args[1:]=参数，调用方用 e.runner(args[0], args[1:]...) 直接执行，
// 不经 shell——从而消除 bash -c 交给解释器执行的注入面。
func splitCmdFlag(cmd string) ([]string, error) {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return nil, fmt.Errorf("empty cmdFlag")
	}
	fields := strings.Fields(cmd)
	if len(fields) == 0 {
		return nil, fmt.Errorf("empty cmdFlag")
	}
	name := fields[0]
	allowed := false
	for _, p := range allowedCmdPrefixes {
		if name == p {
			allowed = true
			break
		}
	}
	if !allowed {
		return nil, fmt.Errorf("cmdFlag %q is not in the allowed command whitelist", name)
	}
	for _, tok := range fields[1:] {
		for _, r := range tok {
			if !isSafeFlagRune(r) {
				return nil, fmt.Errorf("cmdFlag argument %q contains unsafe characters", tok)
			}
		}
	}
	// ssh 特判：参数[1]=远程主机，远程命令（参数[2:]）必须是已知升级脚本，
	// 防止把 ssh 变成任意远程命令执行原语（如 ssh root@host rm -rf /）。
	if name == "ssh" {
		if len(fields) < 2 {
			return nil, fmt.Errorf("ssh cmdFlag: missing remote host")
		}
		if len(fields) < 3 {
			return nil, fmt.Errorf("ssh cmdFlag: missing remote command")
		}
		remote := strings.Join(fields[2:], " ")
		ok := false
		for _, rp := range []string{"mk_bootscr.sh", "/data/ota/local_update.sh", "bm_firmware_update"} {
			if remote == rp || strings.HasPrefix(remote, rp+" ") {
				ok = true
				break
			}
		}
		if !ok {
			return nil, fmt.Errorf("ssh cmdFlag: remote command %q not allowed", remote)
		}
	}
	return fields, nil
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
