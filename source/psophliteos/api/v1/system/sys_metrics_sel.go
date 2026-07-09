package system

import (
	"net/http"

	"sophliteos/database"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

// MetricsSelApi 性能历史指标选择持久化。
type MetricsSelApi struct{}

// Get 返回已存的指标选择列表（无则空数组）。
func (a *MetricsSelApi) Get(c *gin.Context) {
	fields := database.LoadMetricSelection()
	if fields == nil {
		fields = []string{}
	}
	c.JSON(http.StatusOK, mvc.Success(gin.H{"fields": fields}))
}

// Put 保存指标选择列表。
func (a *MetricsSelApi) Put(c *gin.Context) {
	var req struct {
		Fields []string `json:"fields"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "invalid request body"))
		return
	}
	if err := database.SaveMetricSelection(req.Fields); err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "save failed: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, mvc.Success(gin.H{"ok": true}))
}
