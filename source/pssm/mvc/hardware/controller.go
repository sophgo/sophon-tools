package hardware

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"ssm/pkg/response"
)

// Controller 硬件模块 gin handler 集合。
type Controller struct {
	svc *HardwareService
}

// NewController 创建硬件控制器。
func NewController(svc *HardwareService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认（生产）控制器。
func DefaultController() *Controller {
	return NewController(NewDefaultService())
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

	if err := ctrl.svc.Reboot(req.Delay); err != nil {
		// delay 校验错误 → 400
		errMsg := err.Error()
		if len(errMsg) >= 5 && errMsg[:5] == "delay" {
			c.JSON(http.StatusBadRequest, response.Fail(errMsg))
			return
		}
		c.JSON(http.StatusInternalServerError, response.Fail(errMsg))
		return
	}

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
