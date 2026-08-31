package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// --- 测试辅助 ----------------------------------------------------------------

// ssoTestRouter 构造带 SSO 中间件的最小 gin 路由：/api/v1/* 走 SSO() + 探针 handler，
// 并注册 /api/sso/events（与生产 router.go 一致，SSOEvents 不走 SSO 中间件）。
func ssoTestRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	var hit int32
	r.Any("/api/v1/*any", SSO(), func(c *gin.Context) {
		atomic.StoreInt32(&hit, 1)
		// 转发前 query 已被中间件改写（若适用）：回显最终 RawQuery 供断言
		c.JSON(http.StatusOK, gin.H{"hit": true, "query": c.Request.URL.RawQuery})
	})
	r.GET("/api/sso/events", SSOEvents)
	return r
}

func ssoProbe(r *gin.Engine, method, path, auth, query string) *httptest.ResponseRecorder {
	url := path
	if query != "" {
		url += "?" + query
	}
	req := httptest.NewRequest(method, url, nil)
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// resetSSOState 清理包级状态，保证用例互不干扰。
func resetSSOState() {

	ssoMu.Lock()
	ssoUser = ""
	ssoToken = ""
	ssoMu.Unlock()
	ssoTicketMu.Lock()
	ssoTickets = map[string]*ssoTicket{}
	ssoTicketMu.Unlock()
	ssoClientMu.Lock()
	ssoClients = map[string]map[*ssoClient]struct{}{}
	ssoClientMu.Unlock()
	sseConnTimesMu.Lock()
	sseConnTimes = map[string][]time.Time{}
	sseConnTimesMu.Unlock()
}

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

// --- requestToken：只认 Authorization 头 --------------------------------------

func TestRequestTokenIgnoresQuery(t *testing.T) {
	// query 里的 token 不再被接受（MYS-383：防止令牌进 URL/访问日志）
	r := ssoTestRouter()
	resetSSOState()
	SSORegister("alice", "token-a")

	// 仅 query token → 401（历史上会放行）
	w := ssoProbe(r, "GET", "/api/v1/files", "", "token=token-a")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("query-only token: want 401, got %d", w.Code)
	}
	// 仅 Bearer → 放行
	w = ssoProbe(r, "GET", "/api/v1/files", "Bearer token-a", "")
	if w.Code != http.StatusOK {
		t.Fatalf("bearer token: want 200, got %d", w.Code)
	}
}

// --- 一次性票据白名单路径 ------------------------------------------------------

func TestTicketFlowOnWhitelistedPath(t *testing.T) {
	r := ssoTestRouter()
	resetSSOState()
	SSORegister("alice", "token-a")

	// 合法票据：下载路径放行，且 query 被改写为 ?token=<活跃JWT>（bmssm 依赖）
	ticket := SSOIssueTicket("token-a")
	if ticket == "" {
		t.Fatal("SSOIssueTicket returned empty")
	}
	w := ssoProbe(r, "GET", "/api/v1/files/download", "", "path=/etc/a.conf&ticket="+ticket)
	if w.Code != http.StatusOK {
		t.Fatalf("valid ticket: want 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "token=token-a") || strings.Contains(w.Body.String(), "ticket=") {
		t.Fatalf("query rewrite failed, got body: %s", w.Body.String())
	}

	// 一次性：同一票据第二次使用 → 401（防重放）
	w = ssoProbe(r, "GET", "/api/v1/files/download", "", "path=/etc/a.conf&ticket="+ticket)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("replayed ticket: want 401, got %d", w.Code)
	}
}

// 系统日志下载同样支持 <a download> 一次性票据（queryTicketPaths 新增白名单路径）。
func TestTicketOnLogsDownloadPath(t *testing.T) {
	r := ssoTestRouter()
	resetSSOState()
	SSORegister("alice", "token-a")

	ticket := SSOIssueTicket("token-a")
	if ticket == "" {
		t.Fatal("SSOIssueTicket returned empty")
	}
	w := ssoProbe(r, "GET", "/api/v1/logs/download", "", "ticket="+ticket)
	if w.Code != http.StatusOK {
		t.Fatalf("ticket on logs/download: want 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "token=token-a") || strings.Contains(w.Body.String(), "ticket=") {
		t.Fatalf("query rewrite failed, got body: %s", w.Body.String())
	}

	// 同一票据重放 → 401
	w = ssoProbe(r, "GET", "/api/v1/logs/download", "", "ticket="+ticket)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("replayed logs ticket: want 401, got %d", w.Code)
	}
}

func TestTicketBoundToActiveSession(t *testing.T) {
	r := ssoTestRouter()
	SSORegister("alice", "token-a")
	ticket := SSOIssueTicket("token-a")

	// 会话切换（新用户登录）后，旧 token 的票据作废
	SSORegister("bob", "token-b")
	w := ssoProbe(r, "GET", "/api/v1/files/download", "", "path=/etc/a.conf&ticket="+ticket)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("ticket after session switch: want 401, got %d", w.Code)
	}
}

func TestExpiredTicketRejected(t *testing.T) {
	r := ssoTestRouter()
	SSORegister("alice", "token-a")
	ticket := SSOIssueTicket("token-a")

	// 篡改过期时间模拟 60s TTL 到期
	ssoTicketMu.Lock()
	ssoTickets[ticket].expiresAt = time.Now().Add(-time.Second)
	ssoTicketMu.Unlock()
	w := ssoProbe(r, "GET", "/api/v1/files/download", "", "path=/etc/a.conf&ticket="+ticket)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expired ticket: want 401, got %d", w.Code)
	}
}

func TestTicketNotAcceptedOutsideWhitelist(t *testing.T) {
	r := ssoTestRouter()
	SSORegister("alice", "token-a")
	ticket := SSOIssueTicket("token-a")

	// 非白名单路径（如普通文件列表）即使携带合法票据也 401
	w := ssoProbe(r, "GET", "/api/v1/files", "", "path=/etc&ticket="+ticket)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("ticket on non-whitelisted path: want 401, got %d", w.Code)
	}
}

// --- SSE 长连接防护 -----------------------------------------------------------

func TestSSOEventsRequiresActiveToken(t *testing.T) {
	resetSSOState()
	// 无活跃会话：401
	w := ssoProbe(ssoTestRouter(), "GET", "/api/sso/events", "", "")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("no active session: want 401, got %d", w.Code)
	}

	SSORegister("alice", "token-a")
	// token 缺失 → 401
	w = ssoProbe(ssoTestRouter(), "GET", "/api/sso/events", "", "")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("missing token: want 401, got %d", w.Code)
	}
	// token 不匹配（旧 token / 任意非活跃 token）→ 401
	w = ssoProbe(ssoTestRouter(), "GET", "/api/sso/events", "Bearer token-stale", "")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("stale token: want 401, got %d", w.Code)
	}
	// query token 不再被接受 → 401
	w = ssoProbe(ssoTestRouter(), "GET", "/api/sso/events", "", "token=token-a")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("query token: want 401, got %d", w.Code)
	}
}

func TestSSOEventsConnectionCaps(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/sso/events", SSOEvents)

	// 直接注入连接占位至单 token 上限，验证新连接被 429 拒
	ssoClientMu.Lock()
	ssoClients["token-a"] = map[*ssoClient]struct{}{}
	for i := 0; i < sseMaxClientsPerToken; i++ {
		ssoClients["token-a"][&ssoClient{ch: make(chan string, 4)}] = struct{}{}
	}
	ssoClientMu.Unlock()

	req := httptest.NewRequest("GET", "/api/sso/events", nil)
	req.Header.Set("Authorization", "Bearer token-a")
	req.RemoteAddr = "10.0.0.1:1234"
	rec := httptest.NewRecorder()
	sseConnTimesMu.Lock()
	sseConnTimes["10.0.0.1"] = nil
	sseConnTimesMu.Unlock()
	r.ServeHTTP(rec, req)
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("over per-token cap: want 429, got %d", rec.Code)
	}
	// 清理占位（避免影响其他用例）
	ssoClientMu.Lock()
	delete(ssoClients, "token-a")
	ssoClientMu.Unlock()
}

func TestSSEAllowConnectRateLimit(t *testing.T) {
	resetSSOState()
	for i := 0; i < sseMaxConnsPerIPPerMin; i++ {
		if !sseAllowConnect("10.0.0.2") {
			t.Fatalf("connect #%d should be allowed", i+1)
		}
	}
	if sseAllowConnect("10.0.0.2") {
		t.Fatal("connect beyond per-IP per-minute cap should be rejected")
	}
	// 其他 IP 不受影响
	if !sseAllowConnect("10.0.0.3") {
		t.Fatal("different IP should be allowed")
	}
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

// --- 一次性票据单测见上；以下为 MYS-382 审计辅助函数测试 ---

func TestSSOUserByToken(t *testing.T) {
	// 无活跃会话时不可解析
	if name, ok := SSOUserByToken("tok-1"); ok {
		t.Fatalf("no active session: got (%q, true)", name)
	}

	SSORegister("alice", "tok-1")

	// 活跃 token 精确匹配
	if name, ok := SSOUserByToken("tok-1"); !ok || name != "alice" {
		t.Fatalf("active token: got (%q, %v), want (alice, true)", name, ok)
	}
	// 未知 token 不可解析
	if name, ok := SSOUserByToken("tok-2"); ok {
		t.Fatalf("unknown token must not resolve, got %q", name)
	}
	// 空 token 不可解析
	if name, ok := SSOUserByToken(""); ok {
		t.Fatalf("empty token must not resolve, got %q", name)
	}

	// 新登录顶掉旧会话：旧 token 立即失效（审计不得记到旧用户头上）
	SSORegister("bob", "tok-2")
	if name, ok := SSOUserByToken("tok-1"); ok {
		t.Fatalf("stale token must not resolve after re-login, got %q", name)
	}
	if name, ok := SSOUserByToken("tok-2"); !ok || name != "bob" {
		t.Fatalf("new active token: got (%q, %v), want (bob, true)", name, ok)
	}

	// 登出后不可解析
	SSOLogout("tok-2")
	if name, ok := SSOUserByToken("tok-2"); ok {
		t.Fatalf("token after logout must not resolve, got %q", name)
	}
}
