package embed

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxAttempts = 6

// failoverBudget 单次 postJSON 跨全部网关、全部重试的总时限。
// 重试的初衷是吸收瞬时抖动，不是等一条确定性失效的链路自愈。被测主机实测：
// CF 的 443 被 SNI 阻断后，6 次重试 + 退避让一次查询在降级到 BM25 前空等 65 秒
// （静默黑洞形态下甚至撞满 query 的 120s 上限）。这里给整条转移链设硬上限，
// 到点即认输、交由上层降级——降级答案快过沉默。
// 正常路径实测：CF TLS 握手中位数 1.9s（最大 4.6s）、FC 0.07s。
// 预算 18s = 明文 HTTP 兜底预留 12s + TLS 尝试余量 6s；若无兜底候选则 18s 全给 TLS。
// SE_RAG_FAILOVER_BUDGET 可覆盖（Go duration 格式，如 30s）。
var failoverBudget = 18 * time.Second

func init() {
	if v := os.Getenv("SE_RAG_FAILOVER_BUDGET"); v != "" {
		if d, err := time.ParseDuration(v); err == nil && d > 0 {
			failoverBudget = d
		}
	}
}

// gatewayAltPorts Cloudflare 对同一 Worker 额外监听的 HTTPS 端口。
// 443 上的 SNI 阻断未必覆盖这些端口：实测同一 Worker 在 2053/2083/2087/2096/8443
// 均可正常返回向量。但在按 SNI 匹配的深度阻断下（被测主机实测）所有 HTTPS 端口一律
// RST，此时唯一还能走的通道是明文 HTTP（80）——见 gatewayHTTPFallbackPort。
// 仅对 Cloudflare 域名有意义——fcapp.run 等其它网关没有这套端口，不能套用。
var gatewayAltPorts = []string{"2053", "2083", "2087", "2096", "8443"}

// gatewayHTTPFallbackPort 显式 HTTP 的最后兜底端口。
// 阻断规则按 TLS SNI 匹配时，明文 HTTP 根本没有 SNI 可供匹配，因此能穿过去：
// 被测主机实测 443 与全部 5 个备用 HTTPS 端口均 RST，而 80 端口返回 200 + 合法
// 1024 维向量。这是「TLS 全端口被封」时仍然保住第二跳的唯一通道。
const gatewayHTTPFallbackPort = "80"

// httpFallbackReserve 为明文 HTTP 兜底预留的预算。
// CF TLS 握手实测中位数 1.9s、最大 4.6s；配 2 次尝试 + 退避约需 10s 余量，
// 取 14s 并与 failoverBudget 一起保持「总预算 20s」的量级。
const httpFallbackReserve = 12 * time.Second

// allowPlainHTTPFallback 是否允许在 TLS 全端口失效后改走明文 HTTP。
// 默认开启：没有它，第二跳在 SNI 阻断下就是名义上的。可通过
// SE_RAG_ALLOW_HTTP_FALLBACK=0 关闭（关闭后仅有条件信任的场景会退化为降级 BM25）。
var allowPlainHTTPFallback = os.Getenv("SE_RAG_ALLOW_HTTP_FALLBACK") != "0"

// supportsAltPorts 该 URL 是否属于可用 Cloudflare 备用端口的网关。
func supportsAltPorts(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	h := u.Hostname()
	for _, suffix := range altPortHostSuffixes {
		if h == suffix || strings.HasSuffix(h, "."+suffix) {
			return true
		}
	}
	return false
}

// altPortHostSuffixes 享有 Cloudflare 备用 HTTPS 端口的域名后缀（测试可注入）。
var altPortHostSuffixes = []string{"workers.dev"}

// gatewayCooldown 单个网关失败后的熔断时长。
// 没有熔断时每次调用都从 urls[0] 重新开始，主网关持续故障就要每次重付一次超时代价：
// 内置 key 限流把 build 压成串行（约 950 次调用），实测会从 1 次 10s 放大到 950 次。
const gatewayCooldown = 60 * time.Second

// httpClient 全局 HTTP 客户端：其 Transport 对内置网关域名做 IP 优先 + DoH 兜底拨号，
// 其余域名（sophnet、官方回落等）走系统 DNS。所有供应商统一经此 client 发请求。
// Transport 带 ResponseHeaderTimeout/TLSHandshakeTimeout：网关吞连接（发包不响应）时
// 单次请求有限时，不会无限挂起。
var httpClient = newGatewayAwareClient((&net.Dialer{Timeout: dialTimeout}).DialContext)

// newGatewayAwareClient 构造对内置网关域名启用 IP 优先 + DoH 兜底的 HTTP 客户端。
func newGatewayAwareClient(base DialContext) *http.Client {
	doh := newDoHResolver(base)
	tr := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			return dialWithResolve(ctx, network, addr, base, doh)
		},
		TLSHandshakeTimeout:   tlsHandshakeTimeout,
		ResponseHeaderTimeout: respHeaderTimeout,
	}
	return &http.Client{Transport: tr}
}

// gatewayBreaker 记录各网关的失败冷却截止时间，供 postJSON 跳过已知不可用的网关。
// 只解决「同一进程内反复撞同一堵墙」，不跨进程（CLI 单次查询本来就是独立进程）。
type gatewayBreaker struct {
	mu    sync.Mutex
	until map[string]time.Time
}

var breaker = &gatewayBreaker{until: map[string]time.Time{}}

// open 判断 url 是否处于熔断冷却期。
func (b *gatewayBreaker) open(url string, now time.Time) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	t, ok := b.until[url]
	return ok && now.Before(t)
}

// markFail 记录一次失败并进入冷却。
func (b *gatewayBreaker) markFail(url string, now time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.until[url] = now.Add(gatewayCooldown)
}

// markOK 记录一次成功并解除冷却。
func (b *gatewayBreaker) markOK(url string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.until, url)
}

// reset 清空全部冷却（全部网关都在冷却时的半开探测）。
func (b *gatewayBreaker) reset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.until = map[string]time.Time{}
}

// postJSON POST JSON 到 urls（有序网关列表，故障转移链），带 Bearer 鉴权。
// 5xx/408/429/403/连接错误 → 指数退避重试（上限 maxAttempts 次），每次尝试轮转网关地址，
// 并跳过处于熔断冷却期的网关（见 gatewayBreaker）；
// 4xx（除 403 外）→ 快速失败不重试（键/路径错误在任一网关都会复现，无需转移）。
// 退避等待与整体流程感知 ctx 取消（MYS-393），网关吞连接时有限时退出。
// 单地址列表行为与旧版完全一致。
func postJSON(ctx context.Context, urls []string, key string, payload, out any) error {
	_, err := postJSONWithGateway(ctx, urls, key, payload, out)
	return err
}

// postJSONWithGateway 与 postJSON 相同，额外返回实际服务本次请求的网关地址（可观测性）。
// 失败时返回空串。
func postJSONWithGateway(ctx context.Context, urls []string, key string, payload, out any) (string, error) {
	if len(urls) == 0 {
		return "", fmt.Errorf("no gateway base urls configured")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	var lastErr error
	forbidden := map[string]bool{}
	// hardFailed 已确认「重试无意义」的网关：SNI/TLS 被阻断、或代理层拒绝。
	// 这类失败不是抖动，同一进程内再试必然同样失败，因此整条链直接跳过它。
	hardFailed := map[string]bool{}
	// 端口降级：443 被阻断时，同一 Worker 在 Cloudflare 的备用 HTTPS 端口上往往仍可用。
	// 按网关各自记账：每个网关最多降级一次，互不占用名额。
	portDowngraded := map[string]bool{}
	// plainHTTPTried 已对某个网关尝试过明文 HTTP 兜底（每网关一次）。
	plainHTTPTried := map[string]bool{}
	deadline := time.Now().Add(failoverBudget)

	for attempt := 0; attempt < maxAttempts; attempt++ {
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		default:
		}
		// 总预算到点即认输：宁可立刻降级 BM25，也不让客户干等一分多钟。
		if time.Now().After(deadline) {
			if lastErr == nil {
				lastErr = fmt.Errorf("failover budget %s exceeded", failoverBudget)
			}
			break
		}
		now := time.Now()
		u, ok := pickURL(urls, attempt, now, hardFailed)
		if !ok {
			// 全部网关要么在冷却、要么已被判定硬失败：没有可试的了。
			if len(hardFailed) == len(urls) {
				break
			}
			// 仅全部处于冷却：半开探测，清空后按配置顺序再试一轮。
			breaker.reset()
			u = urls[attempt%len(urls)]
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
		if err != nil {
			return "", err
		}
		// 单次尝试也不能越过总预算：网关静默黑洞时一次 TLS 握手就要 10s，
		// 仅靠循环顶部检查会让总耗时膨胀到预算的倍数（实测 20s 预算跑成 30s）。
		attemptDeadline := deadline
		// 给末尾的明文 HTTP 兜底预留时间：TLS 尝试可能把预算整段吃光（被测主机实测
		// 12.3s 全花在这里），预留后才能保证兜底通道确实被走到。
		// 注意必须对**每一次** TLS 尝试都生效，而不只是第一次：否则端口降级那一跳
		// 会用掉全部余额，兜底仍然轮不到（实测正是如此）。
		if allowPlainHTTPFallback && strings.HasPrefix(u, "https://") &&
			supportsAltPorts(u) && hasHTTPFallbackCandidate(urls, plainHTTPTried) {
			attemptDeadline = deadline.Add(-httpFallbackReserve)
		}
		attemptCtx, attemptCancel := context.WithDeadline(ctx, attemptDeadline)
		req = req.WithContext(attemptCtx)
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		resp, err := httpClient.Do(req)
		if err != nil {
			attemptCancel()
			noteTransportFailure(err)
			lastErr = err
			base := portDowngradeBase(u)
			// 相对 TLS 通道而言，超时和被 RST 是同一件事：这条路走不通。
			// 被测主机上 TLS 尝试是静默黑洞（不是 RST），若只对显式硬失败做降级，
			// 预算会被一次尝试整段吃光，明文 HTTP 兜底永远轮不到。
			tlsChannelDead := isHardFailure(err) ||
				(isTimeoutErr(err) && supportsAltPorts(u))
			// TLS 层被阻断 / 代理拒绝：重试同一地址必然失败，标记后跳过，
			// 并把剩下的尝试预算留给下一个网关。
			if tlsChannelDead {
				breaker.markFail(u, time.Now())
				hardFailed[u] = true
				// 端口降级：换到 Cloudflare 备用 HTTPS 端口再试一次（每网关一次）。
				// 只对 workers.dev 生效——其它网关没有这套备用端口。
				if supportsAltPorts(u) && !portDowngraded[base] && len(gatewayAltPorts) > 0 {
					if alt, ok := withAltPort(u, gatewayAltPorts[0]); ok {
						portDowngraded[base] = true
						delete(hardFailed, u)
						urls = replaceURL(urls, u, alt)
						continue
					}
				}
				// 明文 HTTP 兜底：按 SNI 匹配的阻断对没有 SNI 的明文请求无效，
				// 这是 TLS 全端口被封时保住第二跳的最后通道。
				if allowPlainHTTPFallback && supportsAltPorts(u) && !plainHTTPTried[base] {
					if plain, ok := toPlainHTTP(u, gatewayHTTPFallbackPort); ok {
						plainHTTPTried[base] = true
						delete(hardFailed, u)
						urls = replaceURL(urls, u, plain)
						continue
					}
				}
				continue
			}
			if !sleepCtx(ctx, backoff(attempt)) {
				return "", ctx.Err()
			}
			continue
		}
		if resp.StatusCode == 200 {
			breaker.markOK(u)
			if out != nil {
				err := json.NewDecoder(resp.Body).Decode(out)
				resp.Body.Close()
				attemptCancel()
				if err != nil {
					return "", err
				}
			} else {
				resp.Body.Close()
				attemptCancel()
			}
			return u, nil
		}
		body400, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		attemptCancel()
		// 403 参与转移：网关侧欠费/配额耗尽、以及部分网关特有的上游拒绝都表现为 403，
		// 它不像 401/400/404 那样能断定「换哪个网关都一样」。实测主网关对非白名单模型即返回 403。
		retriable := resp.StatusCode == 408 || resp.StatusCode == 429 ||
			resp.StatusCode == 403 || resp.StatusCode >= 500
		if !retriable {
			return "", fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		}
		lastErr = fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		if resp.StatusCode == 403 {
			// 403 未必是网关本身不可用（可能只是该网关的策略拒绝），不熔断，
			// 但若所有网关都回 403，就没有再试的意义了。
			forbidden[u] = true
			if len(forbidden) >= len(urls) {
				return "", lastErr
			}
		} else {
			breaker.markFail(u, time.Now())
		}
		if !sleepCtx(ctx, backoff(attempt)) {
			return "", ctx.Err()
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no successful response after %d attempts", maxAttempts)
	}
	if len(urls) > 1 {
		return "", fmt.Errorf("all %d gateway(s) unreachable (tried %s...): %w", len(urls), urls[0], lastErr)
	}
	return "", fmt.Errorf("postJSON failed: %w", lastErr)
}

// pickURL 从 attempt 位置起轮转，跳过处于冷却期或已判定硬失败的网关。
// 无可选网关时返回 ok=false，由调用方决定是否做半开探测。
func pickURL(urls []string, attempt int, now time.Time, skip map[string]bool) (string, bool) {
	n := len(urls)
	for k := 0; k < n; k++ {
		u := urls[(attempt+k)%n]
		if skip[u] {
			continue
		}
		if !breaker.open(u, now) {
			return u, true
		}
	}
	return "", false
}

// replaceURL 把 urls 中的 old 替换为 new（用于端口降级），保持顺序。
func replaceURL(urls []string, old, new string) []string {
	out := make([]string, len(urls))
	for i, u := range urls {
		if u == old {
			out[i] = new
		} else {
			out[i] = u
		}
	}
	return out
}

// hasHTTPFallbackCandidate 是否还有网关可以尝试明文 HTTP 兜底。
func hasHTTPFallbackCandidate(urls []string, tried map[string]bool) bool {
	for _, u := range urls {
		if supportsAltPorts(u) && !tried[portDowngradeBase(u)] {
			return true
		}
	}
	return false
}

// toPlainHTTP 把 URL 换成明文 HTTP 的指定端口。
// 仅用于 SNI 阻断下的最后兜底：明文请求不带 SNI，按 SNI 匹配的阻断拦不住它。
func toPlainHTTP(raw, port string) (string, bool) {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return "", false
	}
	u.Scheme = "http"
	u.Host = net.JoinHostPort(u.Hostname(), port)
	return u.String(), true
}

// withAltPort 给 base URL 换上指定端口；URL 无法解析时返回 false。
func withAltPort(raw, port string) (string, bool) {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return "", false
	}
	host := u.Hostname()
	u.Host = net.JoinHostPort(host, port)
	return u.String(), true
}

// portDowngradeBase 取 URL 的 scheme+host（不含端口），作为端口降级的记账键。
// 同一网关从 443 换成 2053 后键不变，因此只会降级一次。
func portDowngradeBase(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	return u.Scheme + "://" + u.Hostname() + u.Path
}

// isTimeoutErr 判断是否为超时类错误（含 ctx deadline）。
func isTimeoutErr(err error) bool {
	if err == nil {
		return false
	}
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return true
	}
	return errors.Is(err, context.DeadlineExceeded) ||
		strings.Contains(err.Error(), "i/o timeout") ||
		strings.Contains(err.Error(), "context deadline exceeded")
}

// isHardFailure 判断错误是否属于「重试同一地址必然同样失败」。
// 关键判据是 TLS 层的 RST/EOF：被测主机上 CF 的 443 对某个 SNI 定向阻断，
// ClientHello 发出后立即 ECONNRESET，6 次重试全是空等（实测退化到 65 秒才降级）。
// 代理拒绝（502 CONNECT）同理——继续试只是重复付代理往返。
func isHardFailure(err error) bool {
	if err == nil {
		return false
	}
	if isTLSFailure(err) {
		return true
	}
	msg := err.Error()
	// 代理对 CONNECT 的拒绝
	if strings.Contains(msg, "proxyconnect") || strings.Contains(msg, "Bad Gateway") {
		return true
	}
	// ClientHello 之后被 RST / 连接被对端重置：TLS 定向阻断的典型表现
	if strings.Contains(msg, "connection reset by peer") || strings.Contains(msg, "unexpected EOF") {
		return true
	}
	// 端口不可达（换端口后拒绝连接）：再试同一目标没有意义
	if strings.Contains(msg, "connection refused") {
		return true
	}
	return false
}

// noteTransportFailure 在请求层观察到 TLS 失败时，标记硬编码网关 IP 可能已失效。
// 拨号层看不出「TCP 连上了但 TLS 不通」——CF 调整 anycast 段后正是这种形态：
// 旧 IP 仍能建连，TLS 却拿到错误证书或直接被拒，此时必须改由 DoH 拉当前权威 IP。
func noteTransportFailure(err error) {
	if isTLSFailure(err) {
		markStaticIPTLSSuspect()
	}
}

// isTLSFailure 判断错误是否来自 TLS 握手/证书校验。
func isTLSFailure(err error) bool {
	var recErr tls.RecordHeaderError
	if errors.As(err, &recErr) {
		return true
	}
	var certErr *tls.CertificateVerificationError
	if errors.As(err, &certErr) {
		return true
	}
	msg := err.Error()
	return strings.Contains(msg, "tls:") || strings.Contains(msg, "x509:")
}

// sleepCtx 可中断的退避等待：ctx 取消返回 false。
func sleepCtx(ctx context.Context, d time.Duration) bool {
	select {
	case <-ctx.Done():
		return false
	case <-time.After(d):
		return true
	}
}

func backoff(attempt int) time.Duration {
	d := 100 * time.Millisecond
	for i := 0; i < attempt; i++ {
		d *= 2
		if d > 2*time.Second {
			d = 2 * time.Second
		}
	}
	return d
}

// joinPaths 把 base URL 列表展开为具体接口路径列表（保持有序，与故障转移轮转一致）。
func joinPaths(baseURLs []string, rel string) []string {
	out := make([]string, len(baseURLs))
	for i, b := range baseURLs {
		out[i] = b + rel
	}
	return out
}

// gwRecorder 记录最近一次实际服务请求的网关地址，供上层输出（可观测性）。
// 用原子值以免用户自备 key（无 limiter 串行约束）时并发读写冲突。
type gwRecorder struct {
	url atomic.Value // string
}

func (g *gwRecorder) set(u string) {
	if u != "" {
		g.url.Store(u)
	}
}

// LastGateway 返回最近一次成功请求所用的网关地址（未成功过则为空串）。
func (g *gwRecorder) LastGateway() string {
	if v, ok := g.url.Load().(string); ok {
		return v
	}
	return ""
}
