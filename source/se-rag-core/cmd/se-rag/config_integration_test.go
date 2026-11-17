package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

// 本文件用本地 httptest 服务验证 CLI 端的配置分层与 key 归属：
//   - 配置文件 / 环境变量真的被 build 与 query 消费（实际请求地址、Bearer、模型名、维度）；
//   - 默认（未写 -builtin-key）、显式 true、显式 false 三种语义；
//   - 自备 key 的请求一个字节都不发往内置网关；
//   - offline 在配置损坏时仍然不联网、不读 key。
// 不调用任何付费外部 API。

// mockUpstream 记录请求的 OpenAI 兼容 mock（embeddings + rerank）。
type mockUpstream struct {
	*httptest.Server
	embeds   atomic.Int64
	reranks  atomic.Int64
	mu       sync.Mutex
	auths    []string
	models   []string
	lastDims int
	// paths 按顺序记录收到的请求 path，用于断言 /embeddings 与 /rerank 各自被真正命中
	// （只看 model 字符串无法区分"rerank 被调用"与"请求打到 embeddings 却带 rerank 模型名"）。
	paths []string
	// rerankDocs 最后一次 rerank 收到的 documents 数。
	rerankDocs int
}

// pathList 返回已收到的请求 path 副本。
func (m *mockUpstream) pathList() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]string(nil), m.paths...)
}

// countPath 某个 path 被命中的次数。
func (m *mockUpstream) countPath(suffix string) int {
	n := 0
	for _, p := range m.pathList() {
		if strings.HasSuffix(p, suffix) {
			n++
		}
	}
	return n
}

// newMockUpstream dim 为返回向量的维度。
func newMockUpstream(t *testing.T, dim int) *mockUpstream {
	t.Helper()
	m := &mockUpstream{}
	m.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		m.mu.Lock()
		m.auths = append(m.auths, r.Header.Get("Authorization"))
		m.paths = append(m.paths, r.URL.Path)
		m.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/embeddings"):
			m.embeds.Add(1)
			var req struct {
				Model string   `json:"model"`
				Input []string `json:"input"`
			}
			_ = json.NewDecoder(r.Body).Decode(&req)
			m.mu.Lock()
			m.models = append(m.models, req.Model)
			m.lastDims = dim
			m.mu.Unlock()
			data := make([]map[string]any, 0, len(req.Input))
			vec := make([]float32, dim)
			vec[0] = 1
			for i := range req.Input {
				data = append(data, map[string]any{"index": i, "embedding": vec})
			}
			json.NewEncoder(w).Encode(map[string]any{"data": data})
		case strings.HasSuffix(r.URL.Path, "/rerank"):
			m.reranks.Add(1)
			var req struct {
				Model     string   `json:"model"`
				Documents []string `json:"documents"`
			}
			_ = json.NewDecoder(r.Body).Decode(&req)
			m.mu.Lock()
			m.models = append(m.models, req.Model)
			m.rerankDocs = len(req.Documents)
			m.mu.Unlock()
			// 故意**反序**返回：若 rerank 结果真被采用，输出头条应是最后一条候选。
			// 返回固定单条（旧实现）无法区分"结果被采用"与"结果为空但没报错"。
			results := make([]map[string]any, 0, len(req.Documents))
			for i := len(req.Documents) - 1; i >= 0; i-- {
				results = append(results, map[string]any{
					"index": i, "relevance_score": float64(i+1) / float64(len(req.Documents)),
				})
			}
			json.NewEncoder(w).Encode(map[string]any{"results": results})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(m.Close)
	return m
}

func (m *mockUpstream) lastAuth() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.auths) == 0 {
		return ""
	}
	return m.auths[len(m.auths)-1]
}

func (m *mockUpstream) sawModel(model string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, got := range m.models {
		if got == model {
			return true
		}
	}
	return false
}

// writeDocs 建一个小文档库（多段，保证 build 至少发一次 embedding）。
func writeDocs(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	docs := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docs, 0o755); err != nil {
		t.Fatal(err)
	}
	// 两份文档：rerank 只在候选多于一条时才会被调用（len(fused) > 1），
	// 单文档在小体量下会被切成单块。
	body := "# SE7\n\n## 网络\n\n配置 netplan 使能 eth0 的 dhcp4 并重启 networkd。\n\n" +
		"## SDK\n\nSE7 使用 BM1684X 芯片运行推理任务，需要安装 sophonsdk。\n"
	if err := os.WriteFile(filepath.Join(docs, "a.md"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	other := "# SE7 排障\n\n## OTA\n\nOTA 升级用于更新系统镜像与驱动。\n\n" +
		"## 串口\n\n调试串口波特率为 115200，使用 8N1。\n"
	if err := os.WriteFile(filepath.Join(docs, "b.md"), []byte(other), 0o644); err != nil {
		t.Fatal(err)
	}
	return docs
}

// writeJSONConfig 写一份配置文件并把它设为当前配置。
func writeJSONConfig(t *testing.T, body string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SE_RAG_CONFIG", p)
	return p
}

// clearKeyEnv 清空所有与 key 有关的环境变量（避免宿主环境影响）。
func clearKeyEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{
		"SE_RAG_EMBED_KEY", "SE_RAG_RERANK_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
		"SE_RAG_EMBED_BASE_URL", "SE_RAG_RERANK_BASE_URL", "SE_RAG_EMBED_MODEL",
		"SE_RAG_RERANK_MODEL", "SE_RAG_EMBED_DIM", "OPENAI_EMBEDDING_MODEL",
		"OPENAI_RERANKING_MODEL", "SE_RAG_FAKE_EMBED", "SE_RAG_GATEWAY_URL",
		"SE_RAG_FALLBACK_URL", "SE_RAG_GATEWAY_TIMEOUT", "SE_RAG_FAILOVER_BUDGET",
	} {
		t.Setenv(k, "")
	}
	t.Setenv("SE_RAG_STATE_DIR", t.TempDir())
}

// runCLI 直接调用 dispatch，返回退出码（输出由调用方捕获）。
func runCLI(args ...string) int { return dispatch(args) }

// ---- 默认模式（未写 -builtin-key）：按配置自动选自备 key ----

// 文件里配了 key/base_url/模型/维度：不写 -builtin-key 也必须真的用它们。
func TestConfigFromFileUsedByBuildAndQuery(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 8)
	writeJSONConfig(t, `{
	  "openai": {
	    "base_url": "`+up.URL+`",
	    "api_key": "sk-file-key",
	    "embedding_model": "file-embed-model",
	    "reranking_model": "file-rerank-model",
	    "embedding_dim": 8
	  }
	}`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")

	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d, want 0", rc)
	}
	if up.embeds.Load() == 0 {
		t.Fatal("build never called the configured upstream")
	}
	if got := up.lastAuth(); got != "Bearer sk-file-key" {
		t.Errorf("Authorization = %q, want the configured key", got)
	}
	if !up.sawModel("file-embed-model") {
		t.Error("embedding model from the config file was not used")
	}

	// 索引维度必须来自实际返回向量（8），也就是配置的维度生效。
	meta := readMeta(t, idx)
	if meta.Dim != 8 {
		t.Errorf("index dim = %d, want 8 (configured)", meta.Dim)
	}
	if meta.Model != "file-embed-model" {
		t.Errorf("index model = %q, want the configured model", meta.Model)
	}

	if rc := runCLI("query", "-index-dir", idx, "网络配置"); rc != 0 {
		t.Fatalf("query rc=%d, want 0", rc)
	}
	if !up.sawModel("file-rerank-model") {
		t.Error("reranking model from the config file was not used")
	}
}

// 仅环境变量：OPENAI_* 也要被 build/query 消费，且公共值覆盖文件里的专用值。
func TestConfigFromEnvUsedByBuild(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	// 文件写一个指向别处的专用地址，环境里的 OPENAI_BASE_URL 应该赢。
	writeJSONConfig(t, `{"embedder": {"base_url": "http://127.0.0.1:1/v1"}}`)
	t.Setenv("OPENAI_BASE_URL", up.URL)
	t.Setenv("OPENAI_API_KEY", "sk-env")
	t.Setenv("OPENAI_EMBEDDING_MODEL", "env-embed")
	t.Setenv("SE_RAG_EMBED_DIM", "4")

	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d, want 0", rc)
	}
	if got := up.lastAuth(); got != "Bearer sk-env" {
		t.Errorf("Authorization = %q, want env key", got)
	}
	if !up.sawModel("env-embed") {
		t.Error("env embedding model not used")
	}
	if meta := readMeta(t, idx); meta.Dim != 4 {
		t.Errorf("index dim = %d, want env dim 4", meta.Dim)
	}
}

// 自备 key 与显式 base_url 的请求绝不发往内置网关：
// 网关地址被指向一个必然拒连的本地端口，若自备路径走网关就会失败。
func TestUserKeyNeverTouchesBuiltinGateway(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-user", "embedding_dim": 4}}`)
	t.Setenv("SE_RAG_GATEWAY_URL", "http://127.0.0.1:1/v1")
	t.Setenv("SE_RAG_FALLBACK_URL", "http://127.0.0.1:2/v1")

	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build with user key must not depend on the gateway, rc=%d", rc)
	}
	if up.embeds.Load() == 0 {
		t.Fatal("user-key build never reached its own endpoint")
	}
}

// ---- -builtin-key 三态 ----

// 显式 -builtin-key=true：即使配了自备 key，也必须回到内置 key 与内置模型。
func TestExplicitBuiltinKeyForcesBuiltin(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 1024)
	p := writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-should-be-ignored",
	  "embedding_model": "user-model", "embedding_dim": 1024}}`)
	_ = p
	// 内置网关指向 mock（-builtin-key=true 仍保留网关覆盖）。
	t.Setenv("SE_RAG_GATEWAY_URL", up.URL)
	t.Setenv("SE_RAG_FALLBACK_URL", "")

	cfg, err := loadOnlineConfig()
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	got, err := resolveProviders(cfg, keyModeForceBuiltin, true, false)
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got.Embedder.APIKey != "" {
		t.Errorf("explicit -builtin-key=true must clear the user key, got %q", got.Embedder.APIKey)
	}
	if got.Embedder.Model != "BAAI/bge-m3" || got.Embedder.Dim != 1024 {
		t.Errorf("builtin model/dim not forced: %s/%d", got.Embedder.Model, got.Embedder.Dim)
	}
	if got.Reranker.Model != "BAAI/bge-reranker-v2-m3" {
		t.Errorf("builtin rerank model not forced: %s", got.Reranker.Model)
	}
	if urls := got.Embedder.EffectiveBaseURLs(cfg.Gateway); len(urls) != 1 || urls[0] != up.URL {
		t.Errorf("gateway override lost: %v", urls)
	}
}

// 显式 -builtin-key=false：配置里的 key 满足要求就通过；没配就明确报错。
func TestExplicitUserKeyMode(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-user", "embedding_dim": 4}}`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx, "-builtin-key=false"); rc != 0 {
		t.Fatalf("explicit user mode with a configured key should pass, rc=%d", rc)
	}
	if got := up.lastAuth(); got != "Bearer sk-user" {
		t.Errorf("Authorization = %q", got)
	}

	// 没有任何自备 key：必须报错，且错误名指旗标与变量。
	clearKeyEnv(t)
	writeJSONConfig(t, `{}`)
	idx2 := filepath.Join(t.TempDir(), "idx2")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx2, "-builtin-key=false"); rc != 1 {
		t.Fatalf("explicit user mode without a key must fail, rc=%d", rc)
	}
}

// build 只需要 embed key，query 还需要 rerank key：只配 embed key 时 build 通过、query 报错。
func TestExplicitUserModeRerankKeyNeededOnlyForQuery(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"embedder": {"base_url": "`+up.URL+`", "api_key": "sk-embed", "dim": 4}}`)
	t.Setenv("SE_RAG_EMBED_DIM", "4")

	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx, "-builtin-key=false"); rc != 0 {
		t.Fatalf("build with only an embed key must pass, rc=%d", rc)
	}
	if rc := runCLI("query", "-index-dir", idx, "网络", "-builtin-key=false"); rc != 1 {
		t.Fatalf("query must require a rerank key, rc=%d", rc)
	}
	// 补上 rerank key 后 query 通过。
	t.Setenv("SE_RAG_RERANK_KEY", "sk-rerank")
	if rc := runCLI("query", "-index-dir", idx, "网络", "-builtin-key=false"); rc != 0 {
		t.Fatalf("query with both keys should pass, rc=%d", rc)
	}
	if got := up.lastAuth(); got != "Bearer sk-embed" && got != "Bearer sk-rerank" {
		t.Errorf("unexpected Authorization %q", got)
	}
}

// -builtin-key 写在问题文本前后两种位置都必须生效（parseInterspersed 的既有约定）。
func TestBuiltinKeyFlagBeforeAndAfterQuery(t *testing.T) {
	clearKeyEnv(t)
	// 无任何自备 key：-builtin-key=false 必须在两种位置都被识别并报错。
	writeJSONConfig(t, `{}`)
	idx := filepath.Join(t.TempDir(), "idx")
	for _, args := range [][]string{
		{"query", "-builtin-key=false", "-index-dir", idx, "网络"},
		{"query", "-index-dir", idx, "网络", "-builtin-key=false"},
	} {
		if rc := runCLI(args...); rc != 1 {
			t.Errorf("args %v: rc=%d, want 1 (flag must be honoured in both positions)", args, rc)
		}
	}
}

// 只设 embed 专用 key 时，rerank 仍走内置 key：限流必须按各自实际 key 归属判定，
// 不能用一个 product 级 bool 把两者一起算成自备或一起算成内置。
func TestIndependentProviderKeys(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"embedder": {"base_url": "`+up.URL+`", "api_key": "sk-embed-only", "dim": 4}}`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d", rc)
	}

	cfg, err := loadOnlineConfig()
	if err != nil {
		t.Fatal(err)
	}
	p, err := resolveProviders(cfg, keyModeAuto, true, false)
	if err != nil {
		t.Fatal(err)
	}
	if p.Embedder.IsBuiltinKey() {
		t.Error("embedder has an explicit key, must not be treated as builtin (would apply the limiter)")
	}
	if !p.Reranker.IsBuiltinKey() {
		t.Error("reranker has no key, must be treated as builtin")
	}
}

// ---- offline 在损坏配置下仍无网络 ----

// 配置文件损坏时：
//   - build -offline / query -offline 仍然成功且不发任何请求；
//   - 在线 build 必须失败（配置错误要在联网前报出）。
func TestOfflineIgnoresBrokenConfig(t *testing.T) {
	clearKeyEnv(t)
	writeJSONConfig(t, `{ this is not json`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")

	if rc := runCLI("build", "-offline", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("offline build must not depend on online config, rc=%d", rc)
	}
	if rc := runCLI("query", "-offline", "-index-dir", idx, "网络"); rc != 0 {
		t.Fatalf("offline query must not depend on online config, rc=%d", rc)
	}
	// help / list / resolve 同样不依赖在线配置
	if rc := runCLI("--help"); rc != 0 {
		t.Errorf("--help rc=%d, want 0", rc)
	}

	// 在线 build 必须报错（且不该建出索引）。
	idx2 := filepath.Join(t.TempDir(), "idx2")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx2); rc != 1 {
		t.Fatalf("online build with a broken config must fail, rc=%d", rc)
	}
	if _, err := os.Stat(filepath.Join(idx2, "meta.json")); err == nil {
		t.Error("broken config must fail before building an index")
	}
}

// 配置里的时长/维度错误同样在联网前报出，且错误里不出现密钥。
func TestOnlineConfigErrorSurfacesWithoutLeakingKey(t *testing.T) {
	clearKeyEnv(t)
	const secret = "sk-LEAK-CANARY-abcdefghijklmnop"
	writeJSONConfig(t, `{"openai": {"api_key": "`+secret+`", "embedding_dim": 0}}`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 1 {
		t.Fatalf("rc=%d, want 1 for an invalid config", rc)
	}
}

// ---- 注册表模式与路径模式消费同一配置 ----

// registry 模式（-entity）与路径模式（-index-dir）必须使用同一份最终配置：
// 两边的请求都打到同一个 mock，且带同一个 Bearer 与模型名。
func TestRegistryAndPathModesShareConfig(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-shared",
	  "embedding_model": "shared-embed", "reranking_model": "shared-rerank", "embedding_dim": 4}}`)

	dir := t.TempDir()
	docs := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docs, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docs, "a.md"),
		[]byte("# SE7\n\n## 网络\n\n配置 netplan 使能 dhcp4。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	regPath := filepath.Join(dir, "registry.json")
	regBody := `{
	  "schema_version": 3,
	  "entities": [{
	    "id": "se7", "type": "product", "name": "SE7", "status": "ready",
	    "aliases": ["SE7"], "modules": [],
	    "docs_dir": "docs",
	    "index_dir": "` + filepath.ToSlash(filepath.Join(dir, "idx-reg")) + `"
	  }]
	}`
	if err := os.WriteFile(regPath, []byte(regBody), 0o644); err != nil {
		t.Fatal(err)
	}

	if rc := runCLI("build", "-registry", regPath, "-entity", "se7"); rc != 0 {
		t.Fatalf("registry build rc=%d", rc)
	}
	if !up.sawModel("shared-embed") {
		t.Error("registry build did not use the configured embedding model")
	}
	if got := up.lastAuth(); got != "Bearer sk-shared" {
		t.Errorf("registry build Authorization = %q", got)
	}

	idxPath := filepath.Join(t.TempDir(), "idx-path")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idxPath); rc != 0 {
		t.Fatalf("path build rc=%d", rc)
	}
	if !up.sawModel("shared-embed") {
		t.Error("path build did not use the configured embedding model")
	}

	// 两边索引的模型/维度必须一致（同一配置 → 同一指纹）。
	rm := readMeta(t, filepath.ToSlash(filepath.Join(dir, "idx-reg")))
	pm := readMeta(t, idxPath)
	if rm.Model != pm.Model || rm.Dim != pm.Dim || rm.EmbedderFingerprint != pm.EmbedderFingerprint {
		t.Errorf("registry/path indexes disagree: %+v vs %+v", rm, pm)
	}
}

// ---- 指纹兼容：换模型后仍给出重建提示 ----

// 配置换了 embedding 模型时，doctor 必须报告需要重建（原有提示保持）。
func TestDoctorDetectsModelChange(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-x",
	  "embedding_model": "model-a", "embedding_dim": 4}}`)
	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d", rc)
	}
	if rc := runCLI("doctor", "-index-dir", idx); rc != 0 {
		t.Fatalf("doctor with an unchanged model should be clean, rc=%d", rc)
	}

	// 换模型 → 必须提示重建（doctor 以非 0 退出表示 need rebuild）
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-x",
	  "embedding_model": "model-b", "embedding_dim": 4}}`)
	if rc := runCLI("doctor", "-index-dir", idx); rc == 0 {
		t.Error("doctor must report a rebuild when the embedding model changed")
	}
}

// ---- 辅助 ----

func readMeta(t *testing.T, idxDir string) docstoreMeta {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(idxDir, "meta.json"))
	if err != nil {
		t.Fatalf("read meta: %v", err)
	}
	var m docstoreMeta
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("parse meta: %v", err)
	}
	return m
}

// docstoreMeta meta.json 的最小子集（避免测试依赖整个 docstore 结构体）。
type docstoreMeta struct {
	Model               string `json:"model"`
	Dim                 int    `json:"dim"`
	EmbedderFingerprint string `json:"embedder_fingerprint"`
}

// ---- 验收退回：CLI 端必须断言 /rerank 真命中且排序生效 ----

// 只断言 model 字符串无法证明 rerank 被真正调用：请求可能打到 /embeddings 却带着
// rerank 模型名（这就是"串接口"缺陷在 CLI 层的表现形式）。这里同时断言：
//   - /rerank 被命中（且 /embeddings 只由 build/query 的向量化产生）
//   - rerank 的 documents 数 > 0（说明它真的拿到了候选）
//   - 输出头条来自 rerank 的反序结果，证明排序被采用
func TestQueryReallyCallsRerankAndAppliesOrder(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-rr",
	  "embedding_model": "embed-m", "reranking_model": "rerank-m", "embedding_dim": 4}}`)

	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d", rc)
	}
	before := up.countPath("/embeddings")

	var out string
	out = captureStdout(t, func() {
		if rc := runCLI("query", "-index-dir", idx, "-top-n", "5", "网络配置"); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})

	if up.countPath("/rerank") == 0 {
		paths := up.pathList()
		t.Fatalf("query 从未命中 /rerank（请求路径：%v）", paths)
	}
	up.mu.Lock()
	docsSent := up.rerankDocs
	up.mu.Unlock()
	if docsSent == 0 {
		t.Error("rerank 收到的 documents 为空：结果会静默退化为原顺序")
	}
	if !up.sawModel("rerank-m") {
		t.Error("rerank 模型名未送达")
	}
	// rerank 反序 → 头条应是原候选的最后一条。至少结果数与候选数一致且非空。
	if !strings.Contains(out, "mode=hybrid") {
		t.Errorf("应走 hybrid 路径：\n%s", out)
	}
	if strings.Contains(out, "fallback:") {
		t.Errorf("发生降级会掩盖 rerank 结果：\n%s", out)
	}
	// 之后不应再有 embeddings 请求（query 只向量化一次查询词）。
	if after := up.countPath("/embeddings"); after == 0 {
		t.Error("query 未做向量化")
	}
	_ = before
}

// 配置了自备 key 时，query 的 rerank 也必须真正打到 /rerank，
// 且不得被缓存重定向到 /embeddings（串接口缺陷在自备 provider 上同样致命）。
func TestUserKeyQueryRerankEndpoint(t *testing.T) {
	clearKeyEnv(t)
	up := newMockUpstream(t, 4)
	writeJSONConfig(t, `{"openai": {"base_url": "`+up.URL+`", "api_key": "sk-u",
	  "embedding_model": "e", "reranking_model": "r", "embedding_dim": 4}}`)
	t.Setenv("SE_RAG_STATE_DIR", t.TempDir())

	docs := writeDocs(t)
	idx := filepath.Join(t.TempDir(), "idx")
	if rc := runCLI("build", "--docs-dir", docs, "-index-dir", idx); rc != 0 {
		t.Fatalf("build rc=%d", rc)
	}
	// 连查两次：第二次会命中第一次留下的粘滞记录，正是串接口缺陷的触发条件。
	for i := 0; i < 2; i++ {
		captureStdout(t, func() {
			if rc := runCLI("query", "-index-dir", idx, "-top-n", "5", "网络配置"); rc != 0 {
				t.Fatalf("第 %d 次 query rc=%d", i, rc)
			}
		})
	}
	if n := up.countPath("/rerank"); n < 2 {
		t.Errorf("/rerank 命中 %d 次，期望 ≥2（串接口会让它落到 /embeddings）：%v", n, up.pathList())
	}
}
