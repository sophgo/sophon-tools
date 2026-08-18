package hazard

import (
	"strings"
	"testing"
)

func TestLockConcurrentExclusive(t *testing.T) {
	g1, err := HazardOps.TryAcquire("reboot")
	if err != nil {
		t.Fatalf("first acquire failed: %v", err)
	}
	defer g1.Release()

	if _, err := HazardOps.TryAcquire("ota-upgrade"); err == nil {
		t.Fatal("second acquire should fail while held")
	} else if !strings.Contains(err.Error(), "reboot") {
		t.Fatalf("conflict error should name holder, got: %v", err)
	}

	g1.Release()
	g2, err := HazardOps.TryAcquire("shutdown")
	if err != nil {
		t.Fatalf("acquire after release failed: %v", err)
	}
	g2.Release()
}

func TestLockIdempotentRelease(t *testing.T) {
	g := &Guard{l: HazardOps}
	g.Release()
	g.Release() // 不应 panic
	if _, err := HazardOps.TryAcquire("ota-rollback"); err != nil {
		t.Fatalf("acquire after double release failed: %v", err)
	}
	HazardOps.Release()
}

func TestConfirmCodeReusableWithinTTL(t *testing.T) {
	code := NewConfirmCode()
	if len(code) != confirmCodeLen {
		t.Fatalf("code length = %d, want %d", len(code), confirmCodeLen)
	}
	for _, ch := range code {
		if !strings.ContainsRune(confirmChars, ch) {
			t.Fatalf("code contains invalid char %q", ch)
		}
	}
	if !VerifyConfirmCode(code) {
		t.Fatal("valid code should verify")
	}
	if !VerifyConfirmCode(code) {
		t.Fatal("code should stay valid within TTL window (reusable for concurrent requests)")
	}
}

func TestConfirmCodeWrong(t *testing.T) {
	NewConfirmCode()
	if VerifyConfirmCode("WRONG!!") {
		t.Fatal("wrong code should not verify")
	}
	if VerifyConfirmCode("") {
		t.Fatal("empty code should not verify")
	}
}

// TestNoOpGuardDoesNotReleaseOthers no-op Guard（holder 为空，软件安装等
// 并发场景）释放时不得误清他人持有的锁。
func TestNoOpGuardDoesNotReleaseOthers(t *testing.T) {
	noop, err := HazardOps.TryAcquire("")
	if err != nil {
		t.Fatalf("no-op acquire should always succeed: %v", err)
	}

	// 他人获取真实锁
	g, err := HazardOps.TryAcquire("reboot")
	if err != nil {
		t.Fatalf("real acquire after no-op: %v", err)
	}
	// no-op guard 释放不得影响真实持有
	noop.Release()
	if _, err := HazardOps.TryAcquire("shutdown"); err == nil {
		t.Fatal("no-op guard release must not clear another holder's lock")
	}
	g.Release()
	if _, err := HazardOps.TryAcquire("shutdown"); err != nil {
		t.Fatalf("release after real guard: %v", err)
	}
	HazardOps.Release()
}

// TestGuardReleaseOnlyOwnHolder 持有者变更后，旧 guard 的 Release 不得误清新持有者。
func TestGuardReleaseOnlyOwnHolder(t *testing.T) {
	g, err := HazardOps.TryAcquire("reboot")
	if err != nil {
		t.Fatalf("acquire: %v", err)
	}
	// 模拟异常清空后他人重新获取
	HazardOps.Release()
	g2, err := HazardOps.TryAcquire("shutdown")
	if err != nil {
		t.Fatalf("re-acquire: %v", err)
	}
	// 旧 guard 释放：持有者是 shutdown 而非 reboot，不应被清掉
	g.Release()
	if _, err := HazardOps.TryAcquire("ota-upgrade"); err == nil {
		t.Fatal("stale guard must not release a different holder's lock")
	}
	g2.Release()
}
