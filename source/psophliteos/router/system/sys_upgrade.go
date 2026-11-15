package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type UpgradeRouter struct{}

func (s *UpgradeRouter) InitUpgradeRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	// 旧版两段式自升级（upgrade 上传暂存 → upgrade/confirm 执行）已下线，
	// 两个端点保留路由与鉴权，但固定返回"暂不支持"的非零业务码（MYS-2882/MYS-2885）：
	// 不落盘、不置 BlockAllRequests、不 exec 重启。正式升级请走 OTA（/api/device/ota/*）。
	// 升级/重启属敏感操作：叠加 SSO 单会话 + bmssm JWT 校验，与 /api/v1/* 反代
	// 同一套活跃会话模型，避免未登录客户端直接调用；前端 defHttp 请求自动携带 token。
	// DeadlineMiddleware 将连接读写 deadline 延长到 ota-timeout：固件升级执行
	// 时间可远超常规 30s（MYS-382 超时分离）。
	upgradeRouter := Router.Group("api",
		middleware.SSO(),
		middleware.RequireBMSSMToken(),
		middleware.DeadlineMiddleware(global.OtaTimeOut),
		middleware.TimeoutMiddleware(global.OtaTimeOut))
	versionApi := v1.ApiGroupApp.SystemApiGroup.UpgradeApi
	{
		upgradeRouter.POST("upgrade", versionApi.Upgrade)
		upgradeRouter.POST("upgrade/confirm", versionApi.UpgradeConfirm)
	}

	return upgradeRouter
}
