package initialization

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"sophliteos/config"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// issueBMSSMToken 签发与 bmssm 同格式的 JWT（测试辅助；测试环境无配置文件时
// secret 解析回退到开发默认值，与 bmssm 空配置口径一致）。
func issueBMSSMToken(t *testing.T, username, secret string, temp bool) string {
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

func registerJSON(t *testing.T, router http.Handler, body string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/sso/register", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)
	return w
}

// setProdTimeouts 与生产 InitBase 一致设置超时中间件参数（为 0 会让
// TimeoutMiddleware 立即超时，测试不稳定）；结束后恢复原值，避免影响本包
// 其他测试对超时行为的既有假设。
func setProdTimeouts(t *testing.T) {
	t.Helper()
	origTO, origOta := global.TimeOut, global.OtaTimeOut
	global.TimeOut, _ = time.ParseDuration("30s")
	global.OtaTimeOut, _ = time.ParseDuration("30s")
	t.Cleanup(func() {
		global.TimeOut, global.OtaTimeOut = origTO, origOta
	})
}

// TestSSORegisterRequiresValidJWT 验证 register 鉴权闭环：
// 未携带有效 bmssm JWT 的请求不能自造活跃会话。
func TestSSORegisterRequiresValidJWT(t *testing.T) {
	middleware.SetJWTSecretFilePath("")
	config.LoadConfig()
	setProdTimeouts(t)
	gin.SetMode(gin.TestMode)
	router := Routers(testEmbeddedFS(t))

	// 1) 伪造 token → 401，不建立会话
	w := registerJSON(t, router, `{"username":"admin","token":"evil"}`)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("register with forged token: status=%d want 401 body=%s", w.Code, w.Body.String())
	}
	if _, ok := middleware.SSOActive(); ok {
		t.Fatal("forged register must not create active session")
	}

	// 2) 有效 JWT 但 username 不匹配 sub → 401，不建立会话
	otherTok := issueBMSSMToken(t, "other", middleware.DefaultSecret, false)
	w = registerJSON(t, router, `{"username":"admin","token":"`+otherTok+`"}`)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("register with mismatched username: status=%d want 401 body=%s", w.Code, w.Body.String())
	}
	if _, ok := middleware.SSOActive(); ok {
		t.Fatal("mismatched register must not create active session")
	}

	// 3) 有效 JWT + username 匹配 sub → 200，活跃会话建立
	validTok := issueBMSSMToken(t, "admin", middleware.DefaultSecret, false)
	w = registerJSON(t, router, `{"username":"admin","token":"`+validTok+`"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("register with valid jwt: status=%d want 200 body=%s", w.Code, w.Body.String())
	}
	if u, ok := middleware.SSOActive(); !ok || u != "admin" {
		t.Fatalf("SSOActive after valid register: u=%q ok=%v", u, ok)
	}
	t.Cleanup(func() { middleware.SSOLogout(validTok) })

	// 4) 畸形 body → 400
	w = registerJSON(t, router, `{"username":"admin"}`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("register with incomplete body: status=%d want 400", w.Code)
	}
}

// TestProtectedLocalRoutesUnifiedAuth 验证本地敏感路由统一鉴权口径：
// 无活跃会话（或 token 无效）一律 401，登录注册后放行。
func TestProtectedLocalRoutesUnifiedAuth(t *testing.T) {
	middleware.SetJWTSecretFilePath("")
	config.LoadConfig()
	setProdTimeouts(t)
	gin.SetMode(gin.TestMode)
	router := Routers(testEmbeddedFS(t))

	// 无会话、无 token → 一律 401
	for _, p := range []string{
		"/api/device/version",
		"/api/device/metrics-selection",
		"/api/device/ota/list",
	} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, p, nil)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusUnauthorized {
			t.Errorf("GET %s without session: status=%d want 401 body=%s", p, w.Code, w.Body.String())
		}
	}
	// upgrade 为 POST-only 路由：无会话 → 401（不触发真实升级）
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/upgrade", nil)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Errorf("POST /api/upgrade without session: status=%d want 401 body=%s", w.Code, w.Body.String())
	}

	// 已注册活跃会话 + 携带该 token → 放行
	tok := issueBMSSMToken(t, "admin", middleware.DefaultSecret, false)
	w = registerJSON(t, router, `{"username":"admin","token":"`+tok+`"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("register failed: %d %s", w.Code, w.Body.String())
	}
	defer middleware.SSOLogout(tok)

	for _, p := range []string{"/api/device/version", "/api/device/metrics-selection"} {
		w = httptest.NewRecorder()
		req = httptest.NewRequest(http.MethodGet, p, nil)
		req.Header.Set("Authorization", "Bearer "+tok)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Errorf("GET %s with active session: status=%d want 200 body=%s", p, w.Code, w.Body.String())
		}
	}

	// 有效 JWT 但非活跃 token → 401（SSO 单会话比对）
	// 注：JWT 的 iat 为秒级精度，同秒签发的同 sub token 字节相同（SSO 按字符串比对
	// 视为同一会话），换一个 sub 保证是不同的 token。
	otherTok := issueBMSSMToken(t, "admin2", middleware.DefaultSecret, false)
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/api/device/version", nil)
	req.Header.Set("Authorization", "Bearer "+otherTok)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("unregistered valid JWT: status=%d want 401 body=%s", w.Code, w.Body.String())
	}

	// 活跃 token 是临时 token（首次登录改密场景）→ 本地敏感路由 403，与 bmssm 口径一致
	tempTok := issueBMSSMToken(t, "admin", middleware.DefaultSecret, true)
	w = registerJSON(t, router, `{"username":"admin","token":"`+tempTok+`"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("register temp token failed: %d %s", w.Code, w.Body.String())
	}
	defer middleware.SSOLogout(tempTok)
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/api/device/version", nil)
	req.Header.Set("Authorization", "Bearer "+tempTok)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("temp token on protected local route: status=%d want 403 body=%s", w.Code, w.Body.String())
	}
}
