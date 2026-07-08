// Package alarm 提供 ssm 告警历史 MVC 模块：DB 落库 + 查询 + 落库适配器。
package alarm

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"ssm/database"
	"ssm/pkg/response"
)

// Controller 告警历史 gin handler 集合。
type Controller struct {
	svc *AlarmService
}

// NewController 创建告警历史控制器。
func NewController(svc *AlarmService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 使用 database.DB() 构建默认控制器。
func DefaultController() *Controller {
	return NewController(NewService(database.DB()))
}

// ListAlarms 处理 GET /api/v1/alarms（受保护），支持 offset/limit 分页与
// componentType 过滤（对齐前端 logs/warning 搜索表单）。
func (ctrl *Controller) ListAlarms(c *gin.Context) {
	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	filters := ListFilters{
		ComponentType: c.Query("componentType"),
	}
	if v := c.Query("code"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			filters.Code = n
		}
	}

	result, err := ctrl.svc.ListAlarms(offset, limit, filters)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("failed to query alarms"))
		return
	}
	c.JSON(http.StatusOK, response.OK(result))
}
