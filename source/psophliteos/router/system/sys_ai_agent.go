package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type AiAgentRouter struct{}

// InitAiAgentRouter 注册 AI Agent 本地端点（不经 bmssm 反代）。
// LLM/VLM 配置由 bmssm 的 /api/v1/llm-proxy/config 管理（经 /api/v1/* 反代），
// 此处仅保留 picoclaw 端口探测、本地模型样例与页面转发。
// 鉴权：AI-Agent 端点属设备内部自用（同一设备内部服务/受信任访问，不经 ssm 反代），
// 不设 SSO；MYS-379 的代理目标身份校验/路径白名单/探测缓存等加固保留（见 api 层）。
func (s *AiAgentRouter) InitAiAgentRouter(Router *gin.RouterGroup) (R gin.IRoutes) {
	agentRouter := Router.Group("api/device/ai-agent", middleware.TimeoutMiddleware(global.TimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.AiAgentApi
	{
		agentRouter.GET("port", api.Port)
		// picoclaw web 反代（iframe 同源访问）
		agentRouter.Any("proxy/*any", api.Proxy)
	}
	return agentRouter
}
