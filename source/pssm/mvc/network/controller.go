package network

import (
	"net/http"

	"github.com/gin-gonic/gin"

	netpkg "ssm/pkg/network"
)

// Controller 网络模块 gin handler 集合。
type Controller struct {
	svc *NetworkService
}

// NewController 创建网络控制器。
func NewController(svc *NetworkService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认控制器。
func DefaultController() *Controller {
	return NewController(NewService())
}

// GetIP 处理 GET /api/v1/network/ip（受保护）。
func (ctrl *Controller) GetIP(c *gin.Context) {
	cards, err := ctrl.svc.GetIPList()
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{Error: "failed to query ip", Code: "IP_QUERY_FAILED"})
		return
	}
	c.JSON(http.StatusOK, cards)
}

// SetIP 处理 PUT /api/v1/network/ip（受保护）。
func (ctrl *Controller) SetIP(c *gin.Context) {
	var req SetIPRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid request body", Code: "BAD_REQUEST"})
		return
	}
	if err := ctrl.svc.SetIP(req.Policy, req.Device, req.IP, req.Mask, req.Gateway, req.DNS); err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{Error: err.Error(), Code: "IP_SET_FAILED"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "ip configured"})
}

// AddNAT 处理 POST /api/v1/network/nat（受保护）。
func (ctrl *Controller) AddNAT(c *gin.Context) {
	var req NatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid request body", Code: "BAD_REQUEST"})
		return
	}

	rule := netpkg.NatRule{
		Direction: req.Direction,
		Operation: req.Op,
		Src:       req.Src,
		Dst:       req.Dst,
		SrcPort:   req.SrcPort,
		DstPort:   req.DstPort,
		Protocol:  req.Protocol,
		Flags:     req.Flags,
	}
	if err := ctrl.svc.AddNAT(rule); err != nil {
		// 校验失败返回 400，执行失败返回 500
		if isValidationError(err) {
			c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "VALIDATION_FAILED"})
			return
		}
		c.JSON(http.StatusInternalServerError, ErrorResponse{Error: err.Error(), Code: "NAT_FAILED"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "nat rule applied"})
}

// isValidationError 判断是否为输入校验错误（粗略：Validate 返回的错误信息不含 stderr）。
// 这里用简单约定：ValidationError 由 Validate 返回，是 Go error，不含 ": " 分隔的 stderr。
func isValidationError(err error) bool {
	if err == nil {
		return false
	}
	// 校验错误信息不含 ": "（stderr 拼接格式）
	msg := err.Error()
	for _, prefix := range []string{"direction must", "op must", "invalid src", "invalid dst", "invalid srcPort", "invalid dstPort", "invalid protocol", "invalid flags", "unsupported protocol", "invalid device"} {
		if len(msg) >= len(prefix) && msg[:len(prefix)] == prefix {
			return true
		}
	}
	return false
}
