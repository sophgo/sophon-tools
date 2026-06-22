package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type VersionRouter struct{}

func (s *BasicRouter) InitVersionRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	versionRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.VersionApi
	{
		versionRouter.GET("version", versionApi.Version)

	}

	return versionRouter
}
