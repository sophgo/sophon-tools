package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type MetricsSelRouter struct{}

// InitMetricsSelRouter 注册性能历史指标选择的本地持久化端点（不经 bmssm 反代）。
func (s *MetricsSelRouter) InitMetricsSelRouter(Router *gin.RouterGroup) (R gin.IRoutes) {
	selRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.MetricsSelApi
	{
		selRouter.GET("metrics-selection", api.Get)
		selRouter.PUT("metrics-selection", api.Put)
	}
	return selRouter
}
