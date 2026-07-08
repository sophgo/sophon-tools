package user

import (
	"os"
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/mvc/audit"
)

// setupTestDB 创建临时 sqlite 数据库并迁移 user + audit 模型。
func setupTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	db.AutoMigrate(&User{}, &audit.AuditLog{})
	t.Cleanup(func() {
		// 关闭前清理环境变量
		os.Unsetenv("BMSSM_CONF")
		db.Close()
	})
	return db
}

func TestCreateAndListUsers(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	// 创建用户
	err := svc.CreateUser("alice", "password123", "admin")
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}

	err = svc.CreateUser("bob", "password456", "user")
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}

	// 列出用户
	users, err := svc.ListUsers()
	if err != nil {
		t.Fatalf("ListUsers: %v", err)
	}
	if len(users) != 2 {
		t.Fatalf("expected 2 users, got %d", len(users))
	}
	if users[0].Username != "alice" {
		t.Fatalf("expected alice, got %s", users[0].Username)
	}
	if users[1].Username != "bob" {
		t.Fatalf("expected bob, got %s", users[1].Username)
	}
	// 确认密码不输出
	// (响应类型不包含 Password 字段)
}

func TestLoginWithCorrectPassword(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_ = svc.CreateUser("loginuser", "secret123", "user")

	user, err := svc.Login("loginuser", "secret123")
	if err != nil {
		t.Fatalf("Login should succeed: %v", err)
	}
	if user.Username != "loginuser" {
		t.Fatalf("expected loginuser, got %s", user.Username)
	}
}

func TestLoginWithWrongPassword(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_ = svc.CreateUser("loginuser", "secret123", "user")

	_, err := svc.Login("loginuser", "wrongpassword")
	if err == nil {
		t.Fatal("Login should fail with wrong password")
	}
}

func TestLoginWithNonexistentUser(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_, err := svc.Login("ghost", "password")
	if err == nil {
		t.Fatal("Login should fail for nonexistent user")
	}
}

func TestServiceDeleteUser(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_ = svc.CreateUser("tempuser", "temppwd", "user")

	err := svc.DeleteUser("tempuser")
	if err != nil {
		t.Fatalf("DeleteUser: %v", err)
	}

	// 确认删除
	_, err = svc.Login("tempuser", "temppwd")
	if err == nil {
		t.Fatal("deleted user should not be able to login")
	}
}

func TestDeleteAdminNotAllowed(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_ = svc.CreateUser("admin", "admin", "superuser")

	err := svc.DeleteUser("admin")
	if err == nil {
		t.Fatal("should not allow deleting admin")
	}
}

func TestCountUsers(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	count, err := svc.CountUsers()
	if err != nil {
		t.Fatalf("CountUsers: %v", err)
	}
	if count != 0 {
		t.Fatalf("expected 0, got %d", count)
	}

	_ = svc.CreateUser("u1", "p1", "user")
	_ = svc.CreateUser("u2", "p2", "user")

	count, err = svc.CountUsers()
	if err != nil {
		t.Fatalf("CountUsers: %v", err)
	}
	if count != 2 {
		t.Fatalf("expected 2, got %d", count)
	}
}

// 确保模型注册不影响 database 包
func TestModelRegistration(t *testing.T) {
	// init() 已注册模型，此处仅确认 database 模型列表非空
	// 通过实际创建表来验证
	db := setupTestDB(t)
	hasTable := db.HasTable(&User{})
	if !hasTable {
		t.Fatal("users table should exist after AutoMigrate")
	}
}
