package embed

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"
)

const maxAttempts = 6

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

// postJSON POST JSON 到 urls（有序网关列表，故障转移链），带 Bearer 鉴权。
// 5xx/429/连接错误 → 指数退避重试（上限 maxAttempts 次），每次尝试按 attempt%len(urls) 轮转
// 网关地址：主网关（CF Worker）不可达时下一次即命中 FC 网关，实现 CF → FC 故障转移；
// 4xx → 快速失败不重试（键/路径/白名单错误在任一网关都会复现，无需转移）。
// 退避等待与整体流程感知 ctx 取消（MYS-393），网关吞连接时有限时退出。
// 单地址列表行为与旧版完全一致。
func postJSON(ctx context.Context, urls []string, key string, payload, out any) error {
	if len(urls) == 0 {
		return fmt.Errorf("no gateway base urls configured")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	var lastErr error
	for attempt := 0; attempt < maxAttempts; attempt++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		u := urls[attempt%len(urls)]
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		resp, err := httpClient.Do(req)
		if err != nil {
			lastErr = err
			if !sleepCtx(ctx, backoff(attempt)) {
				return ctx.Err()
			}
			continue
		}
		if resp.StatusCode == 200 {
			defer resp.Body.Close()
			if out != nil {
				if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
					return err
				}
			}
			return nil
		}
		body400, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		retriable := resp.StatusCode == 408 || resp.StatusCode == 429 || resp.StatusCode >= 500
		if !retriable {
			return fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		}
		lastErr = fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		if !sleepCtx(ctx, backoff(attempt)) {
			return ctx.Err()
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no successful response after %d attempts", maxAttempts)
	}
	if len(urls) > 1 {
		return fmt.Errorf("all %d gateway(s) unreachable (tried %s...): %w", len(urls), urls[0], lastErr)
	}
	return fmt.Errorf("postJSON failed: %w", lastErr)
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
