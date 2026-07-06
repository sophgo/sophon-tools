package user

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/database"
	"ssm/mvc/audit"
	"ssm/pkg/auth"
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
		secret = "ssm-dev-secret"
	}
	return secret
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// Login 处理 POST /api/v1/login。
func (ctrl *Controller) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid request body", Code: "BAD_REQUEST"})
		return
	}
	user, err := ctrl.svc.Login(req.Username, req.Password)
	if err != nil {
		// 记录失败审计（用请求体里的 username）
		ctrl.auditWrite(c, req.Username, "login", "auth", "failed")
		c.JSON(http.StatusUnauthorized, ErrorResponse{Error: err.Error(), Code: "LOGIN_FAILED"})
		return
	}
	tokenStr, expiresAt, err := auth.IssueToken(user.Username, getSecret())
	if err != nil {
		ctrl.auditWrite(c, user.Username, "login", "auth", "failed")
		c.JSON(http.StatusInternalServerError, ErrorResponse{Error: "failed to issue token", Code: "TOKEN_ISSUE_FAILED"})
		return
	}
	ctrl.auditWrite(c, user.Username, "login", "auth", "success")
	c.JSON(http.StatusOK, LoginResponse{
		Token:     tokenStr,
		ExpiresAt: expiresAt,
		Role:      user.Role,
	})
}

// Logout 处理 POST /api/v1/logout（受保护，c.Get("user") 有值）。
func (ctrl *Controller) Logout(c *gin.Context) {
	username, _ := c.Get("user")
	userStr, _ := username.(string)
	ctrl.auditWrite(c, userStr, "logout", "auth", "success")
	c.JSON(http.StatusOK, gin.H{"message": "logged out", "user": username})
}

// ListUsers 处理 GET /api/v1/user（受保护）。
func (ctrl *Controller) ListUsers(c *gin.Context) {
	users, err := ctrl.svc.ListUsers()
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{Error: "failed to list users", Code: "DB_ERROR"})
		return
	}
	c.JSON(http.StatusOK, users)
}

// CreateUser 处理 POST /api/v1/user（受保护）。
func (ctrl *Controller) CreateUser(c *gin.Context) {
	var req CreateUserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid request body", Code: "BAD_REQUEST"})
		return
	}
	if req.Role == "" {
		req.Role = "user"
	}
	actor, _ := c.Get("user")
	actorStr, _ := actor.(string)
	if err := ctrl.svc.CreateUser(req.Username, req.Password, req.Role); err != nil {
		ctrl.auditWrite(c, actorStr, "create_user:"+req.Username, "user", "failed")
		c.JSON(http.StatusConflict, ErrorResponse{Error: err.Error(), Code: "CREATE_FAILED"})
		return
	}
	ctrl.auditWrite(c, actorStr, "create_user:"+req.Username, "user", "success")
	c.JSON(http.StatusOK, gin.H{"message": "user created", "username": req.Username})
}

// DeleteUser 处理 DELETE /api/v1/user/:name（受保护）。
func (ctrl *Controller) DeleteUser(c *gin.Context) {
	name := c.Param("name")
	if name == "" {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: "missing user name", Code: "BAD_REQUEST"})
		return
	}
	actor, _ := c.Get("user")
	actorStr, _ := actor.(string)
	if err := ctrl.svc.DeleteUser(name); err != nil {
		ctrl.auditWrite(c, actorStr, "delete_user:"+name, "user", "failed")
		c.JSON(http.StatusForbidden, ErrorResponse{Error: err.Error(), Code: "DELETE_FAILED"})
		return
	}
	ctrl.auditWrite(c, actorStr, "delete_user:"+name, "user", "success")
	c.JSON(http.StatusOK, gin.H{"message": "user deleted", "username": name})
}
