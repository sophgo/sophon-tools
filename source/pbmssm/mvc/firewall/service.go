package firewall

import (
	"sync"

	"bmssm/pkg/firewall"

	"github.com/jinzhu/gorm"
)

// Service is the firewall MVC service, wrapping pkg/firewall logic with a DB handle.
type Service struct {
	db      *gorm.DB
	applier *firewall.Applier
}

// NewService creates a new Service with the given DB.
func NewService(db *gorm.DB) *Service {
	return &Service{db: db, applier: firewall.NewApplier(db, firewall.DefaultRunner)}
}

// defaultServiceOnce 保证 DefaultService 返回单例，使 init.go 的 CrashRecover 与
// HTTP handlers 共享同一个 *Applier（timer/cancel 映射 + mu 串行化统一）。
var (
	defaultServiceOnce sync.Once
	defaultServiceInst *Service
)

// DefaultService 返回懒初始化的包级单例 Service（全局 DB）。
// init.go 的 CrashRecover 必须用同一实例的 Applier，否则崩溃恢复的 resume timer
// 不受 live Confirm/Rollback 的 mu 串行化，重新引入 Task 9 修复的竞态。
func DefaultService() *Service {
	defaultServiceOnce.Do(func() {
		defaultServiceInst = NewService(firewall.DB())
	})
	return defaultServiceInst
}

// DefaultApplier 返回 DefaultService 单例所持的 *Applier，供 init.go CrashRecover 使用。
func DefaultApplier() *firewall.Applier { return DefaultService().applier }

// Status returns environment check results and detected protect ports.
func (s *Service) Status() (firewall.EnvResult, []int, error) {
	env := firewall.CheckEnvironment(firewall.DefaultRunner)
	protect := firewall.ProtectPorts(firewall.DefaultRunner)
	return env, protect, nil
}

// --- Intents ---

// ListIntents returns all persisted firewall intents.
func (s *Service) ListIntents() ([]firewall.Intent, error) { return firewall.ListIntents(s.db) }

// AddIntent validates and persists a new firewall intent.
func (s *Service) AddIntent(req IntentRequest) error {
	it := firewall.Intent{Type: firewall.IntentType(req.Type), Params: req.Params, Enabled: req.Enabled}
	if err := it.Validate(); err != nil {
		return err
	}
	return firewall.SaveIntent(s.db, &it)
}

// DeleteIntent removes an intent by its ID.
func (s *Service) DeleteIntent(id int64) error { return firewall.DeleteIntent(s.db, id) }

// --- Docker Rules ---

// ListDockerRules returns all persisted docker-user rules.
func (s *Service) ListDockerRules() ([]firewall.DockerRule, error) {
	return firewall.ListDockerRules(s.db)
}

// AddDockerRule validates and persists a new docker-user rule.
func (s *Service) AddDockerRule(req DockerRuleRequest) error {
	d := firewall.DockerRule{Scene: firewall.DockerScene(req.Scene), Params: req.Params, Enabled: req.Enabled}
	if err := d.Validate(); err != nil {
		return err
	}
	return firewall.SaveDockerRule(s.db, &d)
}

// DeleteDockerRule removes a docker-user rule by its ID.
func (s *Service) DeleteDockerRule(id int64) error { return firewall.DeleteDockerRule(s.db, id) }

// --- Raw Rules ---

// ListRaw returns live iptables filter table rules.
func (s *Service) ListRaw() ([]firewall.LiveRule, error) {
	return firewall.ListFilter(firewall.DefaultRunner)
}

// AddRaw inserts a raw iptables rule directly into the live ruleset.
func (s *Service) AddRaw(req RawRuleRequest) error {
	return firewall.AddRaw(firewall.DefaultRunner, firewall.RawRule{Chain: req.Chain, Args: req.Args})
}

// DeleteRaw deletes a raw iptables rule by chain and line number.
func (s *Service) DeleteRaw(chain string, num int) error {
	return firewall.DeleteRaw(firewall.DefaultRunner, chain, num)
}

// --- Apply Lifecycle ---

// Apply translates all enabled intents and docker rules, statically checks for risks,
// snapshots, rebuilds, and starts a rollback timer.
func (s *Service) Apply(force bool) (*firewall.ApplyResult, error) { return s.applier.Apply(force) }

// Confirm marks an apply as confirmed, cancels its rollback timer, and cleans protect rules.
func (s *Service) Confirm(token string) error { return s.applier.Confirm(token) }

// Rollback restores the snapshot for the given apply token and cleans it up.
func (s *Service) Rollback(token string) error { return s.applier.Rollback(token) }
