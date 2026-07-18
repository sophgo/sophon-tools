package firewall

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"bmssm/logger"
)

// InsertProtect 在 INPUT 链头插入放行 protect 端口的临时规则（apply 前调）。
func InsertProtect(r CommandRunner, token string, ports []int) error {
	c := fmt.Sprintf("%s %s", CommentProtectPrefix, token)
	for _, p := range ports {
		args := []string{"-I", "INPUT", "1", "-p", "tcp", "--dport", strconv.Itoa(p), "-j", "ACCEPT", "-m", "comment", "--comment", c}
		if _, errStr, err := r.Run("iptables", args...); err != nil {
			return fmt.Errorf("insert protect %d: %s: %s", p, err, errStr)
		}
	}
	return nil
}

// CleanProtect 删除指定 token 的临时放行规则。按注释逐条删（用 -D 带 comment 匹配）。
func CleanProtect(r CommandRunner, token string) error {
	c := fmt.Sprintf("%s %s", CommentProtectPrefix, token)
	// 列 INPUT 规则，找带该注释的行号，逐条删（从大到小删，避免行号移位）
	out, _, _ := r.Run("iptables", "-t", "filter", "-L", "INPUT", "-n", "--line-numbers")
	var nums []int
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, c) {
			fields := strings.Fields(line)
			if len(fields) > 0 {
				if n, err := strconv.Atoi(fields[0]); err == nil {
					nums = append(nums, n)
				}
			}
		}
	}
	for i := len(nums) - 1; i >= 0; i-- {
		if _, errStr, err := r.Run("iptables", "-D", "INPUT", strconv.Itoa(nums[i])); err != nil {
			logger.Warn("clean protect INPUT %d: %s %s", nums[i], err, errStr)
		}
	}
	return nil
}

// CleanManaged 删除所有受管规则（bmssm-fw-intent / bmssm-fw-docker 注释）。rebuild 前清场。
func CleanManaged(r CommandRunner) error {
	for _, prefix := range []string{CommentIntentPrefix, CommentDockerPrefix} {
		for _, chain := range []string{"INPUT", "DOCKER-USER"} {
			out, _, _ := r.Run("iptables", "-t", "filter", "-L", chain, "-n", "--line-numbers")
			var nums []int
			for _, line := range strings.Split(out, "\n") {
				if strings.Contains(line, prefix) {
					fields := strings.Fields(line)
					if len(fields) > 0 {
						if n, err := strconv.Atoi(fields[0]); err == nil {
							nums = append(nums, n)
						}
					}
				}
			}
			for i := len(nums) - 1; i >= 0; i-- {
				if _, errStr, err := r.Run("iptables", "-D", chain, strconv.Itoa(nums[i])); err != nil {
					logger.Warn("clean managed %s %d: %s %s", chain, nums[i], err, errStr)
				}
			}
		}
	}
	return nil
}

// Timer 回滚 timer，context 可取消。
type Timer struct {
	fired atomic.Bool
	done  chan struct{}
}

func (t *Timer) Fired() bool { return t.fired.Load() }

// Done returns a channel that is closed when the timer goroutine finishes.
func (t *Timer) Done() <-chan struct{} { return t.done }

// StartTimer 启动回滚 timer。到期调 onFire（由 Applier 在 a.mu 下执行实际回滚 + 状态
// 重检查，消解与 Confirm/Rollback 的竞态）。ctx 取消则不触发。duration<=0 当作 300s。
func StartTimer(ctx context.Context, duration time.Duration, onFire func()) *Timer {
	t := &Timer{done: make(chan struct{})}
	if duration <= 0 {
		duration = 300 * time.Second
	}
	go func() {
		defer close(t.done)
		select {
		case <-time.After(duration):
			onFire()
		case <-ctx.Done():
			return
		}
	}()
	return t
}

// CrashRecover 启动时扫未 confirm 的 apply，已过 rollback_at 的回滚。
// 接收 live *Applier（与 HTTP handlers 共享的单例），使 resume timer 注册进
// applier.timers/cancels，受 applier.mu 串行化——与 in-process Confirm/Rollback
// 走同一套 fireRollback 重检查逻辑，消解 resume 与 Confirm 的竞态（Task 9 同类）。
func CrashRecover(a *Applier) {
	if a == nil {
		return
	}
	pending, err := ListPendingApplies(a.db)
	if err != nil {
		logger.Error("crash recover list pending: %v", err)
		return
	}
	for _, ap := range pending {
		if time.Now().Before(ap.RollbackAt) {
			// 未过期：注册 StartTimer 进 applier（ctx 可被后续 Confirm/Rollback 取消），
			// 到期调 applier.fireRollback（持 mu + 重检查 cancels/confirmed）。
			logger.Info("firewall: resume pending apply %s timer", ap.Token)
			a.mu.Lock()
			// 若该 token 已有 timer/cancel（异常重复 CrashRecover）→ 跳过避免覆盖。
			if _, exists := a.cancels[ap.Token]; exists {
				a.mu.Unlock()
				continue
			}
			ctx, cancel := context.WithCancel(context.Background())
			a.timers[ap.Token] = StartTimer(ctx, time.Until(ap.RollbackAt), func() { a.fireRollback(ap.Token) })
			a.cancels[ap.Token] = cancel
			a.mu.Unlock()
			continue
		}
		// 已过期：立即回滚（走 rollbackLocked 统一持 mu + 重检查 confirmed，避免与并发 Confirm 竞态）
		logger.Warn("firewall: crash recover expired apply %s", ap.Token)
		a.mu.Lock()
		a.rollbackLocked(ap.Token)
		a.mu.Unlock()
	}
}
