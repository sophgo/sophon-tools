package llmproxy

import (
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
	// 升级后会一直沿用旧模型名。仅在「值仍等于旧默认值」时改写，用户自选过的模型名不动。
	if db.Dialect().HasColumn("llm_proxy_config", "llm_model") {
		if err := db.Exec("UPDATE llm_proxy_config SET llm_model = ? WHERE llm_model = ?",
			DefaultLLMModel, LegacyDefaultLLMModel).Error; err != nil {
			logger.Warn("llmproxy migrate default model %s -> %s failed: %v",
				LegacyDefaultLLMModel, DefaultLLMModel, err)
		}
	}
}
