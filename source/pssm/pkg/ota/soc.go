package ota

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"ssm/logger"
)

// runSOC 执行 SOC（SE5/SE7/SE9）pota_update 刷机方案。
// 流程：PrepareSOC（解压 .tgz + 写 ota.sh/bc）→ RunSOC（sudo bash ota.sh，
// 立即返回）→ 标记 Running → 启动 pollSOC 轮询 /dev/shm 标志推进到 Success/Fail。
// ota.sh 自带 reboot，不需要额外重启步骤。
func (e *Engine) runSOC(flow Workflow) error {
	safeName := sanitizeFileName(flow.FileName)
	if safeName == "" {
		return fmt.Errorf("invalid file name: %q", flow.FileName)
	}
	workDir := filepath.Join(e.paths.SOCWorkRoot, flow.WorkflowID)
	pkgFile := filepath.Join(e.paths.SOCOTADir, safeName)

	if err := PrepareSOC(workDir, pkgFile); err != nil {
		return fmt.Errorf("prepare soc: %w", err)
	}
	lastPartNotFlash := !flow.FlashData
	if err := e.RunSOC(workDir, lastPartNotFlash); err != nil {
		return fmt.Errorf("run soc ota.sh: %w", err)
	}

	// ota.sh 已通过 systemd-run 异步起服务并立即返回；标记 Running，启动轮询。
	e.updateStatus(flow.ID, StatusRunning, "ota.sh launched, polling status")
	go e.pollSOC(flow)
	return nil
}

// PrepareSOC 解压 .tgz 刷机包到 workDir（zip-slip 防护）并就地写入 ota.sh + arm64_bin/bc。
// pkgFile 为上传的 .tgz 路径，workDir 为解压目标（与 ota.sh 同级，供其定位刷机文件）。
func PrepareSOC(workDir, pkgFile string) error {
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return fmt.Errorf("mkdir workdir: %w", err)
	}
	if err := extractTarGz(pkgFile, workDir); err != nil {
		return fmt.Errorf("extract package: %w", err)
	}
	if err := WriteAssets(workDir); err != nil {
		return fmt.Errorf("write ota assets: %w", err)
	}
	return nil
}

// RunSOC 执行 `sudo bash <workDir>/ota.sh [LAST_PART_NOT_FLASH=0]`。
// ota.sh 自身用 systemd-run 异步起服务并立即返回；调用方据此标记 Running。
// lastPartNotFlash=true（默认）不传参，保留 data 分区；false 传 LAST_PART_NOT_FLASH=0。
func (e *Engine) RunSOC(workDir string, lastPartNotFlash bool) error {
	script := filepath.Join(workDir, "ota.sh")
	args := []string{"bash", script}
	if !lastPartNotFlash {
		args = append(args, "LAST_PART_NOT_FLASH=0")
	}
	logger.Info("ota: run soc ota.sh: sudo %v (workDir=%s)", args, workDir)
	_, stderr, err := e.runner("sudo", args...)
	if err != nil {
		return fmt.Errorf("ota.sh failed: %v: %s", err, stderr)
	}
	return nil
}

// StatusSOC 检查 /dev/shm 标志返回当前 SOC OTA 状态与信息。
// dryRun 时直接返 Success。success 标志存在→Success；error 标志存在→Fail（读日志末尾作 Info）；
// 都不存在→Running。
func (e *Engine) StatusSOC() (status int, info string) {
	if e.dryRun {
		return StatusSuccess, "dryRun: simulated success"
	}
	if e.flags.Exists(e.paths.SuccessFlag) {
		return StatusSuccess, ""
	}
	if e.flags.Exists(e.paths.ErrorFlag) {
		return StatusFail, e.flags.ReadPanicLine(e.paths.ShellLog)
	}
	return StatusRunning, ""
}

// pollOnce 调用一次 StatusSOC，返回状态、信息与是否到达终态。
func (e *Engine) pollOnce(flow Workflow) (status int, info string, done bool) {
	st, info := e.StatusSOC()
	if st == StatusRunning {
		return st, info, false
	}
	return st, info, true
}

// pollSOC 轮询 StatusSOC 直到终态或 quit，更新 DB。ota.sh 自带 reboot，无需重启步骤。
func (e *Engine) pollSOC(flow Workflow) {
	ticker := time.NewTicker(e.pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-e.quit:
			return
		case <-ticker.C:
			st, info, done := e.pollOnce(flow)
			if done {
				e.updateStatus(flow.ID, st, info)
				return
			}
		}
	}
}

// parseLastPartNotFlash 从 CmdFlag 解析是否保留 data 分区。
// 默认 true（保留）；CmdFlag 含 "LAST_PART_NOT_FLASH=0" → false（刷 data 分区）。
func parseLastPartNotFlash(cmdFlag string) bool {
	return !strings.Contains(cmdFlag, "LAST_PART_NOT_FLASH=0")
}
