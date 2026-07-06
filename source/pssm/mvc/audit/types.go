// Package audit 提供审计日志 MVC 模块：查询与写入。
package audit

import "time"

// AuditLog 审计日志数据库模型。
type AuditLog struct {
	ID        uint      `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	Username  string    `gorm:"column:username;not null" json:"username"`
	Action    string    `gorm:"column:action;not null" json:"action"`
	Resource  string    `gorm:"column:resource" json:"resource"`
	IP        string    `gorm:"column:ip" json:"ip"`
	Result    string    `gorm:"column:result;default:'success'" json:"result"`
	CreatedAt time.Time `gorm:"column:created_at" json:"createdAt"`
}

// TableName 自定义表名。
func (AuditLog) TableName() string { return "audit_logs" }
