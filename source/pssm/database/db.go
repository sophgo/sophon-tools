// Package database 提供 sqlite(gorm) 初始化与 migration 框架。
// 用户/审计子项目在 init() 中通过 RegisterModel 注册模型并调用 Migrate。
package database

import (
	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
	_ "github.com/mattn/go-sqlite3"

	"ssm/logger"
)

// models 注册表：各业务子项目在 init() 中 append 自身的 gorm 模型指针。
var models []interface{}

// globalDB 持有当前数据库连接，供其他包通过 DB() 访问。
var globalDB *gorm.DB

// RegisterModel 注册一个待 AutoMigrate 的模型（线程安全由 init 阶段单线程保证）。
func RegisterModel(m ...interface{}) { models = append(models, m...) }

// InitDB 打开/创建 sqlite 文件，设置全局句柄并返回 *gorm.DB。
func InitDB(path string) (*gorm.DB, error) {
	db, err := gorm.Open("sqlite3", path)
	if err != nil {
		logger.Error("open sqlite %s failed: %v", path, err)
		return nil, err
	}
	globalDB = db
	return db, nil
}

// DB 返回当前数据库连接。InitDB 调用后可用；否则为 nil。
func DB() *gorm.DB { return globalDB }

// SetDB 替换全局数据库句柄（仅供测试使用）。
func SetDB(db *gorm.DB) { globalDB = db }

// Migrate 对所有已注册模型执行 AutoMigrate。models 为空时等价 no-op。
func Migrate(db *gorm.DB) error {
	if len(models) == 0 {
		return nil
	}
	if err := db.AutoMigrate(models...).Error; err != nil {
		logger.Error("automigrate failed: %v", err)
		return err
	}
	return nil
}
