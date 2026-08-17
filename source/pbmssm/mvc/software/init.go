package software

import "bmssm/database"

// init 注册 OTAFile 模型，让 database.Migrate 建表（重启后 uploadId 可查询）。
func init() {
	database.RegisterModel(&OTAFile{})
}
