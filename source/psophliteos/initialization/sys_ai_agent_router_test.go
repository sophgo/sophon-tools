package initialization

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/fstest"

	"sophliteos/config"
	"sophliteos/middleware"
)

// MYS-379：/api/device/ai-agent/* 必须与 OTA 一致挂 SSO —— 有活跃会话时，
// 无/错误 token 的请求一律 401 SESSION_OFFLINE；携带活跃 token 才放行到 handler。
func TestAiAgentRouterRequiresSSO(t *testing.T) {
	config.LoadConfig()
	router := Routers(fstest.MapFS{ // 无真实前端 dist 也可建路由
		"index.html": {Data: []byte("<html></html>")},
	})

	// 模拟 ssm 登录注入活跃会话
	middleware.SSORegister("tester", "session-token-abc")
	defer middleware.SSOLogout("session-token-abc")

	cases := []struct {
		name   string
		method string
		path   string
		auth   string // Authorization 头；空表示不带
		want   int
	}{
		{"port no token → 401", http.MethodGet, "/api/device/ai-agent/port", "", http.StatusUnauthorized},
		{"port wrong token → 401", http.MethodGet, "/api/device/ai-agent/port", "Bearer wrong-token", http.StatusUnauthorized},
		{"proxy no token → 401", http.MethodGet, "/api/device/ai-agent/proxy/index.html", "", http.StatusUnauthorized},
		{"proxy wrong token → 401", http.MethodPost, "/api/device/ai-agent/proxy/api/chat", "Bearer wrong-token", http.StatusUnauthorized},
		{"port query token mismatch → 401", http.MethodGet, "/api/device/ai-agent/port?token=wrong", "", http.StatusUnauthorized},
	}
	for _, tc := range cases {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(tc.method, tc.path, nil)
		if tc.auth != "" {
			req.Header.Set("Authorization", tc.auth)
		}
		router.ServeHTTP(w, req)
		if w.Code != tc.want {
			t.Errorf("%s: status = %d, want %d (body=%q)", tc.name, w.Code, tc.want, w.Body.String())
		}
	}

	// 携带活跃 token → 放行到 handler（测试机无 picoclaw 时仍是业务响应而非 401）
	for _, tc := range []struct {
		name   string
		method string
		path   string
	}{
		{"port valid token → pass SSO", http.MethodGet, "/api/device/ai-agent/port"},
		{"proxy valid token → pass SSO", http.MethodGet, "/api/device/ai-agent/proxy/index.html"},
	} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(tc.method, tc.path, nil)
		req.Header.Set("Authorization", "Bearer session-token-abc")
		router.ServeHTTP(w, req)
		if w.Code == http.StatusUnauthorized {
			t.Errorf("%s: valid session token must pass SSO, got 401", tc.name)
		}
	}
}

// 与 OTA 对齐：OTA 路由挂 SSO 后本地无会话时仍放行（sophliteos 重启后 SSO 暂不生效）。
// 不做断言，仅确保本测试不污染其他测试的会话状态。
func TestAiAgentRouterSSONoSessionPassthrough(t *testing.T) {
	config.LoadConfig()
	router := Routers(fstest.MapFS{
		"index.html": {Data: []byte("<html></html>")},
	})

	// 无活跃会话：SSO 放行（与 OTA 同一中间件语义），此处只验证不 401
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/device/ai-agent/port", nil)
	router.ServeHTTP(w, req)
	if w.Code == http.StatusUnauthorized {
		t.Fatalf("no active session must pass SSO (same semantics as OTA), got 401")
	}
}