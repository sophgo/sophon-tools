package embed

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// ---- DoH 端点路径 ----

// 每个 DoH 服务器必须使用各自的 JSON API 路径：Cloudflare 是 /dns-query，
// Google 是 /resolve。曾对所有服务器硬编码 /dns-query，导致 dns.google 恒返回 400，
// 整个 DoH 兜底层形同虚设。
func TestDoHResolverUsesPerServerPath(t *testing.T) {
	paths := map[string]int{}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		paths[r.URL.Path]++
		if r.URL.Path == "/resolve" {
			w.Header().Set("Content-Type", "application/dns-json")
			json.NewEncoder(w).Encode(map[string]any{
				"Status": 0,
				"Answer": []map[string]any{{"name": gatewayHost, "type": 1, "data": "104.21.6.72"}},
			})
			return
		}
		// /dns-query 在此 fake 上视为不支持（模拟 Google 的行为）
		http.Error(w, "bad request", http.StatusBadRequest)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext, []dohEndpoint{
		{server: srv.URL, path: "/dns-query"},
		{server: srv.URL, path: "/resolve"},
	})
	r.client = &http.Client{}
	ips, ok := r.resolve(context.Background(), gatewayHost)
	if !ok || len(ips) != 1 || ips[0] != "104.21.6.72" {
		t.Fatalf("resolve = %v ok=%v, want [104.21.6.72] via /resolve", ips, ok)
	}
	if paths["/resolve"] == 0 {
		t.Error("did not query /resolve; per-server path not honoured")
	}
}

// 默认服务器列表必须覆盖两种路径形态，且不含已知恒失败的组合。
func TestDefaultDoHServersUseValidPaths(t *testing.T) {
	want := map[string]string{
		"cloudflare-dns.com": "/dns-query",
		"dns.google":         "/resolve",
	}
	for _, ep := range dohServers {
		if p, ok := want[ep.server]; ok && ep.path != p {
			t.Errorf("DoH %s path = %q, want %q", ep.server, ep.path, p)
		}
		if ep.path == "" {
			t.Errorf("DoH %s has empty path", ep.server)
		}
	}
	for srv := range want {
		found := false
		for _, ep := range dohServers {
			if ep.server == srv {
				found = true
			}
		}
		if !found {
			t.Errorf("default DoH list missing %s", srv)
		}
	}
}

// ---- DoH 应答过滤 ----

// 非 Cloudflare 段的应答必须丢弃：被污染的 DoH 返回伪造 IP，
// 采信它会去连一个完全无关的主机。
func TestDoHResolverRejectsNonCloudflareAnswers(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/dns-json")
		json.NewEncoder(w).Encode(map[string]any{
			"Status": 0,
			"Answer": []map[string]any{
				{"name": gatewayHost, "type": 1, "data": "162.125.32.13"},  // Dropbox 段，伪造
				{"name": gatewayHost, "type": 1, "data": "202.160.130.66"}, // Yahoo 段，伪造
				{"name": gatewayHost, "type": 1, "data": "104.21.6.72"},    // 真 CF
			},
		})
	}))
	defer srv.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext, []dohEndpoint{{server: srv.URL, path: "/dns-query"}})
	r.client = srv.Client()
	ips, ok := r.resolve(context.Background(), gatewayHost)
	if !ok {
		t.Fatal("resolve failed")
	}
	if len(ips) != 1 || ips[0] != "104.21.6.72" {
		t.Errorf("ips = %v, want only the Cloudflare address", ips)
	}
}

// 全部应答都是非 CF 段时，应报错而不是返回伪造地址。
func TestDoHResolverAllForgedAnswersFail(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/dns-json")
		json.NewEncoder(w).Encode(map[string]any{
			"Status": 0,
			"Answer": []map[string]any{{"name": gatewayHost, "type": 1, "data": "173.244.217.42"}},
		})
	}))
	defer srv.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext, []dohEndpoint{{server: srv.URL, path: "/dns-query"}})
	r.client = srv.Client()
	if ips, ok := r.resolve(context.Background(), gatewayHost); ok {
		t.Errorf("resolve = %v ok, want rejection of forged answers", ips)
	}
}

func TestIsCloudflareIP(t *testing.T) {
	cases := map[string]bool{
		"104.21.6.72":    true,
		"172.67.134.151": true,
		"104.16.123.96":  true,
		"162.159.152.4":  true,
		"162.125.32.13":  false, // Dropbox
		"202.160.130.66": false, // Yahoo
		"173.244.217.42": false,
		"211.104.160.39": false,
		"8.8.8.8":        false,
	}
	for ip, want := range cases {
		if got := isCloudflareIP(net.ParseIP(ip)); got != want {
			t.Errorf("isCloudflareIP(%s) = %v, want %v", ip, got, want)
		}
	}
}

// ---- 403 参与转移 ----

// 403 必须触发转移：网关侧欠费/配额耗尽、以及网关特有的上游拒绝都表现为 403，
// 当前主网关对非白名单模型即返回 403。而 403 不像 401/400 那样能断定「换网关也一样」。
func TestPostJSONFailoverOn403(t *testing.T) {
	var primaryHits, fallbackHits atomic.Int64
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		primaryHits.Add(1)
		w.WriteHeader(http.StatusForbidden)
		w.Write([]byte(`{"error":"model not allowed"}`))
	}))
	defer primary.Close()
	fallback := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fallbackHits.Add(1)
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer fallback.Close()

	var out map[string]any
	if err := postJSON(context.Background(), []string{primary.URL, fallback.URL}, "k", map[string]any{}, &out); err != nil {
		t.Fatalf("403 should fail over, got %v", err)
	}
	if fallbackHits.Load() == 0 {
		t.Error("fallback gateway never tried on 403")
	}
}

// 所有网关都 403 → 立刻失败，不做满 6 次无意义重试。
func TestPostJSONAll403FailsFast(t *testing.T) {
	var hits atomic.Int64
	a := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusForbidden)
	}))
	defer a.Close()
	b := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusForbidden)
	}))
	defer b.Close()

	var out map[string]any
	err := postJSON(context.Background(), []string{a.URL, b.URL}, "k", map[string]any{}, &out)
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "403") {
		t.Errorf("error should carry 403, got %q", err)
	}
	if hits.Load() > 2 {
		t.Errorf("all-403 made %d attempts, want ≤2 (both gateways once)", hits.Load())
	}
}

// 401 仍然快速失败不转移（认证错误在任何网关都会复现）。
func TestPostJSONNoFailoverOn401(t *testing.T) {
	var fallbackHits atomic.Int64
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer primary.Close()
	fallback := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fallbackHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer fallback.Close()

	var out map[string]any
	if err := postJSON(context.Background(), []string{primary.URL, fallback.URL}, "k", map[string]any{}, &out); err == nil {
		t.Fatal("expected 401")
	}
	if fallbackHits.Load() != 0 {
		t.Errorf("401 caused %d fallback attempts, want 0", fallbackHits.Load())
	}
}

// ---- 熔断 ----

// 失败网关进入冷却后，后续调用直接跳过，不再重付代价。
func TestBreakerSkipsFailedGateway(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var deadHits atomic.Int64
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		deadHits.Add(1)
		w.WriteHeader(500)
	}))
	defer dead.Close()
	good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":[]}`))
	}))
	defer good.Close()

	// 第一次：打满重试，dead 会被多次命中并熔断。
	var out map[string]any
	if err := postJSON(context.Background(), []string{dead.URL, good.URL}, "k", map[string]any{}, &out); err != nil {
		t.Fatalf("first call should succeed via good gateway: %v", err)
	}
	firstHits := deadHits.Load()
	if firstHits == 0 {
		t.Fatal("dead gateway never tried")
	}

	// 后续调用：dead 处于冷却，应一次都不再拨。
	for i := 0; i < 3; i++ {
		if err := postJSON(context.Background(), []string{dead.URL, good.URL}, "k", map[string]any{}, &out); err != nil {
			t.Fatalf("call %d failed: %v", i, err)
		}
	}
	if got := deadHits.Load(); got != firstHits {
		t.Errorf("dead gateway hit %d more times after cooldown, want 0 (breaker not effective)", got-firstHits)
	}
}

// 全部网关都在冷却时必须半开探测，不能直接报错。
func TestBreakerHalfOpenWhenAllCooling(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var hits atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Write([]byte(`{"data":[]}`))
	}))
	defer srv.Close()

	// 手工把所有网关置入冷却。
	breaker.markFail(srv.URL, time.Now())
	var out map[string]any
	if err := postJSON(context.Background(), []string{srv.URL}, "k", map[string]any{}, &out); err != nil {
		t.Fatalf("half-open probe should succeed, got %v", err)
	}
	if hits.Load() == 0 {
		t.Error("half-open probe never reached the gateway")
	}
}

// ---- 可观测性 ----

// postJSONWithGateway 必须报告实际服务的网关。
func TestPostJSONWithGatewayReportsServingURL(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer bad.Close()
	good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":[]}`))
	}))
	defer good.Close()

	var out map[string]any
	served, err := postJSONWithGateway(context.Background(), []string{bad.URL, good.URL}, "k", map[string]any{}, &out)
	if err != nil {
		t.Fatalf("expected success, got %v", err)
	}
	if served != good.URL {
		t.Errorf("serving gateway = %q, want %q", served, good.URL)
	}
}

// ---- 静态 IP 可疑标记 ----

// TLS 层失败必须让硬编码 IP 变得可疑，从而下次拨号优先走 DoH。
// 这是「TCP 可达 ≠ TLS 可用」的落地：拨号成功不代表这个 IP 还能服务本 Worker。
func TestTLSFailureMarksStaticIPSuspect(t *testing.T) {
	clearStaticIPSuspect()
	defer clearStaticIPSuspect()

	if staticIPSuspect() {
		t.Fatal("should not be suspect initially")
	}
	noteTransportFailure(&net.OpError{Op: "remote error", Err: errTLSTest{}})
	if !staticIPSuspect() {
		t.Error("TLS failure did not mark static IPs suspect")
	}
}

// 非 TLS 错误（普通 dial 超时）不应动摇静态 IP —— 那只是网络不通，DoH 也救不了。
func TestNonTLSErrorKeepsStaticIPTrusted(t *testing.T) {
	clearStaticIPSuspect()
	defer clearStaticIPSuspect()

	noteTransportFailure(&net.OpError{Op: "dial", Err: context.DeadlineExceeded})
	if staticIPSuspect() {
		t.Error("dial timeout should not mark static IPs suspect")
	}
}

// 静态 IP 可疑时，dialWithResolve 必须先问 DoH。
func TestDialPrefersDoHWhenStaticIPSuspect(t *testing.T) {
	clearStaticIPSuspect()
	markStaticIPTLSSuspect()
	defer clearStaticIPSuspect()

	dohIP := "104.16.123.96"
	base, calls := recordingBase(map[string]bool{net.JoinHostPort(dohIP, "443"): true})
	resolver := fakeResolver{ips: []string{dohIP}, ok: true}

	conn, err := dialWithResolve(context.Background(), "tcp", gatewayAddr, base, resolver)
	if err != nil {
		t.Fatalf("dialWithResolve = %v", err)
	}
	conn.Close()
	if len(*calls) == 0 {
		t.Fatal("no dial calls")
	}
	if got := (*calls)[0]; got != "tcp4 "+net.JoinHostPort(dohIP, "443") {
		t.Errorf("first dial = %q, want DoH-resolved IP first", got)
	}
}

type errTLSTest struct{}

func (errTLSTest) Error() string { return "tls: handshake failure" }
