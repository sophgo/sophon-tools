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
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"se-rag-core/internal/config"
)

// maxAttempts 单次 postJSON 跨全部网关、全部重试的尝试次数上限。
//
// 重试的初衷是吸收瞬时抖动，不是等一条确定性失效的链路自愈。被测主机实测：
// CF 的 443 被 SNI 阻断后，6 次重试 + 退避让一次查询在降级到 BM25 前空等 65 秒
// （静默黑洞形态下甚至撞满 query 的 120s 上限）。因此除了次数，还由
// Policy.FailoverBudget 给整条链设硬时限，到点即认输降级——降级答案快过沉默。
const maxAttempts = 6

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

// httpFallbackReserve 为明文 HTTP 兜底预留的预算上限。
// CF TLS 握手实测中位数 1.9s（最大 4.6s）；443 + 一个备用端口两次尝试 + 退避约需 6s，
// 留 12s 给兜底这一跳，与默认 18s 预算对齐。
// 注意这是**上限**：实际预留不超过剩余预算的一半（见 policy.fallbackReserve），
// 否则把总预算配短（如 2s）时一上来就被预留吃光，链还没试就"已过期"。
const httpFallbackReserve = 12 * time.Second

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
// 状态落盘（见 breakerStatePath）：支撑 agent 每次查询都是独立 CLI 进程，
// 纯内存熔断对它们完全无效——实测每次查询都要重付一遍失效链路的代价。
type gatewayBreaker struct {
	mu    sync.Mutex
	until map[string]time.Time
	// prefer 按「网关身份」(stickyKey = host+去掉接口后缀的 path) 记录上次成功服务的完整地址。
	// 必须按 key 分开记：embeddings 与 rerank 是不同的 path，共用一个槽位会互相覆盖，
	// 导致其中一个永远用不上粘滞（实测正是如此）。
	prefer map[string]preferEntry
	// stamp 本状态标记的生成时间。超过 markerTTL 后整份状态作废并重新生成。
	stamp time.Time
}

// preferEntry 一条粘滞记录：可用的完整地址 + 记录时间（用于过期）。
type preferEntry struct {
	URL string
	At  time.Time
}

var breaker = newBreaker()

// newBreaker 载入上次进程的状态；标记过期/缺失时在内存里重新生成一个。
// 注意这里**不落盘**：进程启动只是读，没有产生新的路由判断。重新生成的 stamp
// 会在下一次真正写状态时（markFail/markOK）一并落盘。做法上避免「仅启动就产生
// 副作用」——否则测试、--help、离线查询都会凭空写出一个状态文件。
func newBreaker() *gatewayBreaker {
	st, fresh := loadBreakerState()
	b := &gatewayBreaker{until: st.until, prefer: st.prefer, stamp: st.stamp}
	if !fresh {
		// 标记缺失或已超过 markerTTL：上一轮的路由判断不再可信（网络状况、网关部署
		// 都可能已变），整份作废并从此刻重新计时，而不是继续沿用昨天的结论。
		b.until = map[string]time.Time{}
		b.prefer = map[string]preferEntry{}
		b.stamp = time.Now()
	}
	return b
}

// markerTTL 状态标记的有效期：超过 24 小时即重新生成。
// 与单条记录的 TTL 是两层不同的东西——冷却 60s、粘滞 10min 管「条目」，
// 这个管「整份状态文件」的新鲜度，兜住所有没写 TTL 的遗留字段和时钟异常。
// SE_RAG_STATE_TTL 可覆盖（Go duration 格式）。
var markerTTL = 24 * time.Hour

func init() {
	if v := os.Getenv("SE_RAG_STATE_TTL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil && d > 0 {
			markerTTL = d
		}
	}
}

// preferTTL 「上次成功的网关」粘滞有效期。
// 太短则每个进程都重新踩一遍失效链路；太长则网络恢复后仍被钉在慢路径上。
const preferTTL = 10 * time.Minute

// breakerStatePath 熔断状态文件路径。
// 优先 $SE_RAG_STATE_DIR（便于容器内挂载/清理），否则用用户缓存目录；
// 两者都不可得时返回空串，退化为纯内存熔断。
func breakerStatePath() string {
	if d := os.Getenv("SE_RAG_STATE_DIR"); d != "" {
		return filepath.Join(d, "gateway-breaker.json")
	}
	d, err := os.UserCacheDir()
	if err != nil || d == "" {
		return ""
	}
	return filepath.Join(d, "se-rag", "gateway-breaker.json")
}

// breakerState 一份落盘状态：冷却表 + 粘滞表 + 标记生成时间。
type breakerState struct {
	until  map[string]time.Time
	prefer map[string]preferEntry
	stamp  time.Time
}

// loadBreakerState 读取上次进程留下的状态。
// 第二个返回值为 false 表示「标记缺失 / 损坏 / 已超过 markerTTL」，调用方应重新生成。
// 任何异常都静默退化为空状态——熔断是优化，不该因它启动失败。
func loadBreakerState() (breakerState, bool) {
	st := breakerState{until: map[string]time.Time{}, prefer: map[string]preferEntry{}}
	p := breakerStatePath()
	if p == "" {
		return st, false
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return st, false
	}
	var raw struct {
		Until  map[string]int64 `json:"until"`
		Prefer map[string]struct {
			URL string `json:"url"`
			At  int64  `json:"at"`
		} `json:"prefer"`
		Stamp int64 `json:"stamp_ns"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return st, false
	}

	now := time.Now()
	// 标记新鲜度：没有 stamp（旧版文件）或已超过 markerTTL，一律视为过期。
	// 同时防时钟回拨：stamp 落在未来太多（>1h）说明时钟被改过，也不可信。
	if raw.Stamp <= 0 {
		return st, false
	}
	stamp := time.Unix(0, raw.Stamp)
	if now.Sub(stamp) > markerTTL || stamp.Sub(now) > time.Hour {
		return st, false
	}
	st.stamp = stamp

	for u, ns := range raw.Until {
		t := time.Unix(0, ns)
		if now.Before(t) && now.Sub(t) < time.Hour { // 兼顾时钟回拨：过期过久的直接丢
			st.until[u] = t
		}
	}
	for k, v := range raw.Prefer {
		at := time.Unix(0, v.At)
		// 粘滞偏好也会过期：网络状况会变，不能让一次成功永久钉死路由。
		if v.URL != "" && now.Sub(at) <= preferTTL {
			st.prefer[k] = preferEntry{URL: v.URL, At: at}
		}
	}
	return st, true
}

// saveBreakerState 原子写回冷却记录（临时文件 + rename），写失败静默忽略。
func (b *gatewayBreaker) saveLocked() {
	p := breakerStatePath()
	if p == "" {
		return
	}
	type pj struct {
		URL string `json:"url"`
		At  int64  `json:"at"`
	}
	// stamp 缺失（零值）时补当前时间，保证文件自描述年龄。
	stamp := b.stamp
	if stamp.IsZero() {
		stamp = time.Now()
	}
	raw := struct {
		Until   map[string]int64 `json:"until"`
		Prefer  map[string]pj    `json:"prefer,omitempty"`
		StampNs int64            `json:"stamp_ns"`
	}{
		Until:   make(map[string]int64, len(b.until)),
		Prefer:  make(map[string]pj, len(b.prefer)),
		StampNs: stamp.UnixNano(),
	}
	for u, t := range b.until {
		raw.Until[u] = t.UnixNano()
	}
	for k, v := range b.prefer {
		raw.Prefer[k] = pj{URL: v.URL, At: v.At.UnixNano()}
	}
	data, err := json.Marshal(raw)
	if err != nil {
		return
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return
	}
	tmp := p + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return
	}
	_ = os.Rename(tmp, p)
}

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
	b.saveLocked()
}

// markOK 记录一次成功并解除冷却。
func (b *gatewayBreaker) markOK(url string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	changed := false
	if _, ok := b.until[url]; ok {
		delete(b.until, url)
		changed = true
	}
	// 记住这条能用的路径：下次进程直接从它开始，不必重付失效链路的代价。
	// 键剥掉接口后缀，这样 base 地址列表也能查到它（见 stickyKey）。
	k := stickyKey(url)
	if k != "" {
		if cur, ok := b.prefer[k]; !ok || cur.URL != url {
			b.prefer[k] = preferEntry{URL: url, At: time.Now()}
			changed = true
		}
	}
	if changed {
		b.saveLocked()
	}
}

// orderByPreference 把上次成功的路径排到最前（仅用于测试/无策略场景）。
func orderByPreference(urls []string, prefer string) []string {
	urls, _ = substituePreferredChannel(urls, prefer)
	return promotePreferred(urls, prefer)
}

// substituePreferredChannel 把 prefer 所属网关槽位的**通道**换掉，返回新列表与是否改动。
//
// 关键：只换通道（scheme/host/port），**保留 configured 的 path 与 query**。
// 缓存的完整地址属于某个具体接口（…/v1/embeddings），直接把槽位替换成它会让
// rerank 请求打到 embeddings 路径上——返回空结果且 err=nil，是最难发现的串接口。
func substituePreferredChannel(urls []string, prefer string) ([]string, bool) {
	key := stickyKey(prefer)
	if key == "" || countStickyKey(urls, key) != 1 {
		// 只在身份唯一时替换：同一 host+path 出现多次说明身份不足以区分，宁可不动。
		return urls, false
	}
	for i, u := range urls {
		if stickyKey(u) != key {
			continue
		}
		chanURL, ok := channelURL(u, prefer)
		if !ok || chanURL == u {
			return urls, false
		}
		out := make([]string, len(urls))
		copy(out, urls)
		out[i] = chanURL
		return out, true
	}
	return urls, false
}

// promotePreferred 把 prefer 提到首位（若它在列表里且不在首位）。
func promotePreferred(urls []string, prefer string) []string {
	if prefer == "" || len(urls) == 0 {
		return urls
	}
	for i, u := range urls {
		if u != prefer {
			continue
		}
		if i == 0 {
			return urls
		}
		out := make([]string, 0, len(urls))
		out = append(out, urls[i])
		out = append(out, urls[:i]...)
		out = append(out, urls[i+1:]...)
		return out
	}
	return urls
}

// applyPreference 应用粘滞偏好的完整规则：
//   - 通道替换（同一网关换成上次可用的端口/scheme）生效，但只改通道不改接口路径；
//   - 位置提升只在「prefer 就是配置里的第一跳」或「配置里的第一跳正在熔断冷却」时生效。
//
// 后半条是 CF 优先改造的硬约束：内置链默认 CF → FC，若允许粘滞把 FC 提到首位，
// 一次 FC 成功就会让后续调用长期绕开健康的 CF，把 CF 优先变成名义上的。
// 而 CF 处于冷却时提升 FC 只是省掉一次注定被 pickURL 跳过的检查，不改变语义。
//
// 前置条件：prefer 的网关身份（host+path）必须在链里唯一。链里两跳共享同一身份时
// （如同一主机不同端口部署了两个网关）无法判断 prefer 属于哪一跳，此时一律不动。
func applyPreference(urls []string, prefer string, now time.Time) []string {
	if prefer == "" || len(urls) == 0 {
		return urls
	}
	key := stickyKey(prefer)
	if key == "" || countStickyKey(urls, key) != 1 {
		return urls
	}
	out, _ := substituePreferredChannel(urls, prefer)
	firstHop := urls[0]
	promotable := key == stickyKey(firstHop) || breaker.open(firstHop, now)
	if !promotable {
		return out
	}
	for _, u := range out {
		if stickyKey(u) == key {
			return promotePreferred(out, u)
		}
	}
	return out
}

// gatewayKey 网关身份 = hostname + path（忽略 scheme 与端口）。
// 端口降级/明文兜底只改这两项，因此同一个网关的不同通道会得到相同的 key。
func gatewayKey(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Hostname() == "" {
		return ""
	}
	return u.Hostname() + u.Path
}

// stickyKey 粘滞记录的键。
//
// 传入 postJSON 的 urls 已是 joinPaths 之后的**完整接口地址**，因此 host+path
// 就是「网关 + 接口」的身份：embeddings 与 rerank 落在不同键上，不会串接口。
func stickyKey(raw string) string { return gatewayKey(raw) }

// countStickyKey 链里有多少跳共享同一粘滞身份。
func countStickyKey(urls []string, key string) int {
	n := 0
	for _, u := range urls {
		if stickyKey(u) == key {
			n++
		}
	}
	return n
}

// channelURL 把 configured 的通道（scheme/host/port）换成 recorded 的，
// **保留 configured 的 path 与 query**。返回 false 表示 recorded 不是同一接口。
func channelURL(configured, recorded string) (string, bool) {
	cu, err := url.Parse(configured)
	if err != nil {
		return "", false
	}
	ru, err := url.Parse(recorded)
	if err != nil || ru.Hostname() == "" {
		return "", false
	}
	// 只有同一主机、同一接口路径才谈得上「同一网关的另一个通道」。
	if ru.Hostname() != cu.Hostname() || ru.Path != cu.Path || ru.RawQuery != cu.RawQuery {
		return "", false
	}
	if ru.Scheme != "http" && ru.Scheme != "https" {
		return "", false
	}
	out := *cu
	out.Scheme = ru.Scheme
	out.Host = ru.Host // 含端口
	return out.String(), true
}

// preferredOptions 粘滞记录在本次调用里是否可用。
type preferredOptions struct {
	// allowPlain 允许把 https 通道换成缓存的明文 http 通道。
	// 必须服从本次策略的 gateway.allow_http_fallback——否则关掉开关后，
	// 一条 10 分钟内的旧缓存就能把请求重新降级为明文。
	allowPlain bool
	// allowChannelSwap 允许换端口/scheme。用户自备 key 必须严格使用最终配置的
	// 地址，任何缓存重定向（含备用端口）都不适用；内置 key 才享受通道迁移。
	allowChannelSwap bool
}

// preferredFor 在候选网关中找出上次成功的通道（默认允许换通道与明文）。
func (b *gatewayBreaker) preferredFor(urls []string, now time.Time) string {
	return b.preferredForWith(urls, now, preferredOptions{allowPlain: true, allowChannelSwap: true})
}

// preferredForWith 按给定策略过滤粘滞记录，返回本次可用的地址；无则空串。
func (b *gatewayBreaker) preferredForWith(urls []string, now time.Time, opt preferredOptions) string {
	b.mu.Lock()
	defer b.mu.Unlock()
	if !opt.allowChannelSwap {
		return ""
	}
	for _, u := range urls {
		e, ok := b.prefer[stickyKey(u)]
		if !ok || now.Sub(e.At) > preferTTL {
			continue
		}
		chanURL, ok := channelURL(u, e.URL)
		if !ok {
			continue
		}
		// 本次策略禁止明文时，缓存里的 http 通道一律不可用。
		if strings.HasPrefix(chanURL, "http://") && !opt.allowPlain {
			continue
		}
		// 只接受合法通道：同一端口，或已知的备用 HTTPS 端口 / 明文兜底端口。
		// 拒绝任意端口是必要的——粘滞记录跨进程存活，一个早已下线、恰好同
		// host+path 的旧地址会把请求永久引向死端口。
		if chanURL != u && !channelAllowed(u, chanURL) {
			continue
		}
		return chanURL
	}
	return ""
}

// channelAllowed 记录的通道是否可以作为 configured 这条网关的替代。
//
// 允许：与 configured 端口相同；或记录端口属于 Cloudflare 备用 HTTPS 端口、
// 或明文兜底端口 80。不允许：任意其它端口——那不是同一网关的另一个通道。
func channelAllowed(configured, recorded string) bool {
	cu, err1 := url.Parse(configured)
	ru, err2 := url.Parse(recorded)
	if err1 != nil || err2 != nil || ru.Hostname() == "" || ru.Hostname() != cu.Hostname() {
		return false
	}
	cp, rp := portOf(cu), portOf(ru)
	if rp == cp {
		return true
	}
	if rp == gatewayHTTPFallbackPort {
		// 明文兜底通道。scheme 不额外限制：兜底改的是「无 SNI 的明文端口 80」，
		// 端口本身已足够标识这条路。
		return true
	}
	for _, alt := range gatewayAltPorts {
		if rp == alt {
			return true
		}
	}
	return false
}

// portOf URL 的显式端口，缺省时按 scheme 取 443/80。
func portOf(u *url.URL) string {
	if p := u.Port(); p != "" {
		return p
	}
	if u.Scheme == "http" {
		return gatewayHTTPFallbackPort
	}
	return "443"
}

// reset 清空全部状态（冷却 + 粘滞偏好），用于全冷却时的半开探测。
func (b *gatewayBreaker) reset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.until = map[string]time.Time{}
	b.prefer = map[string]preferEntry{}
	b.saveLocked()
}

// postJSON POST JSON 到 urls（有序网关列表，故障转移链），带 Bearer 鉴权，使用默认网关策略。
func postJSON(ctx context.Context, urls []string, key string, payload, out any) error {
	_, err := postJSONWithGateway(ctx, urls, key, payload, out)
	return err
}

// failover 一次 postJSON 调用的网关链执行计划。
type failover struct {
	urls []string // 有序网关列表（已按粘滞偏好排序）
	gw   config.Gateway
	// multiHop 网关列表是否多于一个。
	multiHop bool
	// builtin 本次请求是否使用内置 key（内置链的策略才适用单次上限/端口降级/明文兜底）。
	// 不能拿 len(urls) 代替：关闭 fallback 的内置链是单地址，但它仍应按 Gateway
	// 策略执行；反过来自备 key 即使被配置成多地址也不该套用这些限制。
	builtin bool
	// deadline 全链总时限（= 开始时刻 + FailoverBudget）。
	deadline time.Time
}

// newFailover 按网关策略构造执行计划。零值/非正时长一律回落到默认值。
func newFailover(urls []string, gw config.Gateway) *failover {
	return newFailoverFor(urls, gw, true)
}

// newFailoverFor 显式指定 key 归属（builtin = 使用内置 key）。
func newFailoverFor(urls []string, gw config.Gateway, builtin bool) *failover {
	d := config.DefaultConfig().Gateway
	if gw.AttemptTimeout <= 0 {
		gw.AttemptTimeout = d.AttemptTimeout
	}
	if gw.FailoverBudget <= 0 {
		gw.FailoverBudget = d.FailoverBudget
	}
	// 单次上限超过总预算没有意义（第一跳会吃光预算、第二跳形同虚设）。
	if gw.AttemptTimeout > gw.FailoverBudget {
		gw.AttemptTimeout = gw.FailoverBudget
	}
	return &failover{
		urls:     urls,
		gw:       gw,
		multiHop: len(urls) > 1,
		builtin:  builtin,
		deadline: time.Now().Add(gw.FailoverBudget),
	}
}

// fallbackReserve 为明文 HTTP 兜底预留的时间。
//
// 上限定为 httpFallbackReserve，并且不超过剩余预算的一半：否则用户把总预算配短
// （例如 2s）时，预留就把整条链的可用时间吃光，第一次尝试一开始就已过期。
func (f *failover) fallbackReserve(now time.Time) time.Duration {
	remaining := f.deadline.Sub(now)
	if remaining <= 0 {
		return 0
	}
	r := httpFallbackReserve
	if half := remaining / 2; r > half {
		r = half
	}
	return r
}

// wantsFallbackReserve 本次尝试是否需要让出明文兜底的时间。
// 只在确有兜底候选、走 TLS、且策略允许明文时为真。
func (f *failover) wantsFallbackReserve(u string, plainHTTPTried map[string]bool) bool {
	return f.builtin && f.gw.AllowHTTPFallback && isHTTPS(u) &&
		supportsAltPorts(u) && hasHTTPFallbackCandidate(f.urls, plainHTTPTried)
}

// attemptDeadline 单次尝试的截止时刻。
//
// 内置链：min(全链 deadline − 明文兜底预留, now + AttemptTimeout)。
// 这是 CF 优先策略的核心——第一跳卡住（TLS 黑洞 / 响应体不返回）时最多花
// AttemptTimeout 就让位给第二跳，而不是一次尝试吃光 18s 预算、让 FC 根本没机会。
//
// 关键：预留必须从**全链** deadline 扣，再与单次上限取 min；不能先裁到
// now+AttemptTimeout 再扣预留——默认 6s 上限 + 9s 预留会得到 now−3s，
// 于是第一跳一开始就已过期、CF 从未被真正尝试。
//
// 自备 key（builtin=false）：不设单次上限、不预留兜底时间，保持原有的等待时长；
// 用户自备地址没有第二跳可让，也不参与端口/明文降级。
func (f *failover) attemptDeadline(now time.Time, u string, plainHTTPTried map[string]bool) time.Time {
	chain := f.deadline
	if f.wantsFallbackReserve(u, plainHTTPTried) {
		if t := chain.Add(-f.fallbackReserve(now)); t.After(now) {
			chain = t
		} else {
			// 剩余预算连预留都盖不住：以剩余预算为准，不留负值。
			chain = now
		}
	}
	if !f.builtin {
		return chain
	}
	if t := now.Add(f.gw.AttemptTimeout); t.Before(chain) {
		return t
	}
	return chain
}

// remaining 距全链 deadline 的剩余时间（不为负）。
func (f *failover) remaining(now time.Time) time.Duration {
	if d := f.deadline.Sub(now); d > 0 {
		return d
	}
	return 0
}

// backoffWithinBudget 在链级预算内退避，返回 false 表示预算/ctx 已耗尽。
//
// 退避同样计入 FailoverBudget：只用父 ctx 睡会把总时长撑出预算
// （实测 40ms 预算跑成 101ms，长退避可再超 2s）。
func (f *failover) backoffWithinBudget(ctx context.Context, attempt int) (bool, error) {
	d := backoff(attempt)
	remaining := f.remaining(time.Now())
	if remaining <= 0 {
		return false, nil
	}
	if d >= remaining {
		// 睡满也超预算：直接结束，把时间留给上层降级。
		return false, nil
	}
	return sleepCtx(ctx, d), nil
}

// isHTTPS 该地址是否走 TLS。明文兜底与端口降级只对 TLS 通道有意义。
func isHTTPS(raw string) bool { return strings.HasPrefix(raw, "https://") }

// postJSONWithGateway 与 postJSON 相同，额外返回实际服务本次请求的网关地址（可观测性）。
// 失败时返回空串。使用默认网关策略（6s 单次上限 / 18s 全链预算 / 允许明文兜底）。
func postJSONWithGateway(ctx context.Context, urls []string, key string, payload, out any) (string, error) {
	return postJSONWithPolicy(ctx, urls, key, payload, out, config.DefaultConfig().Gateway)
}

// postJSONWithPolicy 按给定网关策略执行网关故障转移（视为内置 key 链路）。
func postJSONWithPolicy(ctx context.Context, urls []string, key string, payload, out any, gw config.Gateway) (string, error) {
	return postJSONWithPolicyFor(ctx, urls, key, payload, out, gw, true)
}

// postJSONWithPolicyFor 按给定网关策略执行网关故障转移，并显式声明 key 归属。
//
// builtin=true 才适用内置链专属能力（单次尝试上限、CF 备用端口降级、明文兜底、
// 粘滞通道迁移）；builtin=false（用户自备 key）严格使用最终配置给出的地址，
// 不被任何缓存重定向或降级——不能只看 len(urls)：关闭 fallback 的内置链是单地址，
// 但它仍应按 Gateway 策略执行。
//
// 顺序语义（内置 key 默认链 CF → FC）：
//   - 无故障、无有效熔断时 first 必须是 CF：粘滞偏好只能把「已验证可用的通道」
//     提到首位，且仅在它属于当前链时；旧版按 FC 排位留下的粘滞记录不会颠倒顺序。
//   - CF 单次请求（含读完响应体）最多 AttemptTimeout，到点立即转 FC。
//   - 全链 FailoverBudget（含退避）是硬时限，并尊重更短的父 ctx。
//   - 保留既有能力：403/408/429/5xx 与连接错误触发转移、失败熔断 60s、
//     CF 备用 HTTPS 端口降级、可关闭的明文 HTTP 兜底。
func postJSONWithPolicyFor(ctx context.Context, urls []string, key string, payload, out any, gw config.Gateway, builtin bool) (string, error) {
	if len(urls) == 0 {
		return "", fmt.Errorf("no gateway base urls configured")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	f := newFailoverFor(urls, gw, builtin)
	// 链级 context：请求与退避都被全链 deadline 约束，绝不越过 FailoverBudget。
	// 与父 ctx 区分开，便于向调用方报告「预算耗尽」还是「父 ctx 取消」。
	chainCtx, chainCancel := context.WithDeadline(ctx, f.deadline)
	defer chainCancel()

	// 粘滞：上次成功过的网关通道优先（跨进程有效），避免每次都先撞已知失效的跳。
	// 排序不影响语义——所有网关最终都会被尝试，只是把最可能成功的放前面。
	// 粘滞偏好按「网关+接口」区分：embeddings 与 rerank 各自记住通道，互不覆盖。
	// 候选通道必须服从本次策略：关闭明文开关后不得复用 http 缓存，
	// 自备 key 必须严格使用最终配置地址（不做任何缓存重定向）。
	prefOpts := preferredOptions{allowPlain: builtin && f.gw.AllowHTTPFallback, allowChannelSwap: builtin}
	if pref := breaker.preferredForWith(urls, time.Now(), prefOpts); pref != "" {
		f.urls = applyPreference(urls, pref, time.Now())
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

	budgetExhausted := false
	for attempt := 0; attempt < maxAttempts; attempt++ {
		// 父 ctx 取消优先：这是调用方主动放弃，错误必须如实透传。
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		default:
		}
		now := time.Now()
		// 总预算到点即认输：宁可立刻降级 BM25，也不让客户干等一分多钟。
		if !now.Before(f.deadline) {
			budgetExhausted = true
			if lastErr == nil {
				lastErr = fmt.Errorf("failover budget %s exceeded", f.gw.FailoverBudget)
			}
			break
		}
		u, ok := pickURL(f.urls, attempt, now, hardFailed)
		if !ok {
			// 全部网关要么在冷却、要么已被判定硬失败：没有可试的了。
			if len(hardFailed) == len(f.urls) {
				break
			}
			// 仅全部处于冷却：半开探测，清空后按配置顺序再试一轮。
			breaker.reset()
			u = f.urls[attempt%len(f.urls)]
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
		if err != nil {
			return "", err
		}
		// 单次尝试不能越过总预算：网关静默黑洞时一次 TLS 握手就要 10s，
		// 仅靠循环顶部检查会让总耗时膨胀到预算的倍数（实测 20s 预算跑成 30s）。
		attemptCtx, attemptCancel := context.WithDeadline(chainCtx, f.attemptDeadline(now, u, plainHTTPTried))
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
			// 自备 key 直达：没有第二跳可让，超时按普通抖动重试。
			tlsChannelDead := f.builtin && (isHardFailure(err) ||
				(isTimeoutErr(err) && supportsAltPorts(u)))
			// TLS 层被阻断 / 代理拒绝：重试同一地址必然失败，标记后跳过，
			// 并把剩下的尝试预算留给下一个网关。
			if tlsChannelDead {
				breaker.markFail(u, time.Now())
				hardFailed[u] = true
				// 端口降级：换到 Cloudflare 备用 HTTPS 端口再试一次（每网关一次）。
				// 只对 workers.dev 生效——其它网关没有这套备用端口。
				if f.builtin && supportsAltPorts(u) && !portDowngraded[base] && len(gatewayAltPorts) > 0 {
					if alt, ok := withAltPort(u, gatewayAltPorts[0]); ok {
						portDowngraded[base] = true
						delete(hardFailed, u)
						f.urls = replaceURL(f.urls, u, alt)
						continue
					}
				}
				// 明文 HTTP 兜底：按 SNI 匹配的阻断对没有 SNI 的明文请求无效，
				// 这是 TLS 全端口被封时保住第二跳的最后通道。
				if f.gw.AllowHTTPFallback && supportsAltPorts(u) && !plainHTTPTried[base] {
					if plain, ok := toPlainHTTP(u, gatewayHTTPFallbackPort); ok {
						plainHTTPTried[base] = true
						delete(hardFailed, u)
						f.urls = replaceURL(f.urls, u, plain)
						continue
					}
				}
				continue
			}
			if ok, cerr := f.backoffWithinBudget(ctx, attempt); !ok {
				if cerr != nil {
					return "", cerr
				}
				budgetExhausted = true
				break
			}
			continue
		}
		if resp.StatusCode == 200 {
			// 响应体读取同样受单次上限约束：网关可以先回 200 再卡住正文，
			// 这时若不在这里兜住，一次尝试会吃光全部预算、第二跳根本没机会。
			// 读到一半失败（超时/EOF）按「本次尝试失败」处理，继续走故障转移。
			var decodeErr error
			if out != nil {
				decodeErr = json.NewDecoder(resp.Body).Decode(out)
			}
			resp.Body.Close()
			attemptCancel()
			if decodeErr == nil {
				breaker.markOK(u)
				return u, nil
			}
			lastErr = decodeErr
			if !isTimeoutErr(decodeErr) && !errors.Is(decodeErr, context.DeadlineExceeded) {
				// 非超时的解码错误是确定性失败（响应格式不对），换网关也一样。
				return "", decodeErr
			}
			// 超时：这条通道在本次调用里不可信，冷却后让位给下一跳。
			breaker.markFail(u, time.Now())
			hardFailed[u] = true
			continue
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
			if len(forbidden) >= len(f.urls) {
				return "", lastErr
			}
		} else {
			breaker.markFail(u, time.Now())
		}
		if ok, cerr := f.backoffWithinBudget(ctx, attempt); !ok {
			if cerr != nil {
				return "", cerr
			}
			budgetExhausted = true
			break
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no successful response after %d attempts", maxAttempts)
	}
	if budgetExhausted {
		// 预算耗尽是一种「有界认输」，与父 ctx 取消区分开：前者应触发上层降级，
		// 后者是调用方主动放弃、错误必须如实透传。
		return "", fmt.Errorf("failover budget %s exhausted: %w", f.gw.FailoverBudget, lastErr)
	}
	if len(f.urls) > 1 {
		return "", fmt.Errorf("all %d gateway(s) unreachable (tried %s...): %w", len(f.urls), f.urls[0], lastErr)
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
