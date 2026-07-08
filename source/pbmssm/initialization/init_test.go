package initialization

import (
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	"bmssm/database"
	mwuser "bmssm/mvc/user"
)

// TestCreateDefaultAdminLogin 覆盖双重 bcrypt bug：空 user 表 → createDefaultAdmin
// → 用 admin/admin 走 Login 应成功。
func TestCreateDefaultAdminLogin(t *testing.T) {
	// 准备临时 sqlite
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	defer db.Close()
	if err := db.AutoMigrate(&mwuser.User{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}

	// 临时替换 database 全局 DB 句柄，测试后恢复
	origDB := database.DB()
	database.SetDB(db)
	defer database.SetDB(origDB)

	// 准备配置（LoadFromDir 触发 SetDefault）
	config.LoadFromDir(t.TempDir())

	// user 表为空时创建默认 admin
	createDefaultAdmin(&config.Conf)

	// 用 admin/admin 登录应成功（验证未双重 bcrypt）
	svc := mwuser.NewService(db)
	user, err := svc.Login("admin", "admin")
	if err != nil {
		t.Fatalf("default admin login failed (double-bcrypt bug?): %v", err)
	}
	if user.Username != "admin" {
		t.Fatalf("expected admin, got %s", user.Username)
	}
	if user.Role != "superuser" {
		t.Fatalf("expected superuser role, got %s", user.Role)
	}
}

// TestCreateDefaultAdminSkipsNonEmpty user 表非空时不应重复创建。
func TestCreateDefaultAdminSkipsNonEmpty(t *testing.T) {
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	defer db.Close()
	if err := db.AutoMigrate(&mwuser.User{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}

	// 预先插入一个用户
	svc := mwuser.NewService(db)
	if err := svc.CreateUser("existing", "pwd", "user"); err != nil {
		t.Fatalf("seed user: %v", err)
	}

	origDB := database.DB()
	database.SetDB(db)
	defer database.SetDB(origDB)

	config.LoadFromDir(t.TempDir())
	createDefaultAdmin(&config.Conf)

	// 不应新增 admin
	count, _ := svc.CountUsers()
	if count != 1 {
		t.Fatalf("expected 1 user (no admin created), got %d", count)
	}
}
