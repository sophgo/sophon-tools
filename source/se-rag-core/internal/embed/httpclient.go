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
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxAttempts = 6

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

// pickURL 从 attempt 位置起轮转，跳过处于冷却期的网关。
// 全部冷却时返回 ok=false，由调用方做半开探测。
func pickURL(urls []string, attempt int, now time.Time) (string, bool) {
	n := len(urls)
	for k := 0; k < n; k++ {
		u := urls[(attempt+k)%n]
		if !breaker.open(u, now) {
			return u, true
		}
	}
	return "", false
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
	for attempt := 0; attempt < maxAttempts; attempt++ {
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		default:
		}
		now := time.Now()
		u, ok := pickURL(urls, attempt, now)
		if !ok {
			// 全部网关都在冷却：半开探测，清空后按配置顺序再试一轮。
			breaker.reset()
			u = urls[attempt%len(urls)]
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
		if err != nil {
			return "", err
		}
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		resp, err := httpClient.Do(req)
		if err != nil {
			noteTransportFailure(err)
			breaker.markFail(u, time.Now())
			lastErr = err
			if !sleepCtx(ctx, backoff(attempt)) {
				return "", ctx.Err()
			}
			continue
		}
		if resp.StatusCode == 200 {
			defer resp.Body.Close()
			breaker.markOK(u)
			if out != nil {
				if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
					return "", err
				}
			}
			return u, nil
		}
		body400, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
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
