package hardware

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"bmssm/database"
	"bmssm/mvc/audit"
	"bmssm/pkg/hazard"
	"bmssm/pkg/response"
)

// Controller 硬件模块 gin handler 集合。
type Controller struct {
	svc *HardwareService
	aud *audit.AuditService
}

// NewController 创建硬件控制器。
func NewController(svc *HardwareService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认（生产）控制器。
func DefaultController() *Controller {
	ctrl := NewController(NewDefaultService())
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

// GetHealth 处理 GET /api/v1/hardware/health — 健康状态。
func (ctrl *Controller) GetHealth(c *gin.Context) {
	resp := ctrl.svc.GetHealth()
	c.JSON(http.StatusOK, response.OK(resp))
}

// Reboot 处理 POST /api/v1/hardware/reboot — 重启。
func (ctrl *Controller) Reboot(c *gin.Context) {
	var req RebootRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// MYS-389：二次确认 + 高危互斥 + 审计。
	username, _ := c.Get("user")
	uname, _ := username.(string)
	if !hazard.VerifyConfirmCode(req.Confirm) {
		ctrl.auditWrite(c, uname, "reboot", "hardware", "confirmation_failed")
		c.JSON(http.StatusForbidden, response.Fail("confirmation required: fetch /api/v1/hazard/challenge first"))
		return
	}
	guard, err := hazard.HazardOps.TryAcquire("reboot")
	if err != nil {
		ctrl.auditWrite(c, uname, "reboot", "hardware", "blocked")
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	defer guard.Release()

	if err := ctrl.svc.Reboot(req.Delay); err != nil {
		// delay 校验错误 → 400
		errMsg := err.Error()
		if len(errMsg) >= 5 && errMsg[:5] == "delay" {
			ctrl.auditWrite(c, uname, "reboot", "hardware", "failed")
			c.JSON(http.StatusBadRequest, response.Fail(errMsg))
			return
		}
		ctrl.auditWrite(c, uname, "reboot", "hardware", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(errMsg))
		return
	}
	ctrl.auditWrite(c, uname, "reboot", "hardware", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "reboot scheduled"}))
}

// Challenge 处理 GET /api/v1/hazard/challenge — 下发高危操作一次性确认码。
func (ctrl *Controller) Challenge(c *gin.Context) {
	code := hazard.NewConfirmCode()
	c.JSON(http.StatusOK, response.OK(gin.H{
		"code":          code,
		"expiresInSecs": 120,
	}))
}

// GetLED 处理 GET /api/v1/hardware/led — LED 状态。
func (ctrl *Controller) GetLED(c *gin.Context) {
	resp := ctrl.svc.GetLED()
	// LED 不可用是降级，仍返回 200
	c.JSON(http.StatusOK, response.OK(resp))
}

// SetLED 处理 PUT /api/v1/hardware/led — 设置 LED。
func (ctrl *Controller) SetLED(c *gin.Context) {
	var req LEDRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	if err := ctrl.svc.SetLED(req.State); err != nil {
		errMsg := err.Error()
		// 参数校验错误 → 400
		if len(errMsg) >= 7 && errMsg[:7] == "invalid" {
			c.JSON(http.StatusBadRequest, response.Fail(errMsg))
			return
		}
		// LED 不可用是降级，仍返回 200
		c.JSON(http.StatusOK, response.OK(LEDResponse{
			Available: false,
			Reason:    errMsg,
		}))
		return
	}

	c.JSON(http.StatusOK, response.OK(gin.H{
		"message": "led set",
		"state":   req.State,
	}))
}

// GetCard 处理 GET /api/v1/hardware/card — BM 卡信息（bmlib 占位）。
func (ctrl *Controller) GetCard(c *gin.Context) {
	resp := ctrl.svc.GetCard()
	// bmlib 未接入是降级，返回 200
	c.JSON(http.StatusOK, response.OK(resp))
}
