package ota

import (
	"time"

	"bmssm/logger"
)

// doReboot 执行 reboot 步骤（对齐 bmssm：updateBootTime + sync + shutdown -r now）。
// 仅 PCIE/多节点刷机成功后经 advanceToReboot 到达；SOC 不走此路径（ota.sh 自带 reboot）。
// 先审计（MYS-389：OTA 刷机自动重启记入 audit 模块）并落库 LastRebootTime +
// Status=Success（尽力而为，进程即将被 reboot 终止），
// 再跑 sync 与 shutdown -r now。
// 返回前释放本 workflow 持有的 oplock：设备即将重启（释放与否不影响），
// 且若 shutdown 失败（进程存活）锁也不应悬挂，后续危险操作可再次执行。
func (e *Engine) doReboot(flow Workflow) {
	e.audit(flow.UserID, "ota_reboot", otaLockResource(flow), "", "success")
	e.updateReboot(flow.ID)
	e.releaseOpLock(flow.ID)
	if _, stderr, err := e.runner("sync"); err != nil {
		logger.Warn("ota: sync before reboot failed: %v: %s", err, stderr)
	}
	if _, stderr, err := e.runner("shutdown", "-r", "now"); err != nil {
		logger.Error("ota: shutdown -r now failed: %v: %s", err, stderr)
	}
}

// updateReboot 落库 LastRebootTime 与 Status=Success。
func (e *Engine) updateReboot(id uint) {
	if e.db == nil {
		return
	}
	if err := e.db.Model(&Workflow{}).Where("id = ?", id).Updates(map[string]interface{}{
		"last_reboot_time": time.Now(),
		"status":           StatusSuccess,
		"info":             "rebooting",
	}).Error; err != nil {
		logger.Error("updateReboot failed: id=%d err=%v", id, err)
	}
}
