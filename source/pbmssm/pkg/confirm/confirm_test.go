package confirm

import (
	"testing"
	"time"
)

func TestPrepareVerifyOK(t *testing.T) {
	m := NewManager()
	code, _ := m.Prepare("reboot", "admin", DefaultTTL)
	if len(code) != codeDigits {
		t.Fatalf("code length = %d, want %d (%q)", len(code), codeDigits, code)
	}
	for _, ch := range code {
		if ch < '0' || ch > '9' {
			t.Fatalf("code should contain digits only: %q", code)
		}
	}
	if err := m.Verify("reboot", "admin", code); err != nil {
		t.Fatalf("Verify: %v", err)
	}
}

func TestVerifyOneTimeUse(t *testing.T) {
	m := NewManager()
	code, _ := m.Prepare("shutdown", "admin", DefaultTTL)
	if err := m.Verify("shutdown", "admin", code); err != nil {
		t.Fatalf("first verify: %v", err)
	}
	if err := m.Verify("shutdown", "admin", code); err != ErrMissing {
		t.Fatalf("second verify should be consumed (ErrMissing), got %v", err)
	}
}

func TestVerifyMissing(t *testing.T) {
	m := NewManager()
	if err := m.Verify("reboot", "admin", "123456"); err != ErrMissing {
		t.Fatalf("want ErrMissing, got %v", err)
	}
}

func TestVerifyWrongActionOrUser(t *testing.T) {
	m := NewManager()
	code, _ := m.Prepare("reboot", "admin", DefaultTTL)

	// 组合键不匹配（未对该 action+user 签发）→ ErrMissing
	if err := m.Verify("shutdown", "admin", code); err != ErrMissing {
		t.Fatalf("wrong action: want ErrMissing, got %v", err)
	}
	if err := m.Verify("reboot", "other", code); err != ErrMissing {
		t.Fatalf("wrong user: want ErrMissing, got %v", err)
	}
	// 校验失败不消费码：原主仍可用
	if err := m.Verify("reboot", "admin", code); err != nil {
		t.Fatalf("owner verify after failed attempts: %v", err)
	}
}

func TestVerifyWrongCode(t *testing.T) {
	m := NewManager()
	_, _ = m.Prepare("reboot", "admin", DefaultTTL)
	if err := m.Verify("reboot", "admin", "000000"); err != ErrInvalid {
		t.Fatalf("wrong code: want ErrInvalid, got %v", err)
	}
}

func TestVerifyExpired(t *testing.T) {
	m := NewManager()
	_, _ = m.Prepare("reboot", "admin", 1*time.Millisecond)
	time.Sleep(10 * time.Millisecond)
	if err := m.Verify("reboot", "admin", "000000"); err != ErrExpired {
		t.Fatalf("expired code: want ErrExpired, got %v", err)
	}
}

func TestVerifyExpiredCorrectCode(t *testing.T) {
	m := NewManager()
	code, _ := m.Prepare("reboot", "admin", -1*time.Second) // 已过期
	if err := m.Verify("reboot", "admin", code); err != ErrExpired {
		t.Fatalf("want ErrExpired, got %v", err)
	}
}

func TestPrepareOverwritesOldCode(t *testing.T) {
	m := NewManager()
	oldCode, _ := m.Prepare("reboot", "admin", DefaultTTL)
	newCode, _ := m.Prepare("reboot", "admin", DefaultTTL)
	if oldCode == newCode {
		t.Fatal("two prepares should generate different codes")
	}
	if err := m.Verify("reboot", "admin", oldCode); err != ErrInvalid {
		t.Fatalf("old code should be invalid after re-prepare, got %v", err)
	}
	if err := m.Verify("reboot", "admin", newCode); err != nil {
		t.Fatalf("new code should verify: %v", err)
	}
}

func TestVerifyInvalidBannedAfterAttempts(t *testing.T) {
	m := NewManager()
	code, _ := m.Prepare("reboot", "admin", DefaultTTL)
	for i := 0; i < maxAttempts; i++ {
		_ = m.Verify("reboot", "admin", "000000")
	}
	// 连续失败 maxAttempts 次后会作废：正确码也无效（需要重新 Prepare）
	if err := m.Verify("reboot", "admin", code); err != ErrMissing && err != ErrInvalid {
		t.Fatalf("after max attempts, want ErrMissing/ErrInvalid, got %v", err)
	}
}

func TestGlobalManagerIsShared(t *testing.T) {
	defer Global().Reset()
	code, _ := Global().Prepare("reboot", "admin", DefaultTTL)
	if err := Global().Verify("reboot", "admin", code); err != nil {
		t.Fatalf("global verify: %v", err)
	}
}

func TestRandomCodeFormat(t *testing.T) {
	for i := 0; i < 100; i++ {
		c := randomCode()
		if len(c) != codeDigits {
			t.Fatalf("randomCode length = %d, want %d", len(c), codeDigits)
		}
	}
}
