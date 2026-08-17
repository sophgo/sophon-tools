// Package database 提供 sqlite(gorm) 初始化与 migration 框架。
// 用户/审计子项目在 init() 中通过 RegisterModel 注册模型并调用 Migrate。
package database

import (
	"os"
	"path/filepath"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
	_ "github.com/mattn/go-sqlite3"

	"bmssm/logger"
)

// models 注册表：各业务子项目在 init() 中 append 自身的 gorm 模型指针。
var models []interface{}

// globalDB 持有当前数据库连接，供其他包通过 DB() 访问。
var globalDB *gorm.DB

// RegisterModel 注册一个待 AutoMigrate 的模型（线程安全由 init 阶段单线程保证）。
func RegisterModel(m ...interface{}) { models = append(models, m...) }

// InitDB 打开/创建 sqlite 文件，设置全局句柄并返回 *gorm.DB。
// 权限收紧（MYS-388）：DB 明文存 LLM API key/forwardKey/会话等敏感数据，
// 目录显式 0700、文件显式 0600（不依赖 umask，创建与已有文件均强制），
// 防止本机其他本地用户读取密钥。
func InitDB(path string) (*gorm.DB, error) {
	if dir := filepath.Dir(path); dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			logger.Error("mkdir %s failed: %v", dir, err)
			return nil, err
		}
		_ = os.Chmod(dir, 0o700)
		// 文件不存在时预建为空文件（0600），避免 sqlite 按默认 umask 创建
		// （如 0644）后再次 chmod 之间留出可读窗口
		if _, err := os.Stat(path); os.IsNotExist(err) {
			if f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600); err == nil {
				_ = f.Close()
			}
		}
	}
	db, err := gorm.Open("sqlite3", path)
	if err != nil {
		logger.Error("open sqlite %s failed: %v", path, err)
		return nil, err
	}
	// 已有文件也强制收紧（兼容旧安装遗留的宽松权限）
	if err := os.Chmod(path, 0o600); err != nil {
		logger.Warn("chmod %s 0600 failed: %v", path, err)
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
