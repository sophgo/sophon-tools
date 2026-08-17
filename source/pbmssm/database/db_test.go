package database

import (
	"os"
	"path/filepath"
	"testing"
)

func TestInitDB(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "bmssm.db")
	db, err := InitDB(dbPath)
	if err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	defer db.Close()

	if err := db.DB().Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}
	// migration 框架可调用，无模型时不报错
	if err := Migrate(db); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
}

// TestInitDBFilePermissions 新建 DB 时目录应 0700、文件应 0600（sqlite 明文存密钥/会话数据）。
func TestInitDBFilePermissions(t *testing.T) {
	sub := filepath.Join(t.TempDir(), "nested")
	dbPath := filepath.Join(sub, "bmssm.db")
	db, err := InitDB(dbPath)
	if err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	defer db.Close()

	if err := db.DB().Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}

	fi, err := os.Stat(dbPath)
	if err != nil {
		t.Fatalf("stat db file: %v", err)
	}
	if fi.Mode().Perm() != 0o600 {
		t.Fatalf("expected db file 0600, got %o", fi.Mode().Perm())
	}

	di, err := os.Stat(sub)
	if err != nil {
		t.Fatalf("stat db dir: %v", err)
	}
	if di.Mode().Perm() != 0o700 {
		t.Fatalf("expected db dir 0700, got %o", di.Mode().Perm())
	}
}

// TestInitDBHealsLoosePermissions 已存在但权限过松（0644）的 DB 文件，InitDB 应强制收紧为 0600。
func TestInitDBHealsLoosePermissions(t *testing.T) {
	sub := filepath.Join(t.TempDir(), "nested")
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	dbPath := filepath.Join(sub, "bmssm.db")
	if f, err := os.OpenFile(dbPath, os.O_CREATE|os.O_RDWR, 0o644); err != nil {
		t.Fatalf("pre-create db: %v", err)
	} else {
		f.Close()
	}

	db, err := InitDB(dbPath)
	if err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	defer db.Close()

	if err := db.DB().Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}

	fi, err := os.Stat(dbPath)
	if err != nil {
		t.Fatalf("stat db file: %v", err)
	}
	if fi.Mode().Perm() != 0o600 {
		t.Fatalf("expected db file healed to 0600, got %o", fi.Mode().Perm())
	}

	di, err := os.Stat(sub)
	if err != nil {
		t.Fatalf("stat db dir: %v", err)
	}
	if di.Mode().Perm() != 0o700 {
		t.Fatalf("expected db dir healed to 0700, got %o", di.Mode().Perm())
	}
}
