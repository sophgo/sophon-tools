package compat

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/database"
	"bmssm/middleware"
	"bmssm/mvc/hardware"
	"bmssm/mvc/software"
	"bmssm/mvc/user"
	"bmssm/pkg/ota"
	"bmssm/pkg/response"
)

func init() { gin.SetMode(gin.ReleaseMode) }

// noopRunner 测试用空 runner（dryRun 下不会被调用）。
func noopRunner(string, ...string) (string, string, error) { return "", "", nil }

// ---------------------------------------------------------------
// 测试夹具
// ---------------------------------------------------------------

// setupCompatTest 构建与 router.Register 一致（仅 compat 子集 + /password）的测试路由。
// 所有路由挂在 /api/v1 下，对齐 sophliteos 直调路径。
func setupCompatTest(t *testing.T) *gin.Engine {
	t.Helper()
	_ = os.Setenv("BMSSM_CONF", t.TempDir())
	config.LoadConfig()

	// 每个测试独立 sqlite DB
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := database.InitDB(dbPath)
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	if err := database.Migrate(db); err != nil {
		t.Fatalf("migrate db: %v", err)
	}
	// 创建 admin 用户（密码 == 默认密码 → 登录会拿到 temp token）
	userSvc := user.NewService(db)
	_ = userSvc.CreateUser("admin", "admin", "admin")

	// OTA 引擎：dryRun=true，路径重定向到临时目录
	otaPaths := ota.DefaultPathConfig()
	otaTmp := t.TempDir()
	otaPaths.SOCOTADir = otaTmp
	otaPaths.CtrlOTADir = otaTmp
	otaPaths.CoreTftpDir = otaTmp
	otaPaths.SOCWorkRoot = t.TempDir()
	otaPaths.PCIEBackupDir = otaTmp
	otaPaths.PCIEBootromDir = otaTmp
	otaPaths.PCIEFirmwareDir = otaTmp
	otaPaths.SuccessFlag = filepath.Join(otaTmp, "success")
	otaPaths.ErrorFlag = filepath.Join(otaTmp, "error")
	otaPaths.ShellLog = filepath.Join(otaTmp, "log")
	otaPaths.DiskCheckPath = otaTmp
	otaEngine := ota.NewEngine(db, noopRunner, nil, true, otaPaths)
	otaEngine.Start()
	t.Cleanup(func() { otaEngine.Stop() })

	r := gin.New()

	ctrl := NewController(
		NewCompatServiceWith(defaultFakeMetrics()),
		hardware.NewDefaultService(),
		software.DefaultService(),
		userSvc,
		otaEngine,
	)
	userCtrl := user.NewController(userSvc, nil)

	// 公开 login
	r.POST("/api/v1/login", userCtrl.Login)

	// 受保护组
	api := r.Group("/api/v1", middleware.Auth())
	{
		api.POST("/password", userCtrl.ChangePassword)
		api.GET("/device/basic", ctrl.GetCtrlBasic)
		api.GET("/device/resource", ctrl.GetCtrlResource)
		api.GET("/network/nat", ctrl.GetNAT)
		api.POST("/network/nat", ctrl.AddNAT)
		api.DELETE("/network/nat/:num", ctrl.DeleteNAT)
		api.POST("/hardware/shutdown", ctrl.Shutdown)
		api.POST("/software/notify/subscribe", ctrl.SubscribeAlarm)
		api.POST("/software/notify/unsubscribe", ctrl.UnsubscribeAlarm)
		api.GET("/software/notify/subscribe/:name", ctrl.GetSubscription)
		api.POST("/device/configure/basic", ctrl.SetBasic)
		api.GET("/device/configure/alarm", ctrl.GetAlarm)
		api.POST("/device/configure/alarm", ctrl.SetAlarm)
		api.POST("/ota/upload", ctrl.UploadFirmware)
		api.POST("/ota/upgrade", ctrl.ExecuteUpgrade)
		api.GET("/ota/workflow", ctrl.ListWorkflows)
		api.GET("/ota/workflow/:id", ctrl.GetWorkflow)
		api.POST("/ota/rollback", ctrl.Rollback)
		api.POST("/hardware/scp", ctrl.SCP)
		api.POST("/hardware/exec", ctrl.Exec)
	}

	return r
}

// ---------------------------------------------------------------
// response.Result 信封断言辅助
// ---------------------------------------------------------------

func assertSsmOK(t *testing.T, body []byte, msg string) response.Result {
	t.Helper()
	var resp response.Result
	if err := json.Unmarshal(body, &resp); err != nil {
		t.Fatalf("%s: unmarshal failed: %v, body=%s", msg, err, string(body))
	}
	if resp.Code != 0 {
		t.Errorf("%s: code=%d, want 0, body=%s", msg, resp.Code, string(body))
	}
	if resp.Msg != "请求成功" {
		t.Errorf("%s: msg=%q, want %q", msg, resp.Msg, "请求成功")
	}
	if resp.ErrorCode != 0 {
		t.Errorf("%s: error_code should be 0, got %d", msg, resp.ErrorCode)
	}
	if resp.ErrorMessage != "" {
		t.Errorf("%s: error_message should be empty, got %q", msg, resp.ErrorMessage)
	}
	return resp
}

func assertSsmErr(t *testing.T, body []byte, msg string) response.Result {
	t.Helper()
	var resp response.Result
	if err := json.Unmarshal(body, &resp); err != nil {
		t.Fatalf("%s: unmarshal failed: %v", msg, err)
	}
	if resp.Code != 1 {
		t.Errorf("%s: code=%d, want 1", msg, resp.Code)
	}
	if resp.Msg != "请求失败" {
		t.Errorf("%s: msg=%q, want %q", msg, resp.Msg, "请求失败")
	}
	return resp
}

// loginTempToken 用 admin/admin 登录，返回临时 token（changePass=true）。
func loginTempToken(t *testing.T, r *gin.Engine) string {
	t.Helper()
	body, _ := json.Marshal(user.LoginRequest{Username: "admin", Password: "admin"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("login: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("login unmarshal: %v", err)
	}
	m, _ := resp.Result.(map[string]interface{})
	token, _ := m["token"].(string)
	if token == "" {
		t.Fatalf("login: token empty, result=%v", resp.Result)
	}
	if cp, _ := m["changePass"].(bool); !cp {
		t.Fatal("login with default password should return changePass=true")
	}
	return token
}

// getNormalToken 登录 admin/admin（临时 token）→ 改密为 realpass → 重新登录拿正式 token。
// 这样后续受保护端点不会被 temp 限制 403。
func getNormalToken(t *testing.T, r *gin.Engine) string {
	t.Helper()
	tempToken := loginTempToken(t, r)

	// 改密（临时 token 可调 /password，不校验旧密码）
	body, _ := json.Marshal(user.ChangePasswordRequest{NewPassword: "realpass"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/password", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+tempToken)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("change password: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	// 重新登录拿正式 token
	body2, _ := json.Marshal(user.LoginRequest{Username: "admin", Password: "realpass"})
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer(body2))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("relogin: expected 200, got %d body=%s", w2.Code, w2.Body.String())
	}
	var resp response.Result
	if err := json.Unmarshal(w2.Body.Bytes(), &resp); err != nil {
		t.Fatalf("relogin unmarshal: %v", err)
	}
	m, _ := resp.Result.(map[string]interface{})
	token, _ := m["token"].(string)
	if token == "" {
		t.Fatalf("relogin: token empty, result=%v", resp.Result)
	}
	if cp, _ := m["changePass"].(bool); cp {
		t.Fatal("relogin with non-default password should not return changePass=true")
	}
	return token
}

// 兼容旧调用名
func loginAndGetToken(t *testing.T, r *gin.Engine) string { return getNormalToken(t, r) }

// ---------------------------------------------------------------
// Login + temp token 测试
// ---------------------------------------------------------------

func TestCompatLogin(t *testing.T) {
	r := setupCompatTest(t)

	// 默认密码登录 → 临时 token + changePass=true
	body, _ := json.Marshal(user.LoginRequest{Username: "admin", Password: "admin"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("login: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	resp := assertSsmOK(t, w.Body.Bytes(), "login")
	m, _ := resp.Result.(map[string]interface{})
	if token, _ := m["token"].(string); token == "" {
		t.Errorf("login: token empty, result=%v", resp.Result)
	}
	if role, _ := m["role"].(string); role != "admin" {
		t.Errorf("login: role = %v, want admin", m["role"])
	}
	if cp, _ := m["changePass"].(bool); !cp {
		t.Errorf("login: changePass should be true for default password")
	}

	// 错误密码
	body2, _ := json.Marshal(user.LoginRequest{Username: "admin", Password: "wrong"})
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer(body2))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	assertSsmErr(t, w2.Body.Bytes(), "login wrong password")

	// 无效 JSON
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer([]byte("not json")))
	req3.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w3, req3)
	assertSsmErr(t, w3.Body.Bytes(), "login invalid json")
}

// TestTempTokenRestricted 临时 token 只能调 /api/v1/password，其余端点 403。
func TestTempTokenRestricted(t *testing.T) {
	r := setupCompatTest(t)
	tempToken := loginTempToken(t, r)

	routes := []struct {
		method string
		path   string
		body   []byte
	}{
		{http.MethodGet, "/api/v1/device/basic", nil},
		{http.MethodGet, "/api/v1/device/resource", nil},
		{http.MethodGet, "/api/v1/network/nat", nil},
		{http.MethodPost, "/api/v1/ota/upgrade", []byte(`{"product":"SE7"}`)},
		{http.MethodPost, "/api/v1/hardware/exec", []byte(`{}`)},
	}
	for _, rt := range routes {
		t.Run(rt.method+" "+rt.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(rt.method, rt.path, bytes.NewBuffer(rt.body))
			if rt.body != nil {
				req.Header.Set("Content-Type", "application/json")
			}
			req.Header.Set("Authorization", "Bearer "+tempToken)
			r.ServeHTTP(w, req)
			if w.Code != http.StatusForbidden {
				t.Errorf("%s %s: got %d, want 403 (temp token restricted)", rt.method, rt.path, w.Code)
			}
		})
	}
}

// TestChangePasswordFlow 临时 token 改密 → 拿到正式 token → 正式 token 可访问受保护端点。
func TestChangePasswordFlow(t *testing.T) {
	r := setupCompatTest(t)
	tempToken := loginTempToken(t, r)

	// 临时 token 调 /password（不传 oldPassword）
	body, _ := json.Marshal(user.ChangePasswordRequest{NewPassword: "brandnew"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/password", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+tempToken)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("change password: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	resp := assertSsmOK(t, w.Body.Bytes(), "change password")
	m, _ := resp.Result.(map[string]interface{})
	newToken, _ := m["token"].(string)
	if newToken == "" {
		t.Fatal("change password: should return new normal token")
	}

	// 新正式 token 可访问受保护端点
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/device/basic", nil)
	req2.Header.Set("Authorization", "Bearer "+newToken)
	r.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("new token access: expected 200, got %d body=%s", w2.Code, w2.Body.String())
	}
}

// TestChangePasswordRequiresOldPassword 正式 token 改密必须校验旧密码。
func TestChangePasswordRequiresOldPassword(t *testing.T) {
	r := setupCompatTest(t)
	normalToken := getNormalToken(t, r) // admin/realpass

	// 旧密码错误
	body, _ := json.Marshal(user.ChangePasswordRequest{OldPassword: "wrongold", NewPassword: "newer"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/password", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+normalToken)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Errorf("wrong old password: got %d, want 401", w.Code)
	}

	// 旧密码正确
	body2, _ := json.Marshal(user.ChangePasswordRequest{OldPassword: "realpass", NewPassword: "newer"})
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/password", bytes.NewBuffer(body2))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Authorization", "Bearer "+normalToken)
	r.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("correct old password: got %d body=%s", w2.Code, w2.Body.String())
	}
}

// ---------------------------------------------------------------
// Device Basic 测试
// ---------------------------------------------------------------

func TestCompatGetCtrlBasic(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/device/basic", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("basic: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	resp := assertSsmOK(t, w.Body.Bytes(), "basic")
	resultMap, ok := resp.Result.(map[string]interface{})
	if !ok {
		t.Fatalf("basic: result is not a map, got %T", resp.Result)
	}

	configure, ok := resultMap["configure"].(map[string]interface{})
	if !ok {
		t.Fatalf("basic: configure is not a map")
	}
	basic, ok := configure["basic"].(map[string]interface{})
	if !ok {
		t.Fatalf("basic: configure.basic is not a map")
	}
	if _, ok := basic["deviceName"]; !ok {
		t.Error("basic: configure.basic.deviceName field missing")
	}
	if _, ok := basic["deviceType"]; !ok {
		t.Error("basic: configure.basic.deviceType field missing")
	}
	if _, ok := resultMap["ipList"]; !ok {
		t.Error("basic: ipList field missing")
	}
	if _, ok := resultMap["system"]; !ok {
		t.Error("basic: system field missing")
	}
	if _, ok := resultMap["chipSn"]; !ok {
		t.Error("basic: chipSn field missing")
	}
}

// ---------------------------------------------------------------
// Device Resource 测试
// ---------------------------------------------------------------

func TestCompatGetCtrlResource(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/device/resource", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("resource: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	resp := assertSsmOK(t, w.Body.Bytes(), "resource")
	resultArr, ok := resp.Result.([]interface{})
	if !ok {
		t.Fatalf("resource: result is not an array, got %T", resp.Result)
	}
	if len(resultArr) < 1 {
		t.Fatalf("resource: result array is empty")
	}
	elem, ok := resultArr[0].(map[string]interface{})
	if !ok {
		t.Fatalf("resource: result[0] is not a map, got %T", resultArr[0])
	}
	requiredFields := []string{"deviceSn", "deviceModel", "collectDateTime",
		"sslots", "centralProcessingUnit", "coreComputingUnit"}
	for _, f := range requiredFields {
		if _, ok := elem[f]; !ok {
			t.Errorf("resource: result[0].%s field missing", f)
		}
	}
}

// ---------------------------------------------------------------
// 订阅测试
// ---------------------------------------------------------------

func TestCompatSubscribeFlow(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	subReq := SubscribeRequest{
		Platform:            "test-device",
		SubscribeDetailType: []int{1, 2},
		NotificationURL:     "http://127.0.0.1:8080/api/device/alarm",
	}
	body, _ := json.Marshal(subReq)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/notify/subscribe", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("subscribe: expected 200, got %d", w.Code)
	}
	assertSsmOK(t, w.Body.Bytes(), "subscribe")

	// 查询订阅
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/software/notify/subscribe/test-device", nil)
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("get subscription: expected 200, got %d", w2.Code)
	}
	resp2 := assertSsmOK(t, w2.Body.Bytes(), "get subscription")
	subResult, ok := resp2.Result.(map[string]interface{})
	if !ok {
		t.Fatalf("get subscription: result is not a map")
	}
	if platform, _ := subResult["platform"].(string); platform != "test-device" {
		t.Errorf("get subscription: platform = %v, want test-device", subResult["platform"])
	}

	// 取消订阅
	w4 := httptest.NewRecorder()
	req4 := httptest.NewRequest(http.MethodPost, "/api/v1/software/notify/unsubscribe", bytes.NewBuffer(body))
	req4.Header.Set("Content-Type", "application/json")
	req4.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w4, req4)
	assertSsmOK(t, w4.Body.Bytes(), "unsubscribe")

	// 确认取消后查不到
	w5 := httptest.NewRecorder()
	req5 := httptest.NewRequest(http.MethodGet, "/api/v1/software/notify/subscribe/test-device", nil)
	req5.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w5, req5)
	resp5 := assertSsmOK(t, w5.Body.Bytes(), "get after unsubscribe")
	if resp5.Result != nil {
		t.Error("after unsubscribe: result should be nil")
	}
}

// ---------------------------------------------------------------
// 设备配置降级测试
// ---------------------------------------------------------------

func TestCompatSetBasic(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	reqBody := BasicSettings{Name: "my-device", Type: "SE8"}
	body, _ := json.Marshal(reqBody)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/device/configure/basic", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("set basic: expected 200, got %d", w.Code)
	}
	assertSsmOK(t, w.Body.Bytes(), "set basic")
}

func TestCompatSetAlarm(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	reqBody := AlarmThreshold{
		BoardTemperature: 80,
		CoreTemperature:  85,
	}
	body, _ := json.Marshal(reqBody)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/device/configure/alarm", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("set alarm: expected 200, got %d", w.Code)
	}
	assertSsmOK(t, w.Body.Bytes(), "set alarm")
}

// TestCompatGetAlarm GET /device/configure/alarm 返回当前阈值。
func TestCompatGetAlarm(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	// 默认值 boardTemperature=90
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/device/configure/alarm", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("get alarm: expected 200, got %d", w.Code)
	}
	resp := assertSsmOK(t, w.Body.Bytes(), "get alarm default")
	at, _ := resp.Result.(map[string]interface{})
	if v, _ := at["boardTemperature"].(float64); v != 90 {
		t.Errorf("get alarm: boardTemperature = %v, want 90", at["boardTemperature"])
	}

	// SetAlarm 修改后 GetAlarm 应反映新值
	newAT := AlarmThreshold{BoardTemperature: 77, CoreTemperature: 77}
	body, _ := json.Marshal(newAT)
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/device/configure/alarm", bytes.NewBuffer(body))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	assertSsmOK(t, w2.Body.Bytes(), "set alarm")

	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/api/v1/device/configure/alarm", nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)
	resp3 := assertSsmOK(t, w3.Body.Bytes(), "get alarm after set")
	at3, _ := resp3.Result.(map[string]interface{})
	if v, _ := at3["boardTemperature"].(float64); v != 77 {
		t.Errorf("get alarm after set: boardTemperature = %v, want 77", at3["boardTemperature"])
	}
}

// TestCompatSetAlarmPersistence 验证 SetAlarm 后 GetCtrlBasic 返回更新后的阈值（内存）。
func TestCompatSetAlarmPersistence(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	// Step 1: GET /basic 确认默认值
	w1 := httptest.NewRecorder()
	req1 := httptest.NewRequest(http.MethodGet, "/api/v1/device/basic", nil)
	req1.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w1, req1)
	resp1 := assertSsmOK(t, w1.Body.Bytes(), "basic before set alarm")
	result1, _ := resp1.Result.(map[string]interface{})
	cfg1, _ := result1["configure"].(map[string]interface{})
	at1, _ := cfg1["alarmThreshold"].(map[string]interface{})
	if v, _ := at1["boardTemperature"].(float64); v != 90 {
		t.Errorf("before SetAlarm: boardTemperature = %v, want 90", at1["boardTemperature"])
	}

	// Step 2: POST /configure/alarm 修改阈值
	newAT := AlarmThreshold{
		BoardTemperature: 88,
		CoreTemperature:  88,
		CpuRate:          0.88,
		DiskRate:         0.88,
		TotalMemoryScale: 0.88,
		TpuRate:          0.88,
		TpuScale:         0.88,
	}
	body, _ := json.Marshal(newAT)
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/device/configure/alarm", bytes.NewBuffer(body))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	assertSsmOK(t, w2.Body.Bytes(), "set alarm")

	// Step 3: GET /basic 确认值已更新（内存更新生效）
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/api/v1/device/basic", nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)
	resp3 := assertSsmOK(t, w3.Body.Bytes(), "basic after set alarm")
	result3, _ := resp3.Result.(map[string]interface{})
	cfg3, _ := result3["configure"].(map[string]interface{})
	at3, _ := cfg3["alarmThreshold"].(map[string]interface{})

	checkFloat := func(field string, want float64) {
		t.Helper()
		got, ok := at3[field].(float64)
		if !ok {
			t.Errorf("%s = %v (type %T), want float64", field, at3[field], at3[field])
			return
		}
		if got != want {
			t.Errorf("%s = %v, want %v", field, got, want)
		}
	}
	checkFloat("boardTemperature", 88)
	checkFloat("coreTemperature", 88)
	checkFloat("cpuRate", 0.88)
	checkFloat("diskRate", 0.88)
	checkFloat("totalMemoryScale", 0.88)
	checkFloat("tpuRate", 0.88)
	checkFloat("tpuScale", 0.88)
}

// ---------------------------------------------------------------
// 降级路由测试
// ---------------------------------------------------------------

func TestCompatRollback(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	body, _ := json.Marshal(OtaVersion{
		Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Name: "rb-test",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/rollback", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	resp := assertSsmOK(t, w.Body.Bytes(), "rollback")
	if msg, ok := resp.Result.(string); !ok || msg != "add workflow success" {
		t.Errorf("rollback result = %v, want 'add workflow success'", resp.Result)
	}
}

// ---------------------------------------------------------------
// OTA 端到端：上传 → 升级 → 列表/查询
// ---------------------------------------------------------------

func createMultipartUpload(t *testing.T, fieldName, fileName, content, module string) *http.Request {
	t.Helper()
	body := &bytes.Buffer{}
	mw := multipart.NewWriter(body)
	if module != "" {
		_ = mw.WriteField("module", module)
	}
	fw, err := mw.CreateFormFile(fieldName, fileName)
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	fw.Write([]byte(content))
	mw.Close()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upload", body)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	return req
}

func TestCompatUploadFirmware(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	req := createMultipartUpload(t, "file", "soc_fw.tgz", "fake-tgz-content", "soc")
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("upload: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	resp := assertSsmOK(t, w.Body.Bytes(), "upload")
	m, ok := resp.Result.(map[string]interface{})
	if !ok {
		t.Fatalf("upload result not a map: %T", resp.Result)
	}
	if m["fileName"] != "soc_fw.tgz" {
		t.Errorf("fileName = %v", m["fileName"])
	}
	if m["module"] != "soc" {
		t.Errorf("module = %v", m["module"])
	}
}

func TestCompatUploadFirmwareInvalidPkg(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	req := createMultipartUpload(t, "file", "evil.exe", "x", "soc")
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	resp := assertSsmErr(t, w.Body.Bytes(), "upload invalid")
	if !strings.Contains(resp.ErrorMessage, "invalid ota package") {
		t.Errorf("error_message = %q", resp.ErrorMessage)
	}
}

func TestCompatUploadFirmwareMissingFile(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upload", bytes.NewBufferString(""))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	assertSsmErr(t, w.Body.Bytes(), "upload missing file")
}

func TestCompatExecuteUpgrade(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	body, _ := json.Marshal(OtaVersion{
		Product: "SE7", ModuleName: "soc", FileName: "soc_fw.tgz", Name: "up-test", Version: "1.0.0",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	resp := assertSsmOK(t, w.Body.Bytes(), "upgrade")
	if msg, ok := resp.Result.(string); !ok || msg != "add workflow success" {
		t.Errorf("upgrade result = %v, want 'add workflow success'", resp.Result)
	}
}

func TestCompatExecuteUpgradeInvalidBody(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade", bytes.NewBuffer([]byte("not json")))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	assertSsmErr(t, w.Body.Bytes(), "upgrade invalid body")
}

func TestCompatListAndQueryWorkflow(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	body, _ := json.Marshal(OtaVersion{
		Product: "SE7", FileName: "fw.tgz", Name: "list-test",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	assertSsmOK(t, w.Body.Bytes(), "enqueue for list")

	// 等待 worker 处理（dryRun → Success）
	time.Sleep(100 * time.Millisecond)

	// GET 列表
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/ota/workflow", nil)
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	resp2 := assertSsmOK(t, w2.Body.Bytes(), "list workflows")
	arr, ok := resp2.Result.([]interface{})
	if !ok || len(arr) != 1 {
		t.Fatalf("list result = %v (type %T), want 1-element array", resp2.Result, resp2.Result)
	}
	elem, _ := arr[0].(map[string]interface{})
	wfID, _ := elem["workflowId"].(string)
	if wfID == "" {
		t.Fatal("workflowId empty in list")
	}

	// GET 单个
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/api/v1/ota/workflow/"+wfID, nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)
	resp3 := assertSsmOK(t, w3.Body.Bytes(), "get workflow")
	single, _ := resp3.Result.(map[string]interface{})
	if single["workflowId"] != wfID {
		t.Errorf("get workflow id = %v, want %s", single["workflowId"], wfID)
	}
	if status, _ := single["status"].(float64); status != float64(ota.StatusSuccess) {
		t.Errorf("status = %v, want %d (Success)", single["status"], ota.StatusSuccess)
	}
}

func TestCompatGetWorkflowNotFound(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ota/workflow/nonexistent", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	resp := assertSsmErr(t, w.Body.Bytes(), "get nonexistent workflow")
	if !strings.Contains(resp.ErrorMessage, "not found") {
		t.Errorf("error_message = %q", resp.ErrorMessage)
	}
}

func TestCompatSCP(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/scp", nil)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	resp := assertSsmErr(t, w.Body.Bytes(), "scp")
	if resp.ErrorMessage != "scp not supported" {
		t.Errorf("scp: error_message = %q", resp.ErrorMessage)
	}
}

func TestCompatExec(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	body, _ := json.Marshal(map[string]interface{}{"command": "echo hello", "timeout": 5})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/exec", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	resp := assertSsmOK(t, w.Body.Bytes(), "exec")
	m, _ := resp.Result.(map[string]interface{})
	if m["stdout"] != "hello\n" {
		t.Errorf("exec: stdout=%q, want hello\\n", m["stdout"])
	}
	if m["exitCode"] != float64(0) {
		t.Errorf("exec: exitCode=%v, want 0", m["exitCode"])
	}
}

func TestCompatExecEmptyCommand(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)
	body, _ := json.Marshal(map[string]interface{}{"command": ""})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/hardware/exec", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	resp := assertSsmErr(t, w.Body.Bytes(), "exec empty")
	if resp.ErrorMessage != "invalid request body" {
		t.Errorf("exec empty: error_message=%q, want invalid request body", resp.ErrorMessage)
	}
}

// ---------------------------------------------------------------
// NAT 删除参数校验测试
// ---------------------------------------------------------------

func TestCompatDeleteNATValidation(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	tests := []struct {
		name string
		num  string
		want int
	}{
		{"valid number", "1", http.StatusInternalServerError},
		{"invalid text", "abc", http.StatusBadRequest},
		{"zero", "0", http.StatusBadRequest},
		{"injection semicolon", "1;cat", http.StatusBadRequest},
		{"injection pipe", "1|ls", http.StatusBadRequest},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodDelete, "/api/v1/network/nat/"+tt.num, nil)
			req.Header.Set("Authorization", "Bearer "+token)
			r.ServeHTTP(w, req)
			if w.Code != tt.want {
				t.Errorf("%s: status = %d, want %d body=%s", tt.name, w.Code, tt.want, w.Body.String())
			}
		})
	}
}

// ---------------------------------------------------------------
// 旧 compat 路径已删除测试
// ---------------------------------------------------------------

// TestCompatOldPathsRemoved /bitmain/v1/ssm/* 整组应已删除（404）。
func TestCompatOldPathsRemoved(t *testing.T) {
	r := setupCompatTest(t)
	token := getNormalToken(t, r)

	oldPaths := []struct {
		method string
		path   string
	}{
		{http.MethodPost, "/bitmain/v1/ssm/login"},
		{http.MethodGet, "/bitmain/v1/ssm/software/device/basic"},
		{http.MethodGet, "/bitmain/v1/ssm/hardware/ip"},
		{http.MethodPost, "/bitmain/v1/ssm/workflow/upgrade"},
	}
	for _, p := range oldPaths {
		t.Run(p.method+" "+p.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(p.method, p.path, nil)
			req.Header.Set("Authorization", "Bearer "+token)
			r.ServeHTTP(w, req)
			if w.Code != http.StatusNotFound {
				t.Errorf("%s %s: got %d, want 404 (compat group removed)", p.method, p.path, w.Code)
			}
		})
	}
}

// ---------------------------------------------------------------
// 受保护路由 Auth 测试
// ---------------------------------------------------------------

func TestCompatEndpointsRequireAuth(t *testing.T) {
	r := setupCompatTest(t)

	routes := []struct {
		method string
		path   string
		body   []byte
	}{
		{http.MethodGet, "/api/v1/device/basic", nil},
		{http.MethodGet, "/api/v1/device/resource", nil},
		{http.MethodGet, "/api/v1/network/nat", nil},
		{http.MethodPost, "/api/v1/ota/upgrade", []byte(`{"product":"SE7"}`)},
		{http.MethodPost, "/api/v1/hardware/exec", []byte(`{}`)},
	}

	for _, rt := range routes {
		t.Run(rt.method+" "+rt.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(rt.method, rt.path, bytes.NewBuffer(rt.body))
			if rt.body != nil {
				req.Header.Set("Content-Type", "application/json")
			}
			// 不带 Authorization 头
			r.ServeHTTP(w, req)
			if w.Code != http.StatusUnauthorized {
				t.Errorf("%s %s: got %d, want 401 (auth required)", rt.method, rt.path, w.Code)
			}
		})
	}
}
