package llmproxy

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func init() {
	gin.SetMode(gin.TestMode)
}

// TestResetForwardKeyRotatesHub 验证 MYS-387 转发 key 轮换：
//  1. 新 key 落库，注册的轮换监听者收到新 key（agentproxy Hub 据此热更新，
//     前端 WS 子协议 token 同步轮换）
//  2. 转发 server 热更新配置（key 变化不重启 bmssm）
//
// 注：18080 转发 server 为内部服务，不做强制 key 校验（MYS-171 语义保留），
// 轮换的意义在于 WS 凭据（/agent/ws token）同步失效旧值。
func TestResetForwardKeyRotatesHub(t *testing.T) {
	db := setupTestDB(t)
	defer db.Close()
	svc := NewService(db)

	cfg, err := svc.SaveConfig(SaveRequest{
		LLMApiBase: "http://x/v1", LLMApiKey: "k", LLMModel: "m",
	})
	if err != nil {
		t.Fatalf("save: %v", err)
	}
	oldKey := "old-forward-key"
	cfg.ForwardKey = oldKey
	_ = svc.db.Model(&Config{}).Where("id = ?", 1).Update("forward_key", oldKey).Error
	setActive(svc.LoadConfig())

	// 记录轮换监听通知
	var rotated []string
	fkMu.Lock()
	fkListeners = append(fkListeners, func(k string) { rotated = append(rotated, k) })
	fkMu.Unlock()
	defer func() {
		fkMu.Lock()
		fkListeners = fkListeners[:len(fkListeners)-1]
		fkMu.Unlock()
	}()

	// 调用 Reset 接口
	ctrl := &Controller{svc: svc}
	rec := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(rec)
	ctx.Request = httptest.NewRequest(http.MethodPost, "/api/v1/llm-proxy/forward-key/reset", nil)
	ctrl.ResetForwardKey(ctx)
	if rec.Code != http.StatusOK {
		t.Fatalf("reset status = %d, body = %s", rec.Code, rec.Body.String())
	}
	// 响应信封：{code, msg, result:{forwardKey}}
	var env struct {
		Result struct {
			ForwardKey string `json:"forwardKey"`
		} `json:"result"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatalf("parse reset response: %v (%s)", err, rec.Body.String())
	}
	if env.Result.ForwardKey == "" || env.Result.ForwardKey == oldKey {
		t.Fatalf("new forward key should be generated and differ from old, got %q", env.Result.ForwardKey)
	}

	// 监听者收到新 key
	if len(rotated) != 1 || rotated[0] != env.Result.ForwardKey {
		t.Fatalf("rotated notifications = %v, want [%s]", rotated, env.Result.ForwardKey)
	}

	// DB 已落库新 key
	var stored Config
	if err := svc.db.Select("forward_key").First(&stored, 1).Error; err != nil {
		t.Fatalf("load config: %v", err)
	}
	if stored.ForwardKey != env.Result.ForwardKey {
		t.Errorf("db forward_key = %q, want %q", stored.ForwardKey, env.Result.ForwardKey)
	}

	// 生效配置已热更新（currentConfig 读到新 key）
	if cur := currentConfig(); cur.ForwardKey != env.Result.ForwardKey {
		t.Errorf("active forward_key = %q, want %q", cur.ForwardKey, env.Result.ForwardKey)
	}

	// 转发 server 为内部服务：key 缺失/不匹配不放行校验（MYS-171 语义），
	// 请求仍按原逻辑处理——LLM 未启用时返回 503（不是 401）。
	body, _ := json.Marshal(map[string]interface{}{"model": "x", "messages": []interface{}{}})
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
	rec2 := httptest.NewRecorder()
	handleChatCompletions(rec2, req)
	if rec2.Code != http.StatusServiceUnavailable {
		t.Errorf("no-key request status = %d, want 503 (llm disabled, key not enforced)", rec2.Code)
	}
}

// TestForwardKeyListenerNotify 验证监听通知为空 key 时为 no-op（幂等、不 panic）。
func TestForwardKeyListenerNotify(t *testing.T) {
	notifyForwardKeyRotated("")
	notifyForwardKeyRotated("some-key")
}
