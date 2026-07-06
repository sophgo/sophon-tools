package ota

import (
	"time"

	"ssm/logger"
)

// doReboot 执行 reboot 步骤（对齐 bmssm：updateBootTime + sync + shutdown -r now）。
// 仅 PCIE/多节点刷机成功后经 advanceToReboot 到达；SOC 不走此路径（ota.sh 自带 reboot）。
// 先落库 LastRebootTime + Status=Success（尽力而为，进程即将被 reboot 终止），
// 再跑 sync 与 shutdown -r now。
func (e *Engine) doReboot(flow Workflow) {
	e.updateReboot(flow.ID)
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
