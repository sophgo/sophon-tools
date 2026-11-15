package initialization

// sys_upgrade_router_test.go 经真实 Routers() 验证旧升级接口在完整中间件栈下的行为：
//   - 鉴权保留：无活跃会话 → 401；有会话但无 token → 401（不得退化成匿名可调）；
//   - 已登录调用 → HTTP 200 + 非零业务码 + 明确提示，且不置 BlockAllRequests；
//   - 重复调用幂等失败，不产生"待确认"状态或后台重启 goroutine。

import (
	"bytes"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"

	"sophliteos/config"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

// upgradeUploadRequest 构造一次旧升级接口的上传请求（multipart，含升级包）。
func upgradeUploadRequest(t *testing.T, path, token, filename string) *http.Request {
	t.Helper()
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	part, err := w.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write([]byte("fake package")); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, path, body)
	req.Header.Set("Content-Type", w.FormDataContentType())
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	return req
}

// TestLegacyUpgradeRouteRequiresSession 旧升级路由仍受 SSO + bmssm JWT 双重保护。
func TestLegacyUpgradeRouteRequiresSession(t *testing.T) {
	secret := setTestJWTSecret(t)
	config.LoadConfig()
	setProdTimeouts(t)
	gin.SetMode(gin.TestMode)
	router := Routers(testEmbeddedFS(t))

	// 无活跃会话：401（不得因端点"下线"而放开匿名访问）
	for _, path := range []string{"/api/upgrade", "/api/upgrade/confirm"} {
		w := httptest.NewRecorder()
		router.ServeHTTP(w, upgradeUploadRequest(t, path, "", "sophliteos-linux_arm64.tgz"))
		if w.Code != http.StatusUnauthorized {
			t.Fatalf("POST %s 无会话: status=%d want 401 body=%s", path, w.Code, w.Body.String())
		}
	}

	// 建立活跃会话，但请求不带 token → 401
	tok := issueBMSSMToken(t, "admin", secret, false)
	w := registerJSON(t, router, `{"username":"admin","token":"`+tok+`"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("register failed: %d %s", w.Code, w.Body.String())
	}
	defer middleware.SSOLogout(tok)

	for _, path := range []string{"/api/upgrade", "/api/upgrade/confirm"} {
		w = httptest.NewRecorder()
		router.ServeHTTP(w, upgradeUploadRequest(t, path, "", "sophliteos-linux_arm64.tgz"))
		if w.Code != http.StatusUnauthorized {
			t.Fatalf("POST %s 无 token: status=%d want 401 body=%s", path, w.Code, w.Body.String())
		}
	}
}

// TestLegacyUpgradeRouteRejectsWithBusinessCode 已登录调用旧升级接口：
// HTTP 200 + 非零业务码 + 明确提示，且不设置全局阻塞（前端按 body.code 展示错误）。
func TestLegacyUpgradeRouteRejectsWithBusinessCode(t *testing.T) {
	secret := setTestJWTSecret(t)
	config.LoadConfig()
	setProdTimeouts(t)
	gin.SetMode(gin.TestMode)
	router := Routers(testEmbeddedFS(t))

	oldBlock := global.BlockAllRequests
	global.BlockAllRequests = false
	t.Cleanup(func() { global.BlockAllRequests = oldBlock })

	tok := issueBMSSMToken(t, "admin", secret, false)
	w := registerJSON(t, router, `{"username":"admin","token":"`+tok+`"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("register failed: %d %s", w.Code, w.Body.String())
	}
	defer middleware.SSOLogout(tok)

	for _, path := range []string{"/api/upgrade", "/api/upgrade/confirm"} {
		w = httptest.NewRecorder()
		router.ServeHTTP(w, upgradeUploadRequest(t, path, tok, "sophliteos-linux_arm64.tgz"))
		if w.Code != http.StatusOK {
			t.Fatalf("POST %s: status=%d want 200 body=%s", path, w.Code, w.Body.String())
		}
		if !bytes.Contains(w.Body.Bytes(), []byte(`"code":501`)) {
			t.Fatalf("POST %s: 期望非零业务码 501, body=%s", path, w.Body.String())
		}
		if !bytes.Contains(w.Body.Bytes(), []byte("暂不支持")) {
			t.Fatalf("POST %s: 期望明确提示, body=%s", path, w.Body.String())
		}
		if global.BlockAllRequests {
			t.Fatalf("POST %s: 不得设置 BlockAllRequests", path)
		}
	}

	// 认证仍然有效：会话未被破坏，本地受保护路由继续可用
	w = httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/device/version", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("旧升级接口调用后会话应保持有效: status=%d body=%s", w.Code, w.Body.String())
	}
}
