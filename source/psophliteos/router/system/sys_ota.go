package system

import (
	v1 "sophliteos/api/v1"

	"github.com/gin-gonic/gin"
)

type OtaRouter struct{}

func (s *OtaRouter) InitOtaRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	otaRouter := Router.Group("api/device/ota")
	api := v1.ApiGroupApp.SystemApiGroup.OtaApi
	{
		otaRouter.GET("list", api.OtaFileList)

		otaRouter.POST("chunked", api.OtaFileChunked)
		otaRouter.POST("file", api.OtaFile)
	}

	return otaRouter
}
