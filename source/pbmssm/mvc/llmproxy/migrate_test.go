package llmproxy

import (
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
)

// setupMigrateDB 建带 llm_proxy_config 表的临时 sqlite（不注册全局 DB）。
func setupMigrateDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(&Config{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return db
}

// TestMigrateDefaultModelUpgrade 验证 MYS-2726 的默认模型名换代迁移：
// 仍等于旧默认值的记录改写成新默认值，用户自选过的模型名保持不变。
func TestMigrateDefaultModelUpgrade(t *testing.T) {
	db := setupMigrateDB(t)
	defer db.Close()

	// 用户没改过（仍为旧出厂默认）
	untouched := Config{ID: 1, LLMApiBase: "https://www.sophnet.com/api/open-apis/v1", LLMModel: LegacyDefaultLLMModel}
	if err := db.Save(&untouched).Error; err != nil {
		t.Fatalf("seed untouched: %v", err)
	}
	// 用户手动选过别的模型
	custom := Config{ID: 2, LLMApiBase: "http://10.0.0.5:8000/v1", LLMModel: "my-own-model"}
	if err := db.Save(&custom).Error; err != nil {
		t.Fatalf("seed custom: %v", err)
	}

	Migrate(db)

	var got Config
	if err := db.First(&got, 1).Error; err != nil {
		t.Fatalf("load 1: %v", err)
	}
	if got.LLMModel != DefaultLLMModel {
		t.Errorf("upgraded model = %q, want %q", got.LLMModel, DefaultLLMModel)
	}
	// 用新变量查第二条：gorm v1 的 First 会把 dest 里的非零字段拼进条件，
	// 复用带 ID=1 的 got 会得到 id=1 AND id=2 而查不到。
	var got2 Config
	if err := db.First(&got2, 2).Error; err != nil {
		t.Fatalf("load 2: %v", err)
	}
	if got2.LLMModel != "my-own-model" {
		t.Errorf("user-selected model was clobbered: %q", got2.LLMModel)
	}

	// 幂等：再跑一次结果不变
	Migrate(db)
	var again Config
	if err := db.First(&again, 1).Error; err != nil {
		t.Fatalf("reload 1: %v", err)
	}
	if again.LLMModel != DefaultLLMModel {
		t.Errorf("second migrate changed model = %q", again.LLMModel)
	}
}

// TestMigrateDefaultModelRunsOnlyOnce 迁移只跑一次：用户升级后主动把模型名选回旧值，
// 后续重启不得再被改回（否则 LLMOverride 生效下会持续用错模型且无从察觉）。
func TestMigrateDefaultModelRunsOnlyOnce(t *testing.T) {
	db := setupMigrateDB(t)
	defer db.Close()

	if err := db.Save(&Config{ID: 1, LLMModel: LegacyDefaultLLMModel}).Error; err != nil {
		t.Fatalf("seed: %v", err)
	}
	Migrate(db) // 首次升级：旧值 → 新值

	// 用户改回旧值（模拟 UI 上重新选择同一型号）
	if err := db.Model(&Config{}).Where("id = ?", 1).
		Update("llm_model", LegacyDefaultLLMModel).Error; err != nil {
		t.Fatalf("user reselect: %v", err)
	}

	Migrate(db) // 再次启动
	var got Config
	if err := db.First(&got, 1).Error; err != nil {
		t.Fatalf("reload: %v", err)
	}
	if got.LLMModel != LegacyDefaultLLMModel {
		t.Errorf("second run clobbered user reselection: got %q, want %q", got.LLMModel, LegacyDefaultLLMModel)
	}
}

// TestMigrateSkipsWhenNoTable 表不存在时（首装、AutoMigrate 尚未建表）直接返回，
// 不 panic 也不报错。
func TestMigrateSkipsWhenNoTable(t *testing.T) {
	db, err := gorm.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	defer db.Close()
	Migrate(db) // 不应 panic
	Migrate(nil)
}
