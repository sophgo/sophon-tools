package embed

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"se-rag-core/internal/config"
)

// 本文件覆盖「CF 优先 + 有界快速回退 FC」的行为：
//   - 顺序：无故障时 CF 必须先到；FC 成功粘滞不得颠倒顺序；
//   - 时限：CF 单次请求（含响应体）受 AttemptTimeout 约束，到点转 FC；
//   - 边界：全链总预算、父 ctx 取消、短预算可用、单地址自备请求不套用 6s；
//   - 兼容：403/429/5xx 转移、熔断到期回 CF、明文兜底开关。
//
// 全部用 httptest + 可注入的短时长，不依赖公网时延，测试总时长可控。

// gwPolicy 以默认策略为底，覆盖指定字段。
func gwPolicy(mut func(*config.Gateway)) config.Gateway {
	g := config.DefaultConfig().Gateway
	mut(&g)
	return g
}

// countingServer 记录命中次数的 JSON 服务；status 为 0 表示返回 200 + 合法 embedding。
func countingServer(t *testing.T, status int, hits *atomic.Int64, body string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if status != 0 {
			w.WriteHeader(status)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if body == "" {
			body = `{"data":[{"index":0,"embedding":[1,0]}]}`
		}
		w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	return srv
}

// stallServer 接受连接后既不响应头也不关连接（模拟网关静默黑洞）。
func stallServer(t *testing.T, hits *atomic.Int64) *httptest.Server {
	t.Helper()
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		select {
		case <-release:
		case <-r.Context().Done():
		case <-time.After(30 * time.Second):
		}
	}))
	t.Cleanup(func() {
		close(release)
		srv.Close()
	})
	return srv
}

// bodyStallServer 立即返回 200 + Content-Length，但只写一半就卡住：
// 验证「单次请求含读完响应体」都受 AttemptTimeout 约束，而不只是响应头。
func bodyStallServer(t *testing.T, hits *atomic.Int64) *httptest.Server {
	t.Helper()
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Length", "4096")
		w.WriteHeader(200)
		w.Write([]byte(`{"data":`))
		w.(http.Flusher).Flush()
		select {
		case <-release:
		case <-r.Context().Done():
		case <-time.After(30 * time.Second):
		}
	}))
	t.Cleanup(func() {
		close(release)
		srv.Close()
	})
	return srv
}

// cfThenFC 用真实 siliconflow embedder 跑一次 embedding，返回耗时与服务过的地址。
func cfThenFC(t *testing.T, p config.Provider, gw config.Gateway) (time.Duration, string, error) {
	t.Helper()
	emb, err := NewEmbedderWithGateway(p, gw)
	if err != nil {
		t.Fatalf("new embedder: %v", err)
	}
	start := time.Now()
	_, err = emb.Embed(context.Background(), []string{"SE7 芯片"})
	elapsed := time.Since(start)
	served := ""
	if ge, ok := emb.(interface{ Gateway() string }); ok {
		served = ge.Gateway()
	}
	return elapsed, servedBase(served), err
}

// servedBase 去掉服务地址的接口路径（报告的是「哪个网关」，不是完整 endpoint）。
func servedBase(raw string) string {
	if i := strings.Index(raw, "/embeddings"); i > 0 {
		return raw[:i]
	}
	if i := strings.Index(raw, "/rerank"); i > 0 {
		return raw[:i]
	}
	return raw
}

// ---- 顺序 ----

// CF 健康时只请求 CF，一次都不碰 FC。
func TestCFFirstHealthyOnlyCF(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := countingServer(t, 0, &cfHits, "")
	fc := countingServer(t, 0, &fcHits, "")

	_, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) { g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL }))
	if err != nil {
		t.Fatalf("embed: %v", err)
	}
	if served != cf.URL {
		t.Errorf("served = %q, want CF %q", served, cf.URL)
	}
	if cfHits.Load() != 1 {
		t.Errorf("CF hits = %d, want 1", cfHits.Load())
	}
	if fcHits.Load() != 0 {
		t.Errorf("FC must not be contacted when CF is healthy, got %d hits", fcHits.Load())
	}
}

// CF 响应头卡住：单次上限到点后必须转 FC 并成功，总耗时接近单次上限而非全链预算。
func TestCFTimeoutFailsOverToFC(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := stallServer(t, &cfHits)
	fc := countingServer(t, 0, &fcHits, "")

	elapsed, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) {
			g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
			g.AttemptTimeout = 300 * time.Millisecond
			g.FailoverBudget = 5 * time.Second
		}))
	if err != nil {
		t.Fatalf("expected FC success after CF timeout, got %v", err)
	}
	if served != fc.URL {
		t.Errorf("served = %q, want FC %q", served, fc.URL)
	}
	if cfHits.Load() == 0 {
		t.Error("CF was never attempted")
	}
	if fcHits.Load() == 0 {
		t.Error("FC was never attempted")
	}
	// 到点即转：不该把 5s 预算全部耗在 CF 上。留足 CI 抖动余量。
	if elapsed > 3*time.Second {
		t.Errorf("failover took %v, expected ~attempt timeout (300ms)", elapsed)
	}
}

// CF 返回 200 但响应体卡住：同样受单次上限约束（含读完响应体）。
func TestCFBodyStallFailsOverToFC(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := bodyStallServer(t, &cfHits)
	fc := countingServer(t, 0, &fcHits, "")

	elapsed, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) {
			g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
			g.AttemptTimeout = 300 * time.Millisecond
			g.FailoverBudget = 5 * time.Second
		}))
	if err != nil {
		t.Fatalf("expected FC success when CF body stalls, got %v", err)
	}
	if served != fc.URL {
		t.Errorf("served = %q, want FC", served)
	}
	if elapsed > 3*time.Second {
		t.Errorf("body stall failover took %v, expected ~300ms", elapsed)
	}
}

// 两者都黑洞：总耗时不超过总预算 + 测试容差，且必须走完两跳。
func TestBothStallBoundedByBudget(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := stallServer(t, &cfHits)
	fc := stallServer(t, &fcHits)

	budget := 900 * time.Millisecond
	start := time.Now()
	emb, err := NewEmbedderWithGateway(config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) {
			g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
			g.AttemptTimeout = 200 * time.Millisecond
			g.FailoverBudget = budget
		}))
	if err != nil {
		t.Fatal(err)
	}
	_, err = emb.Embed(context.Background(), []string{"x"})
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("expected failure when both gateways stall")
	}
	if cfHits.Load() == 0 || fcHits.Load() == 0 {
		t.Errorf("both hops must be attempted: cf=%d fc=%d", cfHits.Load(), fcHits.Load())
	}
	// 容差 1.5s 覆盖退避与调度抖动；关键是远小于 maxAttempts × 单次上限的乘积。
	if limit := budget + 1500*time.Millisecond; elapsed > limit {
		t.Errorf("elapsed %v exceeds budget+tolerance %v", elapsed, limit)
	}
}

// 父 ctx 取消：应尽快返回 ctx.Err，不等退避/预算走完。
func TestParentContextCancelEndsFast(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := stallServer(t, &cfHits)
	fc := stallServer(t, &fcHits)

	emb, err := NewEmbedderWithGateway(config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) {
			g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
			g.AttemptTimeout = 10 * time.Second
			g.FailoverBudget = 20 * time.Second
		}))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(200 * time.Millisecond)
		cancel()
	}()
	start := time.Now()
	_, err = emb.Embed(ctx, []string{"x"})
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("expected ctx cancellation error")
	}
	if elapsed > 2*time.Second {
		t.Errorf("cancellation took %v, want prompt return", elapsed)
	}
}

// 较短总预算不立即失效：2s 预算 + 默认 6s 单次上限也必须真的发出请求，
// 不能因为「明文兜底预留 12s」一上来就已过期（历史缺陷）。
func TestShortBudgetStillSendsRequests(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := countingServer(t, 0, &cfHits, "")
	fc := countingServer(t, 0, &fcHits, "")

	elapsed, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
		gwPolicy(func(g *config.Gateway) {
			g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
			g.FailoverBudget = 2 * time.Second
			// 故意保留默认 6s 单次上限：必须被收紧到预算内，而不是让链一开始就过期。
			g.AttemptTimeout = config.DefaultAttemptTimeout
		}))
	if err != nil {
		t.Fatalf("short budget must still work, got %v", err)
	}
	if served != cf.URL || cfHits.Load() == 0 {
		t.Errorf("short budget never reached CF: served=%q hits=%d", served, cfHits.Load())
	}
	if elapsed > 2*time.Second {
		t.Errorf("elapsed %v exceeds the 2s budget", elapsed)
	}
}

// 自备 key 的单 endpoint 请求不硬套内置 6s 上限：慢一点但仍在响应，就该成功。
func TestUserKeySingleEndpointNotCappedByAttemptTimeout(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var hits atomic.Int64
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		time.Sleep(700 * time.Millisecond)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer slow.Close()

	p := config.Provider{
		Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2,
		APIKey: "sk-user", BaseURL: slow.URL,
	}
	// 单次上限设得比服务端延迟还小：多跳链会超时，单地址不应该。
	gw := gwPolicy(func(g *config.Gateway) {
		g.AttemptTimeout = 200 * time.Millisecond
		g.FailoverBudget = 10 * time.Second
	})
	if _, _, err := cfThenFC(t, p, gw); err != nil {
		t.Fatalf("single endpoint must not be capped by attempt timeout, got %v", err)
	}
	if hits.Load() != 1 {
		t.Errorf("hits = %d, want 1", hits.Load())
	}
}

// ---- 粘滞与熔断 ----

// 旧 FC 粘滞不得颠倒顺序：FC 上次成功过，只要 CF 健康，下一次仍必须先到 CF。
func TestStickyFCDoesNotInvertOrder(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits, fcHits atomic.Int64
	cf := countingServer(t, 0, &cfHits, "")
	fc := countingServer(t, 0, &fcHits, "")

	gw := gwPolicy(func(g *config.Gateway) { g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL })
	p := config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2}

	// 先让 FC 拿到一次成功：CF 直接 500，链会转到 FC。
	broken := countingServer(t, 500, new(atomic.Int64), "")
	defer broken.Close()
	brokenGw := gw
	brokenGw.PrimaryURL = broken.URL
	if _, served, err := cfThenFC(t, p, brokenGw); err != nil {
		t.Fatalf("first call: %v", err)
	} else if served != fc.URL {
		t.Fatalf("first call served = %q, want FC", served)
	}
	// 现在 CF 恢复健康，并清掉冷却（模拟 60s 后冷却到期）。
	breaker.reset()
	cfHits.Store(0)
	fcHits.Store(0)

	_, served, err := cfThenFC(t, p, gw)
	if err != nil {
		t.Fatalf("second call: %v", err)
	}
	if served != cf.URL {
		t.Errorf("served = %q, want CF again after cooldown (sticky FC must not win)", served)
	}
	if fcHits.Load() != 0 {
		t.Errorf("FC contacted %d times although CF was healthy", fcHits.Load())
	}
}

// 熔断到期后必须回到 CF（不能被 FC 粘滞永久钉住）。
func TestCooldownExpiryReturnsToCF(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	var cfHits atomic.Int64
	cf := countingServer(t, 0, &cfHits, "")
	var fcHits atomic.Int64
	fc := countingServer(t, 0, &fcHits, "")
	gw := gwPolicy(func(g *config.Gateway) { g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL })

	// CF 处于冷却期 → 直接走 FC。熔断键是完整接口地址（含 /embeddings），
	// 与 postJSON 内部 markFail 用的键保持一致。
	breaker.markFail(cf.URL+"/embeddings", time.Now())
	if _, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2}, gw); err != nil {
		t.Fatalf("call during cooldown: %v", err)
	} else if served != fc.URL {
		t.Fatalf("served = %q, want FC while CF is cooling", served)
	}

	// 冷却到期（清空冷却表，保留 FC 的粘滞记录）→ 必须回到 CF。
	breaker.mu.Lock()
	breaker.until = map[string]time.Time{}
	breaker.mu.Unlock()

	cfHits.Store(0)
	fcHits.Store(0)
	if _, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2}, gw); err != nil {
		t.Fatalf("call after cooldown: %v", err)
	} else if served != cf.URL {
		t.Errorf("served = %q, want CF after cooldown expiry", served)
	}
	if cfHits.Load() == 0 {
		t.Error("CF never retried after cooldown expiry")
	}
	if fcHits.Load() != 0 {
		t.Errorf("FC still contacted %d times after CF recovered", fcHits.Load())
	}
}

// 只有 CF 在冷却时，粘滞的 FC 可以排到前面（省掉一次注定被跳过的检查）。
//
// 用不同的 host+path 表示两跳：网关身份（host+path）必须唯一，否则 applyPreference
// 无从判断粘滞属于哪一跳，会保守地不做重排（见 TestAmbiguousGatewayKeyNotReordered）。
func TestStickyFCPromotedWhileCFCooling(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	// 与生产一致：postJSON 拿到的 urls 已含接口路径（embedder 用 joinPaths 展开）。
	cf := "https://cf.example/v1"
	fc := "https://fc.example/v1"
	cfEp := cf + "/embeddings"
	fcEp := fc + "/embeddings"
	breaker.markOK(fcEp)
	breaker.markFail(cfEp, time.Now())

	urls := []string{cfEp, fcEp}
	pref := breaker.preferredFor(urls, time.Now())
	got := applyPreference(urls, pref, time.Now())
	if got[0] != fcEp {
		t.Errorf("order = %v, want FC first while CF is cooling", got)
	}
}

// CF 健康时，即使 FC 有粘滞记录也不得排到前面——这是 CF 优先的硬约束。
func TestStickyFCNotPromotedWhileCFHealthy(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	cf := "https://cf.example/v1"
	fc := "https://fc.example/v1"
	breaker.markOK(fc + "/embeddings")

	urls := []string{cf + "/embeddings", fc + "/embeddings"}
	pref := breaker.preferredFor(urls, time.Now())
	if pref == "" {
		t.Fatal("preference record missing")
	}
	if got := applyPreference(urls, pref, time.Now()); got[0] != cf+"/embeddings" {
		t.Errorf("order = %v, want CF first while CF is healthy", got)
	}
}

// 链里两跳共享同一网关身份（同一主机的不同端口）时，粘滞一律不重排：
// 无法判断记录属于哪一跳，宁可不动也不能粘错网关。
func TestAmbiguousGatewayKeyNotReordered(t *testing.T) {
	breaker.reset()
	defer breaker.reset()

	a := "http://127.0.0.1:1111/v1"
	b := "http://127.0.0.1:2222/v1"
	breaker.markOK(b + "/embeddings")
	breaker.markFail(a+"/embeddings", time.Now())

	urls := []string{a + "/embeddings", b + "/embeddings"}
	// 即便 a 在冷却（本可提升 b），身份歧义时也不重排。
	if got := applyPreference(urls, breaker.preferredFor(urls, time.Now()), time.Now()); got[0] != urls[0] {
		t.Errorf("ambiguous gateway key must not reorder, got %v", got)
	}
}

// ---- 保留能力：状态码转移 / 明文兜底开关 ----

// 403 / 429 / 5xx 仍然转移：CF 返回这些状态时 FC 必须被尝试。
func TestCFErrorStatusStillFailsOverToFC(t *testing.T) {
	for _, status := range []int{403, 429, 500, 503} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			breaker.reset()
			defer breaker.reset()

			var cfHits, fcHits atomic.Int64
			cf := countingServer(t, status, &cfHits, "")
			fc := countingServer(t, 0, &fcHits, "")

			_, served, err := cfThenFC(t, config.Provider{Type: "siliconflow", Model: "BAAI/bge-m3", Dim: 2},
				gwPolicy(func(g *config.Gateway) {
					g.PrimaryURL, g.FallbackURL = cf.URL, fc.URL
					g.FailoverBudget = 5 * time.Second
				}))
			if err != nil {
				t.Fatalf("status %d should fail over to FC: %v", status, err)
			}
			if served != fc.URL {
				t.Errorf("status %d served = %q, want FC", status, served)
			}
		})
	}
}

// 明文兜底开关仍有效：关闭后不会出现 http:// 兜底尝试。
func TestAllowHTTPFallbackToggle(t *testing.T) {
	breaker.reset()
	defer breaker.reset()
	allowAltPortsForLocal(t)

	cf, _ := rstServer(t)

	// 关闭明文兜底：链里只有 CF 一个地址，失败后不会改写成 http://
	gw := gwPolicy(func(g *config.Gateway) {
		g.PrimaryURL = cf
		g.FallbackURL = ""
		g.AttemptTimeout = 500 * time.Millisecond
		g.FailoverBudget = 2 * time.Second
		g.AllowHTTPFallback = false
	})
	var out map[string]any
	_, err := postJSONWithPolicy(context.Background(), []string{cf}, "k", map[string]any{}, &out, gw)
	if err == nil {
		t.Fatal("expected failure with single blocked gateway")
	}
	if strings.Contains(err.Error(), ":80") {
		t.Errorf("plain HTTP fallback attempted although disabled: %v", err)
	}
}

// ---- 单次上限与总预算的归一化 ----

// 单次上限超过总预算时收紧到预算内：否则第一跳必吃光预算、第二跳形同虚设。
func TestAttemptTimeoutClampedToBudget(t *testing.T) {
	f := newFailover([]string{"https://a/v1", "https://b/v1"}, gwPolicy(func(g *config.Gateway) {
		g.AttemptTimeout = 10 * time.Second
		g.FailoverBudget = 3 * time.Second
	}))
	if f.gw.AttemptTimeout != 3*time.Second {
		t.Errorf("attempt timeout = %v, want clamped to 3s", f.gw.AttemptTimeout)
	}
}

// 零值策略回落到默认值（6s / 18s），不产生「立刻过期」的链。
func TestZeroPolicyFallsBackToDefaults(t *testing.T) {
	f := newFailover([]string{"https://a/v1", "https://b/v1"}, config.Gateway{})
	if f.gw.AttemptTimeout != config.DefaultAttemptTimeout {
		t.Errorf("attempt timeout = %v, want %v", f.gw.AttemptTimeout, config.DefaultAttemptTimeout)
	}
	if f.gw.FailoverBudget != config.DefaultFailoverBudget {
		t.Errorf("budget = %v, want %v", f.gw.FailoverBudget, config.DefaultFailoverBudget)
	}
	if !f.deadline.After(time.Now()) {
		t.Error("a freshly built chain must not already be expired")
	}
}

// 明文兜底预留不超过剩余预算的一半：短预算下链仍然可用。
func TestFallbackReserveLeavesRoomOnShortBudget(t *testing.T) {
	f := newFailover([]string{"https://cf.workers.dev/v1", "https://fc/v1"}, gwPolicy(func(g *config.Gateway) {
		g.AttemptTimeout = 1 * time.Second
		g.FailoverBudget = 2 * time.Second
	}))
	now := time.Now()
	r := f.fallbackReserve(now)
	if r > time.Second {
		t.Errorf("reserve = %v, want ≤ half of the 2s budget", r)
	}
	if d := f.attemptDeadline(now, "https://cf.workers.dev/v1", map[string]bool{}); !d.After(now) {
		t.Errorf("attempt deadline %v already in the past", d.Sub(now))
	}
}
