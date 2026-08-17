package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type OtaRouter struct{}

func (s *OtaRouter) InitOtaRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	// OTA 上传/升级属敏感操作：叠加 SSO 单会话校验 + bmssm JWT 校验，避免未登录
	// 客户端向 /data/ota 写入文件。GET list 仅读本地文件列表，一并纳入统一口径。
	// DeadlineMiddleware 延长连接读写 deadline 到 ota-timeout：50MB/片的分片上传
	// 在慢速链路上需要比常规 30s 更长的窗口（MYS-382 超时分离）。
	otaRouter := Router.Group("api/device/ota",
		middleware.SSO(),
		middleware.RequireBMSSMToken(),
		middleware.DeadlineMiddleware(global.OtaTimeOut),
		middleware.TimeoutMiddleware(global.OtaTimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.OtaApi
	{
		otaRouter.GET("list", api.OtaFileList)

		otaRouter.POST("chunked", api.OtaFileChunked)
		otaRouter.POST("file", api.OtaFile)
	}

	return otaRouter
}
