package llmproxy

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"bmssm/database"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
)

// setupTestDB 建临时 sqlite，注册模型并迁移。
func setupTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(&Config{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	database.SetDB(db)
	return db
}

// setActive 注入当前配置到全局（避免真实 server 端口）。
func setActive(cfg Config) {
	mu.Lock()
	activeCfg = cfg
	mu.Unlock()
}

func TestServiceLLMAndVLMConfig(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)

	// 默认配置
	cfg := svc.LoadConfig()
	if cfg.LLMApiBase != "https://www.sophnet.com/api/open-apis/v1" {
		t.Errorf("default llmApiBase = %q", cfg.LLMApiBase)
	}
	if cfg.LLMModel != "sophnet-deepseek" {
		t.Errorf("default llmModel = %q", cfg.LLMModel)
	}
	if cfg.VLMModel != "qwen3-vl-plus" {
		t.Errorf("default vlmModel = %q", cfg.VLMModel)
	}
	if !cfg.LLMOverride || !cfg.VLMOverride {
		t.Errorf("default override should be on, got LLM=%v VLM=%v", cfg.LLMOverride, cfg.VLMOverride)
	}
	if cfg.ForwardKey == "" {
		t.Error("forward key should be auto-generated")
	}

	// 保存 LLM/VLM 两套
	llmOn, vlmOn := true, true
	saved, err := svc.SaveConfig(SaveRequest{
		LLMApiBase: "https://llm.example.com/v1",
		LLMApiKey:  "llm-key",
		LLMModel:   "llm-model",
		LLMEnabled: &llmOn,
		VLMApiBase: "https://vlm.example.com/v1",
		VLMApiKey:  "vlm-key",
		VLMModel:   "vlm-model",
		VLMEnabled: &vlmOn,
	})
	if err != nil {
		t.Fatalf("save: %v", err)
	}
	if saved.LLMApiKey != "llm-key" || saved.VLMApiKey != "vlm-key" {
		t.Errorf("saved keys = %q/%q", saved.LLMApiKey, saved.VLMApiKey)
	}
	fk := saved.ForwardKey

	// 读取回填
	got := svc.LoadConfig()
	if got.LLMModel != "llm-model" || got.VLMModel != "vlm-model" {
		t.Errorf("loaded = %+v", got)
	}
	if got.ForwardKey != fk {
		t.Error("forward key should persist across loads")
	}

	// key 空串 → 保留原值
	saved2, _ := svc.SaveConfig(SaveRequest{LLMApiKey: "", VLMApiKey: ""})
	if saved2.LLMApiKey != "llm-key" || saved2.VLMApiKey != "vlm-key" {
		t.Errorf("empty keys should keep old: %q/%q", saved2.LLMApiKey, saved2.VLMApiKey)
	}
}

func TestServiceLoadWhenDBEmpty(t *testing.T) {
	database.SetDB(nil)
	svc := NewService(nil)
	cfg := svc.LoadConfig()
	if cfg.LLMModel == "" || cfg.VLMModel == "" {
		t.Error("nil db should return defaults")
	}
}

// TestForwardKeyRelaxed 验证 MYS-171 放宽后的 key 策略：
// 配置了 ForwardKey 时，无 key / 错误 key 均不再 401（放行到上游）。
func TestForwardKeyRelaxed(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)

	// mock 上游，记录收到的请求并返回 200
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "m",
		VLMApiBase: upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "m",
		LLMEnabled: boolPtr(true), VLMEnabled: boolPtr(true),
	})
	// 强制设一个已知转发 key
	cfg.ForwardKey = "test-forward-key"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "test-forward-key").Error
	setActive(svc.LoadConfig())

	body, _ := json.Marshal(map[string]interface{}{"model": "x", "messages": []interface{}{}})

	cases := []struct {
		name string
		auth string // "" 表示不带 Authorization 头
		want int
	}{
		{"no key", "", http.StatusOK},
		{"wrong key", "Bearer wrong-key", http.StatusOK},
		{"matching key", "Bearer test-forward-key", http.StatusOK},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
			if tc.auth != "" {
				req.Header.Set("Authorization", tc.auth)
			}
			rec := httptest.NewRecorder()
			handleChatCompletions(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, tc.want, rec.Body.String())
			}
		})
	}
}

// TestForwardKeyUnset 验证未配置 ForwardKey 时同样放行（不要求鉴权）。
func TestForwardKeyUnset(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "m",
		VLMApiBase: upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "m",
		LLMEnabled: boolPtr(true),
	})
	cfg.ForwardKey = ""
	setActive(cfg)

	body, _ := json.Marshal(map[string]interface{}{"model": "x", "messages": []interface{}{}})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (no forward key configured)", rec.Code)
	}
}

// TestForwardModelPrecedence 验证 MYS-171 model 规则：
// 请求带非空 model → 上游收到该 model；请求无 model → 上游收到默认 llm.ModelName。
func TestForwardModelPrecedence(t *testing.T) {
	var gotModels []string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		if m, _ := req["model"].(string); m != "" {
			gotModels = append(gotModels, m)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-default",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(false),
		VLMApiBase:  upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())

	send := func(model interface{}) {
		m := map[string]interface{}{
			"messages": []map[string]interface{}{
				{"role": "user", "content": "hi"},
			},
		}
		if model != nil {
			m["model"] = model
		}
		body, _ := json.Marshal(m)
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer fk")
		rec := httptest.NewRecorder()
		handleChatCompletions(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
		}
	}

	// 请求带 model=X → 上游收到 X
	send("request-model-a")
	if len(gotModels) != 1 || gotModels[0] != "request-model-a" {
		t.Fatalf("with model: got = %v, want [request-model-a]", gotModels)
	}

	// 请求无 model → 默认 llm.ModelName
	send(nil)
	if len(gotModels) != 2 || gotModels[1] != "llm-default" {
		t.Fatalf("without model: got = %v, want [request-model-a llm-default]", gotModels)
	}

	// 请求 model 为空串 → 默认 llm.ModelName
	send("")
	if len(gotModels) != 3 || gotModels[2] != "llm-default" {
		t.Fatalf("empty model: got = %v, want [request-model-a llm-default llm-default]", gotModels)
	}
}

// TestForwardModelOverride 验证「覆盖下游请求」开关（override）：
// 开启后，无论下游请求带什么 model，转发时一律强制替换为默认模型名；
// 关闭时保留下游 model（由 TestForwardModelPrecedence 覆盖）。
func TestForwardModelOverride(t *testing.T) {
	var gotModels []string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		if m, _ := req["model"].(string); m != "" {
			gotModels = append(gotModels, m)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-default",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(true),
		VLMApiBase:  upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())

	send := func(model interface{}) {
		m := map[string]interface{}{
			"messages": []map[string]interface{}{
				{"role": "user", "content": "hi"},
			},
		}
		if model != nil {
			m["model"] = model
		}
		body, _ := json.Marshal(m)
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
		rec := httptest.NewRecorder()
		handleChatCompletions(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
		}
	}

	// override 开启：请求带任意 model → 一律替换为 llm-default
	send("request-model-a")
	if len(gotModels) != 1 || gotModels[0] != "llm-default" {
		t.Fatalf("override on, with model: got = %v, want [llm-default]", gotModels)
	}
	// 请求无 model → 也补为 llm-default
	send(nil)
	if len(gotModels) != 2 || gotModels[1] != "llm-default" {
		t.Fatalf("override on, no model: got = %v, want [llm-default llm-default]", gotModels)
	}
}

func boolPtr(b bool) *bool { return &b }

// TestVLMUnconfiguredSophnetFallback 验证 MYS-193：VLM 未配置时，LLM API Base 为 Sophnet
// → 隐式 VLM（ApiBase=Sophnet, ModelName=qwen3-vl-plus, key 复用 LLM 的 key）。
func TestVLMUnconfiguredSophnetFallback(t *testing.T) {
	cfg := Config{
		LLMApiBase: SophnetApiBase,
		LLMApiKey:  "llm-key",
		LLMModel:   "sophnet-deepseek",
		LLMEnabled: true,
		// VLM 全空 = 未配置
	}
	vlm := cfg.VLM()
	if !vlm.Enabled {
		t.Error("implicit VLM should be enabled")
	}
	if vlm.ApiBase != SophnetApiBase {
		t.Errorf("implicit VLM ApiBase = %q, want %q", vlm.ApiBase, SophnetApiBase)
	}
	if vlm.ModelName != "qwen3-vl-plus" {
		t.Errorf("implicit VLM ModelName = %q, want qwen3-vl-plus", vlm.ModelName)
	}
	if vlm.ApiKey != "llm-key" {
		t.Errorf("implicit VLM ApiKey = %q, want LLM key", vlm.ApiKey)
	}
}

// TestVLMUnconfiguredLocalKeepsUnset 验证 MYS-193：VLM 未配置且 LLM 非 Sophnet（本地 LLM）
// → 不产生隐式 VLM，保持未配置（转发时跳过描述化直接带 image 透传）。
func TestVLMUnconfiguredLocalKeepsUnset(t *testing.T) {
	cfg := Config{
		LLMApiBase: "http://127.0.0.1:8080/v1",
		LLMApiKey:  "k",
		LLMModel:   "local-model",
		LLMEnabled: true,
		// VLM 全空 = 未配置
	}
	vlm := cfg.VLM()
	if vlm.Enabled {
		t.Error("local LLM must NOT get an implicit VLM")
	}
	if vlm.ModelName != "" || vlm.ApiBase != "" {
		t.Errorf("local LLM VLM should stay empty, got %+v", vlm)
	}
}

// TestVLMConfiguredKeepsConfigured 验证 VLM 已配置时原样返回（不触发隐式兜底）。
func TestVLMConfiguredKeepsConfigured(t *testing.T) {
	cfg := Config{
		LLMApiBase: SophnetApiBase,
		LLMModel:   "sophnet-deepseek",
		LLMEnabled: true,
		VLMApiBase: "http://vlm.example.com/v1",
		VLMModel:   "custom-vlm",
		VLMEnabled: true,
	}
	vlm := cfg.VLM()
	if vlm.ApiBase != "http://vlm.example.com/v1" || vlm.ModelName != "custom-vlm" {
		t.Errorf("configured VLM should be returned as-is, got %+v", vlm)
	}
}

// TestVLMModelDefaultByApiBase 验证 defaultVLMModel：Sophnet → qwen3-vl-plus；本地 → 空。
func TestVLMModelDefaultByApiBase(t *testing.T) {
	if m := defaultVLMModel(SophnetApiBase); m != "qwen3-vl-plus" {
		t.Errorf("sophnet default vlm model = %q, want qwen3-vl-plus", m)
	}
	if m := defaultVLMModel("http://127.0.0.1:8080/v1"); m != "" {
		t.Errorf("local default vlm model = %q, want empty", m)
	}
}

// TestSaveConfigVLMDefaultFallback 验证 SaveConfig：请求不带 VLMModel 时，
// LLM 为 Sophnet → 落库 qwen3-vl-plus；LLM 为本地 → VLMModel 保持空。
func TestSaveConfigVLMDefaultFallback(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)

	// Sophnet LLM：不传 VLMModel → 落库默认 qwen3-vl-plus
	saved, err := svc.SaveConfig(SaveRequest{
		LLMApiBase: SophnetApiBase,
		LLMApiKey:  "k",
		LLMModel:   "sophnet-deepseek",
	})
	if err != nil {
		t.Fatalf("save (sophnet): %v", err)
	}
	if saved.VLMModel != "qwen3-vl-plus" {
		t.Errorf("sophnet save VLMModel = %q, want qwen3-vl-plus", saved.VLMModel)
	}

	// 本地 LLM：不传 VLMModel → VLMModel 保持空（本地 LLM 直接吃图）
	saved2, err := svc.SaveConfig(SaveRequest{
		LLMApiBase: "http://127.0.0.1:8080/v1",
		LLMApiKey:  "k",
		LLMModel:   "local-model",
	})
	if err != nil {
		t.Fatalf("save (local): %v", err)
	}
	if saved2.VLMModel != "" {
		t.Errorf("local save VLMModel = %q, want empty", saved2.VLMModel)
	}
	// normalizeDefaults 同样按 LLM 分流，不把本地场景的 VLMModel 回填为 qwen3-vl-plus
	if got := svc.LoadConfig(); got.VLMModel != "" {
		t.Errorf("local LoadConfig VLMModel = %q, want empty", got.VLMModel)
	}
}

// TestForwardModelKeptForImage 验证带图请求：model 保留请求值，图片仍走 VLM 描述化后整体路由 LLM。
func TestForwardModelKeptForImage(t *testing.T) {
	var gotLLMModel string
	vlmCalls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		if strings.HasPrefix(r.URL.Path, "/vlm") {
			vlmCalls++
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"一只猫在沙发上"}}]}`))
			return
		}
		gotLLMModel, _ = req["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-target",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(false),
		VLMApiBase:  upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
		VLMEnabled:  boolPtr(true),
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())
	globalImageCache = newImageCache(10 << 20)

	imgData := []byte("fake-png-bytes-456")
	b64 := base64.StdEncoding.EncodeToString(imgData)
	body, _ := json.Marshal(map[string]interface{}{
		"model": "my-custom-model",
		"messages": []map[string]interface{}{
			{"role": "user", "content": []map[string]interface{}{
				{"type": "text", "text": "what is this"},
				{"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + b64}},
			}},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer fk")
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if vlmCalls != 1 {
		t.Errorf("VLM should be called once, calls = %d", vlmCalls)
	}
	if gotLLMModel != "my-custom-model" {
		t.Errorf("image request should keep request model, got = %q", gotLLMModel)
	}
}

// TestImageDescribeRouting 验证：纯文本走 LLM；含图请求图片块被 VLM 描述并替换为文本，整体仍走 LLM。
func TestImageDescribeRouting(t *testing.T) {
	var gotLLMModel string
	var gotLLMBody map[string]interface{}
	vlmCalls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		// 区分 VLM 上游（路径 /vlm）与 LLM 上游（路径 /llm）
		if strings.HasPrefix(r.URL.Path, "/vlm") {
			vlmCalls++
			// VLM 返回固定描述
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"一只猫在沙发上"}}]}`))
			return
		}
		gotLLMModel, _ = req["model"].(string)
		gotLLMBody = req
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-target",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(false),
		VLMApiBase:  upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
		VLMEnabled:  boolPtr(true),
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())

	// 纯文本 → LLM，无 VLM 调用
	body, _ := json.Marshal(map[string]interface{}{
		"model": "devproxy",
		"messages": []map[string]interface{}{
			{"role": "user", "content": "hello"},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer fk")
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("text: status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if gotLLMModel != "devproxy" {
		t.Errorf("text: request model should be kept (MYS-171), got %q, want devproxy", gotLLMModel)
	}
	if vlmCalls != 0 {
		t.Errorf("text should not call VLM, calls = %d", vlmCalls)
	}

	// 含图 → 图片块被描述替换为文本，整体走 LLM
	imgData := []byte("fake-png-bytes-123")
	b64 := base64.StdEncoding.EncodeToString(imgData)
	body, _ = json.Marshal(map[string]interface{}{
		"model": "devproxy",
		"messages": []map[string]interface{}{
			{"role": "user", "content": []map[string]interface{}{
				{"type": "text", "text": "what is this"},
				{"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + b64}},
			}},
		},
	})
	req = httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer fk")
	rec = httptest.NewRecorder()
	handleChatCompletions(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("image: status = %d, body = %s", rec.Code, rec.Body.String())
	}
	// 整体走 LLM：请求 model 被保留（devproxy）
	if gotLLMModel != "devproxy" {
		t.Errorf("image request should keep request model, got = %q", gotLLMModel)
	}
	// VLM 被调用一次生成描述
	if vlmCalls != 1 {
		t.Errorf("VLM should be called once, calls = %d", vlmCalls)
	}
	// 图片块被替换为文本块
	msgs := gotLLMBody["messages"].([]interface{})
	m0 := msgs[0].(map[string]interface{})
	content := m0["content"].([]interface{})
	foundDesc := false
	for _, c := range content {
		block := c.(map[string]interface{})
		if block["type"] == "text" && strings.Contains(block["text"].(string), "这里有一个 image") {
			foundDesc = true
			if !strings.Contains(block["text"].(string), "一只猫在沙发上") {
				t.Errorf("description not embedded: %v", block["text"])
			}
		}
		if block["type"] == "image_url" {
			t.Error("image_url block should be replaced by text")
		}
	}
	if !foundDesc {
		t.Errorf("image description text block not found: %v", content)
	}
}

// TestImageCache 验证图片描述缓存：相同图片第二次不调 VLM。
func TestImageCache(t *testing.T) {
	vlmCalls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		if strings.HasPrefix(r.URL.Path, "/vlm") {
			vlmCalls++
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"相同图片描述"}}]}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-target",
		LLMEnabled: boolPtr(true),
		VLMApiBase: upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
		VLMEnabled: boolPtr(true),
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())

	// 清空缓存
	globalImageCache = newImageCache(10 << 20)

	imgData := []byte("same-image-bytes")
	b64 := base64.StdEncoding.EncodeToString(imgData)
	mkBody := func() []byte {
		b, _ := json.Marshal(map[string]interface{}{
			"model": "devproxy",
			"messages": []map[string]interface{}{
				{"role": "user", "content": []map[string]interface{}{
					{"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + b64}},
				}},
			},
		})
		return b
	}
	send := func() {
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(mkBody()))
		req.Header.Set("Authorization", "Bearer fk")
		rec := httptest.NewRecorder()
		handleChatCompletions(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
		}
	}

	send() // 第一次：调 VLM
	if vlmCalls != 1 {
		t.Fatalf("first: VLM calls = %d, want 1", vlmCalls)
	}
	send() // 第二次：缓存命中，不调 VLM
	if vlmCalls != 1 {
		t.Errorf("second: VLM calls = %d, want 1 (cache hit)", vlmCalls)
	}
}

// TestImageCacheLRUEvict 验证缓存超上限时淘汰最久未用项。
func TestImageCacheLRUEvict(t *testing.T) {
	c := newImageCache(100) // 上限 100 字节
	c.Set("a", strings.Repeat("x", 40), time.Hour)
	c.Set("b", strings.Repeat("y", 40), time.Hour)
	c.Set("c", strings.Repeat("z", 40), time.Hour)
	// 3*40=120 > 100，应淘汰最早插入的 a（LRU）
	if c.Get("a") != "" {
		t.Error("a should be evicted")
	}
	if c.Get("b") == "" || c.Get("c") == "" {
		t.Error("b and c should remain")
	}
}

// TestImageCacheTTL 验证缓存过期后重新调用。
func TestImageCacheTTL(t *testing.T) {
	c := newImageCache(10 << 20)
	c.Set("k", "desc", time.Millisecond) // 1ms 后过期
	if c.Get("k") != "desc" {
		t.Fatal("entry should be present before expiry")
	}
	time.Sleep(5 * time.Millisecond)
	if c.Get("k") != "" {
		t.Error("expired entry should not be returned")
	}
}

func mustJSON(v interface{}) string {
	b, _ := json.Marshal(v)
	return string(b)
}

// TestImagePassthroughLocalLLM 验证 MYS-193：VLM 未配置 + LLM 非 Sophnet（本地 LLM）
// → 跳过描述化，含 image 的 body 原样转发到本地 LLM API。
func TestImagePassthroughLocalLLM(t *testing.T) {
	var gotBody map[string]interface{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &gotBody)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	off := false
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "local-model",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(false),
		// VLM 显式未配置（disabled + 空模型）
		VLMEnabled: &off,
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	setActive(svc.LoadConfig())

	imgData := []byte("fake-png-bytes-local")
	b64 := base64.StdEncoding.EncodeToString(imgData)
	body, _ := json.Marshal(map[string]interface{}{
		"model": "devproxy",
		"messages": []map[string]interface{}{
			{"role": "user", "content": []map[string]interface{}{
				{"type": "text", "text": "what is this"},
				{"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + b64}},
			}},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}

	// 上游收到的 body 必须保留 image_url 块（未被描述化替换）
	msgs := gotBody["messages"].([]interface{})
	m0 := msgs[0].(map[string]interface{})
	content := m0["content"].([]interface{})
	foundImage := false
	for _, c := range content {
		block := c.(map[string]interface{})
		if block["type"] == "image_url" {
			foundImage = true
		}
		if block["type"] == "text" && strings.Contains(block["text"].(string), "这里有一个 image") {
			t.Error("image should NOT be described when VLM unconfigured (local LLM)")
		}
	}
	if !foundImage {
		t.Errorf("image_url block should be passed through untouched, got: %s", mustJSON(gotBody))
	}
}

// TestImageDescribedForSophnetImplicitVLM 验证 MYS-193：VLM 未配置 + LLM 为 Sophnet
// → 隐式 VLM（qwen3-vl-plus）仍对图片做描述化，描述请求 model 为 qwen3-vl-plus、
// Authorization 复用 LLM 的 key。
func TestImageDescribedForSophnetImplicitVLM(t *testing.T) {
	var vlmModel string
	var vlmAuth string
	var gotLLMBody map[string]interface{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var req map[string]interface{}
		_ = json.Unmarshal(body, &req)
		if strings.HasPrefix(r.URL.Path, "/vlm") {
			vlmModel, _ = req["model"].(string)
			vlmAuth = r.Header.Get("Authorization")
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"一只猫在沙发上"}}]}`))
			return
		}
		// 其余请求（本测试场景中仅有 LLM 转发）即 LLM 上游
		gotLLMBody = req
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	off := false
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "sophnet-model",
		LLMEnabled:  boolPtr(true),
		LLMOverride: boolPtr(false),
		VLMEnabled:  &off,
	})
	cfg.ForwardKey = "fk"
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", "fk").Error
	// 注入 Sophnet LLM API Base + 隐式 VLM 目标（Mock 上游）
	cfg.LLMApiBase = SophnetApiBase
	cfg.VLMApiBase = upstream.URL + "/vlm"
	cfg.VLMApiKey = ""
	cfg.LLMApiKey = "k"
	setActive(cfg)
	globalImageCache = newImageCache(10 << 20)

	imgData := []byte("fake-png-bytes-sophnet")
	b64 := base64.StdEncoding.EncodeToString(imgData)
	body, _ := json.Marshal(map[string]interface{}{
		"model": "devproxy",
		"messages": []map[string]interface{}{
			{"role": "user", "content": []map[string]interface{}{
				{"type": "text", "text": "what is this"},
				{"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + b64}},
			}},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)
	// 注意：LLM 上游为真实 Sophnet（假 key 无法验证），LLM 转发必然 401；
	// 本测试只验证「VLM 未配置 + LLM=Sophnet 时隐式 VLM 生效」：
	//   1. 含图请求的图片被隐式 VLM（qwen3-vl-plus）描述化（mock 收到描述请求）
	//   2. 描述请求 model=qwen3-vl-plus、Authorization=Bearer <LLM key>
	// 若 mock 未收到描述请求（vlmModel 为空），说明隐式 VLM 未生效 → 测试失败。
	if vlmModel != "qwen3-vl-plus" {
		t.Fatalf("implicit VLM not used: vlmModel = %q, want qwen3-vl-plus (mock should receive describe request)", vlmModel)
	}
	if vlmAuth != "Bearer k" {
		t.Errorf("implicit VLM auth = %q, want Bearer k (LLM key reused)", vlmAuth)
	}
	// 描述请求已到达 mock 即证明图片被描述化链路处理（LLM 转发发 Sophnet，mock 收不到 LLM body）
	if gotLLMBody == nil {
		t.Log("LLM 转发发 Sophnet（预期），mock 仅收到描述请求")
	} else {
		msgs := gotLLMBody["messages"].([]interface{})
		m0 := msgs[0].(map[string]interface{})
		content := m0["content"].([]interface{})
		foundDesc := false
		for _, c := range content {
			block := c.(map[string]interface{})
			if block["type"] == "text" && strings.Contains(block["text"].(string), "这里有一个 image") {
				foundDesc = true
			}
		}
		if !foundDesc {
			t.Errorf("image should be described via implicit VLM, got: %s", mustJSON(gotLLMBody))
		}
	}
}

// TestModelsEndpoint 验证 /v1/models 返回 LLM/VLM 模型名。
func TestModelsEndpoint(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: "http://x/v1", LLMApiKey: "k", LLMModel: "llm-a",
		VLMApiBase: "http://x/v1", VLMApiKey: "k", VLMModel: "vlm-b",
	})
	setActive(cfg)

	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	rec := httptest.NewRecorder()
	handleModels(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var out map[string]interface{}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	data := out["data"].([]interface{})
	ids := map[string]bool{}
	for _, d := range data {
		ids[d.(map[string]interface{})["id"].(string)] = true
	}
	if !ids["llm-a"] || !ids["vlm-b"] {
		t.Errorf("models = %v, want llm-a and vlm-b", ids)
	}
}

// TestDisabledLLMReturns503 验证 LLM/VLM 都 disabled 时转发返回 503。
func TestDisabledReturns503(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)
	off := false
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: "http://x/v1", LLMApiKey: "k", LLMModel: "m", LLMEnabled: &off,
		VLMApiBase: "http://x/v1", VLMApiKey: "k", VLMModel: "m", VLMEnabled: &off,
	})
	cfg.ForwardKey = "fk"
	setActive(cfg)

	body, _ := json.Marshal(map[string]interface{}{"model": "x", "messages": []interface{}{}})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer fk")
	rec := httptest.NewRecorder()
	handleChatCompletions(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
}

// TestRestartPicoclawUsesSystemctl 验证重启走 systemctl restart sophpicoclaw，
// 而非旧的 pkill + 手工 spawn。通过注入 runSystemctlRestart 捕获调用。
func TestRestartPicoclawUsesSystemctl(t *testing.T) {
	var called []string
	old := runSystemctlRestart
	runSystemctlRestart = func(name string) error {
		called = append(called, name)
		return nil
	}
	defer func() { runSystemctlRestart = old }()

	restartPicoclaw()

	if len(called) != 1 || called[0] != "sophpicoclaw.service" {
		t.Fatalf("runSystemctlRestart calls = %v, want [sophpicoclaw.service]", called)
	}
}

// TestDevproxyKeyPathPrefersOptSophon 验证 devproxy.key 优先定位到 /opt/sophon/picoclaw。
// 仅在目标路径存在时生效；CI 环境无该路径则跳过。
func TestDevproxyKeyPathPrefersOptSophon(t *testing.T) {
	if st, err := os.Stat("/opt/sophon/picoclaw/.picoclaw"); err != nil || !st.IsDir() {
		t.Skip("no /opt/sophon/picoclaw/.picoclaw on this host")
	}
	p, err := devproxyKeyPath()
	if err != nil {
		t.Fatalf("devproxyKeyPath: %v", err)
	}
	if p != "/opt/sophon/picoclaw/.picoclaw/devproxy.key" {
		t.Fatalf("devproxyKeyPath = %q, want /opt/sophon/picoclaw/.picoclaw/devproxy.key", p)
	}
}
