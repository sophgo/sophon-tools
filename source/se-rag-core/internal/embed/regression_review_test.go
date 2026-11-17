package embed

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"se-rag-core/internal/config"
)

// 本文件是验收退回（第 1 次）5 个缺陷的回归测试。每条都断言**实际发出的请求**
// （地址 / path / scheme）与**实际耗时**，而不是只看退出码或错误是否为空。
//
// 对应缺陷：
//  1. 默认 CF 从未真正尝试（attemptDeadline 把预留从已裁短的单次 deadline 里扣）
//  2. embedding 与 rerank 粘滞串接口（缓存完整 URL 直接替换槽位，连自备 provider 也受影响）
//  3. 禁止明文开关被缓存绕过 / 自备 key 被缓存重定向
//  4. 退避不受全链预算约束
//  5. 内置单跳忽略配置的单次超时（用 len(urls) 代替 key 归属）

// recordTransport 记录实际发出的请求，并按 handler 返回响应。
// 用它替代真网络：可以精确断言 scheme/host/path，也能观察 ctx deadline。
type recordTransport struct {
	mu   sync.Mutex
	sent []string
	// deadlines 每次请求的 ctx 剩余时间（用于断言单次上限确实生效）。
	deadlines []time.Duration
	handler   func(*http.Request) (*http.Response, error)
}

func (t *recordTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	t.mu.Lock()
	t.sent = append(t.sent, r.URL.String())
	if dl, ok := r.Context().Deadline(); ok {
		t.deadlines = append(t.deadlines, time.Until(dl))
	} else {
		t.deadlines = append(t.deadlines, 0)
	}
	t.mu.Unlock()
	return t.handler(r)
}

func (t *recordTransport) requests() []string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return append([]string(nil), t.sent...)
}

func (t *recordTransport) lastDeadline() time.Duration {
	t.mu.Lock()
	defer t.mu.Unlock()
	if len(t.deadlines) == 0 {
		return 0
	}
	return t.deadlines[len(t.deadlines)-1]
}

// jsonResponse 造一个 200 + 合法 JSON 的响应。
func jsonResponse(r *http.Request, body string) *http.Response {
	return &http.Response{
		StatusCode: 200,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    r,
	}
}

// installTransport 替换全局 httpClient，测试结束恢复。
func installTransport(t *testing.T, rt *recordTransport) {
	t.Helper()
	old := httpClient
	httpClient = &http.Client{Transport: rt}
	t.Cleanup(func() { httpClient = old })
}

// isolatedState 隔离熔断状态目录并清空内存状态。
func isolatedState(t *testing.T) {
	t.Helper()
	t.Setenv("SE_RAG_STATE_DIR", t.TempDir())
	breaker.reset()
	t.Cleanup(breaker.reset)
}

// ---- 缺陷 1：默认 CF 必须先被真正尝试 ----

// 默认策略（6s / 18s / 允许明文）下，第一条尝试的 deadline 必须仍在未来，
// 且实际发出的第一个请求必须是 CF。
//
// 缺陷形态：先把 deadline 裁到 now+6s，再减"总预算的一半"9s → now−3s，
// 于是第一次尝试一开始就已过期，健康 CF 从未被请求，直接落到 FC。
func TestRegressionDefaultCFFirstIsActuallyAttempted(t *testing.T) {
	isolatedState(t)
	gw := config.DefaultConfig().Gateway
	if gw.PrimaryURL != config.GatewayBaseURL {
		t.Fatalf("默认第一跳应为 CF，实际 %q", gw.PrimaryURL)
	}

	f := newFailover(joinPaths(gw.Chain(), "/embeddings"), gw)
	now := time.Now()
	d := f.attemptDeadline(now, gw.PrimaryURL+"/embeddings", map[string]bool{})
	if !d.After(now) {
		t.Fatalf("默认 CF 的 deadline 已过期：remaining=%v（预留不能从已裁短的单次 deadline 里扣）", d.Sub(now))
	}
	// 单次上限仍是 6s：不能被明文预留消掉。
	if remain := d.Sub(now); remain > gw.AttemptTimeout+100*time.Millisecond {
		t.Errorf("默认单次上限应约为 6s，实际 %v", remain)
	}

	// 端到端：用真实默认地址（HTTPS workers.dev）走一遍，断言第一个请求是 CF。
	rt := &recordTransport{handler: func(r *http.Request) (*http.Response, error) {
		return jsonResponse(r, `{"data":[{"index":0,"embedding":[1,0]}]}`), nil
	}}
	installTransport(t, rt)
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", Model: config.BuiltinEmbeddingModel, Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatalf("embed: %v", err)
	}
	sent := rt.requests()
	if len(sent) != 1 {
		t.Fatalf("CF 健康时只该发一次请求，实际 %d 次：%v", len(sent), sent)
	}
	if want := config.GatewayBaseURL + "/embeddings"; sent[0] != want {
		t.Errorf("第一个请求应为 CF %q，实际 %q", want, sent[0])
	}
	if !strings.HasPrefix(sent[0], "https://") {
		t.Errorf("默认 CF 走 HTTPS，实际 %q", sent[0])
	}
	if !strings.Contains(sent[0], "workers.dev") {
		t.Errorf("默认 CF 主机应为 *.workers.dev，实际 %q", sent[0])
	}
}

// 同一约束在"关闭明文兜底"和"明文兜底已尝试过"两种组合下也必须成立——
// 预留只在确有兜底候选时才存在，且不能吃掉单次上限。
func TestRegressionDefaultCFDeadlineAcrossFallbackCombos(t *testing.T) {
	cases := []struct {
		name        string
		allowPlain  bool
		tried       map[string]bool
		wantReserve bool
	}{
		{"允许明文-未尝试兜底", true, map[string]bool{}, true},
		{"允许明文-已尝试兜底", true, map[string]bool{portDowngradeBase(config.GatewayBaseURL + "/embeddings"): true}, false},
		{"禁止明文", false, map[string]bool{}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gw := config.DefaultConfig().Gateway
			gw.AllowHTTPFallback = c.allowPlain
			f := newFailover(joinPaths(gw.Chain(), "/embeddings"), gw)
			now := time.Now()
			d := f.attemptDeadline(now, gw.PrimaryURL+"/embeddings", c.tried)
			if !d.After(now) {
				t.Fatalf("deadline 已过期：remaining=%v", d.Sub(now))
			}
			remain := d.Sub(now)
			if remain > 6100*time.Millisecond {
				t.Errorf("单次上限不应超过 6s，实际 %v", remain)
			}
			if c.wantReserve {
				// 有兜底候选时让出预留，但必须仍留出可观时间（≥ 单次上限 − 预留）。
				if remain < 5*time.Second {
					t.Errorf("预留吃掉了过多时间：remain=%v", remain)
				}
			}
		})
	}
}

// ---- 缺陷 2：embedding 与 rerank 不得串接口 ----

// 同进程先 Embed 再 Rerank：第二条请求必须打 /rerank，且结果排序真实生效。
// 缺陷形态：把缓存的完整 URL（…/embeddings）直接替换当前槽位，rerank 请求
// 打到 embeddings 路径，得到空 results 且 err=nil。
func TestRegressionEmbedThenRerankKeepsEndpoint(t *testing.T) {
	isolatedState(t)
	var mu sync.Mutex
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		switch r.URL.Path {
		case "/v1/embeddings":
			io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
		case "/v1/rerank":
			// 故意返回与输入相反的次序：只有真命中 /rerank 才能观察到。
			io.WriteString(w, `{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}`)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()

	cfg := config.Provider{Type: "siliconflow", APIKey: "review-fake", BaseURL: srv.URL + "/v1", Model: "m", Dim: 2}
	emb, err := NewEmbedder(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatal(err)
	}
	cfg.Model = "m-rerank"
	rr, err := NewReranker(cfg)
	if err != nil {
		t.Fatal(err)
	}
	order, err := rr.Rerank(context.Background(), "q", []string{"a", "b"}, 2)
	if err != nil {
		t.Fatalf("rerank: %v", err)
	}

	mu.Lock()
	gotPaths := append([]string(nil), paths...)
	mu.Unlock()
	if len(gotPaths) != 2 || gotPaths[0] != "/v1/embeddings" || gotPaths[1] != "/v1/rerank" {
		t.Fatalf("接口路径串了：%v（期望 [/v1/embeddings /v1/rerank]）", gotPaths)
	}
	if len(order) != 2 || order[0] != 1 {
		t.Errorf("rerank 结果未生效：order=%v，期望 [1 0]（空结果会被误判为成功）", order)
	}
}

// 跨进程：Embed 成功后新进程重载状态，Rerank 仍须打 /rerank。
// 覆盖「粘滞记录落盘 + 重新加载」这条路径。
func TestRegressionCrossProcessEmbedThenRerank(t *testing.T) {
	isolatedState(t)
	var mu sync.Mutex
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		if r.URL.Path == "/v1/embeddings" {
			io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
			return
		}
		io.WriteString(w, `{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}`)
	}))
	defer srv.Close()

	cfg := config.Provider{Type: "siliconflow", APIKey: "k", BaseURL: srv.URL + "/v1", Model: "m", Dim: 2}
	emb, _ := NewEmbedder(cfg)
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatal(err)
	}

	// 模拟下一个 CLI 进程：只从磁盘读状态。
	st, fresh := loadBreakerState()
	if !fresh {
		t.Fatal("粘滞状态应跨进程存活")
	}
	if _, ok := st.prefer["127.0.0.1/v1/embeddings"]; !ok {
		t.Fatalf("embeddings 的粘滞记录缺失：%v", st.prefer)
	}
	prev := breaker
	breaker = &gatewayBreaker{until: st.until, prefer: st.prefer, stamp: st.stamp}
	t.Cleanup(func() { breaker = prev })

	rr, _ := NewReranker(cfg)
	order, err := rr.Rerank(context.Background(), "q", []string{"a", "b"}, 2)
	if err != nil {
		t.Fatalf("rerank: %v", err)
	}
	mu.Lock()
	gotPaths := append([]string(nil), paths...)
	mu.Unlock()
	if len(gotPaths) != 2 || gotPaths[1] != "/v1/rerank" {
		t.Fatalf("跨进程后接口路径串了：%v", gotPaths)
	}
	if len(order) != 2 || order[0] != 1 {
		t.Errorf("rerank 结果未生效：%v", order)
	}
}

// 两个接口交替多次：任意一次 rerank 都不得落到 embeddings 路径。
func TestRegressionAlternatingEndpointsNeverCross(t *testing.T) {
	isolatedState(t)
	var mu sync.Mutex
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		if r.URL.Path == "/v1/embeddings" {
			io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
			return
		}
		if r.URL.Path == "/v1/rerank" {
			io.WriteString(w, `{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}`)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	cfg := config.Provider{Type: "siliconflow", APIKey: "k", BaseURL: srv.URL + "/v1", Model: "m", Dim: 2}
	emb, _ := NewEmbedder(cfg)
	rr, _ := NewReranker(cfg)
	for i := 0; i < 5; i++ {
		if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
			t.Fatalf("第 %d 轮 embed: %v", i, err)
		}
		order, err := rr.Rerank(context.Background(), "q", []string{"a", "b"}, 2)
		if err != nil {
			t.Fatalf("第 %d 轮 rerank: %v", i, err)
		}
		if len(order) != 2 || order[0] != 1 {
			t.Fatalf("第 %d 轮 rerank 结果未生效：%v", i, order)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	for i, p := range paths {
		want := "/v1/embeddings"
		if i%2 == 1 {
			want = "/v1/rerank"
		}
		if p != want {
			t.Fatalf("第 %d 条请求路径 %q，期望 %q（全部：%v）", i, p, want, paths)
		}
	}
}

// 同一 host 的其它接口（/v1/models 等）也不得被 embeddings 的缓存带跑，
// 且带 query 的地址必须保留 query。
func TestRegressionChannelSwapKeepsPathAndQuery(t *testing.T) {
	// 通道替换只能改 scheme/host/port。
	got, ok := channelURL("https://gw.example/v1/rerank?x=1", "https://gw.example:2053/v1/rerank?x=1")
	if !ok {
		t.Fatal("同接口的通道替换应被允许")
	}
	if want := "https://gw.example:2053/v1/rerank?x=1"; got != want {
		t.Errorf("channelURL = %q, want %q（path/query 必须保留）", got, want)
	}
	// 不同 path 不是同一接口的通道。
	if _, ok := channelURL("https://gw.example/v1/rerank", "https://gw.example/v1/embeddings"); ok {
		t.Error("不同 path 不应被视为同一通道（这正是串接口的成因）")
	}
	if _, ok := channelURL("https://gw.example/v1/rerank?a=1", "https://gw.example/v1/rerank?a=2"); ok {
		t.Error("不同 query 不应被视为同一通道")
	}
}

// ---- 缺陷 3：明文开关与 key 归属必须被缓存尊重 ----

// 关闭 allow_http_fallback 后，缓存里的明文通道不得复用。
// 缺陷形态：复用偏好时只看端口合法，不看本次策略 → 仍发 http://…。
func TestRegressionDisabledHTTPRejectsCachedPlain(t *testing.T) {
	isolatedState(t)
	gw := config.DefaultConfig().Gateway
	gw.AllowHTTPFallback = false
	plain := strings.Replace(gw.PrimaryURL, "https://", "http://", 1) + "/embeddings"
	breaker.markOK(plain)

	rt := &recordTransport{handler: func(r *http.Request) (*http.Response, error) {
		return jsonResponse(r, `{"data":[{"index":0,"embedding":[1,0]}]}`), nil
	}}
	installTransport(t, rt)
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", Model: config.BuiltinEmbeddingModel, Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatalf("embed: %v", err)
	}
	for _, u := range rt.requests() {
		if strings.HasPrefix(u, "http://") {
			t.Errorf("allow_http_fallback=false 仍发出了明文请求：%s", u)
		}
	}
}

// 「先允许明文成功，再关闭」：同一条缓存记录在开关翻转后必须立即失效。
func TestRegressionAllowThenDisableHTTP(t *testing.T) {
	isolatedState(t)
	plainURL := strings.Replace(config.GatewayBaseURL, "https://", "http://", 1) + "/embeddings"
	breaker.markOK(plainURL)

	// 1) 允许：缓存明文通道可用。
	allow := config.DefaultConfig().Gateway
	got := breaker.preferredForWith([]string{config.GatewayBaseURL + "/embeddings"}, time.Now(),
		preferredOptions{allowPlain: true, allowChannelSwap: true})
	if got != plainURL {
		t.Fatalf("允许明文时应复用缓存通道，实际 %q", got)
	}

	// 2) 关闭：同一条记录必须被拒绝。
	deny := allow
	deny.AllowHTTPFallback = false
	got = breaker.preferredForWith([]string{config.GatewayBaseURL + "/embeddings"}, time.Now(),
		preferredOptions{allowPlain: deny.AllowHTTPFallback, allowChannelSwap: true})
	if got != "" {
		t.Errorf("关闭明文后不得复用缓存明文通道，实际 %q", got)
	}
}

// 用户自备 key：同 host 的旧明文/旧端口缓存一律不得生效——
// 自备地址来自最终配置，不能被内置链的历史缓存重定向或降级。
func TestRegressionUserKeyIgnoresCachedChannels(t *testing.T) {
	isolatedState(t)
	const base = "https://user-proxy.example.com/v1"
	ep := base + "/embeddings"

	cases := []struct{ name, cached string }{
		{"旧明文缓存", strings.Replace(ep, "https://", "http://", 1)},
		{"旧备用端口缓存", "https://user-proxy.example.com:2053/v1/embeddings"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			breaker.reset()
			breaker.markOK(c.cached)
			got := breaker.preferredForWith([]string{ep}, time.Now(),
				preferredOptions{allowPlain: false, allowChannelSwap: false})
			if got != "" {
				t.Errorf("自备 key 不得被缓存重定向，实际 %q", got)
			}
		})
	}

	// 端到端：自备 key + 缓存明文，实际请求必须仍是配置的 https 地址。
	breaker.reset()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
	}))
	defer srv.Close()
	host := strings.TrimPrefix(srv.URL, "http://")
	breaker.markOK("http://" + host + "/v1/embeddings")

	rt := &recordTransport{handler: func(r *http.Request) (*http.Response, error) {
		return jsonResponse(r, `{"data":[{"index":0,"embedding":[1,0]}]}`), nil
	}}
	installTransport(t, rt)
	gw := config.DefaultConfig().Gateway
	gw.AllowHTTPFallback = true // 即使允许，自备 key 也不该被降级
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", APIKey: "sk-user", BaseURL: srv.URL + "/v1", Model: "m", Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatalf("embed: %v", err)
	}
	sent := rt.requests()
	if len(sent) != 1 || sent[0] != srv.URL+"/v1/embeddings" {
		t.Errorf("自备 key 必须严格使用配置地址，实际 %v", sent)
	}
}

// ---- 缺陷 4：退避计入全链预算 ----

// 短预算下总耗时必须被硬性约束住：不能用父 ctx 睡满退避。
// 缺陷形态：40ms 预算实际花了 101ms，长退避还能再超 2s。
func TestRegressionBackoffWithinTotalBudget(t *testing.T) {
	isolatedState(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	gw := config.DefaultConfig().Gateway
	gw.FailoverBudget = 40 * time.Millisecond
	gw.AttemptTimeout = 10 * time.Millisecond
	gw.AllowHTTPFallback = false

	start := time.Now()
	var out map[string]any
	_, err := postJSONWithPolicy(context.Background(),
		[]string{srv.URL + "/cf", srv.URL + "/fc"}, "review-fake", map[string]any{}, &out, gw)
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("上游全 503 时应报错")
	}
	// 硬时限：40ms 预算 + 少量调度余量。原实现 101ms。
	if limit := 40*time.Millisecond + 40*time.Millisecond; elapsed > limit {
		t.Errorf("退避越过了总预算：实际 %v，上限 %v", elapsed, limit)
	}
}

// 正常量级的预算同样被硬性约束（一次 2s 退避不得越过 300ms 预算）。
func TestRegressionLongBackoffCannotExceedBudget(t *testing.T) {
	isolatedState(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	gw := config.DefaultConfig().Gateway
	gw.FailoverBudget = 300 * time.Millisecond
	gw.AttemptTimeout = 50 * time.Millisecond
	gw.AllowHTTPFallback = false

	start := time.Now()
	var out map[string]any
	if _, err := postJSONWithPolicy(context.Background(),
		[]string{srv.URL + "/cf", srv.URL + "/fc"}, "k", map[string]any{}, &out, gw); err == nil {
		t.Fatal("应报错")
	}
	if elapsed := time.Since(start); elapsed > 300*time.Millisecond+120*time.Millisecond {
		t.Errorf("长退避越过了预算：%v", elapsed)
	}
}

// 预算耗尽与父 ctx 取消必须可区分：前者是「有界认输」，后者是调用方主动放弃。
func TestRegressionBudgetVsContextCancel(t *testing.T) {
	isolatedState(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(50 * time.Millisecond)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	// 1) 预算耗尽
	gw := config.DefaultConfig().Gateway
	gw.FailoverBudget = 60 * time.Millisecond
	gw.AttemptTimeout = 20 * time.Millisecond
	gw.AllowHTTPFallback = false
	var out map[string]any
	_, err := postJSONWithPolicy(context.Background(), []string{srv.URL + "/cf"}, "k", map[string]any{}, &out, gw)
	if err == nil {
		t.Fatal("应报错")
	}
	if !strings.Contains(err.Error(), "budget") {
		t.Errorf("预算耗尽应可辨识，得到 %v", err)
	}
	if strings.Contains(err.Error(), "context canceled") {
		t.Errorf("预算耗尽不应伪装成 ctx 取消：%v", err)
	}

	// 2) 父 ctx 取消（预算充裕）
	gw2 := config.DefaultConfig().Gateway
	gw2.FailoverBudget = 10 * time.Second
	gw2.AttemptTimeout = 10 * time.Second
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = postJSONWithPolicy(ctx, []string{srv.URL + "/cf"}, "k", map[string]any{}, &out, gw2)
	if err == nil {
		t.Fatal("应报错")
	}
	if !strings.Contains(err.Error(), "context canceled") {
		t.Errorf("父 ctx 取消应如实透传，得到 %v", err)
	}
}

// ---- 缺陷 5：内置单跳仍按配置的单次超时执行 ----

// 关闭备用网关的内置链是**单地址**，但它仍然是内置链：必须按配置的
// AttemptTimeout 约束单次请求，而不是因为 len(urls)==1 就当成自备 key 豁免。
func TestRegressionSingleBuiltinHonoursAttemptTimeout(t *testing.T) {
	gw := config.DefaultConfig().Gateway
	gw.FallbackURL = "" // 单跳
	gw.AttemptTimeout = 100 * time.Millisecond
	gw.FailoverBudget = time.Second
	gw.AllowHTTPFallback = false

	if n := len(gw.Chain()); n != 1 {
		t.Fatalf("前置条件：应为单跳，实际 %d 跳", n)
	}
	f := newFailoverFor(joinPaths(gw.Chain(), "/embeddings"), gw, true)
	now := time.Now()
	d := f.attemptDeadline(now, gw.PrimaryURL+"/embeddings", map[string]bool{})
	if remain := d.Sub(now); remain > 150*time.Millisecond {
		t.Errorf("内置单跳忽略了 100ms 单次上限：remain=%v", remain)
	}

	// 端到端：服务端挂起 3s。单次上限 100ms 生效时，每次尝试都在 100ms 内被切断，
	// 不会出现"某一次挂满 3s"。断言单次请求的实际耗时（服务器端观察到的连接存活时间），
	// 而不是总耗时——总耗时 = 最多 maxAttempts × 单次上限，那是重试次数决定的。
	var hits atomic.Int64
	var maxConnLife atomic.Int64 // 单次请求在服务端的最长存活时间（纳秒）
	stall := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		t0 := time.Now()
		select {
		case <-r.Context().Done():
		case <-time.After(3 * time.Second):
		}
		if d := int64(time.Since(t0)); d > maxConnLife.Load() {
			maxConnLife.Store(d)
		}
	}))
	defer stall.Close()
	gw.PrimaryURL = stall.URL
	gw.AllowHTTPFallback = false
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", Model: config.BuiltinEmbeddingModel, Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	if _, err := emb.Embed(context.Background(), []string{"x"}); err == nil {
		t.Fatal("挂起的上游应报错")
	}
	total := time.Since(start)
	if hits.Load() == 0 {
		t.Fatal("请求根本没发出")
	}
	// 关键断言：没有任何单次尝试挂满服务端的 3s。
	if d := time.Duration(maxConnLife.Load()); d > 600*time.Millisecond {
		t.Errorf("单次尝试未被 100ms 上限切断：最长一次 %v", d)
	}
	// 总耗时受单次上限 × 重试次数约束，不会因黑洞而膨胀到服务端时长。
	if total > 2*time.Second {
		t.Errorf("总耗时失控：%v（服务端每次挂 3s，说明单次上限没生效）", total)
	}
}

// 自备 key 才豁免单次上限：单地址慢响应应能成功。
func TestRegressionUserKeyExemptFromAttemptTimeout(t *testing.T) {
	isolatedState(t)
	var hits atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		time.Sleep(300 * time.Millisecond)
		io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
	}))
	defer srv.Close()

	gw := config.DefaultConfig().Gateway
	gw.AttemptTimeout = 50 * time.Millisecond // 比服务端延迟小
	gw.FailoverBudget = 5 * time.Second
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", APIKey: "sk-user", BaseURL: srv.URL + "/v1", Model: "m", Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatalf("自备 key 不该被单次上限切断：%v", err)
	}
	if hits.Load() != 1 {
		t.Errorf("hits = %d, want 1", hits.Load())
	}
}

// 内置单跳的备用通道开关仍有效：关闭后不得降级为明文/备用端口。
func TestRegressionSingleBuiltinRespectsFallbackToggle(t *testing.T) {
	isolatedState(t)
	gw := config.DefaultConfig().Gateway
	gw.FallbackURL = ""
	gw.AllowHTTPFallback = false
	gw.AttemptTimeout = 200 * time.Millisecond
	gw.FailoverBudget = 2 * time.Second

	// 禁用明文兜底（allow_http_fallback=false）后，不得出现明文降级；
	// 备用 HTTPS 端口降级由该开关控制的是「明文」，端口降级本身是独立的 TLS 通道策略，
	// 因此这里断言的是**没有明文请求**。
	rt := &recordTransport{handler: func(r *http.Request) (*http.Response, error) {
		return nil, fmt.Errorf("connection reset by peer")
	}}
	installTransport(t, rt)
	emb, err := NewEmbedderWithGateway(config.Provider{
		Type: "siliconflow", Model: config.BuiltinEmbeddingModel, Dim: 2,
	}, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err == nil {
		t.Fatal("应报错")
	}
	reqs := rt.requests()
	if len(reqs) == 0 {
		t.Fatal("请求根本没发出")
	}
	for _, u := range reqs {
		if strings.HasPrefix(u, "http://") {
			t.Errorf("关闭明文兜底后仍发出了明文请求：%s", u)
		}
		if !strings.Contains(u, "/v1/embeddings") && !strings.Contains(u, "/embeddings") {
			t.Errorf("备用通道把接口路径带跑了：%s", u)
		}
	}
}

// ---- 退避与预算的单元级断言 ----

// backoffWithinBudget 在剩余预算不足时直接返回「不该继续」，而不是睡满。
func TestRegressionBackoffBudgetUnit(t *testing.T) {
	gw := config.DefaultConfig().Gateway
	gw.FailoverBudget = 100 * time.Millisecond
	f := newFailover(joinPaths(gw.Chain(), "/embeddings"), gw)
	// attempt=4 的退避是 1.6s，远超 100ms 预算 → 必须立即放弃。
	start := time.Now()
	ok, err := f.backoffWithinBudget(context.Background(), 4)
	elapsed := time.Since(start)
	if ok || err != nil {
		t.Errorf("预算不足时应返回 (false, nil)，得到 (%v, %v)", ok, err)
	}
	if elapsed > 20*time.Millisecond {
		t.Errorf("不应真的睡下去：%v", elapsed)
	}

	// 剩余预算充足时正常退避。
	gw2 := config.DefaultConfig().Gateway
	gw2.FailoverBudget = 5 * time.Second
	f2 := newFailover(joinPaths(gw2.Chain(), "/embeddings"), gw2)
	if ok, err := f2.backoffWithinBudget(context.Background(), 0); !ok || err != nil {
		t.Errorf("预算充足时应正常退避，得到 (%v, %v)", ok, err)
	}
}

// 保证 net 包被引用（rstServer 在其它文件里用；此处仅避免 lint 噪音）
var _ = net.JoinHostPort

// 内置 key 的同进程 Embed→Rerank：这是**唯一还会换通道**的路径
// （自备 key 已被 allowChannelSwap=false 拦住，见上一个用例），因此必须单独覆盖。
// 缺陷形态：粘滞键剥掉接口后缀 → embeddings 的成功记录被 rerank 复用，
// 把 rerank 请求改写成 …/embeddings，返回空结果且 err=nil。
func TestRegressionBuiltinEmbedThenRerankKeepsEndpoint(t *testing.T) {
	isolatedState(t)
	var mu sync.Mutex
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		if r.URL.Path == "/embeddings" {
			io.WriteString(w, `{"data":[{"index":0,"embedding":[1,0]}]}`)
			return
		}
		if r.URL.Path == "/rerank" {
			io.WriteString(w, `{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}`)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	gw := config.DefaultConfig().Gateway
	gw.PrimaryURL = srv.URL
	gw.FallbackURL = "" // 单跳，但仍按内置链策略
	cfg := config.Provider{Type: "siliconflow", Model: config.BuiltinEmbeddingModel, Dim: 2}

	emb, err := NewEmbedderWithGateway(cfg, gw)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatalf("embed: %v", err)
	}
	rr, err := NewRerankerWithGateway(cfg, gw)
	if err != nil {
		t.Fatal(err)
	}
	order, err := rr.Rerank(context.Background(), "q", []string{"a", "b"}, 2)
	if err != nil {
		t.Fatalf("rerank: %v", err)
	}
	mu.Lock()
	got := append([]string(nil), paths...)
	mu.Unlock()
	if len(got) != 2 || got[0] != "/embeddings" || got[1] != "/rerank" {
		t.Fatalf("内置链串接口：%v（期望 [/embeddings /rerank]）", got)
	}
	if len(order) != 2 || order[0] != 1 {
		t.Errorf("rerank 结果未生效：%v", order)
	}

	// 再交替一轮，确认换通道逻辑不会在第二轮把 path 带跑。
	if _, err := emb.Embed(context.Background(), []string{"x"}); err != nil {
		t.Fatal(err)
	}
	if _, err := rr.Rerank(context.Background(), "q", []string{"a", "b"}, 2); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	got = append([]string(nil), paths...)
	mu.Unlock()
	if len(got) != 4 || got[3] != "/rerank" {
		t.Fatalf("第二轮串接口：%v", got)
	}
}
