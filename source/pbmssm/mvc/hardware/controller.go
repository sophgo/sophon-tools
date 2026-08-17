package hardware

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"bmssm/database"
	"bmssm/mvc/audit"
	"bmssm/mvc/ops"
	"bmssm/pkg/oplock"
	"bmssm/pkg/response"
)

// Controller 硬件模块 gin handler 集合。
type Controller struct {
	svc *HardwareService
	// aud 审计服务（nil 安全）：reboot 等危险操作记入 audit_logs（MYS-389）。
	aud *audit.AuditService
}

// NewController 创建硬件控制器。
func NewController(svc *HardwareService) *Controller {
	return &Controller{svc: svc}
}

// NewControllerWithAudit 创建硬件控制器（带审计服务）。
func NewControllerWithAudit(svc *HardwareService, aud *audit.AuditService) *Controller {
	return &Controller{svc: svc, aud: aud}
}

// DefaultController 构建默认（生产）控制器。
func DefaultController() *Controller {
	return NewControllerWithAudit(NewDefaultService(), audit.NewService(database.DB()))
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
// 高危操作防护（MYS-389）：必须携带 /ops/confirm 签发的一次性确认码
// （绑定当前用户+reboot 动作）；同时获取全局危险操作互斥锁
// （与 shutdown/OTA 刷机/防火墙 rebuild 互斥），冲突返回 409 明确错误。
func (ctrl *Controller) Reboot(c *gin.Context) {
	var req RebootRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	username, _ := c.Get("user")
	name, _ := username.(string)

	if !ops.Verify(c, "reboot", req.ConfirmCode) {
		ctrl.auditWrite(c, name, "reboot", "hardware", "blocked: missing/invalid confirm code")
		return
	}

	release, err := oplock.Global().Acquire("reboot")
	if err != nil {
		ctrl.auditWrite(c, name, "reboot", "hardware", "blocked: "+err.Error())
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	defer release()

	if err := ctrl.svc.Reboot(req.Delay); err != nil {
		// delay 校验错误 → 400
		errMsg := err.Error()
		if len(errMsg) >= 5 && errMsg[:5] == "delay" {
			ctrl.auditWrite(c, name, "reboot", "hardware", "failed: "+errMsg)
			c.JSON(http.StatusBadRequest, response.Fail(errMsg))
			return
		}
		ctrl.auditWrite(c, name, "reboot", "hardware", "failed: "+errMsg)
		c.JSON(http.StatusInternalServerError, response.Fail(errMsg))
		return
	}

	ctrl.auditWrite(c, name, "reboot", "hardware", "success")
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "reboot scheduled"}))
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
