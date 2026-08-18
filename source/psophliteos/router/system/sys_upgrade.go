package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type UpgradeRouter struct{}

func (s *UpgradeRouter) InitUpgradeRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	// 升级两段式：先上传暂存（upgrade），再确认执行（upgrade/confirm）。
	// 升级/重启属敏感操作：叠加 SSO 单会话 + bmssm JWT 校验，与 /api/v1/* 反代
	// 同一套活跃会话模型，避免未登录客户端直接触发；前端 defHttp 请求自动携带 token。
	upgradeRouter := Router.Group("api", middleware.SSO(), middleware.RequireBMSSMToken(), middleware.TimeoutMiddleware(global.OtaTimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.UpgradeApi
	{
		upgradeRouter.POST("upgrade", versionApi.Upgrade)
		upgradeRouter.POST("upgrade/confirm", versionApi.UpgradeConfirm)
	}

	return upgradeRouter
}
