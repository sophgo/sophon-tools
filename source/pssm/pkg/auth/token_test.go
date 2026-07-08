package auth

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestIssueAndParseToken(t *testing.T) {
	secret := "test-secret"
	username := "testuser"

	tokenStr, expiresAt, err := IssueToken(username, secret, false)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}
	if tokenStr == "" {
		t.Fatal("token should not be empty")
	}
	if time.Until(expiresAt) < TokenTTL-time.Minute {
		t.Fatalf("expiresAt too early: %v (expected ~%v)", expiresAt, time.Now().Add(TokenTTL))
	}

	// 成功解析
	parsedUser, temp, err := ParseToken(tokenStr, secret)
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	if parsedUser != username {
		t.Fatalf("expected username %q, got %q", username, parsedUser)
	}
	if temp {
		t.Fatal("normal token should not be temp")
	}
}

func TestIssueAndParseTempToken(t *testing.T) {
	secret := "test-secret"
	tokenStr, _, err := IssueToken("changepass", secret, true)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}
	user, temp, err := ParseToken(tokenStr, secret)
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	if user != "changepass" {
		t.Fatalf("expected changepass, got %s", user)
	}
	if !temp {
		t.Fatal("temp token should parse as temp=true")
	}
}

func TestParseTokenInvalidSecret(t *testing.T) {
	tokenStr, _, err := IssueToken("user", "secret1", false)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}
	_, _, err = ParseToken(tokenStr, "wrong-secret")
	if err == nil {
		t.Fatal("expected error for wrong secret")
	}
}

func TestParseTokenExpired(t *testing.T) {
	secret := "test-secret"
	username := "expireduser"

	// 手工构造一个已过期的 token
	claims := jwt.MapClaims{
		"sub": username,
		"iat": time.Now().Add(-24 * time.Hour).Unix(),
		"exp": time.Now().Add(-1 * time.Hour).Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(secret))
	if err != nil {
		t.Fatalf("sign: %v", err)
	}

	_, _, err = ParseToken(tokenStr, secret)
	if err == nil {
		t.Fatal("expected error for expired token")
	}
}

func TestParseTokenGarbage(t *testing.T) {
	_, _, err := ParseToken("not-a-valid-jwt", "secret")
	if err == nil {
		t.Fatal("expected error for garbage input")
	}
}

// TestEnsureSecretExplicitConfig 用户显式配置的 secret 直接返回，不读/写文件。
func TestEnsureSecretExplicitConfig(t *testing.T) {
	dir := t.TempDir()
	SetSecretFilePath(filepath.Join(dir, "jwt_secret"))
	defer SetSecretFilePath("/var/lib/ssm/jwt_secret")

	s, usedRandom, err := EnsureSecret("my-explicit-secret")
	if err != nil {
		t.Fatalf("EnsureSecret: %v", err)
	}
	if s != "my-explicit-secret" {
		t.Fatalf("expected explicit secret, got %s", s)
	}
	if usedRandom {
		t.Fatal("explicit secret should not be flagged as random")
	}
}

// TestEnsureSecretGeneratesAndPersists 默认/空 secret 时生成随机 secret 并持久化。
func TestEnsureSecretGeneratesAndPersists(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt_secret")
	SetSecretFilePath(path)
	defer SetSecretFilePath("/var/lib/ssm/jwt_secret")

	s1, usedRandom1, err := EnsureSecret(DefaultSecret)
	if err != nil {
		t.Fatalf("EnsureSecret: %v", err)
	}
	if !usedRandom1 {
		t.Fatal("expected usedRandom=true for default secret")
	}
	if len(s1) != 64 { // 32 bytes hex
		t.Fatalf("expected 64-char hex secret, got len=%d", len(s1))
	}

	// 第二次调用应复用文件中的 secret，不再生成新的
	s2, usedRandom2, err := EnsureSecret("")
	if err != nil {
		t.Fatalf("EnsureSecret reuse: %v", err)
	}
	if s1 != s2 {
		t.Fatal("secret should be reused from file, not regenerated")
	}
	if !usedRandom2 {
		t.Fatal("reused random secret should still be flagged as random (non-explicit)")
	}
}
