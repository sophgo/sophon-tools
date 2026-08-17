// Package ops 提供危险操作二次确认端点（MYS-389）。
//
// 流程：前端执行高危操作（reboot/shutdown/OTA 升级/回滚/防火墙 rebuild）前，
// 先 POST /api/v1/ops/confirm 获取一次性确认码（绑定用户+动作，60s 有效），
// 由用户回显/输入后随危险操作请求携带确认码；服务端 Verify 通过才放行，
// 防止误触、脚本误调用即执行设备级破坏操作。
package ops

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"bmssm/pkg/confirm"
	"bmssm/pkg/response"
)

// AllowedActions 可签发确认码的动作白名单（与各高危操作 handler 的校验动作一致，
// 防随意生成无关动作确认码）。
var AllowedActions = map[string]bool{
	"reboot":           true,
	"shutdown":         true,
	"ota_upgrade":      true,
	"ota_rollback":     true,
	"firewall_rebuild": true,
}

// ConfirmRequest 签发确认码请求。
type ConfirmRequest struct {
	Action string `json:"action" binding:"required"`
}

// Controller 危险操作确认码端点。
type Controller struct{}

// NewController 创建确认码控制器。
func NewController() *Controller { return &Controller{} }

// Prepare 处理 POST /api/v1/ops/confirm：为 action+当前用户签发一次性确认码。
func (ctrl *Controller) Prepare(c *gin.Context) {
	var req ConfirmRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if !AllowedActions[req.Action] {
		c.JSON(http.StatusBadRequest, response.Fail("unsupported action: "+req.Action))
		return
	}

	username, _ := c.Get("user")
	name, _ := username.(string)

	code, expiresAt := confirm.Global().Prepare(req.Action, name, confirm.DefaultTTL)
	c.JSON(http.StatusOK, response.OK(gin.H{
		"action":    req.Action,
		"code":      code,
		"expiresAt": expiresAt.Format("2006-01-02T15:04:05Z07:00"),
	}))
}

// Verify 校验当前用户的 action 确认码；失败时已写 400 响应并返回 false（调用方直接返回）。
func Verify(c *gin.Context, action, code string) bool {
	username, _ := c.Get("user")
	name, _ := username.(string)
	if err := confirm.Global().Verify(action, name, code); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return false
	}
	return true
}
