package config

import (
	"fmt"
	"testing"
)

// 内置 key 是 gateway throwaway 网关钥匙，不落明文到测试文件（避免 git 里铺密钥指纹）。
// 这里只校验解码结果的形态与自洽性，不校验明文值本身。

// builtinKeyLen 为内置网关 key 的固定长度，用于捕获混淆字节被误改/截断。
const builtinKeyLen = 64

func TestBuiltinKeyDecodes(t *testing.T) {
	k := BuiltinKey()
	if k == "" {
		t.Fatal("BuiltinKey() returned empty")
	}
	if len(k) != builtinKeyLen {
		t.Errorf("BuiltinKey() length = %d, want %d", len(k), builtinKeyLen)
	}
	// 往返自洽：同一 key 再次混淆解码应得到相同结果
	re := make([]byte, len(builtinKeyEnc))
	for i, c := range builtinKeyEnc {
		re[i] = c ^ builtinKeyMask
	}
	if string(re) != k {
		t.Errorf("XOR roundtrip mismatch")
	}
}

func TestEffectiveKeyUsesBuiltinWhenEmpty(t *testing.T) {
	d := DefaultConfig()
	p := d.Products[0].Embedder
	if !p.IsBuiltinKey() {
		t.Error("default embedder should use builtin key")
	}
	if p.EffectiveKey() != BuiltinKey() {
		t.Errorf("effective key mismatch: want builtin, got %q", p.EffectiveKey())
	}
}

// 默认链 CF → FC：CF 是第一跳，FC 是 CF 超时后的快速回退。
func TestDefaultGatewayIsCFFirst(t *testing.T) {
	g := DefaultConfig().Gateway
	if g.PrimaryURL != GatewayBaseURL {
		t.Errorf("default primary = %q, want CF %q", g.PrimaryURL, GatewayBaseURL)
	}
	if g.FallbackURL != GatewayFCBaseURL {
		t.Errorf("default fallback = %q, want FC %q", g.FallbackURL, GatewayFCBaseURL)
	}
	if !containsGatewayHost(GatewayBaseURL, "workers.dev") {
		t.Errorf("primary %q should be the Cloudflare worker", GatewayBaseURL)
	}
	if !containsGatewayHost(GatewayFCBaseURL, "fcapp.run") {
		t.Errorf("fallback %q should be the Alibaba FC gateway", GatewayFCBaseURL)
	}
	chain := g.Chain()
	if len(chain) != 2 || chain[0] != GatewayBaseURL || chain[1] != GatewayFCBaseURL {
		t.Errorf("chain = %v, want [CF FC]", chain)
	}
	if g.AttemptTimeout != DefaultAttemptTimeout {
		t.Errorf("attempt timeout = %v, want %v", g.AttemptTimeout, DefaultAttemptTimeout)
	}
	if g.FailoverBudget != DefaultFailoverBudget {
		t.Errorf("failover budget = %v, want %v", g.FailoverBudget, DefaultFailoverBudget)
	}
	if !g.AllowHTTPFallback {
		t.Error("plain HTTP fallback should default to enabled")
	}
}

func containsGatewayHost(raw, suffix string) bool {
	for i := 0; i+len(suffix) <= len(raw); i++ {
		if raw[i:i+len(suffix)] == suffix {
			return true
		}
	}
	return false
}

// 内建模型与维度：内置 key 的白名单只有这两个模型。
func TestDefaultModels(t *testing.T) {
	p := DefaultConfig().Products[0]
	if p.Embedder.Model != BuiltinEmbeddingModel || p.Embedder.Dim != BuiltinEmbeddingDim {
		t.Errorf("default embedder = %s/%d", p.Embedder.Model, p.Embedder.Dim)
	}
	if p.Reranker.Model != BuiltinRerankModel {
		t.Errorf("default reranker model = %s", p.Reranker.Model)
	}
}

// 自备 key：显式 base_url 必须实际生效；只有未提供 URL 时才回落官方 SiliconFlow。
func TestEffectiveBaseURL(t *testing.T) {
	g := DefaultConfig().Gateway
	d := DefaultConfig()
	p := d.Products[0].Embedder
	// 内置 → 网关链首跳（CF）
	if got := p.EffectiveBaseURL(g); got != GatewayBaseURL {
		t.Errorf("builtin effective base url = %q, want gateway %q", got, GatewayBaseURL)
	}
	// 自备 key 未给 URL → 官方 SiliconFlow
	u := p
	u.APIKey = "user-key"
	if got := u.EffectiveBaseURL(g); got != officialSiliconflowBaseURL {
		t.Errorf("user-key effective base url = %q, want official %q", got, officialSiliconflowBaseURL)
	}
	// 自备 key + 显式 URL → 用户地址，不被改写成 SiliconFlow
	c := u
	c.BaseURL = "https://my-proxy.example/v1"
	if got := c.EffectiveBaseURL(g); got != "https://my-proxy.example/v1" {
		t.Errorf("explicit base url ignored: got %q", got)
	}
}

func TestUserKeyOverrides(t *testing.T) {
	p := Provider{Type: "siliconflow", APIKey: "user-key", Model: "BAAI/bge-m3", Dim: 1024}
	if p.IsBuiltinKey() {
		t.Error("explicit api_key should disable builtin key")
	}
	if p.EffectiveKey() != "user-key" {
		t.Errorf("want user-key, got %q", p.EffectiveKey())
	}
}

// 故障转移链：内置 key → [CF 网关（主）, FC 网关（备）]；自备 key → 单地址直达（无故障转移项）。
func TestEffectiveBaseURLs(t *testing.T) {
	g := DefaultConfig().Gateway
	p := DefaultConfig().Products[0].Embedder
	want := []string{GatewayBaseURL, GatewayFCBaseURL}
	if got := p.EffectiveBaseURLs(g); fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("builtin effective base urls = %v, want %v", got, want)
	}

	// 自备 key 无 URL → 仅官方地址，不经网关
	u := p
	u.APIKey = "user-key"
	if got := u.EffectiveBaseURLs(g); fmt.Sprint(got) != fmt.Sprint([]string{officialSiliconflowBaseURL}) {
		t.Errorf("user-key effective base urls = %v, want [official]", got)
	}
	// 自备 key + 显式 URL → 只有该地址（单地址，不走内置网关故障转移）
	u.BaseURL = "https://my-proxy.example/v1"
	if got := u.EffectiveBaseURLs(g); fmt.Sprint(got) != fmt.Sprint([]string{"https://my-proxy.example/v1"}) {
		t.Errorf("user-key explicit base urls = %v, want [my-proxy]", got)
	}
}

// 备与主相同（或备为空）→ 单跳（显式禁用故障转移）。
func TestGatewayChainDedup(t *testing.T) {
	g := DefaultConfig().Gateway

	g.PrimaryURL = "https://gw.example.com/v1"
	g.FallbackURL = "https://fb.example.com/v1"
	if got := g.Chain(); fmt.Sprint(got) != fmt.Sprint([]string{"https://gw.example.com/v1", "https://fb.example.com/v1"}) {
		t.Errorf("custom chain = %v", got)
	}

	g.FallbackURL = "https://gw.example.com/v1"
	if got := g.Chain(); fmt.Sprint(got) != fmt.Sprint([]string{"https://gw.example.com/v1"}) {
		t.Errorf("dedup chain = %v", got)
	}

	// 显式空 = 禁用备用网关
	g.FallbackURL = ""
	if got := g.Chain(); len(got) != 1 {
		t.Errorf("empty fallback chain = %v, want single hop", got)
	}

	// 主地址为空 → 回落默认 CF
	g.PrimaryURL = ""
	g.FallbackURL = GatewayFCBaseURL
	if got := g.Chain(); len(got) != 2 || got[0] != GatewayBaseURL {
		t.Errorf("empty primary chain = %v, want [CF FC]", got)
	}
}

func TestDefaultProductIsSE7(t *testing.T) {
	d := DefaultConfig()
	if len(d.Products) == 0 || d.Products[0].Name != "se7" {
		t.Fatalf("expected default se7 product, got %+v", d.Products)
	}
}

// DefaultConfig 必须纯净：不读环境变量、不读文件，可重复调用得到相同结果。
// 配置读取只发生在 Load，避免包 init 阶段悄悄改掉进程行为。
func TestDefaultConfigIgnoresEnv(t *testing.T) {
	t.Setenv("SE_RAG_GATEWAY_URL", "https://env.example/v1")
	t.Setenv("OPENAI_BASE_URL", "https://env-openai.example/v1")
	g := DefaultConfig().Gateway
	if g.PrimaryURL != GatewayBaseURL {
		t.Errorf("DefaultConfig must not read env: primary = %q", g.PrimaryURL)
	}
}
