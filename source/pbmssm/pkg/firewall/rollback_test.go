package firewall

import (
	"context"
	"testing"
	"time"
)

type cmdRecorder struct {
	calls [][]string
}

func (c *cmdRecorder) Run(name string, args ...string) (string, string, error) {
	c.calls = append(c.calls, append([]string{name}, args...))
	return "", "", nil
}

func TestInsertProtect(t *testing.T) {
	r := &cmdRecorder{}
	if err := InsertProtect(r, "tok1", []int{22, 443}); err != nil {
		t.Fatal(err)
	}
	// 应有 2 次 iptables -I INPUT 1 ... -j ACCEPT ... comment bmssm-fw-protect tok1
	if len(r.calls) != 2 {
		t.Fatalf("got %d calls want 2", len(r.calls))
	}
	for _, c := range r.calls {
		if c[0] != "iptables" || c[2] != "INPUT" {
			t.Errorf("bad call: %v", c)
		}
	}
}

func TestCleanProtectByComment(t *testing.T) {
	r := &cmdRecorder{}
	// CleanProtect 需先 list 再删；fake 返空，应不报错
	if err := CleanProtect(r, "tok1"); err != nil {
		t.Fatal(err)
	}
}

func TestCleanManaged(t *testing.T) {
	r := &cmdRecorder{}
	if err := CleanManaged(r); err != nil {
		t.Fatal(err)
	}
}

func TestCrashRecoverExpired(t *testing.T) {
	db := testDB(t)
	// 存一个已过期未 confirm 的 apply
	row := FirewallApply{Token: "old", AppliedAt: time.Now().Add(-10 * time.Minute), RollbackAt: time.Now().Add(-5 * time.Minute), Confirmed: 0, Snapshot: "*filter\nCOMMIT\n"}
	db.Save(&row)
	r := &cmdRecorder{}
	CrashRecover(newApplierForTest(db, r, nil))
	// 应删除该 apply 记录
	pending, _ := ListPendingApplies(db)
	if len(pending) != 0 {
		t.Error("expired apply should be recovered")
	}
}

func TestTimerCancelByContext(t *testing.T) {
	fired := false
	ctx, cancel := context.WithCancel(context.Background())
	tr := StartTimer(ctx, 10*time.Second, func() { fired = true })
	cancel() // 立即取消
	time.Sleep(50 * time.Millisecond)
	if tr.Fired() {
		t.Error("timer should not fire after cancel")
	}
	if fired {
		t.Error("onFire should not run after cancel")
	}
}

func TestTimerDoneChannel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	tr := StartTimer(ctx, 10*time.Second, func() {})
	cancel()
	<-tr.Done() // should close after goroutine exits
	// Done channel consumed successfully, no hang
}

func TestTimerFireRace(t *testing.T) {
	// Concurrent Store/Load must not race (verified by -race).
	timer := &Timer{done: make(chan struct{})}
	done := make(chan struct{})
	go func() {
		timer.fired.Store(true)
		close(done)
	}()
	// spin reading while writer stores
	for i := 0; i < 100; i++ {
		_ = timer.Fired()
	}
	<-done
	if !timer.Fired() {
		t.Error("fired should be true after Store")
	}
}

func TestTimerFiresOnFire(t *testing.T) {
	// 到期触发 onFire；用极短 duration 确定性地触发。
	called := make(chan struct{}, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	tr := StartTimer(ctx, 5*time.Millisecond, func() { called <- struct{}{} })
	<-called
	<-tr.Done()
	if tr.Fired() {
		t.Error("Fired() reflects timer-internal flag; onFire-driven firing should not set it unless onFire does")
	}
}

// TestCrashRecoverResumeNoOpAfterConfirm 验证 I2 修复：CrashRecover 为未过期 pending
// 注册的 resume timer，若随后 Confirm(token) 抢先，resume 到期调 fireRollback 必须
// no-op（不 Restore、不删记录、保持 confirmed=1）。即 resume 与 in-process Confirm 走
// 同一套 mu 串行化（与 TestFireRollbackNoOpAfterConfirm 同型）。
func TestCrashRecoverResumeNoOpAfterConfirm(t *testing.T) {
	db := testDB(t)
	r := &restoreRecorder{}
	a := newApplierForTest(db, r, []int{22})
	// 存一个未过期 pending apply（rollback_at 在未来），模拟崩溃后重启。
	row := FirewallApply{
		Token:      "resume-tok",
		AppliedAt:  time.Now(),
		RollbackAt: time.Now().Add(2 * time.Second),
		Confirmed:  0,
		Snapshot:   "*filter\nCOMMIT\n",
	}
	if err := db.Save(&row).Error; err != nil {
		t.Fatal(err)
	}
	// CrashRecover 注册 resume timer 进 applier a。
	CrashRecover(a)
	// Confirm 抢先（在 resume timer 到期前）。
	if err := a.Confirm("resume-tok"); err != nil {
		t.Fatal(err)
	}
	restoresBefore := r.restores
	// 等 resume timer 到期 + goroutine 调 fireRollback。
	time.Sleep(3 * time.Second)
	if r.restores != restoresBefore {
		t.Errorf("resume fireRollback should not Restore after Confirm: restores %d→%d", restoresBefore, r.restores)
	}
	ap, err := GetApply(db, "resume-tok")
	if err != nil {
		t.Fatalf("apply record should still exist after Confirm+resume: %v", err)
	}
	if ap.Confirmed != 1 {
		t.Errorf("apply should remain confirmed=1, got %d", ap.Confirmed)
	}
}
