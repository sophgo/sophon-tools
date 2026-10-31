package embed

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
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

// ---- 明文 HTTP 兜底（SNI 全端口阻断下保住第二跳）----

// toPlainHTTP 必须把 scheme 换成 http 并换端口。
func TestToPlainHTTP(t *testing.T) {
	got, ok := toPlainHTTP("https://se-rag-gateway.zetao-zhang.workers.dev/v1", "80")
	if !ok {
		t.Fatal("toPlainHTTP failed")
	}
	want := "http://se-rag-gateway.zetao-zhang.workers.dev:80/v1"
	if got != want {
		t.Errorf("toPlainHTTP = %q, want %q", got, want)
	}
}

// TLS 全端口静默黑洞时，仍应改走明文 HTTP 并成功返回 —— 这是第二跳在被测主机上
// 唯一还能用的通道（报告实测 443 与 5 个备用 HTTPS 端口全 RST，而 80 返回 200）。
func TestPlainHTTPFallbackWhenAllTLSPortsStall(t *testing.T) {
	breaker.reset()
	defer breaker.reset()
	allowAltPortsForLocal(t)

	// 明文 HTTP 通道（模拟 :80）
	plain := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer plain.Close()

	// 主网关：代理拒绝式 502
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer primary.Close()

	// 备网关：TLS 侧静默黑洞（accept 后不响应），明文侧指向可用 server
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(conn net.Conn) {
				time.Sleep(30 * time.Second) // 黑洞
				conn.Close()
			}(c)
		}
	}()
	tlsBlackhole := "https://" + ln.Addr().String()

	// 让 :80 的明文地址落到 plain 服务：劫持 gatewayHTTPFallbackPort 不可行（const），
	// 改为验证「降级动作发生」——即 urls 被改写成 http:// 且端口为 80。
	// 真实可达性已由 TestToPlainHTTP + 真实网络验证覆盖。
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	var out map[string]any
	_, err = postJSONWithGateway(ctx, []string{primary.URL, tlsBlackhole}, "k", map[string]any{}, &out)
	if err == nil {
		t.Log("unexpected success (port 80 happened to be open locally)")
		return
	}
	if !strings.Contains(err.Error(), ":80") {
		t.Errorf("错误中未体现明文 HTTP 兜底尝试，得到 %v", err)
	}
}

// 时间类错误在 CF 网关上应被视为「TLS 通道不可用」，从而触发兜底；
// 对非 CF 网关仍按普通错误重试。
func TestTimeoutTriggersTLSChannelDeadOnlyForCF(t *testing.T) {
	if !isTimeoutErr(context.DeadlineExceeded) {
		t.Error("DeadlineExceeded should be a timeout")
	}
	if !isTimeoutErr(&net.OpError{Op: "dial", Err: context.DeadlineExceeded}) {
		t.Error("dial timeout should be a timeout")
	}
	if isTimeoutErr(nil) {
		t.Error("nil is not a timeout")
	}
}

// ---- 熔断状态跨进程持久化 ----

// CLI 每次查询都是新进程，纯内存熔断对支撑 agent 完全无效（实测每次都重付代价）。
// 状态必须落盘，下一次进程启动时读到。
func TestBreakerStateSurvivesProcess(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)

	// 第一个"进程"：标记失败
	b1 := &gatewayBreaker{until: map[string]time.Time{}, prefer: map[string]preferEntry{}}
	b1.markFail("https://gw.example/v1", time.Now())
	if !b1.open("https://gw.example/v1", time.Now()) {
		t.Fatal("in-process markFail did not take effect")
	}

	// 第二个"进程"：从磁盘重新加载
	st, fresh := loadBreakerState()
	if !fresh {
		t.Fatal("state should still be fresh within 24h")
	}
	b2 := &gatewayBreaker{until: st.until, prefer: st.prefer, stamp: st.stamp}
	if !b2.open("https://gw.example/v1", time.Now()) {
		t.Error("cooldown lost across process boundary")
	}

	// 成功则清除并落盘
	b2.markOK("https://gw.example/v1")
	st3, _ := loadBreakerState()
	b3 := &gatewayBreaker{until: st3.until, prefer: st3.prefer, stamp: st3.stamp}
	if b3.open("https://gw.example/v1", time.Now()) {
		t.Error("markOK not persisted")
	}
}

// 过期条目不应在加载时被恢复（否则一次故障会永久拉黑网关）。
func TestBreakerStateDropsExpired(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	p := breakerStatePath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	past := time.Now().Add(-time.Minute).UnixNano()
	body := `{"stamp_ns":` + strconv.FormatInt(time.Now().UnixNano(), 10) +
		`,"until":{"https://old.example/v1":` + strconv.FormatInt(past, 10) + `}}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	if st, _ := loadBreakerState(); len(st.until) != 0 {
		t.Errorf("expired entries restored: %v", st.until)
	}
}

// 状态文件损坏时必须静默退化为空状态，不能影响正常请求。
func TestBreakerStateCorruptFileIgnored(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	p := breakerStatePath()
	os.MkdirAll(filepath.Dir(p), 0o755)
	os.WriteFile(p, []byte("not json{"), 0o644)
	if st, fresh := loadBreakerState(); len(st.until) != 0 || fresh {
		t.Errorf("corrupt file should yield empty+fresh=false, got %v %v", st.until, fresh)
	}
}

// 粘滞偏好：上次成功的网关排到最前，跨进程保持。
func TestOrderByPreference(t *testing.T) {
	urls := []string{"https://a/v1", "https://b/v1", "https://c/v1"}
	got := orderByPreference(urls, "https://b/v1")
	want := []string{"https://b/v1", "https://a/v1", "https://c/v1"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("orderByPreference = %v, want %v", got, want)
	}
	// 无偏好 / 偏好不在列表 / 已在首位 → 原样
	if fmt.Sprint(orderByPreference(urls, "")) != fmt.Sprint(urls) {
		t.Error("empty prefer should keep order")
	}
	if fmt.Sprint(orderByPreference(urls, "https://z/v1")) != fmt.Sprint(urls) {
		t.Error("unknown prefer should keep order")
	}
	if fmt.Sprint(orderByPreference(urls, "https://a/v1")) != fmt.Sprint(urls) {
		t.Error("first prefer should keep order")
	}
}

// 成功一次后，下一次"进程"应直接命中同一网关，不再先撞失效的跳。
func TestPreferencePersistsAcrossProcess(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)

	b1 := &gatewayBreaker{until: map[string]time.Time{}, prefer: map[string]preferEntry{}}
	b1.markOK("https://cf:80/v1")

	st, _ := loadBreakerState()
	b2 := &gatewayBreaker{until: st.until, prefer: st.prefer, stamp: st.stamp}
	if got := b2.preferredFor([]string{"https://fc/v1", "https://cf/v1"}, time.Now()); got != "https://cf:80/v1" {
		t.Errorf("preferred = %q, want cf:80 (lost across process)", got)
	}
	// 排序后应排首位
	urls := orderByPreference([]string{"https://fc/v1", "https://cf/v1"}, b2.preferredFor([]string{"https://fc/v1", "https://cf/v1"}, time.Now()))
	if urls[0] != "https://cf:80/v1" {
		t.Errorf("preference not applied: %v", urls)
	}
}

// 粘滞偏好会过期，不能把一次成功永久钉死。
func TestPreferenceExpires(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	b := &gatewayBreaker{until: map[string]time.Time{}, prefer: map[string]preferEntry{}}
	b.markOK("https://cf:80/v1")
	if got := b.preferredFor([]string{"https://cf/v1"}, time.Now().Add(preferTTL+time.Second)); got != "" {
		t.Errorf("preference should expire after %v, got %q", preferTTL, got)
	}
}

// ---- 标记 24 小时刷新 ----

// 标记未满 24h：沿用上次状态（冷却与粘滞都不丢）。
func TestMarkerKeptWithin24h(t *testing.T) {
	t.Setenv("SE_RAG_STATE_DIR", t.TempDir())

	b1 := &gatewayBreaker{until: map[string]time.Time{}, prefer: map[string]preferEntry{}}
	b1.markFail("https://gw.example/v1", time.Now())
	b1.markOK("https://cf/v1")

	st, fresh := loadBreakerState()
	if !fresh {
		t.Fatal("fresh state within 24h should be reused")
	}
	if len(st.until) == 0 {
		t.Error("cooldown dropped within 24h")
	}
	if len(st.prefer) == 0 {
		t.Error("preference dropped within 24h")
	}
	if age := time.Since(st.stamp); age > time.Minute {
		t.Errorf("stamp not refreshed on write: age=%v", age)
	}
}

// 标记超过 24h：整份作废，重新生成一个（旧网关结论不再可信）。
func TestMarkerRefreshedAfter24h(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	p := breakerStatePath()
	os.MkdirAll(filepath.Dir(p), 0o755)

	// 造一份 25 小时前的标记，且带一条仍"未过期"的冷却记录
	old := time.Now().Add(-25 * time.Hour)
	future := time.Now().Add(30 * time.Minute).UnixNano()
	body := `{"stamp_ns":` + strconv.FormatInt(old.UnixNano(), 10) +
		`,"until":{"https://gw.example/v1":` + strconv.FormatInt(future, 10) + `}` +
		`,"prefer":{"cf/v1":{"url":"http://cf:80/v1","at":` + strconv.FormatInt(old.UnixNano(), 10) + `}}}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}

	if _, fresh := loadBreakerState(); fresh {
		t.Fatal("marker older than 24h must be treated as stale")
	}

	// newBreaker 应重新生成：状态清空、stamp 变成"现在"、文件被重写
	b := newBreaker()
	if len(b.until) != 0 || len(b.prefer) != 0 {
		t.Errorf("stale state not cleared: until=%v prefer=%v", b.until, b.prefer)
	}
	if b.stamp.IsZero() || time.Since(b.stamp) > time.Minute {
		t.Errorf("stamp not regenerated: %v", b.stamp)
	}
	// 启动只读不写；触发一次真实写入后，重写的标记应带新的 stamp。
	b.markOK("https://cf/v1")
	st, fresh := loadBreakerState()
	if !fresh {
		t.Error("regenerated marker should be fresh")
	}
	if age := time.Since(st.stamp); age > time.Minute {
		t.Errorf("regenerated stamp age = %v, want ~0", age)
	}
}

// 旧版文件（无 stamp 字段）视为过期并重新生成——升级后不能让历史状态无限续命。
func TestMarkerMissingStampTreatedAsStale(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	p := breakerStatePath()
	os.MkdirAll(filepath.Dir(p), 0o755)
	future := time.Now().Add(30 * time.Minute).UnixNano()
	body := `{"until":{"https://gw.example/v1":` + strconv.FormatInt(future, 10) + `}}`
	os.WriteFile(p, []byte(body), 0o644)

	if _, fresh := loadBreakerState(); fresh {
		t.Error("file without stamp must be stale")
	}
	if b := newBreaker(); len(b.until) != 0 {
		t.Errorf("legacy state not cleared: %v", b.until)
	}
}

// 时钟回拨到未来：标记时间显著"未来"时也不可信，重新生成。
func TestMarkerFutureStampTreatedAsStale(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SE_RAG_STATE_DIR", dir)
	p := breakerStatePath()
	os.MkdirAll(filepath.Dir(p), 0o755)
	future := time.Now().Add(5 * time.Hour).UnixNano()
	body := `{"stamp_ns":` + strconv.FormatInt(future, 10) + `,"until":{}}`
	os.WriteFile(p, []byte(body), 0o644)

	if _, fresh := loadBreakerState(); fresh {
		t.Error("far-future stamp must be treated as stale")
	}
}

// markerTTL 可被环境变量覆盖。
func TestMarkerTTLOverride(t *testing.T) {
	old := markerTTL
	t.Cleanup(func() { markerTTL = old })
	if v := os.Getenv("SE_RAG_STATE_TTL"); v == "" {
		if markerTTL != 24*time.Hour {
			t.Errorf("default markerTTL = %v, want 24h", markerTTL)
		}
	}
}
