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
	"bmssm/pkg/hazard"
	"bmssm/pkg/ota"
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

	body, _ := json.Marshal(RebootRequest{Delay: 5, Confirm: hazard.NewConfirmCode()})
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

func TestRebootWithoutConfirm403(t *testing.T) {
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
	body, _ := json.Marshal(RebootRequest{Delay: 0}) // 无 Confirm
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Fatalf("expected 403 without confirm, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatalf("reboot must not be triggered without confirm, calls=%d", rb.calls.Load())
	}
}

func TestRebootBlockedByActiveHazardOp409(t *testing.T) {
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

	// 模拟 OTA 刷机进行中：占用全局高危互斥锁
	guard, err := hazard.HazardOps.TryAcquire("ota.upgrade")
	if err != nil {
		t.Fatalf("acquire for test: %v", err)
	}
	defer guard.Release()

	body, _ := json.Marshal(RebootRequest{Delay: 0, Confirm: hazard.NewConfirmCode()})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("expected 409 while hazard op active, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatalf("reboot must not run while hazard op active, calls=%d", rb.calls.Load())
	}
}

// TestRebootBlockedDuringFlashWindowAndFreeAfter 覆盖 MYS-451 F2 用户可见契约：
// worker 持锁（模拟 OTA 刷机窗口，holder 与 ota 引擎 handleFlash 一致）→
// /hardware/reboot → 409 且 fake rebooter 未被调用（不实际执行 /sbin/reboot）；
// 窗口结束（flow 终态、锁释放）→ 再次 reboot → 200 且正常执行。
func TestRebootBlockedDuringFlashWindowAndFreeAfter(t *testing.T) {
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

	// 模拟刷机中：占用全局高危互斥锁（与 ota.Engine.handleFlash 的持有者一致）
	guard, err := hazard.HazardOps.TryAcquire(ota.HazardHolderFlash)
	if err != nil {
		t.Fatalf("acquire flash window for test: %v", err)
	}
	t.Cleanup(guard.Release)

	postReboot := func() *httptest.ResponseRecorder {
		body, _ := json.Marshal(RebootRequest{Delay: 0, Confirm: hazard.NewConfirmCode()})
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/reboot", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(w, req)
		return w
	}

	// 刷机窗口内：409（TryAcquire 冲突），且不实际执行重启
	w := postReboot()
	if w.Code != http.StatusConflict {
		t.Fatalf("expected 409 while flash window open, got %d body=%s", w.Code, w.Body.String())
	}
	if rb.calls.Load() != 0 {
		t.Fatalf("reboot must not run during flash window, calls=%d", rb.calls.Load())
	}

	// 窗口结束（flow 终态后引擎释放锁）→ reboot 正常 200 并执行
	guard.Release()
	w2 := postReboot()
	if w2.Code != http.StatusOK {
		t.Fatalf("expected 200 after flash window closed, got %d body=%s", w2.Code, w2.Body.String())
	}
	if rb.calls.Load() != 1 {
		t.Fatalf("expected 1 reboot call after window closed, got %d", rb.calls.Load())
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

	body, _ := json.Marshal(RebootRequest{Delay: 301, Confirm: hazard.NewConfirmCode()})
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

	body, _ := json.Marshal(RebootRequest{Delay: -1, Confirm: hazard.NewConfirmCode()})
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
