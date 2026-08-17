package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

// newSSOEngine 构造挂载 SSO() 的测试路由：受保护示例 + 三类跳过路径。
func newSSOEngine() *gin.Engine {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	passthrough := func(c *gin.Context) { c.Status(http.StatusOK) }
	router.GET("/api/v1/foo", SSO(), passthrough)
	router.POST("/api/v1/login", SSO(), passthrough)
	router.POST("/api/v1/password", SSO(), passthrough)
	router.GET("/api/sso/active", SSO(), passthrough)
	return router
}

// resetSSO 清空单会话全局状态（测试间隔离）。
func resetSSO() {
	ssoMu.Lock()
	ssoUser = ""
	ssoToken = ""
	ssoMu.Unlock()
}

func TestSSOWithoutActiveSession(t *testing.T) {
	resetSSO()
	defer resetSSO()
	router := newSSOEngine()

	// 无活跃会话时受保护路由必须 401（此前为放行，属鉴权漏洞）
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/foo", nil)
	req.Header.Set("Authorization", "Bearer any-token")
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("no active session: status=%d want 401 body=%s", w.Code, w.Body.String())
	}
}

func TestSSOActiveSessionMatch(t *testing.T) {
	resetSSO()
	defer resetSSO()
	SSORegister("admin", "active-token-1")
	router := newSSOEngine()

	cases := []struct {
		name     string
		auth     string
		wantCode int
	}{
		{"matching token", "Bearer active-token-1", http.StatusOK},
		{"wrong token", "Bearer other-token", http.StatusUnauthorized},
		{"missing token", "", http.StatusUnauthorized},
	}
	for _, tc := range cases {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/api/v1/foo", nil)
		if tc.auth != "" {
			req.Header.Set("Authorization", tc.auth)
		}
		router.ServeHTTP(w, req)
		if w.Code != tc.wantCode {
			t.Errorf("%s: status=%d want %d body=%s", tc.name, w.Code, tc.wantCode, w.Body.String())
		}
	}
}

func TestSSOSkipsPublicPaths(t *testing.T) {
	resetSSO()
	defer resetSSO()
	router := newSSOEngine()

	// 无活跃会话时，登录/改密/本地 sso 端点仍须放行
	for _, tc := range []struct {
		method, path string
	}{
		{http.MethodPost, "/api/v1/login"},
		{http.MethodPost, "/api/v1/password"},
		{http.MethodGet, "/api/sso/active"},
	} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(tc.method, tc.path, nil)
		req.Header.Set("Authorization", "Bearer whatever")
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Errorf("%s %s: status=%d want 200", tc.method, tc.path, w.Code)
		}
	}
}

func TestSSOActiveAndLogout(t *testing.T) {
	resetSSO()
	defer resetSSO()

	if _, ok := SSOActive(); ok {
		t.Fatal("SSOActive should report no session initially")
	}
	SSORegister("admin", "tok")
	if u, ok := SSOActive(); !ok || u != "admin" {
		t.Fatalf("SSOActive after register: u=%q ok=%v", u, ok)
	}
	SSOLogout("wrong-tok")
	if _, ok := SSOActive(); !ok {
		t.Fatal("logout with non-matching token must not clear session")
	}
	SSOLogout("tok")
	if _, ok := SSOActive(); ok {
		t.Fatal("logout with matching token should clear session")
	}
}
