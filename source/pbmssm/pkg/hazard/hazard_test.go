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
