package audit

import (
	"os"
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
)

func setupTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	db.AutoMigrate(&AuditLog{})
	t.Cleanup(func() {
		os.Unsetenv("BMSSM_CONF")
		db.Close()
	})
	return db
}

func TestWriteAndListAuditLogs(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	// 写入日志
	err := svc.Write("admin", "login", "user", "192.168.1.1", "success")
	if err != nil {
		t.Fatalf("Write: %v", err)
	}
	err = svc.Write("bob", "create_user", "user", "10.0.0.1", "success")
	if err != nil {
		t.Fatalf("Write: %v", err)
	}
	err = svc.Write("admin", "delete_user", "user", "192.168.1.1", "failed")
	if err != nil {
		t.Fatalf("Write: %v", err)
	}

	// 分页查询
	result, err := svc.ListLogs(0, 10)
	if err != nil {
		t.Fatalf("ListLogs: %v", err)
	}
	if result.Total != 3 {
		t.Fatalf("expected total 3, got %d", result.Total)
	}
	if len(result.Logs) != 3 {
		t.Fatalf("expected 3 logs, got %d", len(result.Logs))
	}

	// 按 id desc 排序，第一条应是最新的
	if result.Logs[0].Action != "delete_user" {
		t.Fatalf("expected latest log to be delete_user, got %s", result.Logs[0].Action)
	}
}

func TestListAuditLogsPagination(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	// 写入 5 条
	for i := 0; i < 5; i++ {
		_ = svc.Write("user", "test", "resource", "127.0.0.1", "success")
	}

	// limit=2
	result, err := svc.ListLogs(0, 2)
	if err != nil {
		t.Fatalf("ListLogs: %v", err)
	}
	if result.Total != 5 {
		t.Fatalf("expected total 5, got %d", result.Total)
	}
	if len(result.Logs) != 2 {
		t.Fatalf("expected 2 logs, got %d", len(result.Logs))
	}

	// offset=2, limit=2
	result, err = svc.ListLogs(2, 2)
	if err != nil {
		t.Fatalf("ListLogs: %v", err)
	}
	if len(result.Logs) != 2 {
		t.Fatalf("expected 2 logs, got %d", len(result.Logs))
	}
}

func TestEmptyAuditLogs(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	result, err := svc.ListLogs(0, 10)
	if err != nil {
		t.Fatalf("ListLogs: %v", err)
	}
	if result.Total != 0 {
		t.Fatalf("expected 0 total, got %d", result.Total)
	}
	if len(result.Logs) != 0 {
		t.Fatalf("expected 0 logs, got %d", len(result.Logs))
	}
}
