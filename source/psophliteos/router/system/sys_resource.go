package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type ResourceRouter struct{}

func (s *ResourceRouter) InitResourceRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	deviceRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	deviceApi := v1.ApiGroupApp.SystemApiGroup.ResourceApi
	{
		deviceRouter.GET("resource", deviceApi.NewResource)
	}

	return deviceRouter
}
