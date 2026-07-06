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

	"ssm/config"
	"ssm/database"
	"ssm/middleware"
	"ssm/mvc/hardware"
	"ssm/mvc/software"
	"ssm/mvc/user"
	"ssm/pkg/ota"
)

func init() { gin.SetMode(gin.ReleaseMode) }

// noopRunner 测试用空 runner（dryRun 下不会被调用）。
func noopRunner(string, ...string) (string, string, error) { return "", "", nil }

// ---------------------------------------------------------------
// 测试夹具
// ---------------------------------------------------------------

func setupCompatTest(t *testing.T) *gin.Engine {
	t.Helper()
	_ = os.Setenv("SSM_CONF", t.TempDir())
	config.LoadConfig()

	// 每个测试独立 sqlite DB：避免共享 globalDB 时首个测试 tempdir 被清理后、
	// 后续测试写入已删文件触发 "attempt to write a readonly database"。
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := database.InitDB(dbPath)
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	if err := database.Migrate(db); err != nil {
		t.Fatalf("migrate db: %v", err)
	}
	// 创建 admin 用户供登录测试
	userSvc := user.NewService(db)
	_ = userSvc.CreateUser("admin", "admin", "admin")

	// OTA 引擎：dryRun=true（不实刷），路径重定向到临时目录避免触碰真实 /data/ota
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

	// 注册兼容路由（与 router.go 一致，不走 Auth）
	// 用 fake MetricProvider 注入，避免真机 I/O 与 100ms CPU 采样 sleep
	ctrl := NewController(
		NewCompatServiceWith(defaultFakeMetrics()),
		hardware.NewDefaultService(),
		software.DefaultService(),
		userSvc,
		otaEngine,
	)
	compatGroup := r.Group("/bitmain/v1/ssm")
	compatGroup.POST("/login", ctrl.Login)

	protected := compatGroup.Group("", middleware.Auth())
	{
		protected.GET("/software/device/basic", ctrl.GetCtrlBasic)
		protected.GET("/software/device/resource/list", ctrl.GetCtrlResource)
		protected.GET("/hardware/ip", ctrl.GetIP)
		protected.POST("/hardware/ip", ctrl.SetIP)
		protected.GET("/hardware/nat", ctrl.GetNAT)
		protected.POST("/hardware/nat", ctrl.AddNAT)
		protected.DELETE("/hardware/nat/PREROUTING-:num", ctrl.DeleteNAT)
		protected.POST("/hardware/devices/reset", ctrl.Reboot)
		protected.POST("/hardware/devices/down", ctrl.Shutdown)
		protected.POST("/software/notify/subscribe", ctrl.SubscribeAlarm)
		protected.POST("/software/notify/unsubscribe", ctrl.UnsubscribeAlarm)
		protected.GET("/software/notify/subscribe/:name", ctrl.GetSubscription)
		protected.POST("/software/device/configure/basic", ctrl.SetBasic)
		protected.POST("/software/device/configure/alarm", ctrl.SetAlarm)
		protected.POST("/file/ota", ctrl.UploadFirmware)
		protected.POST("/workflow/upgrade", ctrl.ExecuteUpgrade)
		protected.GET("/workflow/upgrade", ctrl.ListWorkflows)
		protected.GET("/workflow/upgrade/:id", ctrl.GetWorkflow)
		protected.POST("/workflow/rollback", ctrl.Rollback)
		protected.POST("/hardware/devices/scp", ctrl.SCP)
		protected.POST("/hardware/devices/exec", ctrl.Exec)
	}

	return r
}

// ---------------------------------------------------------------
// SsmResult 信封断言辅助
// ---------------------------------------------------------------

// assertSsmOK 断言响应是成功的 SsmResult。
func assertSsmOK(t *testing.T, body []byte, msg string) SsmResult {
	t.Helper()
	var resp SsmResult
	if err := json.Unmarshal(body, &resp); err != nil {
		t.Fatalf("%s: unmarshal failed: %v, body=%s", msg, err, string(body))
	}
	if resp.Code != 0 {
		t.Errorf("%s: code=%d, want 0, body=%s", msg, resp.Code, string(body))
	}
	if resp.Msg != "请求成功" {
		t.Errorf("%s: msg=%q, want %q", msg, resp.Msg, "请求成功")
	}
	// error_code 和 error_message 在成功时应该为 0/空
	if resp.ErrorCode != 0 {
		t.Errorf("%s: error_code should be 0, got %d", msg, resp.ErrorCode)
	}
	if resp.ErrorMessage != "" {
		t.Errorf("%s: error_message should be empty, got %q", msg, resp.ErrorMessage)
	}
	return resp
}

// assertSsmErr 断言响应是失败 SsmResult。
func assertSsmErr(t *testing.T, body []byte, msg string) SsmResult {
	t.Helper()
	var resp SsmResult
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

// loginAndGetToken 登录并返回 Bearer token，供后续受保护请求使用。
func loginAndGetToken(t *testing.T, r *gin.Engine) string {
	t.Helper()
	body, _ := json.Marshal(LoginRequest{UserName: "admin", Password: "admin"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/login", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("loginAndGetToken: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var resp SsmResult
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("loginAndGetToken: unmarshal: %v", err)
	}
	resultMap, _ := resp.Result.(map[string]interface{})
	token, _ := resultMap["token"].(string)
	if token == "" {
		t.Fatalf("loginAndGetToken: token is empty, result=%v", resp.Result)
	}
	return token
}

// ---------------------------------------------------------------
// Login 测试
// ---------------------------------------------------------------

func TestCompatLogin(t *testing.T) {
	r := setupCompatTest(t)

	// 正确的登录
	body, _ := json.Marshal(LoginRequest{UserName: "admin", Password: "admin"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/login", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("login: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	resp := assertSsmOK(t, w.Body.Bytes(), "login")

	// result 应该包含 token
	resultMap, ok := resp.Result.(map[string]interface{})
	if !ok {
		t.Fatalf("login: result is not a map, got %T", resp.Result)
	}
	if token, ok := resultMap["token"].(string); !ok || token == "" {
		t.Errorf("login: result.token is empty or missing, result=%v", resp.Result)
	}
	if role, ok := resultMap["role"].(string); !ok || role != "admin" {
		t.Errorf("login: result.role = %v, want 'admin'", resultMap["role"])
	}

	// 错误密码
	body2, _ := json.Marshal(LoginRequest{UserName: "admin", Password: "wrong"})
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/login", bytes.NewBuffer(body2))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)

	assertSsmErr(t, w2.Body.Bytes(), "login wrong password")

	// 无效 JSON
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/login", bytes.NewBuffer([]byte("not json")))
	req3.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w3, req3)

	assertSsmErr(t, w3.Body.Bytes(), "login invalid json")
}

// ---------------------------------------------------------------
// Device Basic 测试
// ---------------------------------------------------------------

func TestCompatGetCtrlBasic(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/basic", nil)
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

	// 验证关键字段存在
	// configure.basic 应存在
	configure, ok := resultMap["configure"].(map[string]interface{})
	if !ok {
		t.Fatalf("basic: configure is not a map")
	}
	basic, ok := configure["basic"].(map[string]interface{})
	if !ok {
		t.Fatalf("basic: configure.basic is not a map")
	}
	// deviceName/devicetype 应该存在（即使为空字符串）
	if _, ok := basic["deviceName"]; !ok {
		t.Error("basic: configure.basic.deviceName field missing")
	}
	if _, ok := basic["deviceType"]; !ok {
		t.Error("basic: configure.basic.deviceType field missing")
	}

	// ipList 应存在（数组）
	ipList, ok := resultMap["ipList"].([]interface{})
	if !ok {
		t.Errorf("basic: ipList is not an array, got %T", resultMap["ipList"])
	} else {
		t.Logf("basic: ipList has %d entries", len(ipList))
	}

	// system 字段应存在
	if _, ok := resultMap["system"]; !ok {
		t.Error("basic: system field missing")
	}

	// chipSn 应存在
	if _, ok := resultMap["chipSn"]; !ok {
		t.Error("basic: chipSn field missing")
	}

	// bmlib 依赖字段应该为空/零值
	if agencyModule, ok := configure["agencyModule"]; ok {
		if arr, ok := agencyModule.([]interface{}); ok && len(arr) != 0 {
			t.Error("basic: agencyModule should be empty (bmlib not integrated)")
		}
	}
	serviceAddr, _ := configure["serviceAddress"].(map[string]interface{})
	if serviceAddr != nil {
		// 所有 serviceAddress 字段应为空
		for _, key := range []string{"event", "keepalive", "operatingNotification", "register"} {
			if v, ok := serviceAddr[key]; ok && v != nil {
				t.Errorf("basic: serviceAddress.%s should be null, got %v", key, v)
			}
		}
	}
}

// ---------------------------------------------------------------
// Device Resource 测试
// ---------------------------------------------------------------

func TestCompatGetCtrlResource(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/resource/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("resource: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	resp := assertSsmOK(t, w.Body.Bytes(), "resource")

	// result 必须是数组（sophliteos 取 [0]）
	resultArr, ok := resp.Result.([]interface{})
	if !ok {
		t.Fatalf("resource: result is not an array, got %T", resp.Result)
	}
	if len(resultArr) < 1 {
		t.Fatalf("resource: result array is empty, sophliteos accesses [0]")
	}

	// 第一个元素应该是一个对象
	elem, ok := resultArr[0].(map[string]interface{})
	if !ok {
		t.Fatalf("resource: result[0] is not a map, got %T", resultArr[0])
	}

	// 验证关键字段存在（即使为零值）
	requiredFields := []string{"deviceSn", "deviceModel", "collectDateTime",
		"sslots", "centralProcessingUnit", "coreComputingUnit"}
	for _, f := range requiredFields {
		if _, ok := elem[f]; !ok {
			t.Errorf("resource: result[0].%s field missing", f)
		}
	}

	// sslots 应该是数组
	if sslots, ok := elem["sslots"].([]interface{}); !ok {
		t.Errorf("resource: sslots is not an array, got %T", elem["sslots"])
	} else {
		if len(sslots) != 0 {
			t.Errorf("resource: sslots should be empty (bmlib not integrated), got %d", len(sslots))
		}
	}

	// coreComputingUnit.board 现在含 1 个元素（metrics 填充温度/TPU/SDK）
	ccu, _ := elem["coreComputingUnit"].(map[string]interface{})
	if ccu == nil {
		t.Fatalf("resource: coreComputingUnit is missing or not a map")
	}
	board, ok := ccu["board"].([]interface{})
	if !ok {
		t.Fatalf("resource: coreComputingUnit.board is not an array, got %T", ccu["board"])
	}
	if len(board) != 1 {
		t.Fatalf("resource: coreComputingUnit.board len = %d, want 1 (metrics 填充)", len(board))
	}
	board0, ok := board[0].(map[string]interface{})
	if !ok {
		t.Fatalf("resource: board[0] is not a map, got %T", board[0])
	}
	// board[0] 应有温度/SDK 字段（来自 metrics）
	for _, f := range []string{"boardSn", "sdkVersion", "temperature", "chip"} {
		if _, ok := board0[f]; !ok {
			t.Errorf("resource: board[0].%s field missing", f)
		}
	}
	// chip[0] 应有温度/利用率
	chip, ok := board0["chip"].([]interface{})
	if !ok || len(chip) != 1 {
		t.Fatalf("resource: board[0].chip should be array of 1, got %T len=%v", board0["chip"], len(chip))
	}
	chip0, _ := chip[0].(map[string]interface{})
	if chip0 == nil {
		t.Fatal("resource: board[0].chip[0] is not a map")
	}
	for _, f := range []string{"temperature", "utilizationRate", "chipSn"} {
		if _, ok := chip0[f]; !ok {
			t.Errorf("resource: board[0].chip[0].%s field missing", f)
		}
	}
}

// ---------------------------------------------------------------
// IP 查询测试
// ---------------------------------------------------------------

func TestCompatGetIP(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/hardware/ip", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("get ip: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	resp := assertSsmOK(t, w.Body.Bytes(), "get ip")

	// result 应该是数组
	ipArr, ok := resp.Result.([]interface{})
	if !ok {
		t.Fatalf("get ip: result is not an array, got %T", resp.Result)
	}

	t.Logf("get ip: %d network interfaces", len(ipArr))

	// 如果有网卡，验证 ip 结构
	if len(ipArr) > 0 {
		ip, ok := ipArr[0].(map[string]interface{})
		if !ok {
			t.Fatalf("get ip: ip[0] is not a map")
		}
		ipFields := []string{"netCardName", "ip", "netMask", "mac", "dns", "gateway"}
		for _, f := range ipFields {
			if _, ok := ip[f]; !ok {
				t.Errorf("get ip: ip.%s field missing", f)
			}
		}
	}
}

// ---------------------------------------------------------------
// 订阅测试
// ---------------------------------------------------------------

func TestCompatSubscribeFlow(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	// 订阅
	subReq := SubscribeRequest{
		Platform:            "test-device",
		SubscribeDetailType: []int{1, 2},
		NotificationURL:     "http://127.0.0.1:8080/api/device/alarm",
	}
	body, _ := json.Marshal(subReq)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/notify/subscribe", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("subscribe: expected 200, got %d", w.Code)
	}
	assertSsmOK(t, w.Body.Bytes(), "subscribe")

	// 查询订阅
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/notify/subscribe/test-device", nil)
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
	if platform, ok := subResult["platform"].(string); !ok || platform != "test-device" {
		t.Errorf("get subscription: platform = %v, want test-device", subResult["platform"])
	}
	if url, ok := subResult["notificationUrl"].(string); !ok || url != subReq.NotificationURL {
		t.Errorf("get subscription: notificationUrl = %v", subResult["notificationUrl"])
	}

	// 查询不存在的订阅
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/notify/subscribe/nonexistent", nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)

	if w3.Code != http.StatusOK {
		t.Fatalf("get nonexistent subscription: expected 200, got %d", w3.Code)
	}
	resp3 := assertSsmOK(t, w3.Body.Bytes(), "get nonexistent subscription")
	if resp3.Result != nil {
		t.Errorf("get nonexistent subscription: result should be nil, got %v", resp3.Result)
	}

	// 取消订阅
	w4 := httptest.NewRecorder()
	req4 := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/notify/unsubscribe", bytes.NewBuffer(body))
	req4.Header.Set("Content-Type", "application/json")
	req4.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w4, req4)

	if w4.Code != http.StatusOK {
		t.Fatalf("unsubscribe: expected 200, got %d", w4.Code)
	}
	assertSsmOK(t, w4.Body.Bytes(), "unsubscribe")

	// 确认取消后查不到
	w5 := httptest.NewRecorder()
	req5 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/notify/subscribe/test-device", nil)
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
	token := loginAndGetToken(t, r)

	reqBody := BasicSettings{Name: "my-device", Type: "SE8"}
	body, _ := json.Marshal(reqBody)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/device/configure/basic", bytes.NewBuffer(body))
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
	token := loginAndGetToken(t, r)

	reqBody := AlarmThreshold{
		BoardTemperature: 80,
		CoreTemperature:  85,
	}
	body, _ := json.Marshal(reqBody)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/device/configure/alarm", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("set alarm: expected 200, got %d", w.Code)
	}
	assertSsmOK(t, w.Body.Bytes(), "set alarm")
}

// TestCompatSetAlarmPersistence 验证 SetAlarm POST 后 GetCtrlBasic 返回更新后的阈值。
// WriteConfig 依赖已知可写配置文件，因此 setupCompatTest 中 config.LoadConfig
// 用 SSM_CONF tempdir 初始化（空目录），WriteConfig 会失败并降级为仅内存更新。
// 本测试验证内存更新后 BuildCtrlBasic 返回了 post 的新值。
func TestCompatSetAlarmPersistence(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	// Step 1: GET /basic 确认默认值
	w1 := httptest.NewRecorder()
	req1 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/basic", nil)
	req1.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w1, req1)
	resp1 := assertSsmOK(t, w1.Body.Bytes(), "basic before set alarm")
	result1, _ := resp1.Result.(map[string]interface{})
	cfg1, _ := result1["configure"].(map[string]interface{})
	at1, _ := cfg1["alarmThreshold"].(map[string]interface{})
	if v, ok := at1["boardTemperature"].(float64); !ok || v != 90 {
		t.Errorf("before SetAlarm: boardTemperature = %v, want 90", at1["boardTemperature"])
	}

	// Step 2: POST /configure/alarm 修改阈值
	newAT := AlarmThreshold{
		BoardTemperature:     88,
		CoreTemperature:      88,
		CpuRate:              0.88,
		DiskRate:             0.88,
		ExternalHardDiskRate: 0.88,
		FanSpeed:             8888,
		SystemScale:          0.88,
		TotalMemoryScale:     0.88,
		TpuRate:              0.88,
		TpuScale:             0.88,
		VideoScale:           0.88,
	}
	body, _ := json.Marshal(newAT)
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/device/configure/alarm", bytes.NewBuffer(body))
	req2.Header.Set("Content-Type", "application/json")
		req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	assertSsmOK(t, w2.Body.Bytes(), "set alarm")

	// Step 3: GET /basic 确认值已更新（内存更新生效）
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/basic", nil)
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
	checkFloat("externalHardDiskRate", 0.88)
	checkFloat("fanSpeed", 8888)
	checkFloat("systemScale", 0.88)
	checkFloat("totalMemoryScale", 0.88)
	checkFloat("tpuRate", 0.88)
	checkFloat("tpuScale", 0.88)
	checkFloat("videoScale", 0.88)
}

// ---------------------------------------------------------------
// 降级路由测试（不支持的操作）
// ---------------------------------------------------------------

func TestCompatRollback(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	body, _ := json.Marshal(OtaVersion{
		Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Name: "rb-test",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/workflow/rollback", bytes.NewBuffer(body))
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

// createMultipartUpload 构造一个 multipart/form-data 上传请求。
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
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/file/ota", body)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	return req
}

func TestCompatUploadFirmware(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

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
	if path, _ := m["path"].(string); path == "" {
		t.Error("path should be non-empty")
	}
}

func TestCompatUploadFirmwareInvalidPkg(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

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
	token := loginAndGetToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/file/ota", bytes.NewBufferString(""))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	assertSsmErr(t, w.Body.Bytes(), "upload missing file")
}

func TestCompatExecuteUpgrade(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	body, _ := json.Marshal(OtaVersion{
		Product: "SE7", ModuleName: "soc", FileName: "soc_fw.tgz", Name: "up-test", Version: "1.0.0",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/workflow/upgrade", bytes.NewBuffer(body))
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
	token := loginAndGetToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/workflow/upgrade", bytes.NewBuffer([]byte("not json")))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	assertSsmErr(t, w.Body.Bytes(), "upgrade invalid body")
}

func TestCompatListAndQueryWorkflow(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	// 提交一条升级 workflow
	body, _ := json.Marshal(OtaVersion{
		Product: "SE7", FileName: "fw.tgz", Name: "list-test",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/workflow/upgrade", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	resp := assertSsmOK(t, w.Body.Bytes(), "enqueue for list")

	_ = resp
	// 等待 worker 处理（dryRun → Success）
	time.Sleep(100 * time.Millisecond)

	// GET 列表
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/workflow/upgrade", nil)
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
	req3 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/workflow/upgrade/"+wfID, nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)
	resp3 := assertSsmOK(t, w3.Body.Bytes(), "get workflow")
	single, _ := resp3.Result.(map[string]interface{})
	if single["workflowId"] != wfID {
		t.Errorf("get workflow id = %v, want %s", single["workflowId"], wfID)
	}
	// dryRun 应推进到 Success（status=2）
	if status, _ := single["status"].(float64); status != float64(ota.StatusSuccess) {
		t.Errorf("status = %v, want %d (Success)", single["status"], ota.StatusSuccess)
	}
}

func TestCompatGetWorkflowNotFound(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/workflow/upgrade/nonexistent", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	// 不存在时返回 SsmErr（workflow not found），但 HTTP 200（bmssm 兼容：信封内报错）
	resp := assertSsmErr(t, w.Body.Bytes(), "get nonexistent workflow")
	if !strings.Contains(resp.ErrorMessage, "not found") {
		t.Errorf("error_message = %q", resp.ErrorMessage)
	}
}

func TestCompatSCP(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/hardware/devices/scp", nil)
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
	token := loginAndGetToken(t, r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/hardware/devices/exec", nil)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	resp := assertSsmErr(t, w.Body.Bytes(), "exec")
	if resp.ErrorMessage != "exec not supported" {
		t.Errorf("exec: error_message = %q", resp.ErrorMessage)
	}
}

// ---------------------------------------------------------------
// NAT 删除参数校验测试
// ---------------------------------------------------------------

func TestCompatDeleteNATValidation(t *testing.T) {
	r := setupCompatTest(t)
	token := loginAndGetToken(t, r)

	tests := []struct {
		name string
		num  string
		want int // 期望 HTTP 状态码
	}{
		{"valid number", "1", http.StatusInternalServerError}, // iptables 调用可能失败但不会挂
		{"invalid text", "abc", http.StatusBadRequest},
		{"zero", "0", http.StatusBadRequest},
		{"injection semicolon", "1;cat", http.StatusBadRequest},
		{"injection pipe", "1|ls", http.StatusBadRequest},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodDelete, "/bitmain/v1/ssm/hardware/nat/PREROUTING-"+tt.num, nil)
				req.Header.Set("Authorization", "Bearer "+token)
			r.ServeHTTP(w, req)

			if w.Code != tt.want {
				t.Errorf("%s: status = %d, want %d body=%s", tt.name, w.Code, tt.want, w.Body.String())
			}
		})
	}
}

// ---------------------------------------------------------------
// 未注册路由测试（确保不泄露）
// ---------------------------------------------------------------

func TestCompatNoLeakToAPIV1(t *testing.T) {
	r := setupCompatTest(t)

	// /api/v1/* 不应受兼容路由影响
	// 兼容路由不应该注册在 /api/v1 下
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewBuffer([]byte(`{"userName":"admin","password":"admin"}`)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	// 这应该返回 404 因为我们只注册了 compat 路由，没注册 /api/v1
	if w.Code == http.StatusOK {
		// 如果这里有响应，确认它不是 SsmResult 格式（可能是别的原因）
		var ssm SsmResult
		if json.Unmarshal(w.Body.Bytes(), &ssm) == nil && ssm.Code == 0 {
			t.Errorf("/api/v1/login should not be registered in this test router, got SsmResult")
		}
	}
}

// ---------------------------------------------------------------
// 端到端 sophliteos 模拟测试
// ---------------------------------------------------------------

func TestSophliteosE2EFlow(t *testing.T) {
	r := setupCompatTest(t)

	// Step 1: Login
	loginBody, _ := json.Marshal(LoginRequest{UserName: "admin", Password: "admin"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/login", bytes.NewBuffer(loginBody))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	respLogin := assertSsmOK(t, w.Body.Bytes(), "e2e login")
	loginResult, _ := respLogin.Result.(map[string]interface{})
	token, _ := loginResult["token"].(string)
	t.Logf("e2e: got token=%s", token[:min(20, len(token))]+"...")

	// Step 2: GetCtrlBasic
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/basic", nil)
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)
	respBasic := assertSsmOK(t, w2.Body.Bytes(), "e2e basic")
	basicMap, _ := respBasic.Result.(map[string]interface{})
	t.Logf("e2e: basic has deviceName=%v", basicMap["chipSn"])

	// Step 3: GetCtrlResource (sophliteos 取 [0])
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/device/resource/list", nil)
	req3.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w3, req3)
	respResource := assertSsmOK(t, w3.Body.Bytes(), "e2e resource")
	resArr, _ := respResource.Result.([]interface{})
	if len(resArr) == 0 {
		t.Fatal("e2e: resource list is empty, sophliteos would crash")
	}
	resElem, _ := resArr[0].(map[string]interface{})
	t.Logf("e2e: resource[0].deviceSn=%v", resElem["deviceSn"])

	// Step 4: GetIP
	w4 := httptest.NewRecorder()
	req4 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/hardware/ip", nil)
	req4.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w4, req4)
	respIP := assertSsmOK(t, w4.Body.Bytes(), "e2e ip")
	ipArr, _ := respIP.Result.([]interface{})
	t.Logf("e2e: ip list has %d interfaces", len(ipArr))

	// Step 5: SubscribeAlarm
	subReq := SubscribeRequest{
		Platform:            "e2e-test",
		SubscribeDetailType: []int{1, 2},
		NotificationURL:     "http://127.0.0.1:9779/api/device/alarm",
	}
	subBody, _ := json.Marshal(subReq)
	w5 := httptest.NewRecorder()
	req5 := httptest.NewRequest(http.MethodPost, "/bitmain/v1/ssm/software/notify/subscribe", bytes.NewBuffer(subBody))
	req5.Header.Set("Content-Type", "application/json")
	req5.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w5, req5)
	assertSsmOK(t, w5.Body.Bytes(), "e2e subscribe")

	// Step 6: GetSubscription by name (sophliteos uses config.Conf.GetName())
	w6 := httptest.NewRecorder()
	req6 := httptest.NewRequest(http.MethodGet, "/bitmain/v1/ssm/software/notify/subscribe/e2e-test", nil)
	req6.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w6, req6)
	respSub := assertSsmOK(t, w6.Body.Bytes(), "e2e get subscription")
	subResult, _ := respSub.Result.(map[string]interface{})
	if platform, ok := subResult["platform"].(string); !ok || platform != "e2e-test" {
		t.Errorf("e2e: subscription platform = %v", subResult["platform"])
	}
	t.Logf("e2e: all steps passed")
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ---------------------------------------------------------------
// 受保护路由 Auth 测试
// ---------------------------------------------------------------

func TestCompatEndpointsRequireAuth(t *testing.T) {
	r := setupCompatTest(t)

	// 测试受保护路由无 token 时应返回 401
	routes := []struct {
		method string
		path   string
		body   []byte
	}{
		{http.MethodGet, "/bitmain/v1/ssm/software/device/basic", nil},
		{http.MethodGet, "/bitmain/v1/ssm/software/device/resource/list", nil},
		{http.MethodGet, "/bitmain/v1/ssm/hardware/ip", nil},
		{http.MethodGet, "/bitmain/v1/ssm/hardware/nat", nil},
		{http.MethodPost, "/bitmain/v1/ssm/workflow/upgrade", []byte(`{"product":"SE7"}`)},
		{http.MethodPost, "/bitmain/v1/ssm/hardware/devices/exec", []byte(`{}`)},
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

			// 应该返回 401
			if w.Code != http.StatusUnauthorized {
				t.Errorf("%s %s: got %d, want 401 (auth required)", rt.method, rt.path, w.Code)
			}
		})
	}
}
