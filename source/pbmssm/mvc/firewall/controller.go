package firewall

import (
	"errors"
	"net/http"
	"strconv"

	"bmssm/database"
	"bmssm/mvc/audit"
	"bmssm/pkg/firewall"
	"bmssm/pkg/hazard"
	"bmssm/pkg/response"

	"github.com/gin-gonic/gin"
)

// Controller holds a Service and exposes gin handler methods.
type Controller struct {
	svc *Service
	// aud 审计服务（nil 安全）：防火墙 rebuild 属高危操作，记入 audit_logs（MYS-389）。
	aud *audit.AuditService
}

// NewController creates a Controller with the given Service.
func NewController(svc *Service) *Controller { return &Controller{svc: svc} }

// DefaultController creates a Controller backed by the default (global-DB) Service.
func DefaultController() *Controller {
	ctrl := NewController(DefaultService())
	ctrl.aud = audit.NewService(database.DB())
	return ctrl
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// envFail checks the firewall environment. Returns true and writes a 503
// JSON response if the environment is unhealthy; returns false if healthy.
func envFail(c *gin.Context) bool {
	env := firewall.CheckEnvironment(firewall.DefaultRunner)
	if !env.OK {
		c.JSON(http.StatusServiceUnavailable, gin.H{"code": 1, "msg": "环境不满足", "result": gin.H{"environment": env}})
		return true
	}
	return false
}

// --- Status (no env check — returns environment data as the response) ---

// Status handles GET /firewall/status.
func (ctrl *Controller) Status(c *gin.Context) {
	env, protect, err := ctrl.svc.Status()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"environment": env, "protectPorts": protect}))
}

// --- Intents ---

// ListIntents handles GET /firewall/intent.
func (ctrl *Controller) ListIntents(c *gin.Context) {
	if envFail(c) {
		return
	}
	list, err := ctrl.svc.ListIntents()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(list))
}

// AddIntent handles POST /firewall/intent.
func (ctrl *Controller) AddIntent(c *gin.Context) {
	if envFail(c) {
		return
	}
	var req IntentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid body"))
		return
	}
	if err := ctrl.svc.AddIntent(req); err != nil {
		if errors.Is(err, firewall.ErrInvalidInput) {
			c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
			return
		}
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "intent added"}))
}

// DeleteIntent handles DELETE /firewall/intent/:id.
func (ctrl *Controller) DeleteIntent(c *gin.Context) {
	if envFail(c) {
		return
	}
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	if err := ctrl.svc.DeleteIntent(id); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "deleted"}))
}

// Rebuild handles POST /firewall/rebuild.
// 高危操作防护（MYS-389）：与 reboot/shutdown/OTA 共享全局互斥锁与二次确认码
// （防火墙 rebuild 期间重启/OTA 会留下半配置规则或打断刷机），并记审计。
func (ctrl *Controller) Rebuild(c *gin.Context) {
	if envFail(c) {
		return
	}
	var req struct {
		Confirm string `json:"confirm"`
	}
	// 空 body 视为无确认码（校验失败会给出引导性错误），不因解析失败直接 400
	_ = c.ShouldBindJSON(&req)

	username, _ := c.Get("user")
	name, _ := username.(string)

	if !hazard.VerifyConfirmCode(req.Confirm) {
		ctrl.auditWrite(c, name, "firewall_rebuild", "firewall", "confirmation_failed")
		c.JSON(http.StatusForbidden, response.Fail("confirmation required: fetch /api/v1/hazard/challenge first"))
		return
	}
	guard, err := hazard.HazardOps.TryAcquire("firewall_rebuild")
	if err != nil {
		ctrl.auditWrite(c, name, "firewall_rebuild", "firewall", "blocked")
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	defer guard.Release()

	if err := ctrl.svc.Rebuild(); err != nil {
		ctrl.auditWrite(c, name, "firewall_rebuild", "firewall", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, name, "firewall_rebuild", "firewall", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "rebuild ok"}))
}
