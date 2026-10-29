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
	"sync/atomic"
	"time"
)

// 内置网关故障转移链的备用网关（自建 Cloudflare Worker se-rag-gateway）在部分网络下存在
// *.workers.dev 域名 DNS 污染：本地 resolver 把域名解析到错误 IP 导致连接超时。
// 因此对 CF 备网关域名采用「IP 优先 + DoH 兜底」，其他域名（主网关 fcapp.run、sophnet、官方回落自备 key 等）
// 一律走系统 DNS，作用范围严格收窄到 CF 备网关。

// gatewayHost CF 备网关域名，仅对其应用 IP 优先拨号。
const gatewayHost = "se-rag-gateway.zetao-zhang.workers.dev"

// gatewayIPFallbacks 权威 CF Anycast IP，拨号优先直连绕开污染 resolver。
// 注意：TCP 可达 ≠ TLS 可用，且 Cloudflare 会调整 anycast IP；这两个 IP 只在 DialContext
// 拿不到可用地址时作为起点，随后由 DoH 拉取真实 A 记录补齐（见 dialWithResolve）。
var gatewayIPFallbacks = []string{"104.21.6.72", "172.67.134.151"}

// dohEndpoint 一个 DoH 服务器及其 JSON API 路径。
// 注意 JSON API 路径各服务商不同：Cloudflare 用 /dns-query（application/dns-json），
// Google 的 JSON API 在 /resolve——/dns-query 是 RFC8484 wireformat 端点，带 ct=application/dns-json
// 一律返回 400。历史上此处对所有服务器硬编码 /dns-query，导致 8.8.8.8 永远失败、DoH 兜底形同虚设。
type dohEndpoint struct {
	server string // 服务器主机或 IP
	path   string // JSON API 路径
}

// dohServers DoH 兜底服务器（按优先级）。IP 直连 DNS-over-HTTPS，不经过被污染的系统 DNS。
// 只用域名形式：按 IP 直连会命中证书与 IP 绑定的服务商策略（1.1.1.1 在部分出口被阻断），
// 而域名形式对 DoH 提供方自身走系统 DNS 的污染风险可忽略（这些域名不在被针对性污染之列）。
var dohServers = []dohEndpoint{
	{server: "cloudflare-dns.com", path: "/dns-query"},
	{server: "dns.google", path: "/resolve"},
	{server: "1.1.1.1", path: "/dns-query"}, // 域名不可用时的直连备选
}

// cloudflareCIDRs Cloudflare 边缘 IP 段（https://www.cloudflare.com/ips-v4）。
// DoH 应答必须落在这些段内才被采信：部分公共 DoH（实测阿里 223.5.5.5）对
// *.workers.dev 返回伪造地址，且每次不同，不加这个过滤就会把伪造 IP 当作权威地址拨号。
var cloudflareCIDRs = mustParseCIDRs(
	"173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
	"141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
	"197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
	"104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
)

func mustParseCIDRs(cidrs ...string) []*net.IPNet {
	out := make([]*net.IPNet, 0, len(cidrs))
	for _, c := range cidrs {
		_, n, err := net.ParseCIDR(c)
		if err != nil {
			panic("embed: bad cloudflare CIDR " + c)
		}
		out = append(out, n)
	}
	return out
}

// isCloudflareIP 判断 IP 是否属于 Cloudflare 边缘段。
func isCloudflareIP(ip net.IP) bool {
	for _, n := range cloudflareCIDRs {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

const (
	dialTimeout         = 5 * time.Second
	dohTimeout          = 5 * time.Second
	tlsHandshakeTimeout = 10 * time.Second
	respHeaderTimeout   = 60 * time.Second
)

// DialContext 与 net.Dialer.DialContext 同签名，便于测试注入 mock 拨号。
type DialContext func(ctx context.Context, network, addr string) (net.Conn, error)

// ipResolver 实时拉取某域名的权威 A 记录（仅 IPv4）。
type ipResolver interface {
	resolve(ctx context.Context, host string) ([]string, bool)
}

// staticIPSuspectUntil 静态 IP 可疑窗口的截止时刻（UnixNano，0 = 不可疑）。
// 观察不到的东西就不能假设它没坏：TCP 可达并不代表这两个 IP 仍路由到本 Worker。
var staticIPSuspectUntil atomic.Int64

const staticIPSuspectWindow = 10 * time.Minute

// markStaticIPTLSSuspect 在观察到 TLS 层失败后标记硬编码 IP 可疑，后续拨号改为 DoH 优先。
// 这一步不可省：拨号层只能证明 TCP 可达，而故障形态恰恰是「TCP 能连、TLS 不通」
// （CF 调整 anycast 段后旧 IP 仍可建连，但证书或 SNI 路由已不匹配）。
// 若不动摇静态 IP 的优先级，重试会反复命中同一个坏 IP，6 次尝试全部白付。
func markStaticIPTLSSuspect() {
	staticIPSuspectUntil.Store(time.Now().Add(staticIPSuspectWindow).UnixNano())
}

// staticIPSuspect 静态 IP 是否处于可疑窗口内。
func staticIPSuspect() bool {
	return time.Now().UnixNano() < staticIPSuspectUntil.Load()
}

// clearStaticIPSuspect 立即解除可疑标记（测试与显式恢复用）。
// 生产路径不做主动清除：拨号层看不到 TLS 结果，唯一可靠的是让窗口自然过期，
// 否则一次成功拨号就会把优先级翻回已验证失效的静态 IP。
func clearStaticIPSuspect() { staticIPSuspectUntil.Store(0) }

// dialWithResolve 对内置网关域名做 IP 优先 + DoH 兜底：
//  1. 主路径：硬编码 CF IP 先直连（强制 IPv4），URL 仍保留域名，SNI/Host/证书校验不受影响；
//  2. 兜底：硬编码 IP 全失败、或此前观察到 TLS 层失败（静态 IP 可疑）时，
//     用 DoH 实时拉权威 IP 再连，与硬编码重复的 IP 不重复拨号；
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

	dialStatic := func() net.Conn {
		for _, ip := range gatewayIPFallbacks {
			tried[ip] = true
			if conn, err := dialIPv4(ctx, base, ip, port); err == nil {
				return conn
			} else if firstErr == nil {
				firstErr = err
			}
		}
		return nil
	}
	dialDoH := func() net.Conn {
		ips, ok := resolver.resolve(ctx, host)
		if !ok {
			if firstErr == nil {
				firstErr = errors.New("DoH lookup failed")
			}
			return nil
		}
		for _, ip := range ips {
			if tried[ip] {
				continue
			}
			tried[ip] = true
			if conn, err := dialIPv4(ctx, base, ip, port); err == nil {
				return conn
			} else if firstErr == nil {
				firstErr = err
			}
		}
		return nil
	}

	// 静态 IP 已被判可疑（曾出现 TLS 失败）时，让 DoH 先说话。
	if staticIPSuspect() {
		if conn := dialDoH(); conn != nil {
			return conn, nil
		}
		if conn := dialStatic(); conn != nil {
			return conn, nil
		}
	} else {
		if conn := dialStatic(); conn != nil {
			return conn, nil
		}
		if conn := dialDoH(); conn != nil {
			return conn, nil
		}
	}
	return nil, fmt.Errorf("gateway %s unreachable via fallback IPs/DoH: %w", host, firstErr)
}

func dialIPv4(ctx context.Context, base DialContext, ip, port string) (net.Conn, error) {
	return base(ctx, "tcp4", net.JoinHostPort(ip, port))
}

// dohResolver 通过 DNS-over-HTTPS（application/dns-json）实时拉取域名权威 A 记录。
// 每个 DoH 请求直连 DoH 服务器，不依赖系统 resolver，因而不受 *.workers.dev 污染影响。
type dohResolver struct {
	servers []dohEndpoint
	client  *http.Client
}

// newDoHResolver 用默认 DoH 服务器列表构造 resolver。
func newDoHResolver(base DialContext) *dohResolver {
	return newDoHResolverWith(base, dohServers)
}

// newDoHResolverWith 方便测试注入服务器列表与 client。
func newDoHResolverWith(base DialContext, servers []dohEndpoint) *dohResolver {
	// DoH client 强制直连（不用代理、不经过网关拨号逻辑），跳系统 DNS。
	tr := &http.Transport{Proxy: nil, DialContext: base}
	return &dohResolver{
		servers: servers,
		client:  &http.Client{Transport: tr, Timeout: dohTimeout},
	}
}

// resolve 依次尝试各 DoH 服务器，首个成功者返回；全部失败返回 ok=false。
// 应答中的非 Cloudflare 段地址一律丢弃：被污染的公共 DoH 会返回伪造 IP，
// 采信它比解析失败更糟（会去连一个完全无关的主机）。
func (r *dohResolver) resolve(ctx context.Context, host string) ([]string, bool) {
	for _, srv := range r.servers {
		ips, err := r.queryOnce(ctx, srv.server, srv.path, host)
		if err == nil && len(ips) > 0 {
			return ips, true
		}
	}
	return nil, false
}

// queryOnce 查询单个 DoH 服务器。path 为各服务商自己的 JSON API 路径（不可统一硬编码）。
func (r *dohResolver) queryOnce(ctx context.Context, server, path, host string) ([]string, error) {
	base := server
	if !strings.Contains(server, "://") {
		base = "https://" + server
	}
	u := base + path + "?name=" + host + "&type=A&ct=application/dns-json"
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
	dropped := 0
	for _, a := range d.Answers {
		if a.Type != 1 { // 仅 A 记录，忽略 AAAA(IPv6)
			continue
		}
		ip := net.ParseIP(a.Data)
		if ip == nil || ip.To4() == nil {
			continue
		}
		// 只采信 Cloudflare 边缘段：伪造应答（污染 DoH）常返回完全无关的地址，
		// 直接拨过去会连到别的机构主机，必须在这里拦掉。
		if !isCloudflareIP(ip) {
			dropped++
			continue
		}
		if !seen[a.Data] {
			seen[a.Data] = true
			out = append(out, a.Data)
		}
	}
	if len(out) == 0 {
		if dropped > 0 {
			return nil, fmt.Errorf("DoH %s: no Cloudflare A records (%d non-CF answers rejected)", server, dropped)
		}
		return nil, fmt.Errorf("DoH %s: no A records", server)
	}
	return out, nil
}
