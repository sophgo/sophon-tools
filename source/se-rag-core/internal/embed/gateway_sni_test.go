package embed

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// rstServer 模拟「TCP 能连、ClientHello 之后被 RST」——被测主机上 CF 443 的形态。
func rstServer(t *testing.T) (string, *atomic.Int64) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	var hits atomic.Int64
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			hits.Add(1)
			if tc, ok := c.(*net.TCPConn); ok {
				tc.SetLinger(0)
			}
			c.Close()
		}
	}()
	return "http://" + ln.Addr().String(), &hits
}

// 被测主机的真实形态：主网关被代理拒绝 + 备网关 443 被 RST。
// 修复前实测 65s 才降级；修复后必须在一个预算内快速认输，且不再对注定失败的备网关反复空试。
func TestSNIBlockedFailsFast(t *testing.T) {
	breaker.reset()
	defer breaker.reset()
	allowAltPortsForLocal(t)

	blocked, hits := rstServer(t)
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer primary.Close()

	t0 := time.Now()
	var out map[string]any
	err := postJSON(context.Background(), []string{primary.URL, blocked}, "k", map[string]any{}, &out)
	elapsed := time.Since(t0)
	if err == nil {
		t.Fatal("expected failure when both gateways are blocked")
	}
	t.Logf("耗时=%v  RST 命中=%d 次", elapsed.Round(100*time.Millisecond), hits.Load())

	if elapsed > failoverBudget+3*time.Second {
		t.Errorf("耗时 %v 超出预算 %v", elapsed, failoverBudget)
	}
	// RST 是硬失败：重试同一地址无意义，命中次数必须受控（≤2：443 一次 + 端口降级一次）。
	if hits.Load() > 2 {
		t.Errorf("对 RST 网关空试了 %d 次，应 ≤2", hits.Load())
	}
}

// TLS 被阻断时，必须尝试 Cloudflare 的备用 HTTPS 端口（2053 等）。
// 这是在被阻断主机上恢复第二跳、无需自有域名的现成手段。
func TestSNIBlockedAltPortAttempted(t *testing.T) {
	breaker.reset()
	defer breaker.reset()
	allowAltPortsForLocal(t)

	blocked, _ := rstServer(t)
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer primary.Close()

	var out map[string]any
	err := postJSON(context.Background(), []string{primary.URL, blocked}, "k", map[string]any{}, &out)
	if err == nil {
		t.Fatal("expected failure (no real alt port listener)")
	}
}

// isHardFailure 的判定边界：抖动的 dial 超时不算硬失败（值得重试），
// 而 TLS RST / 代理拒绝算。
func TestIsHardFailure(t *testing.T) {
	hard := []error{
		errors.New("read tcp: connection reset by peer"),
		errors.New("unexpected EOF"),
		errors.New("proxyconnect tcp: 502 Bad Gateway"),
		errors.New("tls: handshake failure"),
	}
	for _, e := range hard {
		if !isHardFailure(e) {
			t.Errorf("isHardFailure(%q) = false, want true", e)
		}
	}
	soft := []error{
		errors.New("dial tcp 1.2.3.4:443: i/o timeout"),
		errors.New("dial tcp: lookup x: no such host"),
	}
	for _, e := range soft {
		if isHardFailure(e) {
			t.Errorf("isHardFailure(%q) = true, want false (worth retrying)", e)
		}
	}
}

func TestWithAltPort(t *testing.T) {
	got, ok := withAltPort("https://se-rag-gateway.zetao-zhang.workers.dev/v1", "2053")
	if !ok {
		t.Fatal("withAltPort failed")
	}
	want := "https://se-rag-gateway.zetao-zhang.workers.dev:2053/v1"
	if got != want {
		t.Errorf("withAltPort = %q, want %q", got, want)
	}
}

// 验证「443 硬失败 → 自动改用备用端口」的动作发生在 postJSON 内部，且改端口后能成功返回。
func TestPortDowngradeSwitchesURL(t *testing.T) {
	breaker.reset()
	defer breaker.reset()
	allowAltPortsForLocal(t)

	good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer good.Close()

	blocked, hits := rstServer(t)

	orig := gatewayAltPorts
	gatewayAltPorts = []string{hostPort(t, good.URL)}
	defer func() { gatewayAltPorts = orig }()

	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer primary.Close()

	var out map[string]any
	served, err := postJSONWithGateway(context.Background(),
		[]string{primary.URL, blocked}, "k", map[string]any{}, &out)
	if err != nil {
		t.Fatalf("端口降级后应成功，得到 %v", err)
	}
	if served == "" {
		t.Error("served 网关为空")
	}
	if hits.Load() > 2 {
		t.Errorf("RST 网关被空试 %d 次，应 ≤2", hits.Load())
	}
	t.Logf("served=%s RST命中=%d", served, hits.Load())
}

// hostPort 取 "127.0.0.1:PORT" 形式的端口号（httptest URL 去掉 scheme）。
func hostPort(t *testing.T, raw string) string {
	t.Helper()
	_, p, err := net.SplitHostPort(strings.TrimPrefix(raw, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// allowAltPortsForLocal 让本地 httptest 地址被视为 Cloudflare 域名，
// 从而可测端口降级（生产环境只有 *.workers.dev 享有备用端口）。
func allowAltPortsForLocal(t *testing.T) {
	t.Helper()
	orig := altPortHostSuffixes
	altPortHostSuffixes = append(append([]string{}, orig...), "127.0.0.1")
	t.Cleanup(func() { altPortHostSuffixes = orig })
}
