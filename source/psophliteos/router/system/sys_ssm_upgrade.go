package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type SsmUpgradeRouter struct{}

func (s *SsmUpgradeRouter) InitSsmUpgradeRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	router := Router.Group("api/ssm", middleware.TimeoutMiddleware(global.OtaTimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.SsmUpgradeApi
	{
		router.POST("upgrade", versionApi.Upgrade)
		router.GET("list", versionApi.SsmList)
	}

	return router
}
