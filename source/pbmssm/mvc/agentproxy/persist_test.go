package agentproxy

import "testing"

// TestPersistEnabledRoundTrip 验证「启用」状态能持久化并在重启（重读）后还原。
// 覆盖「启用开关」在 bmssm 重启后保持的核心路径。
func TestPersistEnabledRoundTrip(t *testing.T) {
	db := newTestDB(t)

	// 初始无记录：loadConfigEnabled 返回 not-ok
	if _, ok := loadConfigEnabled(db); ok {
		t.Fatal("should be uninitialized before MigrateConfig")
	}
	MigrateConfig(db)
	if enabled, ok := loadConfigEnabled(db); !ok {
		t.Fatal("should report ok after MigrateConfig")
	} else if !enabled {
		t.Fatal("default enabled should be true")
	}

	// 关闭并重新读取（模拟前端点了停用开关 + bmssm 重启重读）
	if _, err := persistEnabled(db, false); err != nil {
		t.Fatalf("persist false: %v", err)
	}
	if enabled, ok := loadConfigEnabled(db); !ok || enabled {
		t.Fatal("enabled should persist as false")
	}

	// 重新启用
	if _, err := persistEnabled(db, true); err != nil {
		t.Fatalf("persist true: %v", err)
	}
	if enabled, ok := loadConfigEnabled(db); !ok || !enabled {
		t.Fatal("enabled should persist as true")
	}
}
