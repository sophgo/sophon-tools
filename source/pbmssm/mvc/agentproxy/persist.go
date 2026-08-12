package agentproxy

import (
	"errors"
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/logger"
)

// ConfigRecord agentproxy 单例配置的 sqlite 持久化（ID 固定为 1）。
// 目前仅持久化 enabled（「启用」开关），其余字段仍由 bmssm.yaml 提供。
// 引入该表让「启用/禁用 Agent」在 bmssm 重启后保持，且与前端 serviceAction 解耦。
type ConfigRecord struct {
	ID        uint      `gorm:"column:id;primary_key" json:"-"`
	Enabled   bool      `gorm:"column:enabled" json:"enabled"` // false 为空时视为未初始化（回退 viper 默认）
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

// TableName 指定表名。
func (ConfigRecord) TableName() string { return "agentproxy_config" }

// MigrateConfig 显式迁移 agentproxy_config 表（对齐 llmproxy/migrate.go 模式）。
// 表结构简单，AutoMigrate 创建即可；显式调用保证记录存在。
func MigrateConfig(db *gorm.DB) {
	if db == nil {
		return
	}
	if !db.HasTable(&ConfigRecord{}) {
		if err := db.CreateTable(&ConfigRecord{}).Error; err != nil {
			logger.Error("agentproxy: create agentproxy_config failed: %v", err)
			return
		}
	}
	// 预置单例行（无法用 FindOrCreate 的表达，用 first-or-create）。
	var rec ConfigRecord
	if db.First(&rec, 1).RecordNotFound() {
		_ = db.Create(&ConfigRecord{ID: 1, Enabled: true, UpdatedAt: time.Now()}).Error
	}
}

// loadConfigEnabled 读取持久化的 enabled 状态。
// 返回 (value, true) 表示 sqlite 有记录可作准；rovided false 表示未初始化（调用方回退 viper）。
func loadConfigEnabled(db *gorm.DB) (bool, bool) {
	if db == nil {
		return false, false
	}
	var rec ConfigRecord
	if err := db.First(&rec, 1).Error; err != nil {
		return false, false
	}
	return rec.Enabled, true
}

// persistEnabled 持久化 enabled 状态并返回更新后的记录。
func persistEnabled(db *gorm.DB, enabled bool) (ConfigRecord, error) {
	if db == nil {
		return ConfigRecord{}, errors.New("database unavailable")
	}
	var rec ConfigRecord
	err := db.First(&rec, 1).Error
	if err != nil {
		if !gorm.IsRecordNotFoundError(err) {
			return ConfigRecord{}, err
		}
		rec = ConfigRecord{ID: 1, Enabled: enabled, UpdatedAt: time.Now()}
		if err := db.Save(&rec).Error; err != nil {
			return ConfigRecord{}, err
		}
		return rec, nil
	}
	rec.Enabled = enabled
	rec.UpdatedAt = time.Now()
	if err := db.Save(&rec).Error; err != nil {
		return ConfigRecord{}, err
	}
	return rec, nil
}
