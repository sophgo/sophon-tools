package database

import (
	"path/filepath"
	"testing"
)

func TestInitDB(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "ssm.db")
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
