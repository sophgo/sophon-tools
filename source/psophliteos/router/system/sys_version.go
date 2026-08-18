package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type VersionRouter struct{}

func (s *VersionRouter) InitVersionRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	// 版本信息虽为只读，但同样纳入统一鉴权口径（SSO 单会话 + bmssm JWT），
	// 未认证客户端不得探测设备软件版本。
	versionRouter := Router.Group("api/device", middleware.SSO(), middleware.RequireBMSSMToken(), middleware.TimeoutMiddleware(global.TimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.VersionApi
	{
		versionRouter.GET("version", versionApi.Version)

	}

	return versionRouter
}
