// Package audit 提供审计日志 MVC 模块：查询与写入。
package audit

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"ssm/database"
	"ssm/pkg/response"
)

// ErrorResponse 统一错误响应。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}

// Controller 审计日志 gin handler 集合。
type Controller struct {
	svc *AuditService
}

// NewController 创建审计控制器。
func NewController(svc *AuditService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 使用 database.DB() 构建默认控制器。
func DefaultController() *Controller {
	return NewController(NewService(database.DB()))
}

// ListLogs 处理 GET /api/v1/audit（受保护），支持 offset/limit 分页。
func (ctrl *Controller) ListLogs(c *gin.Context) {
	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))

	result, err := ctrl.svc.ListLogs(offset, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("failed to query audit logs"))
		return
	}
	c.JSON(http.StatusOK, response.OK(result))
}
