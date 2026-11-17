package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// writeConfig 在临时目录写一份配置文件并返回路径。
func writeConfig(t *testing.T, body string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// envMap 把 map 变成 load 需要的 envLookup（未列出的变量视为不存在）。
func envMap(m map[string]string) envLookup {
	return func(k string) (string, bool) {
		v, ok := m[k]
		return v, ok
	}
}

// loadWithEnv 用给定环境变量加载（文件路径由 SE_RAG_CONFIG 提供）。
func loadWithEnv(t *testing.T, path string, env map[string]string) (Config, error) {
	t.Helper()
	e := map[string]string{}
	for k, v := range env {
		e[k] = v
	}
	if path != "" {
		e[EnvConfigPath] = path
	} else {
		// 未显式指定：把默认路径也指到临时目录里的不存在文件，
		// 既验证「默认配置缺失按默认值走」，又不读宿主机真实配置。
		orig := defaultConfigPath
		defaultConfigPath = filepath.Join(t.TempDir(), "etc-se-rag-core-config.json")
		t.Cleanup(func() { defaultConfigPath = orig })
	}
	return load(envMap(e))
}

// ---- 无配置 / 仅文件 / 仅环境 / 混合 ----

// 无任何配置：全部取默认值（CF 优先、6s/18s、内置模型）。
func TestLoadNoConfigUsesDefaults(t *testing.T) {
	cfg, err := loadWithEnv(t, "", nil)
	if err != nil {
		t.Fatalf("missing default config file must be allowed, got %v", err)
	}
	d := DefaultConfig()
	if cfg.Gateway != d.Gateway {
		t.Errorf("gateway = %+v, want default %+v", cfg.Gateway, d.Gateway)
	}
	p := cfg.Products[0]
	if p.Embedder.APIKey != "" || p.Reranker.APIKey != "" {
		t.Error("no config should mean builtin key")
	}
	if p.Embedder.Model != BuiltinEmbeddingModel || p.Embedder.Dim != BuiltinEmbeddingDim {
		t.Errorf("embedder = %s/%d, want builtin model/dim", p.Embedder.Model, p.Embedder.Dim)
	}
	if p.Reranker.Model != BuiltinRerankModel {
		t.Errorf("reranker = %s, want builtin model", p.Reranker.Model)
	}
}

// 仅文件：openai 段同时落到 embedder 与 reranker。
func TestLoadFileOnlyOpenAISection(t *testing.T) {
	path := writeConfig(t, `{
	  "openai": {
	    "base_url": "https://file.example/v1",
	    "api_key": "sk-file",
	    "embedding_model": "file-embed",
	    "reranking_model": "file-rerank",
	    "embedding_dim": 768
	  }
	}`)
	cfg, err := loadWithEnv(t, path, nil)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.BaseURL != "https://file.example/v1" || p.Reranker.BaseURL != "https://file.example/v1" {
		t.Errorf("base urls = %q / %q, want both from openai section", p.Embedder.BaseURL, p.Reranker.BaseURL)
	}
	if p.Embedder.APIKey != "sk-file" || p.Reranker.APIKey != "sk-file" {
		t.Error("api_key from openai section must apply to both providers")
	}
	if p.Embedder.Model != "file-embed" {
		t.Errorf("embedding model = %q", p.Embedder.Model)
	}
	if p.Reranker.Model != "file-rerank" {
		t.Errorf("reranking model = %q", p.Reranker.Model)
	}
	if p.Embedder.Dim != 768 {
		t.Errorf("dim = %d, want 768", p.Embedder.Dim)
	}
}

// 仅环境：OPENAI_* 覆盖默认值。
func TestLoadEnvOnly(t *testing.T) {
	cfg, err := loadWithEnv(t, "", map[string]string{
		"OPENAI_BASE_URL":        "https://env.example/v1",
		"OPENAI_API_KEY":         "sk-env",
		"OPENAI_EMBEDDING_MODEL": "env-embed",
		"OPENAI_RERANKING_MODEL": "env-rerank",
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.BaseURL != "https://env.example/v1" || p.Reranker.BaseURL != "https://env.example/v1" {
		t.Errorf("env base urls not applied: %q / %q", p.Embedder.BaseURL, p.Reranker.BaseURL)
	}
	if p.Embedder.APIKey != "sk-env" || p.Reranker.APIKey != "sk-env" {
		t.Error("env api key not applied to both providers")
	}
	if p.Embedder.Model != "env-embed" || p.Reranker.Model != "env-rerank" {
		t.Errorf("env models = %q / %q", p.Embedder.Model, p.Reranker.Model)
	}
}

// 逐字段混合：文件给一部分，环境补另一部分，未提供的仍是默认值。
func TestLoadFieldByFieldMix(t *testing.T) {
	path := writeConfig(t, `{"openai": {"embedding_model": "file-embed", "embedding_dim": 512}}`)
	cfg, err := loadWithEnv(t, path, map[string]string{
		"OPENAI_API_KEY": "sk-env-key",
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.Model != "file-embed" || p.Embedder.Dim != 512 {
		t.Errorf("file fields lost: model=%q dim=%d", p.Embedder.Model, p.Embedder.Dim)
	}
	if p.Reranker.Model != BuiltinRerankModel {
		t.Errorf("untouched field should keep default, got %q", p.Reranker.Model)
	}
	if p.Embedder.APIKey != "sk-env-key" || p.Reranker.APIKey != "sk-env-key" {
		t.Error("env key should reach both providers")
	}
}

// 环境层整体优于文件层：环境里的公共值覆盖文件里的专用值。
func TestLoadEnvCommonOverridesFileSpecific(t *testing.T) {
	path := writeConfig(t, `{"embedder": {"base_url": "https://file-embed/v1", "model": "file-embed"},
	                          "reranker": {"base_url": "https://file-rerank/v1", "model": "file-rerank"}}`)
	cfg, err := loadWithEnv(t, path, map[string]string{
		"OPENAI_BASE_URL":        "https://env/v1",
		"OPENAI_EMBEDDING_MODEL": "env-embed",
		"OPENAI_RERANKING_MODEL": "env-rerank",
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.BaseURL != "https://env/v1" || p.Reranker.BaseURL != "https://env/v1" {
		t.Errorf("env common base url must beat file per-provider: %q / %q",
			p.Embedder.BaseURL, p.Reranker.BaseURL)
	}
	if p.Embedder.Model != "env-embed" || p.Reranker.Model != "env-rerank" {
		t.Errorf("env common models must beat file per-provider: %q / %q", p.Embedder.Model, p.Reranker.Model)
	}
}

// 同层专用覆盖公共：文件里 embedder/reranker 段压过 openai 段；
// 环境里 SE_RAG_EMBED_* / SE_RAG_RERANK_* 压过 OPENAI_*。
func TestLoadSpecificOverridesCommon(t *testing.T) {
	path := writeConfig(t, `{
	  "openai": {"base_url": "https://common/v1", "api_key": "sk-common", "embedding_model": "common-embed", "reranking_model": "common-rerank", "embedding_dim": 1024},
	  "embedder": {"base_url": "https://embed/v1", "api_key": "sk-embed", "model": "embed-model", "dim": 512},
	  "reranker": {"base_url": "https://rerank/v1", "api_key": "sk-rerank", "model": "rerank-model"}
	}`)
	cfg, err := loadWithEnv(t, path, map[string]string{
		"OPENAI_API_KEY":        "sk-env-common",
		"SE_RAG_EMBED_BASE_URL": "https://env-embed/v1",
		"SE_RAG_RERANK_KEY":     "sk-env-rerank",
		"SE_RAG_EMBED_DIM":      "256",
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	// 文件层：专用压过公共
	if p.Embedder.BaseURL != "https://env-embed/v1" {
		t.Errorf("embed base url = %q, want env-specific", p.Embedder.BaseURL)
	}
	if p.Reranker.BaseURL != "https://rerank/v1" {
		t.Errorf("rerank base url = %q, want file-specific", p.Reranker.BaseURL)
	}
	if p.Embedder.Model != "embed-model" || p.Reranker.Model != "rerank-model" {
		t.Errorf("file models = %q / %q, want per-provider", p.Embedder.Model, p.Reranker.Model)
	}
	if p.Embedder.Dim != 256 {
		t.Errorf("env SE_RAG_EMBED_DIM should win, got %d", p.Embedder.Dim)
	}
	// 环境层：公共 OPENAI_API_KEY 覆盖文件两个专用 key，但同层 SE_RAG_RERANK_KEY 再覆盖它
	if p.Embedder.APIKey != "sk-env-common" {
		t.Errorf("embed key = %q, want env common (env layer beats file layer)", p.Embedder.APIKey)
	}
	if p.Reranker.APIKey != "sk-env-rerank" {
		t.Errorf("rerank key = %q, want env specific", p.Reranker.APIKey)
	}
}

// 空值语义：普通空字符串视为未提供；SE_RAG_FALLBACK_URL 显式空禁用备用网关；
// 文件 fallback_url 显式空同样禁用。
func TestLoadEmptyValueSemantics(t *testing.T) {
	path := writeConfig(t, `{"openai": {"api_key": ""}, "gateway": {"fallback_url": ""}}`)
	cfg, err := loadWithEnv(t, path, map[string]string{
		"OPENAI_EMBEDDING_MODEL": "", // 空 = 未提供
		"SE_RAG_GATEWAY_URL":     "", // 空 = 未提供
		"SE_RAG_FALLBACK_URL":    "", // 显式空 = 禁用备用
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.APIKey != "" {
		t.Error("empty api_key in file must not count as provided")
	}
	if p.Embedder.Model != BuiltinEmbeddingModel {
		t.Errorf("empty env model must not override default, got %q", p.Embedder.Model)
	}
	if cfg.Gateway.PrimaryURL != GatewayBaseURL {
		t.Errorf("empty SE_RAG_GATEWAY_URL must not override default, got %q", cfg.Gateway.PrimaryURL)
	}
	if got := cfg.Gateway.Chain(); len(got) != 1 || got[0] != GatewayBaseURL {
		t.Errorf("empty fallback must disable second hop, chain = %v", got)
	}
}

// ---- 文件读取错误 ----

// 显式指定但不存在 / 不可读 / 格式错 / 未知字段 → 明确报错。
func TestLoadFileErrors(t *testing.T) {
	t.Run("explicit missing", func(t *testing.T) {
		p := filepath.Join(t.TempDir(), "nope.json")
		if _, err := loadWithEnv(t, p, nil); err == nil {
			t.Fatal("explicitly specified missing file must be an error")
		}
	})
	t.Run("unreadable", func(t *testing.T) {
		dir := t.TempDir()
		p := filepath.Join(dir, "config.json")
		if err := os.WriteFile(p, []byte(`{}`), 0o000); err != nil {
			t.Fatal(err)
		}
		if os.Geteuid() == 0 {
			t.Skip("running as root: mode 000 is still readable")
		}
		if _, err := loadWithEnv(t, p, nil); err == nil {
			t.Fatal("unreadable file must be an error")
		}
	})
	t.Run("malformed json", func(t *testing.T) {
		if _, err := loadWithEnv(t, writeConfig(t, `{not json`), nil); err == nil {
			t.Fatal("malformed JSON must be an error")
		}
	})
	t.Run("unknown field", func(t *testing.T) {
		_, err := loadWithEnv(t, writeConfig(t, `{"openai": {"base_urls": "x"}}`), nil)
		if err == nil {
			t.Fatal("unknown field must be an error")
		}
		if !strings.Contains(err.Error(), "base_urls") {
			t.Errorf("error should name the unknown field, got %v", err)
		}
	})
	t.Run("wrong type", func(t *testing.T) {
		if _, err := loadWithEnv(t, writeConfig(t, `{"openai": {"embedding_dim": "big"}}`), nil); err == nil {
			t.Fatal("wrong type must be an error")
		}
	})
	t.Run("trailing data", func(t *testing.T) {
		if _, err := loadWithEnv(t, writeConfig(t, `{} {}`), nil); err == nil {
			t.Fatal("trailing data must be an error")
		}
	})
	t.Run("default path missing is fine", func(t *testing.T) {
		// 未显式指定 + 默认路径不存在 → 允许（用默认值）
		orig := defaultConfigPath
		defaultConfigPath = filepath.Join(t.TempDir(), "absent-config.json")
		t.Cleanup(func() { defaultConfigPath = orig })
		cfg, err := load(envMap(nil))
		if err != nil {
			t.Fatalf("missing default config file must be allowed, got %v", err)
		}
		if cfg.Gateway.PrimaryURL != GatewayBaseURL {
			t.Errorf("primary = %q, want default", cfg.Gateway.PrimaryURL)
		}
	})
	t.Run("default path present but malformed", func(t *testing.T) {
		// 默认路径存在但内容坏掉 → 报错（不能静默用默认值把用户的配置吞掉）
		dir := t.TempDir()
		p := filepath.Join(dir, "config.json")
		if err := os.WriteFile(p, []byte(`{broken`), 0o644); err != nil {
			t.Fatal(err)
		}
		orig := defaultConfigPath
		defaultConfigPath = p
		t.Cleanup(func() { defaultConfigPath = orig })
		if _, err := load(envMap(nil)); err == nil {
			t.Fatal("malformed file at the default path must be an error")
		}
	})
}

// ---- URL / 维度 / 时长 / 布尔 错误 ----

func TestLoadValidationErrors(t *testing.T) {
	cases := []struct {
		name string
		body string
		env  map[string]string
		want string
	}{
		{"bad gateway url", `{"gateway":{"primary_url":"not a url"}}`, nil, "primary_url"},
		{"bad scheme", `{"gateway":{"primary_url":"ftp://x/v1"}}`, nil, "scheme"},
		{"no host", `{"gateway":{"fallback_url":"https:///v1"}}`, nil, "host"},
		{"bad attempt timeout", `{"gateway":{"attempt_timeout":"soon"}}`, nil, "attempt_timeout"},
		{"negative attempt timeout", `{"gateway":{"attempt_timeout":"-1s"}}`, nil, "attempt_timeout"},
		{"zero failover budget", `{"gateway":{"failover_budget":"0s"}}`, nil, "failover_budget"},
		{"bad env duration", `{}`, map[string]string{"SE_RAG_GATEWAY_TIMEOUT": "6"}, "SE_RAG_GATEWAY_TIMEOUT"},
		{"bad env budget", `{}`, map[string]string{"SE_RAG_FAILOVER_BUDGET": "abc"}, "SE_RAG_FAILOVER_BUDGET"},
		{"bad env bool", `{}`, map[string]string{"SE_RAG_ALLOW_HTTP_FALLBACK": "maybe"}, "SE_RAG_ALLOW_HTTP_FALLBACK"},
		{"bad env dim", `{}`, map[string]string{"SE_RAG_EMBED_DIM": "wide"}, "SE_RAG_EMBED_DIM"},
		{"zero dim", `{"openai":{"embedding_dim":0}}`, nil, "dim"},
		{"negative dim", `{"openai":{"embedding_dim":-8}}`, nil, "dim"},
		{"reranker dim", `{"reranker":{"dim":1024}}`, nil, "dim"},
		{"bad user base url", `{"openai":{"api_key":"sk-x","base_url":"://bad"}}`, nil, "base_url"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, err := loadWithEnv(t, writeConfig(t, c.body), c.env)
			if err == nil {
				t.Fatalf("expected error mentioning %q", c.want)
			}
			if !strings.Contains(err.Error(), c.want) {
				t.Errorf("error should mention %q, got %v", c.want, err)
			}
		})
	}
}

// 较短总预算仍须可用：attempt_timeout 超过总预算时收紧到预算内，
// 而不是让第一跳一上来就吃掉全部预算（历史上 12s 明文预留 + 短预算会立刻过期）。
func TestLoadShortBudgetStaysUsable(t *testing.T) {
	cfg, err := loadWithEnv(t, writeConfig(t, `{"gateway":{"failover_budget":"2s"}}`), nil)
	if err != nil {
		t.Fatalf("short budget must be accepted, got %v", err)
	}
	if cfg.Gateway.FailoverBudget != 2*time.Second {
		t.Fatalf("budget = %v, want 2s", cfg.Gateway.FailoverBudget)
	}
	if cfg.Gateway.AttemptTimeout > cfg.Gateway.FailoverBudget {
		t.Errorf("attempt timeout %v exceeds budget %v", cfg.Gateway.AttemptTimeout, cfg.Gateway.FailoverBudget)
	}
}

// 内置 key（未配置自备 key）时，Provider.BaseURL 不生效也不参与校验：
// 一个拼错的 URL 不该让本来只用网关的组合无法启动。
// 但真配了自备 key 就必须校验——那是实际会用的地址。
func TestLoadBaseURLValidatedOnlyWhenUserKey(t *testing.T) {
	if _, err := loadWithEnv(t, writeConfig(t, `{"openai":{"base_url":"https://ok/v1"}}`), nil); err != nil {
		t.Fatalf("valid url without user key must load, got %v", err)
	}
	// 内置 key 模式下 base_url 不生效，非法值也不该阻断（避免误伤已有部署）
	if _, err := loadWithEnv(t, writeConfig(t, `{"openai":{"base_url":"nonsense"}}`), nil); err != nil {
		t.Fatalf("unused base_url must not block builtin-key setups, got %v", err)
	}
	if _, err := loadWithEnv(t, writeConfig(t, `{"openai":{"base_url":"nonsense","api_key":"sk-x"}}`), nil); err == nil {
		t.Fatal("user key + invalid base_url must be rejected")
	}
}

// ---- 诊断不泄露密钥 ----

// 任何加载错误都不得把密钥值写进错误信息——错误会被打到 stderr / 日志 / issue 里。
func TestLoadErrorsNeverLeakKeys(t *testing.T) {
	const secret = "sk-SUPER-SECRET-do-not-leak-1234567890"
	bodies := []string{
		// 合法 key + 非法时长
		`{"openai":{"api_key":"` + secret + `"},"gateway":{"attempt_timeout":"nope"}}`,
		// 合法 key + 未知字段
		`{"openai":{"api_key":"` + secret + `","bogus":1}}`,
		// 合法 key + 非法 URL
		`{"openai":{"api_key":"` + secret + `","base_url":"ftp://x/v1"}}`,
		// 合法 key + 非法维度
		`{"openai":{"api_key":"` + secret + `","embedding_dim":0}}`,
		// 合法 key + 语法错误
		`{"openai":{"api_key":"` + secret + `"`,
	}
	for i, body := range bodies {
		_, err := loadWithEnv(t, writeConfig(t, body), nil)
		if err == nil {
			t.Fatalf("case %d: expected an error", i)
		}
		if strings.Contains(err.Error(), secret) {
			t.Errorf("case %d: error leaks the key: %v", i, err)
		}
	}

	// 环境变量里的密钥同样不能泄露
	_, err := loadWithEnv(t, writeConfig(t, `{}`), map[string]string{
		"OPENAI_API_KEY":         secret,
		"SE_RAG_FAILOVER_BUDGET": "not-a-duration",
	})
	if err == nil {
		t.Fatal("expected an error for bad env duration")
	}
	if strings.Contains(err.Error(), secret) {
		t.Errorf("env error leaks the key: %v", err)
	}
}

// gateway 段：合法取值全部生效，时长按 Go duration 解析。
func TestLoadGatewaySection(t *testing.T) {
	cfg, err := loadWithEnv(t, writeConfig(t, `{"gateway":{
	  "primary_url":"https://cf.example/v1",
	  "fallback_url":"https://fc.example/v1",
	  "attempt_timeout":"2500ms",
	  "failover_budget":"9s",
	  "allow_http_fallback":false
	}}`), nil)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	g := cfg.Gateway
	if g.PrimaryURL != "https://cf.example/v1" || g.FallbackURL != "https://fc.example/v1" {
		t.Errorf("urls = %q / %q", g.PrimaryURL, g.FallbackURL)
	}
	if g.AttemptTimeout != 2500*time.Millisecond {
		t.Errorf("attempt timeout = %v", g.AttemptTimeout)
	}
	if g.FailoverBudget != 9*time.Second {
		t.Errorf("budget = %v", g.FailoverBudget)
	}
	if g.AllowHTTPFallback {
		t.Error("allow_http_fallback=false must be honoured")
	}
}

// 旧 SE_RAG_* 变量继续可用，且新增 SE_RAG_GATEWAY_TIMEOUT 生效。
func TestLoadLegacyAndNewEnv(t *testing.T) {
	cfg, err := loadWithEnv(t, "", map[string]string{
		"SE_RAG_EMBED_KEY":           "sk-embed",
		"SE_RAG_RERANK_KEY":          "sk-rerank",
		"SE_RAG_GATEWAY_URL":         "https://main2.example/v1",
		"SE_RAG_FALLBACK_URL":        "https://fb2.example/v1",
		"SE_RAG_GATEWAY_TIMEOUT":     "3s",
		"SE_RAG_FAILOVER_BUDGET":     "20s",
		"SE_RAG_ALLOW_HTTP_FALLBACK": "0",
	})
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.APIKey != "sk-embed" || p.Reranker.APIKey != "sk-rerank" {
		t.Errorf("legacy keys = %q / %q", p.Embedder.APIKey, p.Reranker.APIKey)
	}
	g := cfg.Gateway
	if g.PrimaryURL != "https://main2.example/v1" || g.FallbackURL != "https://fb2.example/v1" {
		t.Errorf("gateway overrides = %q / %q", g.PrimaryURL, g.FallbackURL)
	}
	if g.AttemptTimeout != 3*time.Second {
		t.Errorf("attempt timeout = %v, want 3s", g.AttemptTimeout)
	}
	if g.FailoverBudget != 20*time.Second || g.AllowHTTPFallback {
		t.Errorf("budget/fallback = %v / %v", g.FailoverBudget, g.AllowHTTPFallback)
	}
}

// 布尔值同时接受 0/1 与 true/false（保持 SE_RAG_ALLOW_HTTP_FALLBACK=0 的历史用法）。
func TestLoadBoolForms(t *testing.T) {
	for raw, want := range map[string]bool{"0": false, "1": true, "true": true, "false": false, "TRUE": true} {
		cfg, err := loadWithEnv(t, "", map[string]string{"SE_RAG_ALLOW_HTTP_FALLBACK": raw})
		if err != nil {
			t.Fatalf("%q: %v", raw, err)
		}
		if cfg.Gateway.AllowHTTPFallback != want {
			t.Errorf("%q → %v, want %v", raw, cfg.Gateway.AllowHTTPFallback, want)
		}
	}
}

// 仓库里发布的示例配置必须真的能被 Load 接受（否则文档又在宣传不存在的能力）。
// 示例里的 key 是占位符（sk-your-*），只验证结构与取值合法。
func TestShippedExampleConfigLoads(t *testing.T) {
	path := filepath.Join("..", "..", "example", "config.example.json")
	if _, err := os.Stat(path); err != nil {
		t.Skipf("example config not found: %v", err)
	}
	cfg, err := load(envMap(map[string]string{EnvConfigPath: path}))
	if err != nil {
		t.Fatalf("shipped example must load: %v", err)
	}
	p := cfg.Products[0]
	if p.Embedder.APIKey != "sk-your-embed-key" {
		t.Errorf("example embedder key = %q（专用段应覆盖 openai 段）", p.Embedder.APIKey)
	}
	if p.Reranker.APIKey != "sk-your-rerank-key" {
		t.Errorf("example reranker key = %q", p.Reranker.APIKey)
	}
	if p.Embedder.BaseURL != "https://embed-proxy.example.com/v1" {
		t.Errorf("example embedder base url = %q", p.Embedder.BaseURL)
	}
	if p.Embedder.Dim != 1024 {
		t.Errorf("example dim = %d", p.Embedder.Dim)
	}
	if cfg.Gateway.AttemptTimeout != 6*time.Second || cfg.Gateway.FailoverBudget != 18*time.Second {
		t.Errorf("example gateway timeouts = %v / %v", cfg.Gateway.AttemptTimeout, cfg.Gateway.FailoverBudget)
	}
	if !cfg.Gateway.AllowHTTPFallback {
		t.Error("example should keep the plain-HTTP fallback enabled")
	}
	// 默认链仍是 CF → FC
	if chain := cfg.Gateway.Chain(); len(chain) != 2 || chain[0] != GatewayBaseURL {
		t.Errorf("example gateway chain = %v", chain)
	}
}
