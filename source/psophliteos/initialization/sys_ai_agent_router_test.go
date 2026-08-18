package initialization

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/fstest"

	"sophliteos/config"
)

// MYS-379 后续（用户裁定）：AI-Agent 端点属设备内部自用，不设 SSO 鉴权（跟随变更见
// router/system/sys_ai_agent.go）。此处仅验证端点路由本身可用（port 返回业务响应而非
// NotImplemented/404），SSO 拦截用例随鉴权移除而删除。
func TestAiAgentRouterEndpointsReachable(t *testing.T) {
	config.LoadConfig()
	router := Routers(fstest.MapFS{ // 无真实前端 dist 也可建路由
		"index.html": {Data: []byte("<html></html>")},
	})

	for _, tc := range []struct {
		name   string
		method string
		path   string
	}{
		{"port", http.MethodGet, "/api/device/ai-agent/port"},
		{"proxy", http.MethodGet, "/api/device/ai-agent/proxy/index.html"},
	} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(tc.method, tc.path, nil)
		router.ServeHTTP(w, req)
		if w.Code == http.StatusNotFound {
			t.Fatalf("%s: route must be registered, got 404", tc.name)
		}
		if w.Code == http.StatusUnauthorized {
			t.Fatalf("%s: endpoint must not require SSO, got 401", tc.name)
		}
	}
}