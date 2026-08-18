package embed

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

// 内置默认 SiliconFlow 网关（自建 Cloudflare Worker se-rag-gateway）在部分网络下存在
// *.workers.dev 域名 DNS 污染：本地 resolver 把域名解析到错误 IP 导致连接超时。
// 因此对内置网关域名采用「IP 优先 + DoH 兜底」，其他域名（sophnet、官方回落自备 key 等）
// 一律走系统 DNS，作用范围严格收窄到内置网关。

// gatewayHost 内置网关域名，仅对其应用 IP 优先拨号。
const gatewayHost = "se-rag-gateway.zetao-zhang.workers.dev"

// gatewayIPFallbacks 权威 CF Anycast IP（Cloudflare 官方，TCP 已验证可达），拨号优先直连绕开污染 resolver。
var gatewayIPFallbacks = []string{"104.21.6.72", "172.67.134.151"}

// dohServers DoH 兜底服务器（按优先级）。IP 直连 DNS-over-HTTPS，不经过被污染的系统 DNS。
var dohServers = []string{"1.1.1.1", "8.8.8.8"}

const (
	dialTimeout = 5 * time.Second
	dohTimeout  = 5 * time.Second
)

// DialContext 与 net.Dialer.DialContext 同签名，便于测试注入 mock 拨号。
type DialContext func(ctx context.Context, network, addr string) (net.Conn, error)

// ipResolver 实时拉取某域名的权威 A 记录（仅 IPv4）。
type ipResolver interface {
	resolve(ctx context.Context, host string) ([]string, bool)
}

// dialWithResolve 对内置网关域名做 IP 优先 + DoH 兜底：
//  1. 主路径：硬编码权威 CF IP 优先直连（强制 IPv4），URL 仍保留域名，SNI/Host/证书校验不受影响；
//  2. 兜底：硬编码 IP 全失败后用 DoH 实时拉权威 IP 再连，与硬编码重复的 IP 不重复拨号；
//  3. 兜底的兜底：DoH 也失败时返回错误走降级，不回调被污染的系统 DNS。
//
// 非内置网关域名直接透传 base（系统 DNS），不影响其他供应商。
func dialWithResolve(ctx context.Context, network, addr string, base DialContext, resolver ipResolver) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return base(ctx, network, addr)
	}
	if host != gatewayHost {
		return base(ctx, network, addr)
	}

	tried := map[string]bool{}
	firstErr := error(nil)
	for _, ip := range gatewayIPFallbacks {
		tried[ip] = true
		if conn, err := dialIPv4(ctx, base, ip, port); err == nil {
			return conn, nil
		} else if firstErr == nil {
			firstErr = err
		}
	}

	// 兜底：DoH 实时拉权威 IP。
	var ips []string
	if got, ok := resolver.resolve(ctx, host); ok {
		ips = got
	} else {
		firstErr = errors.New("DoH lookup failed")
	}
	for _, ip := range ips {
		if tried[ip] {
			continue
		}
		tried[ip] = true
		if conn, err := dialIPv4(ctx, base, ip, port); err == nil {
			return conn, nil
		}
	}
	return nil, fmt.Errorf("gateway %s unreachable via fallback IPs/DoH: %w", host, firstErr)
}

func dialIPv4(ctx context.Context, base DialContext, ip, port string) (net.Conn, error) {
	return base(ctx, "tcp4", net.JoinHostPort(ip, port))
}

// dohResolver 通过 DNS-over-HTTPS（application/dns-json）实时拉取域名权威 A 记录。
// 每个 DoH 请求直连 DoH 服务器 IP，不依赖系统 resolver，因而不受 *.workers.dev 污染影响。
type dohResolver struct {
	servers []string
	client  *http.Client
}

// newDoHResolver 用默认 DoH 服务器列表构造 resolver。
func newDoHResolver(base DialContext) *dohResolver {
	return newDoHResolverWith(base, dohServers)
}

// newDoHResolverWith 方便测试注入服务器列表与 client。
func newDoHResolverWith(base DialContext, servers []string) *dohResolver {
	// DoH client 强制直连（不用代理、不经过网关拨号逻辑），跳系统 DNS。
	tr := &http.Transport{Proxy: nil, DialContext: base}
	return &dohResolver{
		servers: servers,
		client:  &http.Client{Transport: tr, Timeout: dohTimeout},
	}
}

// resolve 依次尝试各 DoH 服务器，首个成功者返回；全部失败返回 ok=false。
func (r *dohResolver) resolve(ctx context.Context, host string) ([]string, bool) {
	for _, srv := range r.servers {
		ips, err := r.queryOnce(ctx, srv, host)
		if err == nil {
			return ips, true
		}
	}
	return nil, false
}

func (r *dohResolver) queryOnce(ctx context.Context, server, host string) ([]string, error) {
	base := server
	if !strings.Contains(server, "://") {
		base = "https://" + server
	}
	u := base + "/dns-query?name=" + host + "&type=A&ct=application/dns-json"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/dns-json")
	resp, err := r.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("DoH %s: status %d", server, resp.StatusCode)
	}
	var d struct {
		Status  int `json:"status"`
		Answers []struct {
			Type int    `json:"type"`
			Data string `json:"data"`
		} `json:"Answer"`
	}
	if err := json.Unmarshal(body, &d); err != nil {
		return nil, err
	}
	if d.Status != 0 { // RCODE 0 = NOERROR
		return nil, fmt.Errorf("DoH %s: RCODE %d", server, d.Status)
	}
	seen := map[string]bool{}
	var out []string
	for _, a := range d.Answers {
		if a.Type != 1 { // 仅 A 记录，忽略 AAAA(IPv6)
			continue
		}
		ip := net.ParseIP(a.Data)
		if ip == nil || ip.To4() == nil {
			continue
		}
		if !seen[a.Data] {
			seen[a.Data] = true
			out = append(out, a.Data)
		}
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("DoH %s: no A records", server)
	}
	return out, nil
}
