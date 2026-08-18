package embed

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"se-rag-core/internal/config"
)

// gatewayAddr 内置网关"域名:端口"拨号地址（transport 传给 DialContext 的形式）。
const gatewayAddr = gatewayHost + ":443"

func pipedConn() (net.Conn, error) {
	c, _ := net.Pipe()
	return c, nil
}

// recordingBase 记录每个拨号目标；仅当 addr 在 success 集合内时返回成功，其余拒绝。
func recordingBase(success map[string]bool) (func(ctx context.Context, network, addr string) (net.Conn, error), *[]string) {
	var calls []string
	return func(ctx context.Context, network, addr string) (net.Conn, error) {
		calls = append(calls, network+" "+addr)
		if success[addr] {
			return pipedConn()
		}
		return nil, errors.New("dial refused")
	}, &calls
}

// fakeResolver 可注入的 IP resolver。
type fakeResolver struct {
	ips []string
	ok  bool
}

func (f fakeResolver) resolve(ctx context.Context, host string) ([]string, bool) {
	return f.ips, f.ok
}

// 主路径：拨号目标是内置网关时，优先直连硬编码的权威 CF IP（强制 IPv4）。
func TestDialWithResolveGatewayPrefersHardcodedIP(t *testing.T) {
	wantIP := gatewayIPFallbacks[0]
	base, calls := recordingBase(map[string]bool{
		net.JoinHostPort(wantIP, "443"): true,
	})
	resolver := fakeResolver{}
	conn, err := dialWithResolve(context.Background(), "tcp", gatewayAddr, base, resolver)
	if err != nil {
		t.Fatalf("dialWithResolve = %v, want success", err)
	}
	conn.Close()
	if len(*calls) == 0 {
		t.Fatal("no dial calls")
	}
	if got := (*calls)[0]; got != "tcp4 "+net.JoinHostPort(wantIP, "443") {
		t.Errorf("first dial target = %q, want tcp4 %s", got, net.JoinHostPort(wantIP, "443"))
	}
}

// 作用范围收窄：非内置网关域名（官方回落 api.siliconflow.cn、sophnet、FC 网关 fcapp.run）
// 直接走系统拨号，不做 IP 覆盖。阿里云 FC 网关是国内域名，走系统 DNS 不受 IP 优先逻辑影响。
func TestDialWithResolveNonGatewayPassesThrough(t *testing.T) {
	for _, host := range []string{"api.siliconflow.cn", "www.sophnet.com", "se-rag-gateway-chrzlcfiqt.cn-hangzhou.fcapp.run", "127.0.0.1"} {
		addr := net.JoinHostPort(host, "443")
		base, calls := recordingBase(map[string]bool{addr: true})
		_, err := dialWithResolve(context.Background(), "tcp", addr, base, fakeResolver{})
		if err != nil {
			t.Fatalf("dial %s = %v", host, err)
		}
		if len(*calls) != 1 {
			t.Fatalf("calls=%v, want exactly 1 passthrough", *calls)
		}
		if got := (*calls)[0]; got != "tcp "+addr {
			t.Errorf("passthrough target = %q, want %q", got, addr)
		}
	}
}

// 兜底：硬编码 IP 全失败后，改用 DoH 解析出的权威 IP 再连；与硬编码重复的 IP 不重复拨号。
func TestDialWithResolveDoHFallback(t *testing.T) {
	// 硬编码两个 CF IP 全部失败；DoH 返回一个新 IP 才通。
	resolved := "1.2.3.4"
	success := map[string]bool{
		net.JoinHostPort(resolved, "443"): true,
	}
	base, calls := recordingBase(success)
	resolver := fakeResolver{ips: append(append([]string{}, gatewayIPFallbacks...), resolved), ok: true}
	conn, err := dialWithResolve(context.Background(), "tcp", gatewayAddr, base, resolver)
	if err != nil {
		t.Fatalf("dialWithResolve = %v, want DoH fallback success", err)
	}
	conn.Close()

	dialed := *calls
	// 去重：DoH 返回的与硬编码重复的 IP 不应被再次拨号。
	dup := net.JoinHostPort(gatewayIPFallbacks[0], "443")
	n := 0
	for _, c := range dialed {
		if strings.HasSuffix(c, " "+dup) {
			n++
		}
	}
	if n > 1 {
		t.Errorf("duplicate dial to %s: %d times, want ≤1 (dedup)", dup, n)
	}
	found := false
	for _, c := range dialed {
		if c == "tcp4 "+net.JoinHostPort(resolved, "443") {
			found = true
		}
	}
	if !found {
		t.Errorf("did not dial DoH-resolved IP %s; calls=%v", resolved, dialed)
	}
}

// 主路径一次命中：成功时不应触发 DoH。
func TestDialWithResolveSkipsDoHOnSuccess(t *testing.T) {
	base, _ := recordingBase(map[string]bool{
		net.JoinHostPort(gatewayIPFallbacks[0], "443"): true,
	})
	resolver := &countingResolver{}
	conn, err := dialWithResolve(context.Background(), "tcp", gatewayAddr, base, resolver)
	if err != nil {
		t.Fatalf("dialWithResolve = %v", err)
	}
	conn.Close()
	if resolver.calls != 0 {
		t.Errorf("DoH resolve called %d times, want 0 on hardcoded-IP success", resolver.calls)
	}
}

type countingResolver struct {
	calls int
}

func (c *countingResolver) resolve(ctx context.Context, host string) ([]string, bool) {
	c.calls++
	return nil, false
}

// 兜底的兜底：硬编码 IP 与 DoH 全部失败时返回明确的错误（走降级，不碰被污染的系统 DNS）。
func TestDialWithResolveAllFail(t *testing.T) {
	base, _ := recordingBase(map[string]bool{}) // 全部拒绝
	resolver := fakeResolver{ips: []string{"5.6.7.8"}, ok: true}
	_, err := dialWithResolve(context.Background(), "tcp", gatewayAddr, base, resolver)
	if err == nil {
		t.Fatal("expected error when all dial targets fail")
	}
	if !strings.Contains(err.Error(), gatewayHost) {
		t.Errorf("error should mention gateway host, got %q", err)
	}
}

// dohResolver 解析：仅取 IPv4 A 记录、去重、RCODE0 才有效。
func TestDoHResolverParsesAnswers(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/dns-query", func(w http.ResponseWriter, r *http.Request) {
		if got := r.URL.Query().Get("name"); got != gatewayHost {
			t.Errorf("dns-query name = %q, want %q", got, gatewayHost)
		}
		if got := r.URL.Query().Get("type"); got != "A" {
			t.Errorf("dns-query type = %q, want A", got)
		}
		w.Header().Set("Content-Type", "application/dns-json")
		b, _ := json.Marshal(map[string]any{
			"Status": 0,
			"Answer": []map[string]any{
				{"name": gatewayHost, "type": 1, "data": "104.21.6.72"},           // A 重复项 → 去重
				{"name": gatewayHost, "type": 1, "data": "104.21.6.72"},           // 重复
				{"name": gatewayHost, "type": 1, "data": "172.67.134.151"},        // A
				{"name": gatewayHost, "type": 28, "data": "2606:4700:4700::1111"}, // AAAA → 忽略
				{"name": gatewayHost, "type": 1, "data": "bogus"},                 // 非法 → 忽略
			},
		})
		w.Write(b)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext, []string{srv.URL})
	r.client = srv.Client()
	ips, ok := r.resolve(context.Background(), gatewayHost)
	if !ok {
		t.Fatal("resolve failed, want ok")
	}
	if len(ips) != 2 {
		t.Fatalf("ips = %v, want 2 unique IPv4", ips)
	}
	for _, ip := range ips {
		if p := net.ParseIP(ip); p == nil || p.To4() == nil {
			t.Errorf("got non-IPv4 %q", ip)
		}
	}
}

// DoH 服务器返回 RCODE!=0 时应视为失败。
func TestDoHResolverRcodeError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/dns-query", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/dns-json")
		fmt.Fprintf(w, `{"Status":3,"Comment":"NXDOMAIN"}`)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext, []string{srv.URL})
	r.client = srv.Client()
	if ips, ok := r.resolve(context.Background(), gatewayHost); ok {
		t.Errorf("resolve with RCODE=3 = %v ok, want failure", ips)
	}
}

// 兜底链：多个 DoH 服务器，第一个失败时启用第二个。
func TestDoHResolverFailsOverServer(t *testing.T) {
	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "boom", 500)
	}))
	defer bad.Close()
	good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/dns-json")
		fmt.Fprintf(w, `{"Status":0,"Answer":[{"name":"%s","type":1,"data":"104.21.6.72"}]}`, gatewayHost)
	}))
	defer good.Close()

	r := newDoHResolverWith((&net.Dialer{}).DialContext,
		[]string{bad.URL, good.URL})
	r.client = &http.Client{}
	ips, ok := r.resolve(context.Background(), gatewayHost)
	if !ok || len(ips) != 1 || ips[0] != "104.21.6.72" {
		t.Errorf("failover resolve = %v ok=%v, want [104.21.6.72]", ips, ok)
	}
}

// 防止常量漂移：内置网关 host 必须与 config.GatewayBaseURL 一致。
func TestGatewayHostMatchesConfig(t *testing.T) {
	u, err := url.Parse(config.GatewayBaseURL)
	if err != nil {
		t.Fatal(err)
	}
	if u.Hostname() != gatewayHost {
		t.Errorf("gatewayHost = %q, config base URL host = %q", gatewayHost, u.Hostname())
	}
}
