package ota

import "bmssm/database"

// init 注册 Workflow 模型，让 database.Migrate 建表。
func init() {
	database.RegisterModel(&Workflow{})
}
