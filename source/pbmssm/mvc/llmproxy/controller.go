package llmproxy

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"bmssm/database"
	"bmssm/pkg/response"
)

// Controller LLM 转发配置管理 handler 集合。
type Controller struct {
	svc *Service
}

// DefaultController 使用 database.DB() 构建默认控制器。
func DefaultController() *Controller {
	return &Controller{svc: NewService(database.DB())}
}

// GetConfig GET /api/v1/llm-proxy/config
// 返回已存配置（LLM/VLM 各 key 脱敏；ForwardKey 明文——仅 superuser/admin
// 可访问，路由注册于 admin 组，MYS-386：forwardKey 是 /agent/ws 唯一凭据）。
func (ctrl *Controller) GetConfig(c *gin.Context) {
	cfg := ctrl.svc.LoadConfig()
	c.JSON(http.StatusOK, response.OK(cfg.ToResponse()))
}

// SaveConfig PUT /api/v1/llm-proxy/config
// 保存 LLM/VLM 两套配置并热更新转发 server。
func (ctrl *Controller) SaveConfig(c *gin.Context) {
	var req SaveRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	cfg, err := ctrl.svc.SaveConfig(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("save failed: "+err.Error()))
		return
	}
	// 热更新转发 server（不重启 bmssm）
	UpdateServer(cfg)
	c.JSON(http.StatusOK, response.OK(cfg.ToResponse()))
}

// ResetForwardKey POST /api/v1/llm-proxy/forward-key/reset
// 重置转发 key（生成新 key 并落库），并通知注册的监听者（agentproxy Hub
// 换用新 key，前端 WS 子协议 token 同步轮换；旧 token 立即失效）。
func (ctrl *Controller) ResetForwardKey(c *gin.Context) {
	key, err := ctrl.svc.ResetForwardKey()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("reset failed: "+err.Error()))
		return
	}
	// 热更新配置（转发 key 变化）
	UpdateServer(ctrl.svc.LoadConfig())
	// 通知监听者（agentproxy Hub.SetKey），旧 key 立即失效
	notifyForwardKeyRotated(key)
	c.JSON(http.StatusOK, response.OK(gin.H{"forwardKey": key}))
}

// ListModels GET /api/v1/llm-proxy/models?kind=llm|vlm
// 从对应供应商的 openai 接口拉取模型列表（供前端弹窗选择）。
func (ctrl *Controller) ListModels(c *gin.Context) {
	cfg := ctrl.svc.LoadConfig()
	kind := Provider(strings.ToLower(c.Query("kind")))
	prov := cfg.Provider(kind)
	if prov.ApiBase == "" || prov.ApiKey == "" {
		c.JSON(http.StatusBadRequest, response.Fail("upstream not configured for "+string(kind)))
		return
	}
	models, err := fetchModels(prov)
	if err != nil {
		c.JSON(http.StatusBadGateway, response.Fail("fetch models failed: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"models": models}))
}
