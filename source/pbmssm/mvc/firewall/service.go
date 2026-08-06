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
func (s *Service) AddIntent(req IntentRequest) error {
	it := firewall.Intent{ID: req.ID, Type: firewall.IntentType(req.Type), Params: req.Params, Enabled: req.Enabled}
	if err := it.Validate(); err != nil {
		return err
	}

	protect := firewall.ProtectPorts(firewall.DefaultRunner)
	if err := firewall.CheckProtectDeny(&it, protect); err != nil {
		return err
	}

	return firewall.SaveIntent(s.db, &it)
}

// DeleteIntent removes an intent by its ID.
func (s *Service) DeleteIntent(id int64) error { return firewall.DeleteIntent(s.db, id) }

// Rebuild translates all enabled intents, cleans managed rules, inserts the new ruleset,
// and persists to rules.v4. 失败时恢复快照，避免 live 处于半配置状态。
func (s *Service) Rebuild() error {
	intents, err := firewall.ListIntents(s.db)
	if err != nil {
		return err
	}
	var rules []firewall.IptablesRule
	for _, it := range intents {
		if !it.Enabled {
			continue
		}
		rs, err := it.Translate()
		if err != nil {
			return err
		}
		rules = append(rules, rs...)
	}

	r := firewall.DefaultRunner

	// 快照当前规则，CleanManaged/插入任一失败时恢复，保证原子性。
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
	return firewall.PersistRules(r, persistPath)
}
