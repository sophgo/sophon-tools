package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type UpgradeRouter struct{}

func (s *UpgradeRouter) InitUpgradeRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	upgradeRouter := Router.Group("api", middleware.TimeoutMiddleware(global.OtaTimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.UpgradeApi
	{
		upgradeRouter.POST("upgrade", versionApi.Upgrade)
	}

	return upgradeRouter
}
