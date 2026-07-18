package firewall

import (
	"testing"
)

func TestApplyEnvFail(t *testing.T) {
	db := testDB(t)
	r := fakeRunner{miss: true} // 环境不满足
	a := NewApplier(db, r)
	_, err := a.Apply(false)
	if err == nil {
		t.Fatal("want env error")
	}
}

func TestApplyRiskDetectedNoForce(t *testing.T) {
	db := testDB(t)
	// 存一条会屏蔽 protect 端口的意图
	SaveIntent(db, &Intent{Type: "port_deny", Params: `{"proto":"tcp","port":22}`, Enabled: true})
	r := &applyFake{} // protect 注入为 [22] via newApplierForTest
	a := newApplierForTest(db, r, []int{22})
	res, err := a.Apply(false)
	if err == nil {
		t.Fatal("want risk error")
	}
	if res == nil || len(res.Risks) == 0 {
		t.Fatal("want risks")
	}
}

func TestApplyForceBypassRisk(t *testing.T) {
	db := testDB(t)
	SaveIntent(db, &Intent{Type: "port_deny", Params: `{"proto":"tcp","port":22}`, Enabled: true})
	r := &applyFake{}
	a := newApplierForTest(db, r, []int{22})
	res, err := a.Apply(true) // force
	if err != nil {
		t.Fatalf("force should bypass: %v", err)
	}
	if res.Token == "" {
		t.Error("no token")
	}
	if res.RollbackSeconds != 300 {
		t.Errorf("default RollbackSeconds should be 300, got %d", res.RollbackSeconds)
	}
}

func TestApplyPendingReject(t *testing.T) {
	db := testDB(t)
	SaveApply(db, "existing", "SNAP") // 已有未 confirm
	r := &applyFake{}
	a := newApplierForTest(db, r, []int{22})
	_, err := a.Apply(false)
	if err == nil {
		t.Fatal("want pending reject")
	}
}

func TestConfirmCancelsTimer(t *testing.T) {
	db := testDB(t)
	r := &applyFake{}
	a := newApplierForTest(db, r, []int{22})
	res, err := a.Apply(true)
	if err != nil {
		t.Fatal(err)
	}
	if err := a.Confirm(res.Token); err != nil {
		t.Fatal(err)
	}
	// apply 记录应 confirmed
	ap, _ := GetApply(db, res.Token)
	if ap.Confirmed != 1 {
		t.Error("not confirmed")
	}
}

// applyFake 模拟环境 OK（iptables/iptables-save/iptables-restore/ufw/test 都在）
type applyFake struct {
	calls [][]string
}

func (a *applyFake) Run(name string, args ...string) (string, string, error) {
	a.calls = append(a.calls, append([]string{name}, args...))
	return "", "", nil // 所有命令成功；ufw status 返空(不含 active)→ 不冲突
}

// restoreRecorder 记录 iptables-restore 调用次数，用于断言 fireRollback 是否执行回滚。
type restoreRecorder struct {
	applyFake
	restores int
}

func (r *restoreRecorder) Run(name string, args ...string) (string, string, error) {
	r.calls = append(r.calls, append([]string{name}, args...))
	if name == "iptables-restore" {
		r.restores++
	}
	return "", "", nil
}

// TestFireRollbackNoOpAfterConfirm 验证 Finding 1 修复：timer 到期时若 Confirm 已提交
// confirmed=1，fireRollback 必须是 no-op（不 Restore、不删记录、fired 不置位）。
func TestFireRollbackNoOpAfterConfirm(t *testing.T) {
	db := testDB(t)
	r := &restoreRecorder{}
	a := newApplierForTest(db, r, []int{22})
	res, err := a.Apply(true)
	if err != nil {
		t.Fatal(err)
	}
	// Confirm 抢先：在 timer 触发前提交 confirmed=1 + 取消 timer。
	if err := a.Confirm(res.Token); err != nil {
		t.Fatal(err)
	}
	restoresBefore := r.restores
	// 模拟 timer 到期：直接调 fireRollback（StartTimer 内部就是这么调的）。
	a.fireRollback(res.Token)
	if r.restores != restoresBefore {
		t.Errorf("fireRollback should not Restore after Confirm: restores %d→%d", restoresBefore, r.restores)
	}
	ap, err := GetApply(db, res.Token)
	if err != nil {
		t.Fatalf("apply record should still exist after Confirm+fireRollback: %v", err)
	}
	if ap.Confirmed != 1 {
		t.Errorf("apply should remain confirmed=1, got %d", ap.Confirmed)
	}
}

// TestFireRollbackRestoresWhenNotConfirmed 验证未确认时 fireRollback 执行回滚。
func TestFireRollbackRestoresWhenNotConfirmed(t *testing.T) {
	db := testDB(t)
	r := &restoreRecorder{}
	a := newApplierForTest(db, r, []int{22})
	res, err := a.Apply(true)
	if err != nil {
		t.Fatal(err)
	}
	restoresBefore := r.restores
	a.fireRollback(res.Token)
	if r.restores != restoresBefore+1 {
		t.Errorf("fireRollback should Restore once: restores %d→%d", restoresBefore, r.restores)
	}
	if _, err := GetApply(db, res.Token); err == nil {
		t.Error("apply record should be deleted by fireRollback")
	}
}
