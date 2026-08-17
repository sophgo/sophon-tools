package ops

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/middleware"
	"bmssm/pkg/auth"
	"bmssm/pkg/confirm"
)

func init() { gin.SetMode(gin.ReleaseMode) }

// setupOpsTest 构建 /ops/confirm 测试路由（Auth 中间件 + Prepare）。
func setupOpsTest(t *testing.T) *gin.Engine {
	t.Helper()
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}

	r := gin.New()
	api := r.Group("/api/v1", middleware.Auth())
	api.POST("/ops/confirm", NewController().Prepare)
	return r
}

func authToken(t *testing.T, username string) string {
	t.Helper()
	secret := auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
	token, _, err := auth.IssueToken(username, secret, false)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func TestPrepareIssuesConfirmCode(t *testing.T) {
	defer confirm.Global().Reset()
	r := setupOpsTest(t)

	body, _ := json.Marshal(ConfirmRequest{Action: "reboot"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ops/confirm", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+authToken(t, "admin"))
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Result struct {
			Action    string `json:"action"`
			Code      string `json:"code"`
			ExpiresAt string `json:"expiresAt"`
		} `json:"result"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if env.Result.Action != "reboot" {
		t.Errorf("action = %q", env.Result.Action)
	}
	if len(env.Result.Code) != 6 {
		t.Errorf("code length = %d, want 6", len(env.Result.Code))
	}
	if env.Result.ExpiresAt == "" {
		t.Error("expiresAt should not be empty")
	}

	// 签发的码必须能被同用户校验通过
	if err := confirm.Global().Verify("reboot", "admin", env.Result.Code); err != nil {
		t.Errorf("issued code should verify: %v", err)
	}
}

func TestPrepareRejectsUnsupportedAction(t *testing.T) {
	defer confirm.Global().Reset()
	r := setupOpsTest(t)

	body, _ := json.Marshal(ConfirmRequest{Action: "format_disk"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ops/confirm", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+authToken(t, "admin"))
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for unsupported action, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestPrepareRequiresAuth(t *testing.T) {
	r := setupOpsTest(t)

	body, _ := json.Marshal(ConfirmRequest{Action: "reboot"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ops/confirm", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 without token, got %d", w.Code)
	}
}

func TestVerifyWritesErrorResponse(t *testing.T) {
	defer confirm.Global().Reset()

	// 未取码直接调用 Verify → 400 + ErrMissing 信息
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ops/confirm", nil)
	req.Header.Set("Authorization", "Bearer "+authToken(t, "admin"))
	c, _ := gin.CreateTestContext(w)
	c.Request = req
	if Verify(c, "reboot", "123456") {
		t.Fatal("Verify should fail without issued code")
	}
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}
