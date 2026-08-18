package database

import (
	"testing"

	"sophliteos/config"
)

// adminPassword 注入优先级（MYS-382）：
// 环境变量 SOPHLITEOS_ADMIN_PASSWORD > 外部配置 server.admin-password > 空串。
// 仓库模板已不含明文口令，验证环境变量通道在未配置外部覆盖时依然可用。
func TestAdminPasswordPrecedence(t *testing.T) {
	// 与 InitBase 相同的启动顺序：先加载配置（测试环境无配置文件，viper 保持空）
	config.LoadConfig()

	t.Setenv("SOPHLITEOS_ADMIN_PASSWORD", "env-md5")
	if got := adminPassword(); got != "env-md5" {
		t.Fatalf("env var not honored: got %q, want env-md5", got)
	}

	t.Setenv("SOPHLITEOS_ADMIN_PASSWORD", "")
	if got := adminPassword(); got != "" {
		t.Fatalf("no injection sources: got %q, want empty", got)
	}
}
