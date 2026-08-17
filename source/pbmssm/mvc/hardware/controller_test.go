package hardware

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
	"bmssm/pkg/oplock"
	"bmssm/pkg/response"
)

func init() { gin.SetMode(gin.ReleaseMode) }

// decodeResult 解析统一信封，将 env.Result 反序列化到 out。
func decodeResult(t *testing.T, body []byte, out interface{}) {
	t.Helper()
	var env response.Result
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("unmarshal envelope: %v body=%s", err, body)
	}
	if env.Code != 0 {
		t.Fatalf("expected envelope code=0, got %d msg=%s err=%s body=%s",
			env.Code, env.Msg, env.ErrorMessage, body)
	}
	raw, err := json.Marshal(env.Result)
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	if err := json.Unmarshal(raw, out); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, body)
	}
}

func setupHardwareTest(t *testing.T) {
	t.Helper()
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}
}

// makeAuthToken 签发测试用 JWT token。
func makeAuthToken(t *testing.T) string {
	t.Helper()
	secret := auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
	tokenStr, _, err := auth.IssueToken("admin", secret, false)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return tokenStr
}

// ========== Health ==========

func TestGetHealthWithAuth(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/health", ctrl.GetHealth)

	token := makeAuthToken(t)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/health", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp HealthResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Uptime == "" {
		t.Fatal("expected non-empty uptime")
	}
}

func TestGetHealthWithoutToken(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/health", ctrl.GetHealth)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/health", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

// ========== Reboot ==========

// rebootConfirmCode 为 "reboot"+admin 签发一次性确认码（MYS-389 高危操作二次确认）。
func rebootConfirmCode(t *testing.T) string {
	t.Helper()
	code, _ := confirm.Global().Prepare("reboot", "admin", confirm.DefaultTTL)
	return code
}

func TestRebootWithAuth(t *testing.T) {
	setupHardwareTest(t)

	// 使用 fake rebooter 避免真重启
	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	body, _ := json.Marshal(RebootRequest{Delay: 5, ConfirmCode: rebootConfirmCode(t)})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 1 {
		t.Fatalf("expected 1 reboot call, got %d", rb.calls.Load())
	}
}

// TestRebootRequiresConfirmCode 无确认码的高危操作必须被拒（MYS-389）。
func TestRebootRequiresConfirmCode(t *testing.T) {
	setupHardwareTest(t)

	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	// 不带 confirmCode
	body, _ := json.Marshal(RebootRequest{Delay: 0})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 without confirm code, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatalf("reboot must not run without confirm code, got %d calls", rb.calls.Load())
	}
}

// TestRebootWrongConfirmCode 错误确认码必须被拒且不执行重启。
func TestRebootWrongConfirmCode(t *testing.T) {
	setupHardwareTest(t)

	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	// 错误确认码
	body, _ := json.Marshal(RebootRequest{Delay: 0, ConfirmCode: "000000"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 with wrong confirm code, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatal("reboot must not run with wrong confirm code")
	}
}

// TestRebootBusyConflict 另一危险操作进行中时，重启返回 409 明确冲突（MYS-389）。
func TestRebootBusyConflict(t *testing.T) {
	setupHardwareTest(t)

	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	// 模拟 OTA 刷机正在进行（占用全局危险操作锁）
	release, err := oplock.Global().Acquire("ota:upgrade:SE7:pkg.tgz")
	if err != nil {
		t.Fatalf("simulate busy: %v", err)
	}
	defer release()

	body, _ := json.Marshal(RebootRequest{Delay: 0, ConfirmCode: rebootConfirmCode(t)})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("expected 409 while another dangerous op in progress, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatal("reboot must not run while another dangerous op in progress")
	}
}

func TestRebootWithoutToken(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	body, _ := json.Marshal(RebootRequest{Delay: 0})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestRebootDelayTooLarge400(t *testing.T) {
	setupHardwareTest(t)

	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	body, _ := json.Marshal(RebootRequest{Delay: 301, ConfirmCode: rebootConfirmCode(t)})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for delay > 300, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestRebootNegativeDelay400(t *testing.T) {
	setupHardwareTest(t)

	fr := newFakeFileReader()
	rb := &fakeRebooter{}
	svc := NewService(&fakeCmdRunner{}, fr, rb)
	ctrl := NewController(svc)

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/hardware/reboot", ctrl.Reboot)

	token := makeAuthToken(t)

	body, _ := json.Marshal(RebootRequest{Delay: -1, ConfirmCode: rebootConfirmCode(t)})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for negative delay, got %d body=%s", w.Code, w.Body.String())
	}
}

// ========== LED ==========

func TestGetLEDWithAuth(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/led", ctrl.GetLED)

	token := makeAuthToken(t)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/led", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp LEDResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Available {
		t.Fatal("expected LED not available (degradation)")
	}
}

func TestGetLEDWithoutToken(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/led", ctrl.GetLED)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/led", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestSetLEDWithAuth(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.PUT("/hardware/led", ctrl.SetLED)

	token := makeAuthToken(t)

	body, _ := json.Marshal(LEDRequest{State: "on"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/api/v1/hardware/led", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	// LED 不可用，降级返回 200 with available:false
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degradation), got %d body=%s", w.Code, w.Body.String())
	}

	var resp LEDResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Available {
		t.Fatal("expected LED not available (degradation)")
	}
}

func TestSetLEDInvalidState400(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.PUT("/hardware/led", ctrl.SetLED)

	token := makeAuthToken(t)

	body, _ := json.Marshal(LEDRequest{State: "flash"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/api/v1/hardware/led", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for invalid LED state, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestSetLEDWithoutToken(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.PUT("/hardware/led", ctrl.SetLED)

	body, _ := json.Marshal(LEDRequest{State: "on"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/api/v1/hardware/led", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

// ========== Card ==========

func TestGetCardWithAuth(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/card", ctrl.GetCard)

	token := makeAuthToken(t)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/card", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp CardResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Available {
		t.Fatal("expected card not available (bmlib not integrated)")
	}
	if resp.Reason != "bmlib not integrated" {
		t.Fatalf("expected reason 'bmlib not integrated', got %s", resp.Reason)
	}
}

func TestGetCardWithoutToken(t *testing.T) {
	setupHardwareTest(t)
	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/hardware/card", ctrl.GetCard)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hardware/card", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}
