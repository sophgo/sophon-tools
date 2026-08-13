package llmproxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// setupTestController 建临时 db + mock 上游 + 返回 Controller 与上游调用记录。
func setupTestController(t *testing.T) (*Controller, *httptest.Server) {
	t.Helper()
	db := setupTestDB(t)
	t.Cleanup(func() { db.Close() })

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// 区分 VLM 与 LLM 上游
		if strings.HasPrefix(r.URL.Path, "/vlm") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"测试图片描述"}}]}`))
			return
		}
		// LLM 上游
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"测试回复"}}]}`))
	}))
	t.Cleanup(upstream.Close)

	svc := NewService(db)
	cfg, _ := svc.SaveConfig(SaveRequest{
		LLMApiBase: upstream.URL + "/llm", LLMApiKey: "k", LLMModel: "llm-target",
		LLMEnabled: boolPtr(true),
		VLMApiBase: upstream.URL + "/vlm", VLMApiKey: "k", VLMModel: "vlm-target",
		VLMEnabled: boolPtr(true),
	})
	setActive(cfg)
	return &Controller{svc: svc}, upstream
}

// TestRunTestAllOK 验证一键测试两个场景都通过。
func TestRunTestAllOK(t *testing.T) {
	ctrl, _ := setupTestController(t)
	// 清空图片缓存，确保描述走 VLM
	globalImageCache = newImageCache(10 << 20)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/llm-proxy/test", nil)
	rec := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(rec)
	ctx.Request = req
	ctrl.RunTest(ctx)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var out struct {
		Result TestResponse `json:"result"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if !out.Result.AllOK {
		t.Errorf("allOk = false, results = %+v", out.Result.Results)
	}
	if len(out.Result.Results) != 2 {
		t.Fatalf("results count = %d, want 2", len(out.Result.Results))
	}
	names := map[string]bool{}
	for _, r := range out.Result.Results {
		names[r.Name] = true
		if !r.OK {
			t.Errorf("test %q failed: %s", r.Name, r.Message)
		}
	}
	if !names["带图分发"] || !names["LLM 推理"] {
		t.Errorf("missing tests, names = %v", names)
	}
}

// TestRunTestLLMDisabled 验证 LLM 未配置时两项测试都失败（信息明确）。
func TestRunTestLLMDisabled(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	off := false
	svc := NewService(db)
	_, _ = svc.SaveConfig(SaveRequest{
		LLMApiBase: "http://x/v1", LLMApiKey: "k", LLMModel: "m", LLMEnabled: &off,
		VLMApiBase: "http://x/v1", VLMApiKey: "k", VLMModel: "m",
	})
	ctrl := &Controller{svc: svc}

	req := httptest.NewRequest(http.MethodPost, "/api/v1/llm-proxy/test", nil)
	rec := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(rec)
	ctx.Request = req
	ctrl.RunTest(ctx)

	var out struct {
		Result TestResponse `json:"result"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if out.Result.AllOK {
		t.Error("allOk should be false when LLM disabled")
	}
	for _, r := range out.Result.Results {
		if r.OK {
			t.Errorf("test %q should fail when LLM disabled", r.Name)
		}
		if !strings.Contains(r.Message, "未配置") && !strings.Contains(r.Message, "未启用") {
			t.Errorf("test %q message = %q, want 未配置/未启用 hint", r.Name, r.Message)
		}
	}
}
