package user

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/database"
	"bmssm/mvc/audit"
	"bmssm/pkg/auth"
	"bmssm/pkg/response"
)

// Controller 用户模块 gin handler 集合（需要 db 指针）。
type Controller struct {
	svc  *UserService
	aud  *audit.AuditService
}

// NewController 创建用户控制器。
func NewController(svc *UserService, aud *audit.AuditService) *Controller {
	return &Controller{svc: svc, aud: aud}
}

// DefaultController 使用 database.DB() 构建默认控制器。
func DefaultController() *Controller {
	db := database.DB()
	return NewController(NewService(db), audit.NewService(db))
}

// getSecret 从配置获取 JWT secret。
func getSecret() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	secret := conf.GetViper().GetString("server.authSecret")
	if secret == "" {
		secret = auth.DefaultSecret
	}
	return secret
}

// getDefaultPassword 返回配置中的默认密码（仅用于判定是否首次登录、是否需强制改密）。
func getDefaultPassword() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	p := conf.GetViper().GetString("server.defaultPassword")
	if p == "" {
		p = "admin"
	}
	return p
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// Login 处理 POST /api/v1/login。
// 若提供的密码等于配置的默认密码，视为用户未改密，签发临时 token 并返回 changePass=true，
// 前端据此引导改密；否则签发正常 token。
func (ctrl *Controller) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	user, err := ctrl.svc.Login(req.Username, req.Password)
	if err != nil {
		// 记录失败审计（用请求体里的 username）
		ctrl.auditWrite(c, req.Username, "login", "auth", "failed")
		c.JSON(http.StatusUnauthorized, response.Fail(err.Error()))
		return
	}
	temp := req.Password == getDefaultPassword()
	tokenStr, expiresAt, err := auth.IssueToken(user.Username, getSecret(), temp)
	if err != nil {
		ctrl.auditWrite(c, user.Username, "login", "auth", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail("failed to issue token"))
		return
	}
	ctrl.auditWrite(c, user.Username, "login", "auth", "success")
	c.JSON(http.StatusOK, response.OK(LoginResponse{
		Token:      tokenStr,
		ExpiresAt:  expiresAt,
		Role:       user.Role,
		ChangePass: temp,
	}))
}

// Logout 处理 POST /api/v1/logout（受保护，c.Get("user") 有值）。
func (ctrl *Controller) Logout(c *gin.Context) {
	username, _ := c.Get("user")
	userStr, _ := username.(string)
	ctrl.auditWrite(c, userStr, "logout", "auth", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "logged out", "user": username}))
}

// ListUsers 处理 GET /api/v1/user（受保护）。
func (ctrl *Controller) ListUsers(c *gin.Context) {
	users, err := ctrl.svc.ListUsers()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("failed to list users"))
		return
	}
	c.JSON(http.StatusOK, response.OK(users))
}

// CreateUser 处理 POST /api/v1/user（受保护）。
func (ctrl *Controller) CreateUser(c *gin.Context) {
	var req CreateUserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if req.Role == "" {
		req.Role = "user"
	}
	actor, _ := c.Get("user")
	actorStr, _ := actor.(string)
	if err := ctrl.svc.CreateUser(req.Username, req.Password, req.Role); err != nil {
		ctrl.auditWrite(c, actorStr, "create_user:"+req.Username, "user", "failed")
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, actorStr, "create_user:"+req.Username, "user", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "user created", "username": req.Username}))
}

// DeleteUser 处理 DELETE /api/v1/user/:name（受保护）。
func (ctrl *Controller) DeleteUser(c *gin.Context) {
	name := c.Param("name")
	if name == "" {
		c.JSON(http.StatusBadRequest, response.Fail("missing user name"))
		return
	}
	actor, _ := c.Get("user")
	actorStr, _ := actor.(string)
	if err := ctrl.svc.DeleteUser(name); err != nil {
		ctrl.auditWrite(c, actorStr, "delete_user:"+name, "user", "failed")
		c.JSON(http.StatusForbidden, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, actorStr, "delete_user:"+name, "user", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "user deleted", "username": name}))
}

// ChangePassword 处理 POST /api/v1/password（受保护，临时 token 可调）。
//   - 临时 token（c.Get("temp")==true）：不校验旧密码，直接设新密码（首次改密场景）。
//   - 正式 token：必须校验旧密码（svc.Login 验证），通过后才改。
// 改密成功后签发新的正式 token 返回。
func (ctrl *Controller) ChangePassword(c *gin.Context) {
	var req ChangePasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	username, _ := c.Get("user")
	usernameStr, _ := username.(string)
	if usernameStr == "" {
		c.JSON(http.StatusUnauthorized, response.Fail("unauthorized"))
		return
	}

	tempVal, _ := c.Get("temp")
	isTemp, _ := tempVal.(bool)

	// 正式 token 需校验旧密码
	if !isTemp {
		if _, err := ctrl.svc.Login(usernameStr, req.OldPassword); err != nil {
			ctrl.auditWrite(c, usernameStr, "change_password", "auth", "failed")
			c.JSON(http.StatusUnauthorized, response.Fail("invalid old password"))
			return
		}
	}

	if err := ctrl.svc.ChangePassword(usernameStr, req.NewPassword); err != nil {
		ctrl.auditWrite(c, usernameStr, "change_password", "auth", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	// 改密成功，签发正式 token
	var role string
	if u, err := ctrl.svc.FindUser(usernameStr); err == nil {
		role = u.Role
	}
	tokenStr, expiresAt, err := auth.IssueToken(usernameStr, getSecret(), false)
	if err != nil {
		ctrl.auditWrite(c, usernameStr, "change_password", "auth", "success")
		c.JSON(http.StatusOK, response.OK(gin.H{"message": "password changed, please re-login"}))
		return
	}
	ctrl.auditWrite(c, usernameStr, "change_password", "auth", "success")
	c.JSON(http.StatusOK, response.OK(ChangePasswordResponse{
		Token:     tokenStr,
		ExpiresAt: expiresAt,
		Role:      role,
	}))
}
