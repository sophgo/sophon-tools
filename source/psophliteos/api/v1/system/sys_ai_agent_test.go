package system

import (
	"bytes"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// --- 测试工具 ---------------------------------------------------------------

// fakePicoclaw 起一个假 picoclaw web（GET / 200），返回其端口。
func fakePicoclaw(t *testing.T) int {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		fmt.Fprintf(w, "<html>fake picoclaw %s</html>", r.URL.Path)
	}))
	t.Cleanup(srv.Close)
	return srv.Listener.Addr().(*net.TCPAddr).Port
}

// fakeProbe 返回注入用的 picoclawWebUp 实现（带探测次数计数）。
func fakeProbe(upPorts map[int]bool) (probe func(int) bool, count *int32) {
	var n int32
	return func(port int) bool {
		atomic.AddInt32(&n, 1)
		return upPorts[port]
	}, &n
}

// newTestEngine 组装最小路由（与生产路由同构：port + proxy/*any）。
func newTestEngine(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	api := &AiAgentApi{}
	g := r.Group("api/device/ai-agent")
	g.GET("port", api.Port)
	g.Any("proxy/*any", api.Proxy)
	return r
}

// doReq 通过真实 HTTP server 发起请求（gin 的 responseWriter.CloseNotify 需要
// 真实连接对象，httptest.NewRecorder 不实现 http.CloseNotifier，会 panic）。
func doReq(r *gin.Engine, method, rawPath string) *httptest.ResponseRecorder {
	srv := httptest.NewServer(r)
	defer srv.Close()
	req, err := http.NewRequest(method, srv.URL+rawPath, nil)
	if err != nil {
		panic(err)
	}
	cli := &http.Client{Timeout: 5 * time.Second,
		// 不跟随重定向：与探测探针口径一致，直接拿到 302 本身
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := cli.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return &httptest.ResponseRecorder{Code: resp.StatusCode, Body: bytesBufferOf(body)}
}

// bytesBufferOf 包装 []byte 为 *bytes.Buffer，供 ResponseRecorder.Body 断言用。
func bytesBufferOf(b []byte) *bytes.Buffer {
	return bytes.NewBuffer(b)
}

// --- 探测缓存 ---------------------------------------------------------------

func TestDetectPicoclawPortUsesCache(t *testing.T) {
	port := fakePicoclaw(t)
	oldCands, oldUp, oldInst := picoclawCandidates, picoclawWebUp, picoclawInstalled
	picoclawCandidates = []int{port}
	probeUp, count := fakeProbe(map[int]bool{port: true})
	picoclawWebUp = probeUp
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawWebUp, picoclawInstalled = oldCands, oldUp, oldInst
		resetPicoclawProbeCache()
	})

	p1, up1 := detectPicoclawPort()
	p2, up2 := detectPicoclawPort()
	p3, up3 := detectPicoclawPort()
	if !up1 || !up2 || !up3 {
		t.Fatalf("all should be up: %v %v %v", up1, up2, up3)
	}
	if p1 != port || p2 != port || p3 != port {
		t.Fatalf("port mismatch: %d/%d/%d want %d", p1, p2, p3, port)
	}
	if got := atomic.LoadInt32(count); got != 1 {
		t.Fatalf("probe called %d times, want 1 (cache must absorb repeats)", got)
	}
}

func TestDetectPicoclawPortNegativeCache(t *testing.T) {
	oldCands, oldUp, oldInst := picoclawCandidates, picoclawWebUp, picoclawInstalled
	picoclawCandidates = []int{18800}
	probeUp, count := fakeProbe(map[int]bool{})
	picoclawWebUp = probeUp
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawWebUp, picoclawInstalled = oldCands, oldUp, oldInst
		resetPicoclawProbeCache()
	})

	p1, up1 := detectPicoclawPort()
	p2, up2 := detectPicoclawPort()
	if up1 || up2 {
		t.Fatalf("should be down: %v %v", up1, up2)
	}
	if p1 != defaultPicoclawPort || p2 != defaultPicoclawPort {
		t.Fatalf("down probe should fall back to default port: %d/%d", p1, p2)
	}
	if got := atomic.LoadInt32(count); got != 1 {
		t.Fatalf("negative probe called %d times, want 1 (negative cache)", got)
	}
}

func TestDetectPicoclawPortRequiresInstallAnchor(t *testing.T) {
	oldCands, oldUp, oldInst := picoclawCandidates, picoclawWebUp, picoclawInstalled
	picoclawCandidates = []int{18800}
	probeUp, count := fakeProbe(map[int]bool{18800: true})
	picoclawWebUp = probeUp
	picoclawInstalled = func() bool { return false } // 未安装 → 不探测、不代理
	t.Cleanup(func() {
		picoclawCandidates, picoclawWebUp, picoclawInstalled = oldCands, oldUp, oldInst
		resetPicoclawProbeCache()
	})

	p, up := detectPicoclawPort()
	if up {
		t.Fatalf("uninstalled device must not report up")
	}
	if p != defaultPicoclawPort {
		t.Fatalf("uninstalled port fallback mismatch: %d", p)
	}
	if got := atomic.LoadInt32(count); got != 0 {
		t.Fatalf("probe must not run when picoclaw not installed, called %d times", got)
	}
}

func TestDetectPicoclawPortRefreshesAfterTTL(t *testing.T) {
	port := fakePicoclaw(t)
	oldCands, oldUp, oldInst, oldOK := picoclawCandidates, picoclawWebUp, picoclawInstalled, probeOKTTL
	picoclawCandidates = []int{port}
	probeUp, count := fakeProbe(map[int]bool{port: true})
	picoclawWebUp = probeUp
	picoclawInstalled = func() bool { return true }
	probeOKTTL = 50 * time.Millisecond // 缩短 TTL 验证过期重探
	t.Cleanup(func() {
		picoclawCandidates, picoclawWebUp, picoclawInstalled, probeOKTTL = oldCands, oldUp, oldInst, oldOK
		resetPicoclawProbeCache()
	})

	detectPicoclawPort()
	detectPicoclawPort()
	time.Sleep(120 * time.Millisecond)
	detectPicoclawPort()
	if got := atomic.LoadInt32(count); got != 2 {
		t.Fatalf("probe called %d times, want 2 (expired cache must re-probe)", got)
	}
}

// --- 路径/方法白名单 ----------------------------------------------------------

func TestPicoclawProxyPathAllowed(t *testing.T) {
	cases := []struct {
		path string
		want bool
	}{
		{"/", true},
		{"/index.html", true},
		{"/favicon.ico", true},
		{"/robots.txt", true},
		{"/assets/app.js", true},
		{"/static/css/style.css", true},
		{"/static/img/logo.png", true},
		{"/api/sessions", true},
		{"/api/chat", true},
		{"/ws", true},
		{"/ws/chat", true},
		{"/index.html?token=abc", true},

		{"/etc/passwd", false},
		{"/etc/shadow", false},
		{"/api/../etc/passwd", false},
		{"./etc/passwd", false},
		{"/api/..%2f..%2fetc", false}, // 含 ..（未解码判定）→ 拒绝
		{"/proc/self/environ", false},
		{"/cmd", false},
		{"/admin/exec", false},
		{"/data/ota", false},
		{"", false},
		{`/api/\etc`, false}, // 反斜杠 → 拒绝
	}
	for _, tc := range cases {
		if got := picoclawProxyPathAllowed(tc.path); got != tc.want {
			t.Errorf("path %q = %v, want %v", tc.path, got, tc.want)
		}
	}
}

func TestPicoclawProxyMethodAllowed(t *testing.T) {
	ok := []string{http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut,
		http.MethodDelete, http.MethodPatch, http.MethodOptions}
	for _, m := range ok {
		if !picoclawProxyMethodAllowed(m) {
			t.Errorf("method %s should be allowed", m)
		}
	}
	bad := []string{http.MethodConnect, http.MethodTrace, "TRACK", "BREW"}
	for _, m := range bad {
		if picoclawProxyMethodAllowed(m) {
			t.Errorf("method %s should be rejected", m)
		}
	}
}

// --- Proxy handler ----------------------------------------------------------

func TestProxyRejectsForbiddenPath(t *testing.T) {
	port := fakePicoclaw(t)
	oldCands, oldInst := picoclawCandidates, picoclawInstalled
	picoclawCandidates = []int{port}
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawInstalled = oldCands, oldInst
		resetPicoclawProbeCache()
	})

	r := newTestEngine(t)
	w := doReq(r, http.MethodGet, "/api/device/ai-agent/proxy/etc/passwd")
	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
	if strings.Contains(w.Body.String(), "127.0.0.1") || strings.Contains(w.Body.String(), fmt.Sprintf("%d", port)) {
		t.Fatalf("response must not leak target, body=%q", w.Body.String())
	}
}

func TestProxyRejectsUnallowedMethod(t *testing.T) {
	port := fakePicoclaw(t)
	oldCands, oldInst := picoclawCandidates, picoclawInstalled
	picoclawCandidates = []int{port}
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawInstalled = oldCands, oldInst
		resetPicoclawProbeCache()
	})

	r := newTestEngine(t)
	w := doReq(r, http.MethodConnect, "/api/device/ai-agent/proxy/")
	if w.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", w.Code)
	}
}

func TestProxyProxiesAllowedPath(t *testing.T) {
	port := fakePicoclaw(t)
	oldCands, oldInst := picoclawCandidates, picoclawInstalled
	picoclawCandidates = []int{port}
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawInstalled = oldCands, oldInst
		resetPicoclawProbeCache()
	})

	r := newTestEngine(t)
	w := doReq(r, http.MethodGet, "/api/device/ai-agent/proxy/index.html")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%q)", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "fake picoclaw") {
		t.Fatalf("body should come from upstream, got %q", w.Body.String())
	}
}

func TestProxyGenericErrorWhenNotUp(t *testing.T) {
	oldCands, oldInst := picoclawCandidates, picoclawInstalled
	picoclawCandidates = []int{18800}
	picoclawInstalled = func() bool { return false } // 无安装锚定 → 未就绪
	t.Cleanup(func() {
		picoclawCandidates, picoclawInstalled = oldCands, oldInst
		resetPicoclawProbeCache()
	})

	r := newTestEngine(t)
	w := doReq(r, http.MethodGet, "/api/device/ai-agent/proxy/index.html")
	if w.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", w.Code)
	}
	// 不回显探测失败细节（端口、网络错误、扫描线索）
	body := w.Body.String()
	for _, leak := range []string{"18800", "18790", "8081", "探测", "proxy target error", "connection", "bad gateway"} {
		if strings.Contains(strings.ToLower(body), leak) {
			t.Fatalf("response leaks probe detail %q: %q", leak, body)
		}
	}
}

// --- Port 端点 ---------------------------------------------------------------

func TestPortEndpointShape(t *testing.T) {
	oldCands, oldUp, oldInst := picoclawCandidates, picoclawWebUp, picoclawInstalled
	picoclawCandidates = []int{18800}
	probeUp, _ := fakeProbe(map[int]bool{18800: true})
	picoclawWebUp = probeUp
	picoclawInstalled = func() bool { return true }
	t.Cleanup(func() {
		picoclawCandidates, picoclawWebUp, picoclawInstalled = oldCands, oldUp, oldInst
		resetPicoclawProbeCache()
	})

	r := newTestEngine(t)
	w := doReq(r, http.MethodGet, "/api/device/ai-agent/port")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	body := w.Body.String()
	if !strings.Contains(body, `"port":18800`) || !strings.Contains(body, `"up":true`) {
		t.Fatalf("port response shape mismatch: %q", body)
	}
}