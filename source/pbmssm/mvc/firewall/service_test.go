package firewall

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	fw "bmssm/pkg/firewall"
)

// fakeRunner 实现 fw.CommandRunner，脚本化响应并记录调用。
type fakeRunner struct {
	mu      sync.Mutex
	calls   [][2]string
	respond func(name string, args []string) (string, string, error)
}

func (f *fakeRunner) Run(name string, args ...string) (string, string, error) {
	f.mu.Lock()
	f.calls = append(f.calls, [2]string{name, name + " " + strings.Join(args, " ")})
	f.mu.Unlock()
	if f.respond == nil {
		return "", "", nil
	}
	return f.respond(name, args)
}

func (f *fakeRunner) count(needle string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := 0
	for _, c := range f.calls {
		if strings.Contains(c[1], needle) {
			n++
		}
	}
	return n
}

// setupTestEnv 建临时 sqlite + 防火墙配置（persistPath 指向临时文件），并替换 DefaultRunner。
func setupTestEnv(t *testing.T) (*gorm.DB, *fakeRunner, string) {
	t.Helper()
	db, err := gorm.Open("sqlite3", filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	db.AutoMigrate(&fw.FirewallIntent{})
	t.Cleanup(func() { db.Close() })

	persistPath := filepath.Join(t.TempDir(), "rules.v4")
	cfgDir := t.TempDir()
	cfg := fmt.Sprintf("firewall:\n  enabled: true\n  persistPath: %s\n  rollbackSeconds: 300\n  protectPorts: []\n", persistPath)
	if err := os.WriteFile(filepath.Join(cfgDir, "bmssm.yaml"), []byte(cfg), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("BMSSM_CONF", cfgDir)
	config.LoadConfig()

	f := &fakeRunner{}
	old := fw.DefaultRunner
	fw.DefaultRunner = f
	t.Cleanup(func() { fw.DefaultRunner = old })
	return db, f, persistPath
}

func mustInsertIntent(t *testing.T, db *gorm.DB, id int64, typ string, params map[string]interface{}) {
	t.Helper()
	b, _ := json.Marshal(params)
	if err := db.Create(&fw.FirewallIntent{ID: id, Type: typ, Params: string(b), Enabled: 1}).Error; err != nil {
		t.Fatalf("insert intent: %v", err)
	}
}

// 非 Docker 环境（DOCKER-USER 链不存在）Rebuild 主路径必须成功 —— B1 回归。
func TestRebuildNonDocker(t *testing.T) {
	db, f, persistPath := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortAllow), map[string]interface{}{"proto": "tcp", "port": 8080})

	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"), strings.Contains(j, "netstat -tlnp"):
			return "", "not found", errors.New("not found")
		case strings.Contains(j, "iptables-save -t filter"):
			return "*filter\nCOMMIT\n", "", nil
		case strings.Contains(j, "-L DOCKER-USER"):
			return "", "iptables: No chain/target/match by that name.", errors.New("exit status 1")
		case strings.Contains(j, "-L INPUT"):
			return "", "", nil
		case strings.Contains(j, "iptables-save"):
			return "*filter\n-A INPUT -j ACCEPT\nCOMMIT\n", "", nil
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err != nil {
		t.Fatalf("Rebuild on non-Docker device must succeed: %v", err)
	}
	if f.count("-A INPUT") == 0 {
		t.Error("expected intent rule insertion")
	}
	// 持久化文件已写入
	data, err := os.ReadFile(persistPath)
	if err != nil {
		t.Fatalf("persist file not written: %v", err)
	}
	if !strings.Contains(string(data), "-A INPUT -j ACCEPT") {
		t.Errorf("persisted content: %q", string(data))
	}
}

// Docker 设备：DOCKER-USER 遗留规则被清理，Rebuild 成功。
func TestRebuildDockerCleanupLegacy(t *testing.T) {
	db, f, _ := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortAllow), map[string]interface{}{"proto": "tcp", "port": 8080})

	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"), strings.Contains(j, "netstat -tlnp"):
			return "", "not found", errors.New("not found")
		case strings.Contains(j, "iptables-save -t filter"):
			return "*filter\nCOMMIT\n", "", nil
		case strings.Contains(j, "-L DOCKER-USER"):
			return "1  bmssm-fw-docker 1  -p tcp --dport 8080 -j DROP\n", "", nil
		case strings.Contains(j, "-L INPUT"):
			return "1  bmssm-fw-intent 9  tcp dpt:8080\n", "", nil
		case strings.Contains(j, "iptables-save"):
			return "*filter\nCOMMIT\n", "", nil
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	if f.count("-D DOCKER-USER") == 0 {
		t.Error("expected legacy DOCKER-USER rule deletion")
	}
}

// INPUT 列表失败 → CleanManaged 报错 → Rebuild 回滚快照。
func TestRebuildCleanFailureRollsBack(t *testing.T) {
	db, f, _ := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortAllow), map[string]interface{}{"proto": "tcp", "port": 8080})

	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"), strings.Contains(j, "netstat -tlnp"):
			return "", "not found", errors.New("not found")
		case strings.Contains(j, "iptables-save -t filter"):
			return "*filter\n-A INPUT -j ACCEPT\nCOMMIT\n", "", nil
		case strings.Contains(j, "-L INPUT"):
			return "", "iptables: Permission denied (you must be root)", errors.New("exit status 3")
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err == nil {
		t.Fatal("expected error when INPUT list fails")
	}
	if f.count("iptables-restore") == 0 {
		t.Error("expected snapshot restore on clean failure")
	}
}

// 插入失败 → Rebuild 回滚快照。
func TestRebuildInsertFailureRollsBack(t *testing.T) {
	db, f, _ := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortAllow), map[string]interface{}{"proto": "tcp", "port": 8080})

	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"), strings.Contains(j, "netstat -tlnp"):
			return "", "not found", errors.New("not found")
		case strings.Contains(j, "iptables-save -t filter"):
			return "*filter\nCOMMIT\n", "", nil
		case strings.Contains(j, "-L DOCKER-USER"):
			return "", "No chain", errors.New("exit status 1")
		case strings.Contains(j, "-L INPUT"):
			return "", "", nil
		case strings.Contains(j, "-A INPUT"):
			return "", "iptables: Resource temporarily unavailable", errors.New("exit status 1")
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err == nil {
		t.Fatal("expected error when rule insert fails")
	}
	if f.count("iptables-restore") == 0 {
		t.Error("expected snapshot restore on insert failure")
	}
}

// 持久化失败 → live 已替换但 rules.v4 未更新 → 回滚快照。
func TestRebuildPersistFailureRollsBack(t *testing.T) {
	db, f, _ := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortAllow), map[string]interface{}{"proto": "tcp", "port": 8080})

	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"), strings.Contains(j, "netstat -tlnp"):
			return "", "not found", errors.New("not found")
		case strings.Contains(j, "iptables-save -t filter"):
			return "*filter\nCOMMIT\n", "", nil
		case strings.Contains(j, "-L DOCKER-USER"):
			return "", "No chain", errors.New("exit status 1")
		case strings.Contains(j, "-L INPUT"):
			return "", "", nil
		case strings.Contains(j, "iptables-save"):
			return "", "iptables-save: failed", errors.New("exit status 1")
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err == nil {
		t.Fatal("expected error when persist fails")
	}
	if f.count("iptables-restore") == 0 {
		t.Error("expected snapshot restore on persist failure")
	}
}

// 保护端口守卫：探测到 sshd 在 22，port_deny 全网段 22 被拦截，不产生任何 iptables 变更。
func TestRebuildGuardBlocksDeny(t *testing.T) {
	db, f, _ := setupTestEnv(t)
	mustInsertIntent(t, db, 1, string(fw.IntentPortDeny), map[string]interface{}{"proto": "tcp", "port": 22})

	ssOut := "LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:((\"sshd\",pid=1,fd=3))\n"
	f.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "ss -tlnpH"):
			return ssOut, "", nil
		}
		return "", "", nil
	}

	svc := NewService(db)
	if err := svc.Rebuild(); err == nil {
		t.Fatal("expected guard to block deny on protect port 22")
	}
	if f.count("iptables-save") != 0 || f.count("-A INPUT") != 0 {
		t.Error("no iptables mutation should happen when guard blocks")
	}
}