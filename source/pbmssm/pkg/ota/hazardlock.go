package ota

import (
	"bmssm/logger"
	"bmssm/pkg/hazard"
)

// HazardHolderFlash 是 OTA 刷机/回滚窗口在高危互斥锁上的占用者标识（MYS-451）。
// 窗口 = flow 开始执行（handleFlash 非干跑入口）→ 该 flow 到达终态（Success/Fail）。
// 持有期间任何 reboot/shutdown/OTA/等其他危险操作的 TryAcquire 一律冲突
// （HTTP 层表现为 409），且不会实际执行 reboot/shutdown。
// 锁为内存态：刷机终了设备本就会重启，进程随重启复位属预期；
// 要防的是重启前刷机窗口内的并发 reboot/shutdown 指令。
const HazardHolderFlash = "ota.flash"

// acquireFlashGuard 尝试占用全局高危互斥锁（holder 见 HazardHolderFlash），
// 成功则记入 flow.guard，随 flow 拷贝流转直到释放点。被占用返回错误，
// 调用方（handleFlash）应将 flow 标为 Fail——快速拒绝并发刷机，不排队不等待。
func (e *Engine) acquireFlashGuard(flow *Workflow) error {
	guard, err := hazard.HazardOps.TryAcquire(HazardHolderFlash)
	if err != nil {
		logger.Warn("ota: flash blocked by hazardous op: wf=%s err=%v", flow.WorkflowID, err)
		return err
	}
	flow.guard = guard
	return nil
}

// releaseFlashGuard 释放 flow 携带的刷机互斥锁（幂等，可安全重复调用）。
// 未持锁（dryRun 或直接调用 runSOC 的测试路径）时为空操作。
func releaseFlashGuard(flow *Workflow) {
	if flow.guard == nil {
		return
	}
	flow.guard.Release()
	flow.guard = nil
}
