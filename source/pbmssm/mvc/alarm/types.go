// Package alarm 提供 ssm 告警历史 MVC 模块：DB 落库 + 查询 + 落库适配器。
//
// 表 alarms 字段对齐原 sophliteos Alarm 表（id/code/core_unit_board_sn/
// component_type/msg/created_at）。component_type 存字符串标签（cpu/memory/
// disk/board/chip），与前端 logs/warning 列的 i18n key 对齐。
package alarm

import "time"

// Alarm 告警历史数据库模型。
type Alarm struct {
	ID              uint      `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	Code            int       `gorm:"column:code;not null" json:"code"`
	CoreUnitBoardSn string    `gorm:"column:core_unit_board_sn" json:"coreUnitBoardSn,omitempty"`
	ComponentType   string    `gorm:"column:component_type" json:"componentType,omitempty"`
	Msg             string    `gorm:"column:msg" json:"msg"`
	CreatedAt       time.Time `gorm:"column:created_at" json:"createdAt"`
}

// TableName 自定义表名。
func (Alarm) TableName() string { return "alarms" }
