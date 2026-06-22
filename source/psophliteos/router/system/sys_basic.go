package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type BasicRouter struct{}

func (s *BasicRouter) InitBasicRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	basicRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	basicApi := v1.ApiGroupApp.SystemApiGroup.BasicApi
	{
		basicRouter.POST("basic", basicApi.BasicMod)

	}

	return basicRouter
}
