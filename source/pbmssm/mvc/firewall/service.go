package firewall

import (
	"fmt"
	"sync"

	"bmssm/logger"
	"bmssm/pkg/firewall"

	"github.com/jinzhu/gorm"
)

// Service is the firewall MVC service, wrapping pkg/firewall logic with a DB handle.
type Service struct {
	db *gorm.DB

	// rebuildMu 串行化 Rebuild，防止并发 rebuild 交错 CleanManaged/插入产生重复或残缺规则集。
	rebuildMu sync.Mutex
}

// NewService creates a new Service with the given DB.
func NewService(db *gorm.DB) *Service {
	return &Service{db: db}
}

var (
	defaultServiceOnce sync.Once
	defaultServiceInst *Service
)

// DefaultService 返回懒初始化的包级单例 Service（全局 DB）。
func DefaultService() *Service {
	defaultServiceOnce.Do(func() {
		defaultServiceInst = NewService(firewall.DB())
	})
	return defaultServiceInst
}

// Status returns environment check results and detected protect ports.
func (s *Service) Status() (firewall.EnvResult, []int, error) {
	env := firewall.CheckEnvironment(firewall.DefaultRunner)
	protect := firewall.ProtectPorts(firewall.DefaultRunner)
	return env, protect, nil
}

// --- Intents ---

// ListIntents returns all persisted firewall intents.
func (s *Service) ListIntents() ([]firewall.Intent, error) { return firewall.ListIntents(s.db) }

// AddIntent validates and persists a new or updated firewall intent.
// Blocks port_deny rules targeting protect ports with 0.0.0.0/0.
// 仅在启用（Enabled=true）时执行保护端口守卫：关闭/禁用一条已存在的意图是降低风险操作，
// 不应被创建期守卫拦阻（否则旧版遗留的保护端口 deny 规则无法通过 UI 关闭）。
func (s *Service) AddIntent(req IntentRequest) error {
	it := firewall.Intent{ID: req.ID, Type: firewall.IntentType(req.Type), Params: req.Params, Enabled: req.Enabled}
	if err := it.Validate(); err != nil {
		return err
	}

	if req.Enabled {
		protect := firewall.ProtectPorts(firewall.DefaultRunner)
		if err := firewall.CheckProtectDeny(&it, protect); err != nil {
			return err
		}
	}

	return firewall.SaveIntent(s.db, &it)
}

// DeleteIntent removes an intent by its ID.
func (s *Service) DeleteIntent(id int64) error { return firewall.DeleteIntent(s.db, id) }

// Rebuild translates all enabled intents, cleans managed rules, inserts the new ruleset,
// and persists to rules.v4. 失败时恢复快照，避免 live 处于半配置状态。
// 串行化执行（rebuildMu），防止并发 rebuild 交错产生重复/残缺规则集。
// 安全边界：无旧 Apply 的"临时放行 + 回滚计时器"兜底，仅靠 CheckProtectDeny 守卫
// （见 pkg/firewall.CheckProtectDeny 注释的已知边界）。
func (s *Service) Rebuild() error {
	s.rebuildMu.Lock()
	defer s.rebuildMu.Unlock()

	intents, err := firewall.ListIntents(s.db)
	if err != nil {
		return err
	}
	var rules []firewall.IptablesRule
	// 应用前用当前探测的保护端口复审全部 enabled 意图：
	// 创建时合法（如 sshd 停机时 22 未被保护）、现在危险的意图在此被拦截（S2）。
	protect := firewall.ProtectPorts(firewall.DefaultRunner)
	for _, it := range intents {
		if !it.Enabled {
			continue
		}
		if err := firewall.CheckProtectDeny(&it, protect); err != nil {
			return err
		}
		rs, err := it.Translate()
		if err != nil {
			return err
		}
		rules = append(rules, rs...)
	}

	r := firewall.DefaultRunner

	// 快照当前规则，CleanManaged/插入/持久化任一失败时恢复，保证原子性。
	snap, err := firewall.Snapshot(r)
	if err != nil {
		return err
	}

	rollback := func() {
		if rerr := firewall.Restore(r, snap); rerr != nil {
			logger.Error("rebuild rollback restore failed: %v", rerr)
		}
	}

	if err := firewall.CleanManaged(r); err != nil {
		rollback()
		return err
	}
	for _, rule := range rules {
		tableArgs := []string{}
		if rule.Table != "" {
			tableArgs = append(tableArgs, "-t", rule.Table)
		}
		args := append(append(tableArgs, "-A", rule.Chain), rule.Args...)
		if _, errStr, err := r.Run("iptables", args...); err != nil {
			rollback()
			return fmt.Errorf("insert rule %v: %s: %s", rule.Args, err, errStr)
		}
	}

	_, persistPath, _, _ := firewall.FirewallConfig()
	if err := firewall.PersistRules(r, persistPath); err != nil {
		// live 已全部替换但 rules.v4 未更新：回滚快照，避免重启后规则静默丢失（S3）。
		rollback()
		return err
	}
	return nil
}
