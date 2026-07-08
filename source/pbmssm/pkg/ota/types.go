// Package ota 实现 OTA 系统升级，按设备模式分发：
//   - SOC（SE5/SE7/SE9）走 pota_update ota.sh 方案（embed 资源）
//   - PCIE（SC5/SC7）走 bm_firmware_update
//   - 多节点（SE6/SE8）走 local_update.sh / 远程 ssh
//
// workflow 引擎结构与状态流转对齐 bmssm pkg/workflow。
package ota

import "time"

// ---------------------------------------------------------------
// 状态 / 类型常量（对齐 bmssm）
// ---------------------------------------------------------------

// Workflow 状态。Commit=已提交待执行；Success/Fail=终态；Running=SOC 异步刷机进行中。
const (
	StatusCommit  = 1
	StatusSuccess = 2
	StatusFail    = 3
	StatusRunning = 4
)

// Workflow 类型。Upgrade=升级；Rollback=回滚（对齐 bmssm Type=3）。
const (
	TypeUpgrade  = 1
	TypeRollback = 3
)

// Strategy / Step 字段取值。
const (
	StrategyFlash  = "flash"
	StrategyReboot = "reboot"
	StepFlash      = "flash"
	StepReboot     = "reboot"
)

// ProductClass 设备模式分类，用于 dispatch。
type ProductClass int

const (
	ClassUnknown   ProductClass = 0
	ClassSOC       ProductClass = 1
	ClassPCIE      ProductClass = 2
	ClassMultiNode ProductClass = 3
)

// Workflow OTA 升级工作流记录，字段对齐 bmssm workflow 表。
type Workflow struct {
	ID             uint      `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	UserID         string    `gorm:"column:user_id" json:"userId"`
	WorkflowID     string    `gorm:"column:workflow_id;index" json:"workflowId"`
	Name           string    `gorm:"column:name" json:"name"`
	Type           int       `gorm:"column:type" json:"type"`
	Status         int       `gorm:"column:status" json:"status"`
	Info           string    `gorm:"column:info" json:"info"`
	Product        string    `gorm:"column:product" json:"product"`
	ModuleName     string    `gorm:"column:module_name" json:"moduleName"`
	FileName       string    `gorm:"column:file_name" json:"fileName"`
	Strategy       string    `gorm:"column:strategy" json:"strategy"`
	Step           string    `gorm:"column:step" json:"step"`
	CmdFlag        string    `gorm:"column:cmd_flag" json:"cmdFlag"`
	Version        string    `gorm:"column:version" json:"version"`
	FlashData      bool      `gorm:"-" json:"flashData"`
	CreateTime     time.Time `gorm:"column:create_time" json:"createTime"`
	LastRebootTime time.Time `gorm:"column:last_reboot_time" json:"lastRebootTime"`
}

// TableName 自定义表名。
func (Workflow) TableName() string { return "workflows" }
