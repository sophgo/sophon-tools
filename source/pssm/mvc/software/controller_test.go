package software

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/middleware"
	"ssm/pkg/auth"
	"ssm/pkg/response"
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

// decodeErrorEnvelope 解析失败信封。
func decodeErrorEnvelope(t *testing.T, body []byte) response.Result {
	t.Helper()
	var env response.Result
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("unmarshal envelope: %v body=%s", err, body)
	}
	if env.Code != 1 {
		t.Fatalf("expected envelope code=1, got %d body=%s", env.Code, body)
	}
	return env
}

func setupSoftwareTest(t *testing.T) {
	t.Helper()
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}
}

func makeToken() string {
	secret := config.Conf.GetViper().GetString("server.authSecret")
	if secret == "" {
		secret = "ssm-dev-secret"
	}
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)
	return tokenStr
}

// setupTestService 创建用独立 tempdir 的 SoftwareService，返回 svc 和 controller。
func setupTestService(t *testing.T) (*SoftwareService, *Controller) {
	t.Helper()
	root := t.TempDir()
	svc := NewSoftwareService(root, t.TempDir(), t.TempDir(), DefaultMaxSize)
	ctrl := NewController(svc)
	return svc, ctrl
}

// setupRouter 创建带 Auth 中间件的测试路由，注入指定 controller。
func setupSoftwareRouter(ctrl *Controller) *gin.Engine {
	r := gin.New()
	// 设置 multipart 内存限制
	r.MaxMultipartMemory = 64 << 20
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	{
		api.GET("/software", ctrl.ListSoftware)
		api.POST("/software/install", ctrl.Install)
		api.POST("/software/upgrade", ctrl.Upgrade)
		api.POST("/ota/upload", ctrl.OTAUpload)
		api.GET("/ota/download/:id", ctrl.OTADownload)
		api.POST("/ota/upgrade", ctrl.OTAUpgrade)
	}
	return r
}

// ----------------------------------------------------------------
// multipart 文件上传辅助
// ----------------------------------------------------------------

// createMultipartBody 创建含文件的 multipart/form-data 请求体。
func createMultipartBody(fieldName, fileName, content string) (*bytes.Buffer, string) {
	buf := new(bytes.Buffer)
	w := multipart.NewWriter(buf)
	part, _ := w.CreateFormFile(fieldName, fileName)
	io.WriteString(part, content)
	w.Close()
	return buf, w.FormDataContentType()
}

// ----------------------------------------------------------------
// 软件列表
// ----------------------------------------------------------------

func TestControllerListSoftware(t *testing.T) {
	setupSoftwareTest(t)
	svc, ctrl := setupTestService(t)

	// 创建一些测试模块
	os.MkdirAll(filepath.Join(svc.softwareRoot, "module1"), 0o755)
	os.WriteFile(filepath.Join(svc.softwareRoot, "module1", "VERSION"), []byte("1.0.0\n"), 0o644)
	os.MkdirAll(filepath.Join(svc.softwareRoot, "module2"), 0o755)
	os.WriteFile(filepath.Join(svc.softwareRoot, "module2", "version"), []byte("2.0.0\n"), 0o644)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/software", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var result []SoftwareInfo
	decodeResult(t, w.Body.Bytes(), &result)
	if len(result) != 2 {
		t.Fatalf("expected 2 modules, got %d", len(result))
	}
}

// ----------------------------------------------------------------
// 软件安装（multipart 上传）
// ----------------------------------------------------------------

func TestControllerInstallTarGz(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	// 创建测试 tar.gz
	body, contentType := createMultipartBody("file", "testpkg.tar.gz",
		makeTarGzString(t, map[string]string{"VERSION": "1.0.0\n"}))

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp InstallResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if !resp.Success {
		t.Fatalf("expected success=true, got %+v", resp)
	}
}

func TestControllerInstallMissingFile(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	// 缺少 Content-Type 和 multipart body
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestControllerInstallInvalidFileName(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	// Go 的 multipart 解析器自动剥离路径部分，返回 base name。
	// 但非法字符（如分号、空格等注入字符）仍会被 isValidPackageName 拒绝。
	body, contentType := createMultipartBody("file", "test;rm-rf.tar.gz", "evil")

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for invalid filename chars, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestControllerInstallUnsupportedFormat(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	body, contentType := createMultipartBody("file", "test.rar", "contents")

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// 软件升级
// ----------------------------------------------------------------

func TestControllerUpgrade(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	body, contentType := createMultipartBody("file", "upgrade-pkg.tar.gz",
		makeTarGzString(t, map[string]string{"VERSION": "2.0.0\n"}))

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/upgrade", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var resp InstallResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if !resp.Success {
		t.Errorf("expected success=true, got %+v", resp)
	}
}

// ----------------------------------------------------------------
// OTA 上传
// ----------------------------------------------------------------

func TestControllerOTAUpload(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	body, contentType := createMultipartBody("file", "firmware_v1.tgz",
		makeTarGzString(t, map[string]string{"upgrade.sh": "#!/bin/sh\necho ok"}))

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upload", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp OTAUploadResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.UploadID == "" {
		t.Fatal("uploadId should not be empty")
	}
}

func TestControllerOTAUploadInvalidName(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	body, contentType := createMultipartBody("file", "evil.exe", "bad")

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upload", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// OTA 下载/查询
// ----------------------------------------------------------------

func TestControllerOTADownload(t *testing.T) {
	setupSoftwareTest(t)
	svc, ctrl := setupTestService(t)

	// 先上传一个固件
	fwPath := filepath.Join(t.TempDir(), "fw.tgz")
	os.WriteFile(fwPath, []byte("data"), 0o644)
	uploadResp, _ := svc.UploadFirmware(fwPath, "fw.tgz", 4)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ota/download/"+uploadResp.UploadID, nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp OTADownloadResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.FileName != "fw.tgz" {
		t.Errorf("fileName: %s", resp.FileName)
	}
}

func TestControllerOTADownloadNotFound(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ota/download/nonexistent", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// OTA 升级
// ----------------------------------------------------------------

func TestControllerOTAUpgrade(t *testing.T) {
	setupSoftwareTest(t)
	svc, ctrl := setupTestService(t)

	// 创建含 upgrade.sh 的固件
	fwContent := map[string]string{
		"upgrade.sh": "#!/bin/sh\necho 'upgrade done'",
	}
	fwPath := createTestTarGz(t, fwContent)
	uploadResp, _ := svc.UploadFirmware(fwPath, "fw_upgrade.tgz", 100)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade?uploadId="+uploadResp.UploadID, nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp OTAUpgradeResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if !resp.Available {
		t.Fatal("expected available=true")
	}
	if !resp.Success {
		t.Errorf("expected success=true, got %+v", resp)
	}
}

func TestControllerOTAUpgradeDegraded(t *testing.T) {
	setupSoftwareTest(t)
	svc, ctrl := setupTestService(t)

	// 固件不含升级脚本
	fwContent := map[string]string{
		"data.bin": "raw data",
	}
	fwPath := createTestTarGz(t, fwContent)
	uploadResp, _ := svc.UploadFirmware(fwPath, "fw_no_script.tgz", 100)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade?uploadId="+uploadResp.UploadID, nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}

	var resp OTAUpgradeResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Available {
		t.Fatal("expected available=false for firmware without upgrade script")
	}
}

func TestControllerOTAUpgradeMissingUploadId(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// 401 认证测试
// ----------------------------------------------------------------

func TestSoftwareEndpointsWithoutToken(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)
	r := setupSoftwareRouter(ctrl)

	endpoints := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/api/v1/software"},
		{http.MethodPost, "/api/v1/software/install"},
		{http.MethodPost, "/api/v1/software/upgrade"},
		{http.MethodPost, "/api/v1/ota/upload"},
		{http.MethodGet, "/api/v1/ota/download/test-id"},
		{http.MethodPost, "/api/v1/ota/upgrade?uploadId=test"},
	}

	for _, ep := range endpoints {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(ep.method, ep.path, nil)
		r.ServeHTTP(w, req)

		if w.Code != http.StatusUnauthorized {
			t.Errorf("expected 401 for %s %s, got %d body=%s", ep.method, ep.path, w.Code, w.Body.String())
		}
	}
}

// ----------------------------------------------------------------
// 文件大小限制测试
// ----------------------------------------------------------------

func TestControllerInstallFileTooLarge(t *testing.T) {
	setupSoftwareTest(t)
	// 使用很小的 maxSize 模拟超限
	svc := NewSoftwareService(t.TempDir(), t.TempDir(), t.TempDir(), 10) // max 10 bytes
	ctrl := NewController(svc)

	body, contentType := createMultipartBody("file", "pkg.tar.gz",
		makeTarGzString(t, map[string]string{"a": "this is more than 10 bytes"}))

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", w.Code, w.Body.String())
	}

	env := decodeErrorEnvelope(t, w.Body.Bytes())
	if !strings.Contains(env.ErrorMessage, "file too large") {
		t.Errorf("expected error_message containing 'file too large', got %q", env.ErrorMessage)
	}
}

// ----------------------------------------------------------------
// 辅助：在内存中创建 tar.gz 字符串
// ----------------------------------------------------------------

func makeTarGzString(t *testing.T, files map[string]string) string {
	t.Helper()
	path := createTestTarGz(t, files)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read test tar.gz: %v", err)
	}
	return string(data)
}

// ----------------------------------------------------------------
// 并发安全
// ----------------------------------------------------------------

func TestControllerConcurrentUploads(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)
	r := setupSoftwareRouter(ctrl)

	tgzData := createTarGzBytes(t, map[string]string{"VERSION": "1.0\n"})

	done := make(chan int, 5)
	for i := range 5 {
		go func(idx int) {
			// 每个 goroutine 使用唯一文件名，避免并发写同一文件
			fname := fmt.Sprintf("pkg%d.tar.gz", idx)
			body, contentType := createMultipartFileBody(t, "file", fname, tgzData)
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
			req.Header.Set("Authorization", "Bearer "+makeToken())
			req.Header.Set("Content-Type", contentType)
			r.ServeHTTP(w, req)
			done <- w.Code
		}(i)
	}

	for range 5 {
		code := <-done
		if code != http.StatusOK {
			t.Errorf("concurrent upload got %d", code)
		}
	}
}

// ----------------------------------------------------------------
// tar.gz 内容构造（用于 multipart body，直接生成字节流）
// ----------------------------------------------------------------

func init() {
	// 确保 gin 在 Release 模式
	gin.SetMode(gin.ReleaseMode)
}

// createTarGzBytes 在内存中创建 tar.gz 字节流。
func createTarGzBytes(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var err error
	path := createTestTarGz(t, files)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read tar.gz: %v", err)
	}
	return data
}

// createMultipartFileBody 创建含文件内容的 multipart body（使用实际文件内容）。
func createMultipartFileBody(t *testing.T, fieldName, fileName string, content []byte) (*bytes.Buffer, string) {
	t.Helper()
	buf := new(bytes.Buffer)
	w := multipart.NewWriter(buf)
	part, _ := w.CreateFormFile(fieldName, fileName)
	part.Write(content)
	w.Close()
	return buf, w.FormDataContentType()
}

// TestControllerInstallWithTarGzBytes 使用真实 tar.gz 字节流测试安装。
func TestControllerInstallWithTarGzBytes(t *testing.T) {
	setupSoftwareTest(t)
	_, ctrl := setupTestService(t)

	tgzData := createTarGzBytes(t, map[string]string{
		"app/":    "",
		"VERSION": "3.0.0\n",
	})
	body, contentType := createMultipartFileBody(t, "file", "myapp.tar.gz", tgzData)

	r := setupSoftwareRouter(ctrl)
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/software/install", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var resp InstallResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if !resp.Success {
		t.Errorf("expected success=true, got %+v", resp)
	}
}

// TestControllerOTAUpgradeWithScriptInBody 上传含脚本的固件，然后升级。
func TestControllerOTAUpgradeWithScriptInBody(t *testing.T) {
	setupSoftwareTest(t)
	svc, ctrl := setupTestService(t)
	r := setupSoftwareRouter(ctrl)

	// 上传固件
	tgzData := createTarGzBytes(t, map[string]string{
		"install.sh": "#!/bin/sh\necho 'flash done'",
	})
	body, contentType := createMultipartFileBody(t, "file", "update.tgz", tgzData)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upload", body)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	req.Header.Set("Content-Type", contentType)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("upload: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var uploadResp OTAUploadResponse
	decodeResult(t, w.Body.Bytes(), &uploadResp)
	if uploadResp.UploadID == "" {
		t.Fatal("uploadId empty")
	}

	// 执行升级
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/ota/upgrade?uploadId="+uploadResp.UploadID, nil)
	req2.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusOK {
		t.Fatalf("upgrade: expected 200, got %d body=%s", w2.Code, w2.Body.String())
	}

	var upResp OTAUpgradeResponse
	decodeResult(t, w2.Body.Bytes(), &upResp)
	if !upResp.Available {
		t.Fatal("expected available=true")
	}

	// 验证状态
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/api/v1/ota/download/"+uploadResp.UploadID, nil)
	req3.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w3, req3)

	var dlResp OTADownloadResponse
	decodeResult(t, w3.Body.Bytes(), &dlResp)
	if dlResp.Status != "completed" {
		t.Errorf("expected status 'completed', got '%s'", dlResp.Status)
	}

	_ = svc // suppress unused warning
}
