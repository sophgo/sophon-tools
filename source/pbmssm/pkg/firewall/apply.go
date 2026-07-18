package firewall

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"sync"
	"time"

	"bmssm/logger"

	"github.com/jinzhu/gorm"
)

type ApplyResult struct {
	Token           string `json:"token"`
	Risks           []Risk `json:"risks"`
	ProtectPorts    []int  `json:"protectPorts"`
	RollbackSeconds int    `json:"rollbackSeconds"`
}

type Applier struct {
	db              *gorm.DB
	r               CommandRunner
	mu              sync.Mutex
	timers          map[string]*Timer
	cancels         map[string]context.CancelFunc
	protectOverride []int // 测试用；生产为 nil 走动态探测
}

func NewApplier(db *gorm.DB, r CommandRunner) *Applier {
	return &Applier{db: db, r: r, timers: map[string]*Timer{}, cancels: map[string]context.CancelFunc{}}
}

// newApplierForTest 测试用，注入 protect 端口覆盖。
func newApplierForTest(db *gorm.DB, r CommandRunner, protect []int) *Applier {
	a := NewApplier(db, r)
	a.protectOverride = protect
	return a
}

func (a *Applier) protectPorts() []int {
	if a.protectOverride != nil {
		return a.protectOverride
	}
	return ProtectPorts(a.r)
}

func newToken() string {
	b := make([]byte, 8)
	rand.Read(b)
	return hex.EncodeToString(b) + fmt.Sprintf("%d", time.Now().UnixNano())
}

// Apply 编排：环境→翻译→静态检测→快照→临时放行→rebuild→持久化→timer。原子。
func (a *Applier) Apply(force bool) (*ApplyResult, error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	// ① 环境硬门禁
	env := CheckEnvironment(a.r)
	if !env.OK {
		return nil, fmt.Errorf("%w: 环境不满足，请先修复: %v", ErrEnvironment, env.Issues)
	}

	// 并发：拒绝未确认的 pending
	pending, _ := ListPendingApplies(a.db)
	if len(pending) > 0 {
		return nil, fmt.Errorf("%w: 上一次应用 %s 尚未确认，请先确认或回滚", ErrPendingApply, pending[0].Token)
	}

	// ② 翻译所有 enabled 意图 + docker 规则
	intents, err := ListIntents(a.db)
	if err != nil {
		return nil, err
	}
	var rules []IptablesRule
	for _, it := range intents {
		if !it.Enabled {
			continue
		}
		rs, err := it.Translate()
		if err != nil {
			return nil, fmt.Errorf("intent %d translate: %w", it.ID, err)
		}
		rules = append(rules, rs...)
	}
	dockerRules, err := ListDockerRules(a.db)
	if err != nil {
		return nil, err
	}
	for _, d := range dockerRules {
		if !d.Enabled {
			continue
		}
		rs, err := d.Translate()
		if err != nil {
			return nil, fmt.Errorf("docker %d translate: %w", d.ID, err)
		}
		rules = append(rules, rs...)
	}

	// ③ 静态检测
	protect := a.protectPorts()
	risks := CheckRisks(rules, protect)
	if len(risks) > 0 && !force {
		return &ApplyResult{Risks: risks, ProtectPorts: protect}, fmt.Errorf("%w: 检测到 %d 条屏蔽风险，请修改规则或使用 force", ErrRiskDetected, len(risks))
	}

	token := newToken()
	logger.Info("firewall apply %s start, %d rules, protect=%v, force=%v", token, len(rules), protect, force)

	// ④ 快照（apply 前完整状态，回滚用）
	snap, err := Snapshot(a.r)
	if err != nil {
		return nil, fmt.Errorf("snapshot: %w", err)
	}

	// ⑤ 临时放行（四道闸之一）
	if err := InsertProtect(a.r, token, protect); err != nil {
		// 部分插入失败 → 清已插入的 protect 规则，避免孤儿。rebuild 尚未运行，
		// managed 规则未动，CleanProtect 足以回到 apply 前状态；Restore 快照兜底保证精确一致。
		logger.Error("firewall apply %s insert protect failed, cleaning partial: %v", token, err)
		CleanProtect(a.r, token)
		if rerr := Restore(a.r, snap); rerr != nil {
			logger.Error("restore after insert-protect fail: %v", rerr)
		}
		return nil, fmt.Errorf("insert protect: %w", err)
	}

	// ⑥ rebuild：清场 + 插入。任一失败 → restore 快照 + clean protect + 返错（原子性）
	if err := a.rebuild(rules); err != nil {
		logger.Error("firewall apply %s rebuild failed, restoring snapshot: %v", token, err)
		if rerr := Restore(a.r, snap); rerr != nil {
			logger.Error("restore after fail: %v", rerr)
		}
		CleanProtect(a.r, token)
		return nil, fmt.Errorf("rebuild: %w", err)
	}

	// ⑦ 存 apply 记录（先于 PersistRules：若 SaveApply 失败，live 已回滚，rules.v4 未改，无 reboot landmine）
	if err := SaveApply(a.db, token, snap); err != nil {
		// 持久化失败但 live 已生效 + protect 已插入 + 无 timer → 下次 Apply 见无 pending 行
		// 会继续，孤儿化本次 live 状态。回滚到快照 + 清 protect，使 caller 收错且状态干净。
		logger.Error("firewall apply %s save apply failed, rolling back live: %v", token, err)
		if rerr := Restore(a.r, snap); rerr != nil {
			logger.Error("restore after save-apply fail: %v", rerr)
		}
		CleanProtect(a.r, token)
		return nil, fmt.Errorf("save apply: %w", err)
	}

	// ⑧ 持久化 rules.v4（SaveApply 已成功；PersistRules 失败仅警告——live 已生效 + 记录已存）
	_, persistPath, _, _ := FirewallConfig()
	if err := PersistRules(a.r, persistPath); err != nil {
		logger.Error("firewall apply %s persist failed (live rules OK): %v", token, err)
	}

	// ⑨ 启 timer
	_, _, sec, _ := FirewallConfig()
	if sec <= 0 {
		sec = 300
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.timers[token] = StartTimer(ctx, time.Duration(sec)*time.Second, func() { a.fireRollback(token) })
	a.cancels[token] = cancel

	return &ApplyResult{Token: token, Risks: risks, ProtectPorts: protect, RollbackSeconds: sec}, nil
}

// rebuild 清场后逐条插入。任一失败返错（由 Apply 负责回滚）。
func (a *Applier) rebuild(rules []IptablesRule) error {
	if err := CleanManaged(a.r); err != nil {
		return err
	}
	for _, r := range rules {
		tableArgs := []string{}
		if r.Table != "" {
			tableArgs = append(tableArgs, "-t", r.Table)
		}
		args := append(append(tableArgs, "-A", r.Chain), r.Args...)
		if _, errStr, err := a.r.Run("iptables", args...); err != nil {
			return fmt.Errorf("insert rule %v: %s: %s", r.Args, err, errStr)
		}
	}
	return nil
}

// Confirm 取消 timer + 删临时放行 + 标记 confirmed。
func (a *Applier) Confirm(token string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if cancel, ok := a.cancels[token]; ok {
		cancel()
		delete(a.cancels, token)
	}
	delete(a.timers, token)
	if err := ConfirmApply(a.db, token); err != nil {
		return err
	}
	CleanProtect(a.r, token)
	logger.Info("firewall apply %s confirmed", token)
	return nil
}

// Rollback 立即回滚到快照 + 清临时放行 + 删 apply 记录。
func (a *Applier) Rollback(token string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if cancel, ok := a.cancels[token]; ok {
		cancel()
		delete(a.cancels, token)
	}
	delete(a.timers, token)
	apply, err := GetApply(a.db, token)
	if err != nil {
		return err
	}
	if err := Restore(a.r, apply.Snapshot); err != nil {
		return err
	}
	CleanProtect(a.r, token)
	DeleteApply(a.db, token)
	logger.Info("firewall apply %s rolled back", token)
	return nil
}

// fireRollback 由 timer 到期回调。在 a.mu 下重新检查状态：若 Confirm/Rollback 已
// 抢先（cancels[token] 已删 或 confirmed==1）→ no-op；否则执行 Restore+CleanProtect+DeleteApply。
// 重新检查消解 timer goroutine 与 Confirm/Rollback 之间的竞态：旧实现 goroutine 不持
// mu，可能在 Confirm 提交 confirmed=1 前读到 0 并回滚一个已确认的 apply（锁出用户）。
func (a *Applier) fireRollback(token string) {
	a.mu.Lock()
	defer a.mu.Unlock()

	// Confirm/Rollback 已抢先：二者均在 mu 下 cancel()+delete(cancels) 原子完成。
	// cancels[token] 缺失即代表它们已接管善后，timer no-op。
	// （CrashRecover 过期路径直接调 rollbackLocked，不经此 guard。）
	if _, ok := a.cancels[token]; !ok {
		return
	}
	a.rollbackLocked(token)
}

// rollbackLocked 执行实际回滚 + 状态重检查（须持 a.mu）。fireRollback（in-process timer）
// 先经 cancels guard 再调此；CrashRecover 过期路径直接调此（无 cancel 映射）。
// 重检查 Confirmed：若 Confirm 已提交 → no-op，绝不回滚已确认的 apply。
func (a *Applier) rollbackLocked(token string) {
	apply, err := GetApply(a.db, token)
	if err != nil {
		// 记录已不在（可能 Rollback 已删）→ 清 timer/cancel 映射后 no-op。
		delete(a.timers, token)
		delete(a.cancels, token)
		return
	}
	if apply.Confirmed == 1 {
		// Confirm 已提交 → no-op，绝不回滚已确认的 apply（belt-and-suspenders）。
		delete(a.timers, token)
		delete(a.cancels, token)
		return
	}

	logger.Warn("firewall apply %s auto-rollback fired", token)
	if err := Restore(a.r, apply.Snapshot); err != nil {
		// Restore 失败 → 保留 protect + apply 记录（Task 8 安全语义），等人工介入。
		// timer 已触发（goroutine 退出），清 timer/cancel 映射避免泄漏。
		logger.Error("rollback restore %s: %v — keeping protect rules and apply record for safety", token, err)
		delete(a.timers, token)
		delete(a.cancels, token)
		return
	}
	CleanProtect(a.r, token)
	DeleteApply(a.db, token)
	if t, ok := a.timers[token]; ok {
		t.fired.Store(true)
	}
	delete(a.timers, token)
	delete(a.cancels, token)
}
