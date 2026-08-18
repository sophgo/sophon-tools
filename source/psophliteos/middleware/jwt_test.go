package middleware

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// issueToken 用指定 secret 签发与 bmssm 相同格式的 HS256 JWT（测试辅助）。
func issueToken(t *testing.T, username, secret string, temp bool) string {
	t.Helper()
	now := time.Now()
	claims := jwt.MapClaims{
		"sub": username,
		"iat": now.Unix(),
		"exp": now.Add(12 * time.Hour).Unix(),
	}
	if temp {
		claims["temp"] = true
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	s, err := tok.SignedString([]byte(secret))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return s
}

// resetJWTSecretFile 覆盖持久化 secret 文件路径，测试结束恢复。
func resetJWTSecretFile(t *testing.T, path string) {
	t.Helper()
	orig := jwtSecretFile
	jwtSecretFile = path
	t.Cleanup(func() { jwtSecretFile = orig })
}

func TestCheckBMSSMTokenDefaultSecret(t *testing.T) {
	// 无配置、无持久化文件 → 回退开发默认 secret（与 bmssm 空配置口径一致）
	resetJWTSecretFile(t, "")

	u, temp, err := CheckBMSSMToken(issueToken(t, "admin", DefaultSecret, false))
	if err != nil || u != "admin" || temp {
		t.Fatalf("valid token rejected: u=%q temp=%v err=%v", u, temp, err)
	}

	if _, _, err := CheckBMSSMToken("garbage-token"); err == nil {
		t.Fatal("garbage token accepted")
	}
	if _, _, err := CheckBMSSMToken(issueToken(t, "admin", "wrong-secret", false)); err == nil {
		t.Fatal("token signed with wrong secret accepted")
	}
	// 临时 token 标志透出
	if _, temp, err := CheckBMSSMToken(issueToken(t, "admin", DefaultSecret, true)); err != nil || !temp {
		t.Fatalf("temp flag not reported: temp=%v err=%v", temp, err)
	}
	// 缺 sub 的 token 拒绝
	claims := jwt.MapClaims{"exp": time.Now().Add(time.Hour).Unix()}
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(DefaultSecret))
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := CheckBMSSMToken(tok); err == nil {
		t.Fatal("token without subject accepted")
	}
	// 已过期 token 拒绝
	expired := jwt.MapClaims{
		"sub": "admin",
		"iat": time.Now().Add(-2 * time.Hour).Unix(),
		"exp": time.Now().Add(-1 * time.Hour).Unix(),
	}
	exTok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, expired).SignedString([]byte(DefaultSecret))
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := CheckBMSSMToken(exTok); err == nil {
		t.Fatal("expired token accepted")
	}
}

func TestCheckBMSSMTokenPersistedSecret(t *testing.T) {
	secret := "persisted-random-secret-0123456789abcdef"
	path := filepath.Join(t.TempDir(), "jwt_secret")
	if err := os.WriteFile(path, []byte(secret), 0o600); err != nil {
		t.Fatal(err)
	}
	resetJWTSecretFile(t, path)

	if u, _, err := CheckBMSSMToken(issueToken(t, "admin", secret, false)); err != nil || u != "admin" {
		t.Fatalf("persisted-secret token rejected: u=%q err=%v", u, err)
	}
	// 持久化 secret 生效时，开发默认签发的 token 必须被拒
	if _, _, err := CheckBMSSMToken(issueToken(t, "admin", DefaultSecret, false)); err == nil {
		t.Fatal("default-secret token accepted while persisted secret active")
	}
}

func TestRequireBMSSMTokenMiddleware(t *testing.T) {
	resetJWTSecretFile(t, "")
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/protected", RequireBMSSMToken(), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"user": c.GetString("user")})
	})

	// 无 token → 401
	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/protected", nil))
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("no token: status=%d want 401", w.Code)
	}

	// 伪造 token → 401
	w = httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/protected", nil)
	req.Header.Set("Authorization", "Bearer not-a-jwt")
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("forged token: status=%d want 401", w.Code)
	}

	// 临时 token → 403（与 bmssm 口径一致：改密前无可用的受保护能力）
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/protected", nil)
	req.Header.Set("Authorization", "Bearer "+issueToken(t, "admin", DefaultSecret, true))
	router.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("temp token: status=%d want 403", w.Code)
	}

	// 有效 token（Authorization 头）→ 200 + user
	w = httptest.NewRecorder()
	tok := issueToken(t, "admin", DefaultSecret, false)
	req = httptest.NewRequest(http.MethodGet, "/protected", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("valid token: status=%d want 200 body=%s", w.Code, w.Body.String())
	}

	// query 形式不再放行（MYS-383：与 requestToken 同为 Bearer-only，防令牌进 URL）→ 401
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/protected?token="+tok, nil)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("query token: status=%d want 401 body=%s", w.Code, w.Body.String())
	}
}
