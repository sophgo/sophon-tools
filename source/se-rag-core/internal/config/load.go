package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// EnvConfigPath 指定配置文件的替代路径（容器内挂载、测试用）。未设置时读 DefaultConfigPath。
const EnvConfigPath = "SE_RAG_CONFIG"

// DefaultConfigPath 系统级配置文件路径。
const DefaultConfigPath = "/etc/se-rag-core/config.json"

// defaultConfigPath 实际使用的默认路径。提成变量只为让测试指向临时目录，
// 生产代码不修改它（没有 SE_RAG_CONFIG 时就是 /etc/se-rag-core/config.json）。
var defaultConfigPath = DefaultConfigPath

// envLookup 供测试注入的环境变量读取入口（生产固定 os.LookupEnv）。
type envLookup func(key string) (string, bool)

// Load 加载最终配置：默认值 ← 文件 ← 环境变量，逐字段合并，环境层整体优于文件层。
//
// 文件来源：$SE_RAG_CONFIG 指定的路径；未指定时用 /etc/se-rag-core/config.json。
// 默认文件不存在视为「没有文件」，直接用默认值；显式指定（或默认路径存在但不可读/格式错误）
// 一律返回错误。错误信息只提字段名与路径，永不包含密钥值。
//
// Load 不修改进程环境、不在 init 阶段执行，也不联网；纯默认构造请用 DefaultConfig。
func Load() (Config, error) {
	return load(os.LookupEnv)
}

func load(lookup envLookup) (Config, error) {
	cfg := DefaultConfig()

	explicit := false
	path := defaultConfigPath
	if v, ok := lookup(EnvConfigPath); ok && strings.TrimSpace(v) != "" {
		path = strings.TrimSpace(v)
		explicit = true
	}
	fileCfg, err := readConfigFile(path, explicit)
	if err != nil {
		return Config{}, err
	}
	if fileCfg != nil {
		if err := applyFile(&cfg, *fileCfg); err != nil {
			return Config{}, fmt.Errorf("config file %s: %w", path, err)
		}
	}
	if err := applyEnv(&cfg, lookup); err != nil {
		return Config{}, fmt.Errorf("environment: %w", err)
	}
	if err := validate(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// fileOpenAI openai 段：embedding 与 rerank 共用的默认值。
type fileOpenAI struct {
	BaseURL   *string `json:"base_url"`
	APIKey    *string `json:"api_key"`
	EmbedMdl  *string `json:"embedding_model"`
	RerankMdl *string `json:"reranking_model"`
	EmbedDim  *int    `json:"embedding_dim"`
}

// fileProvider embedder / reranker 段：各自覆盖 openai 段的公共值。
type fileProvider struct {
	BaseURL *string `json:"base_url"`
	APIKey  *string `json:"api_key"`
	Model   *string `json:"model"`
	Dim     *int    `json:"dim"`
}

// fileGateway gateway 段：内置网关故障转移链。时长为 Go duration 字符串（如 "6s"）。
type fileGateway struct {
	PrimaryURL        *string `json:"primary_url"`
	FallbackURL       *string `json:"fallback_url"`
	AttemptTimeout    *string `json:"attempt_timeout"`
	FailoverBudget    *string `json:"failover_budget"`
	AllowHTTPFallback *bool   `json:"allow_http_fallback"`
}

type fileConfig struct {
	OpenAI   *fileOpenAI   `json:"openai"`
	Embedder *fileProvider `json:"embedder"`
	Reranker *fileProvider `json:"reranker"`
	Gateway  *fileGateway  `json:"gateway"`
}

// readConfigFile 读取并解析配置文件。
//
// 返回 (nil, nil) 表示「没有配置文件，按默认值走」：仅当未显式指定路径、且默认路径不存在时。
// 其余异常都返回错误——显式指定的文件缺失/不可读是一种配置错误，静默回落默认值
// 会让用户以为自备 key 生效了却仍在用内置 key。
func readConfigFile(path string, explicit bool) (*fileConfig, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		if !explicit && errors.Is(err, fs.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("read config file %s: %w", path, err)
	}
	var fc fileConfig
	dec := json.NewDecoder(strings.NewReader(string(b)))
	// 未知字段报错：拼错的键（如 base_urls）静默忽略会让人以为配置生效了。
	dec.DisallowUnknownFields()
	if err := dec.Decode(&fc); err != nil {
		return nil, fmt.Errorf("parse config file %s: %w", path, err)
	}
	// 拒绝文件末尾的多余内容（如两段 JSON 拼接）。
	if dec.More() {
		return nil, fmt.Errorf("parse config file %s: unexpected trailing data", path)
	}
	return &fc, nil
}

// applyFile 把文件配置合并进 cfg：先 openai 公共值，再 embedder/reranker 专用值。
// 空字符串视为「未提供」，沿用下一层（默认值或已合并的值）。
func applyFile(cfg *Config, fc fileConfig) error {
	p := &cfg.Products[0]
	if o := fc.OpenAI; o != nil {
		if err := setStr(&p.Embedder.BaseURL, o.BaseURL); err != nil {
			return err
		}
		if err := setStr(&p.Reranker.BaseURL, o.BaseURL); err != nil {
			return err
		}
		if err := setStr(&p.Embedder.APIKey, o.APIKey); err != nil {
			return err
		}
		if err := setStr(&p.Reranker.APIKey, o.APIKey); err != nil {
			return err
		}
		if err := setStr(&p.Embedder.Model, o.EmbedMdl); err != nil {
			return err
		}
		if err := setStr(&p.Reranker.Model, o.RerankMdl); err != nil {
			return err
		}
		if err := setInt(&p.Embedder.Dim, o.EmbedDim); err != nil {
			return err
		}
	}
	if e := fc.Embedder; e != nil {
		if err := applyFileProvider(&p.Embedder, e); err != nil {
			return fmt.Errorf("embedder: %w", err)
		}
	}
	if r := fc.Reranker; r != nil {
		if err := applyFileProvider(&p.Reranker, r); err != nil {
			return fmt.Errorf("reranker: %w", err)
		}
		// reranker 没有维度概念：显式写了 dim 属于配置错误，不能默默忽略。
		if r.Dim != nil {
			return errors.New("reranker: dim is not applicable")
		}
	}
	if g := fc.Gateway; g != nil {
		if err := applyFileGateway(&cfg.Gateway, g); err != nil {
			return fmt.Errorf("gateway: %w", err)
		}
	}
	return nil
}

func applyFileProvider(p *Provider, f *fileProvider) error {
	if err := setStr(&p.BaseURL, f.BaseURL); err != nil {
		return err
	}
	if err := setStr(&p.APIKey, f.APIKey); err != nil {
		return err
	}
	if err := setStr(&p.Model, f.Model); err != nil {
		return err
	}
	return setInt(&p.Dim, f.Dim)
}

func applyFileGateway(g *Gateway, f *fileGateway) error {
	// fallback_url 的显式空串是合法语义（禁用备用网关），与其它字段的「空=未提供」不同，
	// 因此这里按指针存在与否判断，不看值是否为空。
	if f.PrimaryURL != nil {
		v := strings.TrimSpace(*f.PrimaryURL)
		if v != "" {
			g.PrimaryURL = v
		}
	}
	if f.FallbackURL != nil {
		g.FallbackURL = strings.TrimSpace(*f.FallbackURL)
	}
	if f.AttemptTimeout != nil {
		d, err := parsePositiveDuration("gateway.attempt_timeout", *f.AttemptTimeout)
		if err != nil {
			return err
		}
		g.AttemptTimeout = d
	}
	if f.FailoverBudget != nil {
		d, err := parsePositiveDuration("gateway.failover_budget", *f.FailoverBudget)
		if err != nil {
			return err
		}
		g.FailoverBudget = d
	}
	if f.AllowHTTPFallback != nil {
		g.AllowHTTPFallback = *f.AllowHTTPFallback
	}
	return nil
}

// applyEnv 环境变量层：整体优先于文件层，同层内专用变量优先于公共变量。
//
// 普通空字符串视为未提供（与 shell 里 `export X=` 的习惯一致）；唯一例外是
// SE_RAG_FALLBACK_URL 的显式空串——它保留「禁用备用网关」的既有语义。
func applyEnv(cfg *Config, lookup envLookup) error {
	p := &cfg.Products[0]
	get := func(k string) (string, bool) {
		v, ok := lookup(k)
		if !ok {
			return "", false
		}
		v = strings.TrimSpace(v)
		if v == "" {
			return "", false
		}
		return v, true
	}

	// 公共 openai 变量，先落到两个 provider。
	if v, ok := get("OPENAI_BASE_URL"); ok {
		p.Embedder.BaseURL = v
		p.Reranker.BaseURL = v
	}
	if v, ok := get("OPENAI_API_KEY"); ok {
		p.Embedder.APIKey = v
		p.Reranker.APIKey = v
	}
	if v, ok := get("OPENAI_EMBEDDING_MODEL"); ok {
		p.Embedder.Model = v
	}
	if v, ok := get("OPENAI_RERANKING_MODEL"); ok {
		p.Reranker.Model = v
	}

	// 专用变量，覆盖同层的公共值。
	if v, ok := get("SE_RAG_EMBED_BASE_URL"); ok {
		p.Embedder.BaseURL = v
	}
	if v, ok := get("SE_RAG_RERANK_BASE_URL"); ok {
		p.Reranker.BaseURL = v
	}
	if v, ok := get("SE_RAG_EMBED_KEY"); ok {
		p.Embedder.APIKey = v
	}
	if v, ok := get("SE_RAG_RERANK_KEY"); ok {
		p.Reranker.APIKey = v
	}
	if v, ok := get("SE_RAG_EMBED_MODEL"); ok {
		p.Embedder.Model = v
	}
	if v, ok := get("SE_RAG_RERANK_MODEL"); ok {
		p.Reranker.Model = v
	}
	if v, ok := get("SE_RAG_EMBED_DIM"); ok {
		n, err := strconv.Atoi(v)
		if err != nil {
			return fmt.Errorf("SE_RAG_EMBED_DIM: %q is not an integer", v)
		}
		p.Embedder.Dim = n
	}

	// 内置网关链。
	if v, ok := get("SE_RAG_GATEWAY_URL"); ok {
		cfg.Gateway.PrimaryURL = v
	}
	if v, ok := lookup("SE_RAG_FALLBACK_URL"); ok {
		// 显式空串 = 禁用备用网关（既有语义，保持不变）。
		cfg.Gateway.FallbackURL = strings.TrimSpace(v)
	}
	if v, ok := get("SE_RAG_GATEWAY_TIMEOUT"); ok {
		d, err := parsePositiveDuration("SE_RAG_GATEWAY_TIMEOUT", v)
		if err != nil {
			return err
		}
		cfg.Gateway.AttemptTimeout = d
	}
	if v, ok := get("SE_RAG_FAILOVER_BUDGET"); ok {
		d, err := parsePositiveDuration("SE_RAG_FAILOVER_BUDGET", v)
		if err != nil {
			return err
		}
		cfg.Gateway.FailoverBudget = d
	}
	if v, ok := get("SE_RAG_ALLOW_HTTP_FALLBACK"); ok {
		b, err := parseBool("SE_RAG_ALLOW_HTTP_FALLBACK", v)
		if err != nil {
			return err
		}
		cfg.Gateway.AllowHTTPFallback = b
	}
	return nil
}

// validate 校验最终配置：URL 形态、维度、时长。任一不合法都明确报错（不含密钥值）。
//
// 自备 key 的 URL 只有在该 provider 真的自备 key 时才参与校验——内置 key 的请求
// 只走网关链，此时 Provider.BaseURL 不生效，不该因一个用不上的字段拒绝启动。
func validate(cfg *Config) error {
	g := &cfg.Gateway
	if err := validateURL("gateway.primary_url", g.PrimaryURL); err != nil {
		return err
	}
	if g.FallbackURL != "" {
		if err := validateURL("gateway.fallback_url", g.FallbackURL); err != nil {
			return err
		}
	}
	if g.AttemptTimeout <= 0 {
		return errors.New("gateway.attempt_timeout must be positive")
	}
	if g.FailoverBudget <= 0 {
		return errors.New("gateway.failover_budget must be positive")
	}
	// 单次尝试上限超过总预算时没有意义：那样第一跳永远会吃光预算，
	// 第二跳形同虚设。收紧到预算内而不是报错——用户可能只改了其中一个值。
	if g.AttemptTimeout > g.FailoverBudget {
		g.AttemptTimeout = g.FailoverBudget
	}

	p := &cfg.Products[0]
	if p.Embedder.Type == "" {
		return errors.New("embedder type is empty")
	}
	if p.Reranker.Type == "" {
		return errors.New("reranker type is empty")
	}
	if strings.TrimSpace(p.Embedder.Model) == "" {
		return errors.New("embedder model is empty")
	}
	if strings.TrimSpace(p.Reranker.Model) == "" {
		return errors.New("reranker model is empty")
	}
	// 维度：内置 key 时由配置决定（默认 1024）；自备 key 允许不写（0 = 未知，
	// 由实际返回向量定维度），但写了就必须为正。
	if p.Embedder.Dim <= 0 {
		return fmt.Errorf("embedder dim must be positive, got %d", p.Embedder.Dim)
	}
	if p.Embedder.APIKey != "" {
		if err := validateURL("embedder.base_url", p.Embedder.BaseURL); err != nil {
			return err
		}
	}
	if p.Reranker.APIKey != "" {
		if err := validateURL("reranker.base_url", p.Reranker.BaseURL); err != nil {
			return err
		}
	}
	return nil
}

// validateURL 校验绝对 http(s) URL；空串视为合法（表示「用默认地址」）。
func validateURL(field, raw string) error {
	if raw == "" {
		return nil
	}
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("%s: invalid URL: %w", field, err)
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return fmt.Errorf("%s: scheme must be http or https, got %q", field, u.Scheme)
	}
	if u.Host == "" {
		return fmt.Errorf("%s: URL has no host", field)
	}
	return nil
}

// parsePositiveDuration 解析 Go duration 字符串，要求 > 0。
func parsePositiveDuration(field, raw string) (time.Duration, error) {
	d, err := time.ParseDuration(strings.TrimSpace(raw))
	if err != nil {
		return 0, fmt.Errorf("%s: %q is not a Go duration (e.g. \"6s\")", field, raw)
	}
	if d <= 0 {
		return 0, fmt.Errorf("%s: must be positive, got %q", field, raw)
	}
	return d, nil
}

// parseBool 解析布尔值：接受 Go 的 ParseBool 集合，额外容忍 0/1。
func parseBool(field, raw string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "0":
		return false, nil
	case "1":
		return true, nil
	}
	b, err := strconv.ParseBool(strings.TrimSpace(raw))
	if err != nil {
		return false, fmt.Errorf("%s: %q is not a boolean (true/false/1/0)", field, raw)
	}
	return b, nil
}

// setStr 指针字段合并：nil 或空白视为「未提供」。
func setStr(dst *string, src *string) error {
	if src == nil {
		return nil
	}
	v := strings.TrimSpace(*src)
	if v == "" {
		return nil
	}
	*dst = v
	return nil
}

// setInt 指针字段合并：nil 视为「未提供」，0 视为需要报错的显式取值。
func setInt(dst *int, src *int) error {
	if src == nil {
		return nil
	}
	*dst = *src
	return nil
}
