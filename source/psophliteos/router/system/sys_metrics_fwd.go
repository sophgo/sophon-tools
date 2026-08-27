package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type MetricsFwdRouter struct{}

// InitMetricsFwdRouter 注册指标转发路由：
//   - GET /metrics：公开端点（Prometheus 抓取入口，token 鉴权在 handler 内），不走 SSO
//   - /api/device/metrics-forward*：管理端点（开关/状态/轮换），与 metrics_sel 同前缀
//     （不能用 /api/v1/* 前缀：与 /api/v1/*any bmssm 反代通配路由冲突 panic）
func (s *MetricsFwdRouter) InitMetricsFwdRouter(Router *gin.RouterGroup) (R gin.IRoutes) {
	api := v1.ApiGroupApp.SystemApiGroup.MetricsFwdApi

	// 公开转发端点：Prometheus 无法携带 SSO JWT，handler 内做静态 token 校验
	Router.GET("metrics", api.Forward)

	fwd := Router.Group("api/device/metrics-forward",
		middleware.SSO(), middleware.RequireBMSSMToken(), middleware.TimeoutMiddleware(global.TimeOut))
	{
		fwd.GET("", api.Status)
		fwd.PUT("", api.SetEnabled)
		fwd.POST("token", api.RotateToken)
	}
	return fwd
}
