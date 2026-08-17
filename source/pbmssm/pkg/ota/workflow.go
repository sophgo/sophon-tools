package ota

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"bmssm/logger"
)

// newWorkflowID 生成随机 workflow id（16 hex 字符）。
func newWorkflowID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// ---------------------------------------------------------------
// 入队 / 查询
// ---------------------------------------------------------------

// EnqueueFlow 提交一条 workflow：写库 + 入队 worker，立即返回。
// 调用方设置 Product/ModuleName/FileName/CmdFlag/Version/Name/Type；
// Strategy/Step/Status/WorkflowID 由本方法补全并写回 *flow。返回 nil 表示已入队。
func (e *Engine) EnqueueFlow(flow *Workflow) error {
	if e.db == nil {
		return errDBUnavailable
	}
	if flow.WorkflowID == "" {
		flow.WorkflowID = newWorkflowID()
	}
	if flow.Type == 0 {
		flow.Type = TypeUpgrade
	}
	if flow.Strategy == "" {
		flow.Strategy = StrategyFlash
	}
	if flow.Step == "" {
		flow.Step = StepFlash
	}
	flow.Status = StatusCommit
	flow.CreateTime = time.Now()

	if err := e.db.Create(flow).Error; err != nil {
		return fmt.Errorf("create workflow: %w", err)
	}

	// 非阻塞入队（cap 32 充足）；满则删除刚写入的 DB 行并报错，避免状态悬挂
	// （DB 已落 Commit 但 worker 永不消费）。
	select {
	case e.worker <- *flow:
		return nil
	default:
		delErr := e.db.Where("workflow_id = ?", flow.WorkflowID).Delete(&Workflow{}).Error
		if delErr != nil {
			logger.Error("rollback orphan workflow %s after enqueue failure: %v", flow.WorkflowID, delErr)
		}
		return errWorkerFull
	}
}

// QueryAll 返回全部 workflow（按创建时间倒序）。
func (e *Engine) QueryAll() ([]Workflow, error) {
	if e.db == nil {
		return nil, errDBUnavailable
	}
	var flows []Workflow
	if err := e.db.Order("create_time DESC").Find(&flows).Error; err != nil {
		return nil, err
	}
	return flows, nil
}

// Query 按 workflowId 查单个 workflow。
func (e *Engine) Query(id string) (*Workflow, error) {
	if e.db == nil {
		return nil, errDBUnavailable
	}
	var flow Workflow
	if err := e.db.Where("workflow_id = ?", id).First(&flow).Error; err != nil {
		return nil, err
	}
	return &flow, nil
}

// ---------------------------------------------------------------
// worker goroutine
// ---------------------------------------------------------------

// startCmd 消费 worker，按 Step 分发。退出条件：quit 关闭。
func (e *Engine) startCmd() {
	for {
		select {
		case <-e.quit:
			return
		case flow := <-e.worker:
			e.processFlow(flow)
		}
	}
}

// processFlow 按 Step 路由：flash→handleFlash；reboot→handleReboot。
func (e *Engine) processFlow(flow Workflow) {
	switch flow.Step {
	case StepFlash:
		e.handleFlash(flow)
	case StepReboot:
		e.handleReboot(flow)
	}
}

// handleFlash 处理刷机步骤。
// dryRun：直接标 Success（模拟）。
// SOC 非干跑：runSOC 已置 Running + 启动轮询，ota.sh 自带 reboot。
// PCIE/多节点非干跑：刷机成功后推进到 reboot 步骤并重新入队。
// 危险操作互斥（MYS-389）：非干跑刷机从本步骤开始持有全局 oplock，
// 与其他危险操作（reboot/shutdown/防火墙 rebuild/另一轮 OTA）互斥；
// 获取失败直接把 workflow 置 Fail（冲突返回明确错误而非排队混跑）。
func (e *Engine) handleFlash(flow Workflow) {
	if e.dryRun {
		logger.Info("[dryRun] simulate flash success: product=%s file=%s flashData=%v", flow.Product, flow.FileName, flow.FlashData)
		e.updateStatus(flow.ID, StatusSuccess, "dryRun: flash simulated")
		return
	}

	release, err := e.opLock.Acquire(otaLockHolder(flow))
	if err != nil {
		logger.Warn("flash blocked by another dangerous operation: wf=%s err=%v", flow.WorkflowID, err)
		e.audit(flow.UserID, "ota_flash", otaLockResource(flow), "", "blocked: "+err.Error())
		e.updateStatus(flow.ID, StatusFail, "blocked: "+err.Error())
		return
	}
	e.opMu.Lock()
	e.opReleases[flow.ID] = release
	e.opMu.Unlock()

	if err := e.runCmd(flow); err != nil {
		logger.Error("flash failed: product=%s wf=%s err=%v", flow.Product, flow.WorkflowID, err)
		e.updateStatus(flow.ID, StatusFail, err.Error())
		return
	}

	switch productClass(flow.Product) {
	case ClassSOC:
		// runSOC 已置 Running 并启动轮询 goroutine，ota.sh 自带 reboot，无需推进。
		// 锁由 pollSOC 到达终态后经 updateStatus 释放。
	case ClassPCIE, ClassMultiNode:
		e.advanceToReboot(flow)
	default:
		logger.Warn("flash success but unknown product: %s", flow.Product)
		e.updateStatus(flow.ID, StatusSuccess, "unknown product, marked success")
	}
}

// otaLockHolder 描述刷机持锁者（放入 oplock.BusyError，向冲突方展示）。
func otaLockHolder(flow Workflow) string {
	return "ota:" + otaLockResource(flow)
}

// otaLockResource 审计资源描述（product:fileName）。
func otaLockResource(flow Workflow) string {
	return fmt.Sprintf("%s:%s", flow.Product, flow.FileName)
}

// handleReboot 处理重启步骤（仅 PCIE/多节点非干跑路径会到达）。
func (e *Engine) handleReboot(flow Workflow) {
	if e.dryRun {
		e.updateStatus(flow.ID, StatusSuccess, "dryRun: reboot simulated")
		return
	}
	e.doReboot(flow)
}

// advanceToReboot 推进 flow 到 reboot 步骤并重新入队（对齐 bmssm nextStep+Strategy|=reboot）。
// 锁在推进后保持持有（同 workflow 的 reboot 步骤继续占用，直至 doReboot 重启进程）。
func (e *Engine) advanceToReboot(flow Workflow) {
	newStrategy := flow.Strategy
	if !strings.Contains(newStrategy, StrategyReboot) {
		newStrategy = newStrategy + "|" + StrategyReboot
	}
	if err := e.db.Model(&Workflow{}).Where("id = ?", flow.ID).Updates(map[string]interface{}{
		"step":     StepReboot,
		"strategy": newStrategy,
	}).Error; err != nil {
		logger.Error("advanceToReboot update failed: %v", err)
		e.updateStatus(flow.ID, StatusFail, "advance reboot step: "+err.Error())
		return
	}
	flow.Step = StepReboot
	flow.Strategy = newStrategy
	select {
	case e.worker <- flow:
	default:
		logger.Error("worker full when re-enqueueing reboot: wf=%s", flow.WorkflowID)
		e.updateStatus(flow.ID, StatusFail, "worker queue full on reboot")
	}
}

// updateStatus 更新 workflow 状态与信息；进入终态（Success/Fail）时释放该
// workflow 持有的危险操作锁（无论由哪个 goroutine 到达终态——SOC 轮询、
// 刷机失败、未知 product 等路径统一在此回收，避免锁悬挂）。
func (e *Engine) updateStatus(id uint, status int, info string) {
	// 终态锁释放不依赖 DB 可用性（先于 db 判空，防止 db==nil 时跳过释放）
	if status == StatusSuccess || status == StatusFail {
		e.releaseOpLock(id)
	}
	if e.db == nil {
		return
	}
	if err := e.db.Model(&Workflow{}).Where("id = ?", id).Updates(map[string]interface{}{
		"status": status,
		"info":   info,
	}).Error; err != nil {
		logger.Error("updateStatus failed: id=%d status=%d err=%v", id, status, err)
	}
}

// releaseOpLock 释放 flow 持有的 oplock（幂等）。
func (e *Engine) releaseOpLock(id uint) {
	e.opMu.Lock()
	release, ok := e.opReleases[id]
	delete(e.opReleases, id)
	e.opMu.Unlock()
	if ok && release != nil {
		release()
	}
}
