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
//
// MYS-451：非干跑刷机从本入口起全程持高危互斥锁（holder=HazardHolderFlash），
// 直到本 flow 到达终态（Success/Fail）才释放——防止刷机/OTA 自带重启的窗口内
// 被并发 reboot/shutdown 打断（brick 场景）。锁随 flow 拷贝携带：
// SOC 由 pollSOC 终态判定后释放；PCIE/多节点随 flow 传递到 reboot 步骤执行完毕；
// runCmd 失败与未知产品路径在本函数内释放。
func (e *Engine) handleFlash(flow Workflow) {
	if e.dryRun {
		logger.Info("[dryRun] simulate flash success: product=%s file=%s flashData=%v", flow.Product, flow.FileName, flow.FlashData)
		e.updateStatus(flow.ID, StatusSuccess, "dryRun: flash simulated")
		return
	}

	// 已有人在刷机/高危操作中 → 本 flow 快速拒绝（不排队不等待），标 Fail 供查询。
	if err := e.acquireFlashGuard(&flow); err != nil {
		e.updateStatus(flow.ID, StatusFail, "hazard lock: "+err.Error())
		return
	}

	if err := e.runCmd(flow); err != nil {
		logger.Error("flash failed: product=%s wf=%s err=%v", flow.Product, flow.WorkflowID, err)
		e.updateStatus(flow.ID, StatusFail, err.Error())
		releaseFlashGuard(&flow)
		return
	}

	switch productClass(flow.Product) {
	case ClassSOC:
		// runSOC 已置 Running 并启动轮询 goroutine，ota.sh 自带 reboot，无需推进；
		// 互斥锁由 pollSOC 在成功/失败终态判定后释放（flow.guard 随 flow 传入）。
	case ClassPCIE, ClassMultiNode:
		e.advanceToReboot(flow) // 锁随 flow 重新入队到 reboot 步骤，handleReboot 末尾释放
	default:
		logger.Warn("flash success but unknown product: %s", flow.Product)
		e.updateStatus(flow.ID, StatusSuccess, "unknown product, marked success")
		releaseFlashGuard(&flow)
	}
}

// handleReboot 处理重启步骤（仅 PCIE/多节点非干跑路径会到达）。
func (e *Engine) handleReboot(flow Workflow) {
	if e.dryRun {
		e.updateStatus(flow.ID, StatusSuccess, "dryRun: reboot simulated")
		return
	}
	// MYS-451：刷机窗口的互斥锁经 advanceToReboot 延续到此；reboot 步骤执行完毕
	// 即该 flow 终态，延迟释放。doReboot 内 shutdown -r now 成功时进程随之重启、
	// 内存锁随进程复位——此处显式释放是干净关闭的兜底（如重启命令失败的场景）。
	defer releaseFlashGuard(&flow)
	e.doReboot(flow)
}

// advanceToReboot 推进 flow 到 reboot 步骤并重新入队（对齐 bmssm nextStep+Strategy|=reboot）。
// MYS-451：不重新入队即失败的路径（DB 更新失败 / worker 满）在此释放刷机互斥锁，
// 避免锁被已失败 flow 泄漏。
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
		releaseFlashGuard(&flow)
		return
	}
	flow.Step = StepReboot
	flow.Strategy = newStrategy
	select {
	case e.worker <- flow:
	default:
		logger.Error("worker full when re-enqueueing reboot: wf=%s", flow.WorkflowID)
		e.updateStatus(flow.ID, StatusFail, "worker queue full on reboot")
		releaseFlashGuard(&flow)
	}
}

// updateStatus 更新 workflow 状态与信息。
func (e *Engine) updateStatus(id uint, status int, info string) {
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
