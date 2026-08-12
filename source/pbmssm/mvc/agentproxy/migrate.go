package agentproxy

import (
	"github.com/jinzhu/gorm"

	"bmssm/logger"
)

// Migrate 对 agent_session 表做显式迁移（对齐 llmproxy/migrate.go 模式）。
// 在 bmssm 启动（InitBase）时调用一次。
func Migrate(db *gorm.DB) {
	if db == nil {
		return
	}
	// 表不存在由 AutoMigrate 创建（RegisterModel 已注册）
	if db.HasTable(&WebchatSession{}) {
		// 补齐旧版本缺的列（当前无历史版本，预留）
		cols := []struct {
			name string
			typ  string
		}{
			{"acp_session_id", "text"},
			{"title", "text"},
			{"cwd", "text"},
			{"messages_json", "text"},
			{"state", "text"},
		}
		for _, c := range cols {
			if db.Dialect().HasColumn("agent_session", c.name) {
				continue
			}
			sql := "ALTER TABLE agent_session ADD COLUMN " + c.name + " " + c.typ
			if err := db.Exec(sql).Error; err != nil {
				logger.Warn("agentproxy migrate add %s failed: %v", c.name, err)
			} else {
				logger.Info("agentproxy migrate: added column %s", c.name)
			}
		}
	}
	// 持久化 enabled 状态表（「启用」/服务管理开关）
	MigrateConfig(db)
}
