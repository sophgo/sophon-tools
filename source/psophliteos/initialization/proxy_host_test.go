package initialization

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"sophliteos/config"
	"sophliteos/global"
)

// TestProxyHostPreservesAgentWSOriginHost 回归：/agent/ws 反代必须保留浏览器原始
// Host（bmssm serveWS 的 CSWSH CheckOrigin 用 Origin.Host == r.Host 做同源校验，
// 反代改写 Host 会把一切浏览器同源握手 403）；/api/v1/* 维持改写为上游 Host。
//
// 说明：ReverseProxy 依赖 CloseNotify，需用真实 server（httptest.NewServer）
// 而非 ResponseRecorder 直调路由（httptest.ResponseRecorder 无 CloseNotify，
// gin + ReverseProxy 会 panic）。
func TestProxyHostPreservesAgentWSOriginHost(t *testing.T) {
	config.LoadConfig()

	// DeadlineMiddleware 使用 global.OtaTimeOut；测试环境未走 InitBase（0 值会
	// 让 /agent/ws 的写超时即刻过期导致反代 copy 失败），固定为长窗口。
	origOta := global.OtaTimeOut
	global.OtaTimeOut = 12 * time.Minute
	t.Cleanup(func() { global.OtaTimeOut = origOta })

	// 假上游：原样回显收到的 Host 头。
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprint(w, r.Host)
	}))
	defer upstream.Close()
	upstreamHost := strings.TrimPrefix(upstream.URL, "http://")

	conf := &config.Conf
	conf.Lock()
	conf.GetViper().Set("bmssm.server", upstreamHost)
	conf.Unlock()
	t.Cleanup(func() {
		conf.Lock()
		conf.GetViper().Set("bmssm.server", "127.0.0.1:9779")
		conf.Unlock()
	})

	router := Routers(fstest.MapFS{"index.html": {Data: []byte("<html></html>")}})
	front := httptest.NewServer(router)
	defer front.Close()

	// 浏览器视角：入口 Host 为前端 server 地址（模拟任意外部入口）。
	clientHost := strings.TrimPrefix(front.URL, "http://")
	client := &http.Client{}

	get := func(t *testing.T, path string) string {
		t.Helper()
		resp, err := client.Get(front.URL + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return string(b)
	}

	t.Run("agent/ws 保留原始 Host", func(t *testing.T) {
		// 假上游回显 r.Host：应等于浏览器入口 Host（而非上游 127.0.0.1:port）
		if got := get(t, "/agent/ws"); got != clientHost {
			t.Fatalf("upstream saw Host=%q, want %q (Host 被反代改写了)", got, clientHost)
		}
	})

	t.Run("api/v1 维持改写为上游 Host", func(t *testing.T) {
		if got := get(t, "/api/v1/login"); got != upstreamHost {
			t.Fatalf("upstream saw Host=%q, want %q", got, upstreamHost)
		}
	})
}
