package system

import (
	v1 "sophliteos/api/v1"

	"github.com/gin-gonic/gin"
)

type OtaRouter struct{}

func (s *OtaRouter) InitOtaRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	// otaRouter := Router.Group("api/device/ota", middleware.TimeoutMiddleware(global.OtaTimeOut))
	otaRouter := Router.Group("api/device/ota")
	api := v1.ApiGroupApp.SystemApiGroup.OtaApi
	{
		otaRouter.POST("upgrade", api.OtaUpgrate)
		otaRouter.GET("upgrade", api.OtaUpgradeList)
		otaRouter.GET("list", api.OtaFileList)

		otaRouter.POST("chunked", api.OtaFileChunked)
		otaRouter.POST("file", api.OtaFile)
	}

	return otaRouter
}
