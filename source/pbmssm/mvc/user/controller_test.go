package user

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	"bmssm/middleware"
	"bmssm/mvc/audit"
	"bmssm/pkg/auth"
	"bmssm/pkg/response"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func setupController(t *testing.T) (*Controller, *audit.AuditService, func()) {
	t.Helper()
	db := setupTestDB(t)

	// 确保 config 可读
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}

	svc := NewService(db)
	audSvc := audit.NewService(db)
	ctrl := NewController(svc, audSvc)

	cleanup := func() { db.Close() }
	return ctrl, audSvc, cleanup
}

func TestLoginSuccess(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	// 创建用户
	_ = ctrl.svc.CreateUser("testuser", "password123", "user")

	r := gin.New()
	r.POST("/api/v1/login", ctrl.Login)

	body, _ := json.Marshal(LoginRequest{Username: "testuser", Password: "password123"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if resp.Code != 0 {
		t.Fatalf("expected code=0, got %d body=%s", resp.Code, w.Body.String())
	}
	raw, _ := json.Marshal(resp.Result)
	var lr LoginResponse
	if err := json.Unmarshal(raw, &lr); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if lr.Token == "" {
		t.Fatal("token should not be empty")
	}
}

func TestLoginWrongPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("testuser", "password123", "user")

	r := gin.New()
	r.POST("/api/v1/login", ctrl.Login)

	body, _ := json.Marshal(LoginRequest{Username: "testuser", Password: "wrong"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestLoginWritesAuditLog 登录成功后应写入审计日志。
func TestLoginWritesAuditLog(t *testing.T) {
	ctrl, audSvc, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("audituser", "pwd123", "user")

	r := gin.New()
	r.POST("/api/v1/login", ctrl.Login)

	body, _ := json.Marshal(LoginRequest{Username: "audituser", Password: "pwd123"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("login: %d body=%s", w.Code, w.Body.String())
	}

	result, err := audSvc.ListLogs(0, 10)
	if err != nil {
		t.Fatalf("ListLogs: %v", err)
	}
	if result.Total != 1 {
		t.Fatalf("expected 1 audit log, got %d", result.Total)
	}
	if result.Logs[0].Action != "login" {
		t.Fatalf("expected action login, got %s", result.Logs[0].Action)
	}
	if result.Logs[0].Username != "audituser" {
		t.Fatalf("expected username audituser, got %s", result.Logs[0].Username)
	}
	if result.Logs[0].Result != "success" {
		t.Fatalf("expected result success, got %s", result.Logs[0].Result)
	}
}

// TestLoginFailedWritesAuditLog 登录失败也应写入审计日志（用请求体 username）。
func TestLoginFailedWritesAuditLog(t *testing.T) {
	ctrl, audSvc, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("realuser", "pwd123", "user")

	r := gin.New()
	r.POST("/api/v1/login", ctrl.Login)

	body, _ := json.Marshal(LoginRequest{Username: "realuser", Password: "wrong"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/login", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}

	result, _ := audSvc.ListLogs(0, 10)
	if result.Total != 1 {
		t.Fatalf("expected 1 audit log, got %d", result.Total)
	}
	if result.Logs[0].Result != "failed" {
		t.Fatalf("expected result failed, got %s", result.Logs[0].Result)
	}
}

func TestLogout(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/logout", ctrl.Logout)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/logout", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestListUsersWithAuth(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("alice", "pass1", "admin")
	_ = ctrl.svc.CreateUser("bob", "pass2", "user")

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/user", ctrl.ListUsers)

	// 签发 token
	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("alice", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var usersResp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &usersResp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if usersResp.Code != 0 {
		t.Fatalf("expected code=0, got %d body=%s", usersResp.Code, w.Body.String())
	}
	raw, _ := json.Marshal(usersResp.Result)
	var users []UserResponse
	if err := json.Unmarshal(raw, &users); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if len(users) != 2 {
		t.Fatalf("expected 2 users, got %d", len(users))
	}
}

func TestListUsersWithoutToken(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/user", ctrl.ListUsers)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestCreateUser(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/user", ctrl.CreateUser)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	body, _ := json.Marshal(CreateUserRequest{Username: "newuser", Password: "newpass", Role: "user"})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/user", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	// 验证新用户可登录
	_, err := ctrl.svc.Login("newuser", "newpass")
	if err != nil {
		t.Fatalf("new user should be able to login: %v", err)
	}
}

func TestControllerDeleteUser(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()

	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")
	_ = ctrl.svc.CreateUser("victim", "pwd", "user")

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.DELETE("/user/:name", ctrl.DeleteUser)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/user/victim", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	// 确认已删除
	_, err := ctrl.svc.Login("victim", "pwd")
	if err == nil {
		t.Fatal("victim should not be able to login after deletion")
	}
}
