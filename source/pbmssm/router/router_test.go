package router

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	"bmssm/database"
	"bmssm/global"
	"bmssm/mvc/user"
	"bmssm/pkg/auth"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestHealthz(t *testing.T) {
	global.DeviceType = "soc"
	global.DeviceRole = "SE"
	global.DeviceTypeEx = "SE8"
	global.DeviceSnEx = "DEVSN456"
	global.Version = global.BuildInfo{Version: "1.0.0", GitCommit: "abc", BuildTime: "2026-01-01"}

	r := gin.New()
	Register(r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if body["status"] != "ok" {
		t.Fatalf("status=%s", body["status"])
	}
	if body["deviceType"] != "soc" {
		t.Fatalf("deviceType=%s", body["deviceType"])
	}
	if body["role"] != "SE" {
		t.Fatalf("role=%s", body["role"])
	}
	if body["deviceTypeEx"] != "SE8" {
		t.Fatalf("deviceTypeEx=%s", body["deviceTypeEx"])
	}
	if body["sn"] != "DEVSN456" {
		t.Fatalf("sn=%s", body["sn"])
	}
	if body["version"] != "1.0.0" {
		t.Fatalf("version=%s", body["version"])
	}
	if body["uptime"] == "" {
		t.Fatalf("uptime empty")
	}
}

// TestLlmProxyRoutes 验证 llm-proxy 配置路由的访问控制（MYS-386）：
// - 无 token：401（Auth 中间件拦截，路由已注册而非 404）
// - 普通用户（role=user）：403 —— P0 回归：forwardKey 是 /agent/ws 唯一凭据，
//   不得泄露给非管理员
// - 管理员（role=admin）：200，响应含完整性 forwardKey（供 WebChat WS 连接）
func TestLlmProxyRoutes(t *testing.T) {
	gin.SetMode(gin.ReleaseMode)
	// Auth 中间件读取 config.Conf；测试需先初始化（用默认值即可）
	config.LoadFromDir(t.TempDir())

	// RequireAdmin 查 users 表（database.DB() 全局句柄）；注入 user/admin 两行
	db := newRouterTestDB(t)
	oldDB := database.DB()
	database.SetDB(db)
	t.Cleanup(func() { database.SetDB(oldDB) })
	if err := db.Create(&user.User{Username: "alice", Password: "x", Role: "user"}).Error; err != nil {
		t.Fatalf("create user: %v", err)
	}
	if err := db.Create(&user.User{Username: "root", Password: "x", Role: "admin"}).Error; err != nil {
		t.Fatalf("create admin: %v", err)
	}

	r := gin.New()
	Register(r)

	// GET 无 token → 401（路由存在且被 Auth 拦截）
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/llm-proxy/config", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("GET config without token = %d, want 401", w.Code)
	}

	// PUT 无 token → 401
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPut, "/api/v1/llm-proxy/config", nil)
	r.ServeHTTP(w2, req2)
	if w2.Code != http.StatusUnauthorized {
		t.Fatalf("PUT config without token = %d, want 401", w2.Code)
	}

	// 普通用户 GET → 403
	w3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodGet, "/api/v1/llm-proxy/config", nil)
	req3.Header.Set("Authorization", "Bearer "+issueTestToken(t, "alice"))
	r.ServeHTTP(w3, req3)
	if w3.Code != http.StatusForbidden {
		t.Fatalf("GET config with user token = %d, want 403, body=%s", w3.Code, w3.Body.String())
	}

	// 管理员 GET → 200 且返回完整性 forwardKey（WebChat WS 连接依赖）
	w4 := httptest.NewRecorder()
	req4 := httptest.NewRequest(http.MethodGet, "/api/v1/llm-proxy/config", nil)
	req4.Header.Set("Authorization", "Bearer "+issueTestToken(t, "root"))
	r.ServeHTTP(w4, req4)
	if w4.Code != http.StatusOK {
		t.Fatalf("GET config with admin token = %d, want 200, body=%s", w4.Code, w4.Body.String())
	}
	var out struct {
		Code   int `json:"code"`
		Result struct {
			ForwardKey string `json:"forwardKey"`
		} `json:"result"`
	}
	if err := json.Unmarshal(w4.Body.Bytes(), &out); err != nil {
		t.Fatalf("unmarshal admin response: %v body=%s", err, w4.Body.String())
	}
	if out.Code != 0 {
		t.Fatalf("admin GET code = %d, body=%s", out.Code, w4.Body.String())
	}
	if out.Result.ForwardKey == "" {
		t.Errorf("admin GET returned empty forwardKey, body=%s", w4.Body.String())
	}
}

// newRouterTestDB 建临时 sqlite：迁移 RequireAdmin 需要的 users 表及
// 已注册业务模型（llmproxy Config 等，保证 GetConfig 可落库读配置）。
func newRouterTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open("sqlite3", filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	if err := db.AutoMigrate(&user.User{}).Error; err != nil {
		t.Fatalf("migrate users: %v", err)
	}
	if err := database.Migrate(db); err != nil {
		t.Fatalf("migrate registered models: %v", err)
	}
	return db
}

// issueTestToken 用默认/持久化 secret 签发测试 JWT（与 Auth 中间件同 secret）。
func issueTestToken(t *testing.T, username string) string {
	t.Helper()
	tok, _, err := auth.IssueToken(username, auth.EffectiveSecret(""), false)
	if err != nil {
		t.Fatalf("issue token for %s: %v", username, err)
	}
	return tok
}
