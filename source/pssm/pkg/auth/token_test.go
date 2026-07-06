package auth

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestIssueAndParseToken(t *testing.T) {
	secret := "test-secret"
	username := "testuser"

	tokenStr, expiresAt, err := IssueToken(username, secret)
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
	parsedUser, err := ParseToken(tokenStr, secret)
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	if parsedUser != username {
		t.Fatalf("expected username %q, got %q", username, parsedUser)
	}
}

func TestParseTokenInvalidSecret(t *testing.T) {
	tokenStr, _, err := IssueToken("user", "secret1")
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}
	_, err = ParseToken(tokenStr, "wrong-secret")
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

	_, err = ParseToken(tokenStr, secret)
	if err == nil {
		t.Fatal("expected error for expired token")
	}
}

func TestParseTokenGarbage(t *testing.T) {
	_, err := ParseToken("not-a-valid-jwt", "secret")
	if err == nil {
		t.Fatal("expected error for garbage input")
	}
}
