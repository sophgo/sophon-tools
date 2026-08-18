package user

// 默认凭据接管链安全测试（MYS-385）：
//   - 默认密码登录只能拿到 temp token（changePass=true）
//   - temp token 仅能用于改密（其余端点 403）
//   - temp 改密必须校验旧密码
//   - 新密码不得等于默认密码
//   - temp 改密成功不签发正式 token，强制重新登录
//   - 改密后默认密码永久失效，新密码登录拿到正式 token

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
	"bmssm/pkg/response"
)

// setupSecurityRouter 挂载 login/password/user 路由（password 与 user 走真实 Auth 中间件，
// 使 c.Get("user")/c.Get("temp") 与线上一致）。
func setupSecurityRouter(ctrl *Controller) *gin.Engine {
	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	{
		api.POST("/password", ctrl.ChangePassword)
		api.GET("/user", ctrl.ListUsers)
	}
	r.POST("/api/v1/login", ctrl.Login)
	return r
}

func securitySecret() string {
	return auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
}

func securityDoJSON(t *testing.T, r http.Handler, method, path, token string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		reader = bytes.NewReader(b)
	} else {
		reader = bytes.NewReader(nil)
	}
	w := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	r.ServeHTTP(w, req)
	return w
}

// securityLogin 登录并解析 LoginResponse。
func securityLogin(t *testing.T, r http.Handler, username, password string) (*httptest.ResponseRecorder, LoginResponse) {
	t.Helper()
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/login", "", LoginRequest{Username: username, Password: password})
	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal login envelope: %v body=%s", err, w.Body.String())
	}
	raw, _ := json.Marshal(resp.Result)
	var lr LoginResponse
	if err := json.Unmarshal(raw, &lr); err != nil {
		t.Fatalf("unmarshal login result: %v body=%s", err, w.Body.String())
	}
	return w, lr
}

// TestLoginDefaultPasswordIssuesOnlyTempToken 用默认密码登录必须签发 temp token 并标记 changePass。
func TestLoginDefaultPasswordIssuesOnlyTempToken(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	r := setupSecurityRouter(ctrl)
	w, lr := securityLogin(t, r, "admin", "admin")
	if w.Code != http.StatusOK {
		t.Fatalf("login with default password: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	if !lr.ChangePass {
		t.Fatal("expected changePass=true for default password login")
	}
	if lr.Token == "" {
		t.Fatal("expected temp token to be issued")
	}
	username, temp, err := auth.ParseToken(lr.Token, securitySecret())
	if err != nil {
		t.Fatalf("parse temp token: %v", err)
	}
	if username != "admin" {
		t.Fatalf("expected username admin, got %s", username)
	}
	if !temp {
		t.Fatal("expected token to carry temp=true")
	}
}

// TestTempTokenCannotAccessOtherEndpoints temp token 访问改密之外的端点必须 403。
func TestTempTokenCannotAccessOtherEndpoints(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	tempToken, _, err := auth.IssueToken("admin", securitySecret(), true)
	if err != nil {
		t.Fatalf("issue temp token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodGet, "/api/v1/user", tempToken, nil)
	if w.Code != http.StatusForbidden {
		t.Fatalf("temp token on /api/v1/user: expected 403, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestTempChangePasswordRejectsWrongOldPassword temp 改密也须校验旧密码（当前密码=默认密码）。
func TestTempChangePasswordRejectsWrongOldPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	tempToken, _, err := auth.IssueToken("admin", securitySecret(), true)
	if err != nil {
		t.Fatalf("issue temp token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", tempToken,
		ChangePasswordRequest{OldPassword: "wrong-old", NewPassword: "NewPass123"})
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("temp change password with wrong old password: expected 401, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestTempChangePasswordRejectsDefaultNewPassword 新密码不得等于默认密码（防止改密后默认凭据仍有效）。
func TestTempChangePasswordRejectsDefaultNewPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	tempToken, _, err := auth.IssueToken("admin", securitySecret(), true)
	if err != nil {
		t.Fatalf("issue temp token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", tempToken,
		ChangePasswordRequest{OldPassword: "admin", NewPassword: "admin"})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("temp change password to default password: expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestChangePasswordRequiresOldPassword 改密请求必须提供旧密码。
func TestChangePasswordRequiresOldPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	tempToken, _, err := auth.IssueToken("admin", securitySecret(), true)
	if err != nil {
		t.Fatalf("issue temp token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", tempToken,
		ChangePasswordRequest{OldPassword: "", NewPassword: "NewPass123"})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("change password without old password: expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestTempChangePasswordSuccessForcesReLogin temp 改密成功：
// 不签发正式 token；旧默认密码失效；新密码登录返回正式 token 且 changePass=false。
func TestTempChangePasswordSuccessForcesReLogin(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("admin", "admin", "superuser")

	tempToken, _, err := auth.IssueToken("admin", securitySecret(), true)
	if err != nil {
		t.Fatalf("issue temp token: %v", err)
	}
	r := setupSecurityRouter(ctrl)

	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", tempToken,
		ChangePasswordRequest{OldPassword: "admin", NewPassword: "NewPass123"})
	if w.Code != http.StatusOK {
		t.Fatalf("temp change password: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	// 响应中不得携带可直接使用的正式 token
	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal envelope: %v", err)
	}
	raw, _ := json.Marshal(resp.Result)
	var cpr ChangePasswordResponse
	if err := json.Unmarshal(raw, &cpr); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if cpr.Token != "" {
		t.Fatalf("temp change password must not return a formal token, got %q", cpr.Token)
	}

	// 改密后：默认密码登录必须失败
	w2, _ := securityLogin(t, r, "admin", "admin")
	if w2.Code == http.StatusOK {
		t.Fatal("login with default password must fail after password changed")
	}

	// 新密码登录：正常签发正式 token，changePass=false
	w3, lr := securityLogin(t, r, "admin", "NewPass123")
	if w3.Code != http.StatusOK {
		t.Fatalf("login with new password: expected 200, got %d body=%s", w3.Code, w3.Body.String())
	}
	if lr.ChangePass {
		t.Fatal("expected changePass=false after password changed")
	}
	_, temp, err := auth.ParseToken(lr.Token, securitySecret())
	if err != nil {
		t.Fatalf("parse new token: %v", err)
	}
	if temp {
		t.Fatal("expected formal token after real password login")
	}
	// 正式 token 可访问其他端点
	w4 := securityDoJSON(t, r, http.MethodGet, "/api/v1/user", lr.Token, nil)
	if w4.Code != http.StatusOK {
		t.Fatalf("formal token on /api/v1/user: expected 200, got %d body=%s", w4.Code, w4.Body.String())
	}
}

// TestFormalChangePasswordRejectsWrongOldPassword 正式 token 改密仍须校验旧密码（既有行为回归）。
func TestFormalChangePasswordRejectsWrongOldPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("alice", "pass123", "user")

	formalToken, _, err := auth.IssueToken("alice", securitySecret(), false)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", formalToken,
		ChangePasswordRequest{OldPassword: "wrong", NewPassword: "NewPass456"})
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("formal change password with wrong old password: expected 401, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestFormalChangePasswordRejectsDefaultNewPassword 正式改密同样禁止将密码改回默认值。
func TestFormalChangePasswordRejectsDefaultNewPassword(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("alice", "pass123", "user")

	formalToken, _, err := auth.IssueToken("alice", securitySecret(), false)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", formalToken,
		ChangePasswordRequest{OldPassword: "pass123", NewPassword: "admin"})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("formal change password to default: expected 400, got %d body=%s", w.Code, w.Body.String())
	}
}

// TestFormalChangePasswordSuccessReturnsNewToken 正式 token 改密成功返回新正式 token（既有行为回归）。
func TestFormalChangePasswordSuccessReturnsNewToken(t *testing.T) {
	ctrl, _, cleanup := setupController(t)
	defer cleanup()
	_ = ctrl.svc.CreateUser("alice", "pass123", "user")

	formalToken, _, err := auth.IssueToken("alice", securitySecret(), false)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	r := setupSecurityRouter(ctrl)
	w := securityDoJSON(t, r, http.MethodPost, "/api/v1/password", formalToken,
		ChangePasswordRequest{OldPassword: "pass123", NewPassword: "NewPass456"})
	if w.Code != http.StatusOK {
		t.Fatalf("formal change password: expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal envelope: %v", err)
	}
	raw, _ := json.Marshal(resp.Result)
	var cpr ChangePasswordResponse
	if err := json.Unmarshal(raw, &cpr); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if cpr.Token == "" {
		t.Fatal("formal change password must return a new formal token")
	}
	// 新密码可登录
	if _, err := ctrl.svc.Login("alice", "NewPass456"); err != nil {
		t.Fatalf("new password should work after change: %v", err)
	}
}