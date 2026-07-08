package docker

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/middleware"
	"ssm/pkg/auth"
	"ssm/pkg/response"

	dockerclient "github.com/fsouza/go-dockerclient"
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

// decodeErrorEnvelope 解析失败信封，返回 (ErrorMessage, Code)。
func decodeErrorEnvelope(t *testing.T, body []byte) response.Result {
	t.Helper()
	var env response.Result
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("unmarshal envelope: %v body=%s", err, body)
	}
	return env
}

func setupDockerTest(t *testing.T) {
	t.Helper()
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}
}

// makeToken 签发测试 token。
func makeToken() string {
	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)
	return tokenStr
}

// setupRouter 创建带 Auth 中间件的测试路由，注入指定 controller。
func setupRouter(ctrl *Controller) *gin.Engine {
	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	{
		api.GET("/docker/container", ctrl.ListContainers)
		api.POST("/docker/container/:name/start", ctrl.StartContainer)
		api.POST("/docker/container/:name/stop", ctrl.StopContainer)
		api.DELETE("/docker/container/:name", ctrl.RemoveContainer)
		api.GET("/docker/image", ctrl.ListImages)
		api.DELETE("/docker/image/:id", ctrl.RemoveImage)
		api.GET("/docker/logs/:name", ctrl.GetLogs)
	}
	return r
}

// fakeWithContainers 创建注入 fake 数据的 controller。
func fakeWithContainers(t *testing.T) *Controller {
	t.Helper()
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	fake.images = fakeImages()
	fake.logs["nginx"] = "fake log line 1\nfake log line 2\n"
	return NewController(NewDockerServiceWithClient(fake))
}

// ----------------------------------------------------------------
// Endpoint 测试
// ----------------------------------------------------------------

func TestListContainersWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/container", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var containers []ContainerSummary
	decodeResult(t, w.Body.Bytes(), &containers)
	if len(containers) != 2 {
		t.Fatalf("expected 2 containers, got %d", len(containers))
	}
}

func TestListContainersWithStatusFilter(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/container?status=running", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var containers []ContainerSummary
	decodeResult(t, w.Body.Bytes(), &containers)
	if len(containers) != 1 {
		t.Fatalf("expected 1 running container, got %d", len(containers))
	}
}

func TestStartContainerWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/nginx/start", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestStopContainerWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/nginx/stop", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestStopContainerWithTimeout(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/nginx/stop?timeout=5", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestRemoveContainerWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/container/redis", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestRemoveContainerForce(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/container/nginx?force=true", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestListImagesWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/image", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var images []ImageSummary
	decodeResult(t, w.Body.Bytes(), &images)
	if len(images) != 2 {
		t.Fatalf("expected 2 images, got %d", len(images))
	}
}

func TestRemoveImageWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/image/sha256:aaa", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestGetLogsWithAuth(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/logs/nginx?tail=50", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp LogsResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Logs == "" {
		t.Fatal("expected non-empty logs")
	}
}

// ----------------------------------------------------------------
// 降级测试（available=false）
// ----------------------------------------------------------------

func TestDegradedListContainers(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/container", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}

	var resp DegradedResponse
	decodeResult(t, w.Body.Bytes(), &resp)
	if resp.Available {
		t.Fatal("expected available=false")
	}
}

func TestDegradedStartContainer(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/test/start", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

func TestDegradedStopContainer(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/test/stop", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

func TestDegradedRemoveContainer(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/container/test", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

func TestDegradedListImages(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/image", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

func TestDegradedRemoveImage(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/image/sha256:abc", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

func TestDegradedGetLogs(t *testing.T) {
	setupDockerTest(t)
	ctrl := NewController(NewDegradedService())
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/logs/test", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (degraded), got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// 401 认证测试
// ----------------------------------------------------------------

func TestDockerEndpointsWithoutToken(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	endpoints := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/api/v1/docker/container"},
		{http.MethodPost, "/api/v1/docker/container/test/start"},
		{http.MethodPost, "/api/v1/docker/container/test/stop"},
		{http.MethodDelete, "/api/v1/docker/container/test"},
		{http.MethodGet, "/api/v1/docker/image"},
		{http.MethodDelete, "/api/v1/docker/image/sha256:abc"},
		{http.MethodGet, "/api/v1/docker/logs/test"},
	}

	for _, ep := range endpoints {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(ep.method, ep.path, nil)
		r.ServeHTTP(w, req)

		if w.Code != http.StatusUnauthorized {
			t.Errorf("expected 401 for %s %s, got %d", ep.method, ep.path, w.Code)
		}
	}
}

// ----------------------------------------------------------------
// 参数校验测试（注入防护）
// ----------------------------------------------------------------

func TestInvalidContainerName(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	// 使用 URL 安全的注入尝试，但包含非法字符
	badNames := []string{
		"test%3Brm-rf",    // 包含 % 非法字符
		"test%24(whoami)", // 包含 $ (encoded as %24) 的非法字符
		"test%60ls%60",    // 包含 ` (encoded as %60) 非法字符
	}

	for _, name := range badNames {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/"+name+"/start", nil)
		req.Header.Set("Authorization", "Bearer "+makeToken())
		r.ServeHTTP(w, req)

		if w.Code != http.StatusBadRequest {
			t.Errorf("expected 400 for bad name %q, got %d body=%s", name, w.Code, w.Body.String())
		}
	}
}

func TestEmptyContainerName(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	// 空 name param（gin 路由不会匹配，改为用缺少 param 的路径）
	// 直接用 /start 不包含 :name — gin 不会路由到该 handler
	// 这里测试 handler 层面的防护：如果路由匹配到空 name，validateName 会返回 400
	// 我们测 controller 层面的 name 校验
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/docker/container/!@#/start", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400 for invalid name, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestInvalidImageID(t *testing.T) {
	setupDockerTest(t)
	ctrl := fakeWithContainers(t)
	r := setupRouter(ctrl)

	// 包含非法字符的镜像 ID
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/docker/image/test%3Brm-rf", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400 for bad image id, got %d body=%s", w.Code, w.Body.String())
	}
}

// ----------------------------------------------------------------
// docker API 错误 502 测试
// ----------------------------------------------------------------

func TestDockerErrorReturns502(t *testing.T) {
	setupDockerTest(t)
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	fake.listContainersErr = &dockerclient.Error{Status: 500, Message: "docker internal error"}
	ctrl := NewController(NewDockerServiceWithClient(fake))
	r := setupRouter(ctrl)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/docker/container", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken())
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 for docker error, got %d body=%s", w.Code, w.Body.String())
	}

	env := decodeErrorEnvelope(t, w.Body.Bytes())
	if env.Code != 1 {
		t.Errorf("expected envelope code=1, got %d", env.Code)
	}
	if !strings.Contains(env.ErrorMessage, "docker internal error") {
		t.Errorf("expected error_message containing 'docker internal error', got %q", env.ErrorMessage)
	}
}

// ----------------------------------------------------------------
// 并发安全（NewDockerServiceWithClient 不应 panic）
// ----------------------------------------------------------------

func TestNewDockerServiceWithClientConcurrently(t *testing.T) {
	done := make(chan struct{})
	for range 10 {
		go func() {
			fake := newFakeDockerClient()
			svc := NewDockerServiceWithClient(fake)
			if !svc.IsAvailable() {
				t.Error("expected available=true")
			}
			done <- struct{}{}
		}()
	}
	for range 10 {
		<-done
	}
}
