package initialization

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	mwuser "bmssm/mvc/user"
)

// writeConf 在 dir 写一个最小 bmssm.yaml，指向 dbPath、默认密码 admin。
func writeConf(t *testing.T, dir, dbPath string) {
	t.Helper()
	yaml := "db:\n  path: " + dbPath + "\nserver:\n  defaultPassword: admin\n"
	if err := os.WriteFile(filepath.Join(dir, "bmssm.yaml"), []byte(yaml), 0644); err != nil {
		t.Fatalf("write conf: %v", err)
	}
}

// withConfEnv 设 BMSSM_CONF=dir 并在测试后恢复。
func withConfEnv(t *testing.T, dir string) {
	t.Helper()
	orig := os.Getenv("BMSSM_CONF")
	os.Setenv("BMSSM_CONF", dir)
	t.Cleanup(func() { os.Setenv("BMSSM_CONF", orig) })
}

// TestResetPasswordExistingUser 已存在用户 → 改密为默认，旧密码失效、默认密码可登录。
func TestResetPasswordExistingUser(t *testing.T) {
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	// 先用裸连接建表 + 建一个改过密的 admin
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := db.AutoMigrate(&mwuser.User{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	svc := mwuser.NewService(db)
	if err := svc.CreateUser("admin", "changed-pwd", "superuser"); err != nil {
		t.Fatalf("seed: %v", err)
	}
	db.Close()

	confDir := t.TempDir()
	writeConf(t, confDir, dbPath)
	withConfEnv(t, confDir)

	if code := RunResetPassword(""); code != 0 {
		t.Fatalf("expected exit 0, got %d", code)
	}

	// 重新打开校验：默认密码 admin 可登录，旧密码 changed-pwd 失败
	db2, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()
	s2 := mwuser.NewService(db2)
	if _, err := s2.Login("admin", "admin"); err != nil {
		t.Fatalf("login with reset default password failed: %v", err)
	}
	if _, err := s2.Login("admin", "changed-pwd"); err == nil {
		t.Fatalf("old password still works, reset did not take effect")
	}
}

// TestResetPasswordAdminMissing 用户表无 admin → 重建默认 admin。
func TestResetPasswordAdminMissing(t *testing.T) {
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := db.AutoMigrate(&mwuser.User{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	db.Close()

	confDir := t.TempDir()
	writeConf(t, confDir, dbPath)
	withConfEnv(t, confDir)

	if code := RunResetPassword("admin"); code != 0 {
		t.Fatalf("expected exit 0, got %d", code)
	}

	db2, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()
	s2 := mwuser.NewService(db2)
	if _, err := s2.Login("admin", "admin"); err != nil {
		t.Fatalf("recreated admin login with default password failed: %v", err)
	}
}

// TestResetPasswordNonAdminMissing 非 admin 用户不存在 → 报错退出 1，不误建。
func TestResetPasswordNonAdminMissing(t *testing.T) {
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := db.AutoMigrate(&mwuser.User{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	db.Close()

	confDir := t.TempDir()
	writeConf(t, confDir, dbPath)
	withConfEnv(t, confDir)

	if code := RunResetPassword("ghost"); code != 1 {
		t.Fatalf("expected exit 1 for missing non-admin, got %d", code)
	}

	db2, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()
	s2 := mwuser.NewService(db2)
	if c, _ := s2.CountUsers(); c != 0 {
		t.Fatalf("expected no users created, got %d", c)
	}
}
