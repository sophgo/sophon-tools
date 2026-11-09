package llmproxy

import (
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/logger"
)

// Migrate 对 llm_proxy_config 表做显式迁移：gorm v1 AutoMigrate 对 sqlite
// 已有表加新列不可靠，这里用 ALTER TABLE 补齐旧版本缺的列。
// 在 bmssm 启动（InitBase）时调用一次。
func Migrate(db *gorm.DB) {
	if db == nil {
		return
	}
	if !db.HasTable(&Config{}) {
		// 表不存在由 AutoMigrate 创建（含全部新列）
		return
	}
	cols := []struct {
		name string
		typ  string
	}{
		{"llm_api_base", "text"},
		{"llm_api_key", "text"},
		{"llm_model", "text"},
		{"llm_enabled", "bool"},
		{"llm_override_model", "bool"},
		{"vlm_api_base", "text"},
		{"vlm_api_key", "text"},
		{"vlm_model", "text"},
		{"vlm_enabled", "bool"},
		{"vlm_override_model", "bool"},
		{"forward_key", "text"},
	}
	for _, c := range cols {
		if db.Dialect().HasColumn("llm_proxy_config", c.name) {
			continue
		}
		sql := "ALTER TABLE llm_proxy_config ADD COLUMN " + c.name + " " + c.typ
		if err := db.Exec(sql).Error; err != nil {
			logger.Warn("llmproxy migrate add %s failed: %v", c.name, err)
		} else {
			logger.Info("llmproxy migrate: added column %s", c.name)
		}
	}
	// 旧版本字段迁移到新结构（旧 api_base/api_key/target_model/enabled → llm_*）。
	// 必须先确认旧列存在再 UPDATE，否则全新表（AutoMigrate 直接建 llm_* 新结构、
	// 无 api_base 等旧列）会反复报 "no such column" 并污染启动日志。
	migrateCol := func(oldCol, newCol string) {
		if !db.Dialect().HasColumn("llm_proxy_config", oldCol) {
			return
		}
		if err := db.Exec("UPDATE llm_proxy_config SET "+newCol+" = "+oldCol+" WHERE "+newCol+" IS NULL AND "+oldCol+" IS NOT NULL").Error; err != nil {
			logger.Warn("llmproxy migrate %s -> %s failed: %v", oldCol, newCol, err)
		}
	}
	migrateCol("api_base", "llm_api_base")
	migrateCol("api_key", "llm_api_key")
	migrateCol("target_model", "llm_model")
	migrateCol("enabled", "llm_enabled")

	// 默认模型名换代（MYS-2726）：旧版把 LegacyDefaultLLMModel 作为出厂默认写进库，
	// 而 LLMOverride 默认开启（转发时强制用库里的模型名），用户若没手动改过，
	// 升级后会一直沿用旧模型名。
	//
	// 只跑一次（marker 表记录）：若每次启动都按值匹配改写，用户升级后刻意把模型名
	// 选回旧值会被下次重启悄悄改回，且 OvenOverride 生效下请求持续打到不存在的模型。
	migrateDefaultModelOnce(db)
}

// migrationMarker 记录已执行的一次性迁移（name 主键）。
type migrationMarker struct {
	Name      string `gorm:"column:name;primary_key"`
	AppliedAt string `gorm:"column:applied_at"`
}

// TableName 指定表名。
func (migrationMarker) TableName() string { return "llmproxy_migration" }

// migrateDefaultModelOnce 一次性把「仍是旧出厂默认」的模型名换成新默认值。
// 已有 marker 则直接返回（用户之后即使把模型名改回旧值也不再被覆盖）。
func migrateDefaultModelOnce(db *gorm.DB) {
	const name = "default_llm_model_2_4_0"
	if !db.Dialect().HasColumn("llm_proxy_config", "llm_model") {
		return
	}
	if !db.HasTable(&migrationMarker{}) {
		if err := db.CreateTable(&migrationMarker{}).Error; err != nil {
			// 建不了 marker 表就不做改写：宁可这次不升级模型名，也不能变成每次启动都改
			logger.Warn("llmproxy migrate: create marker table failed, skip default model upgrade: %v", err)
			return
		}
	}
	var m migrationMarker
	if err := db.First(&m, "name = ?", name).Error; err == nil {
		return // 已执行
	}
	if err := db.Exec("UPDATE llm_proxy_config SET llm_model = ? WHERE llm_model = ?",
		DefaultLLMModel, LegacyDefaultLLMModel).Error; err != nil {
		logger.Warn("llmproxy migrate default model %s -> %s failed: %v",
			LegacyDefaultLLMModel, DefaultLLMModel, err)
		return
	}
	if err := db.Create(&migrationMarker{Name: name, AppliedAt: time.Now().Format(time.RFC3339)}).Error; err != nil {
		logger.Warn("llmproxy migrate: record marker %s failed: %v", name, err)
	}
}
