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
	written := ctrl.svc.ForwardKeyWritten()
	c.JSON(http.StatusOK, response.OK(cfg.ToResponse(written)))
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
	c.JSON(http.StatusOK, response.OK(cfg.ToResponse(ctrl.svc.ForwardKeyWritten())))
}

// ResetForwardKey POST /api/v1/llm-proxy/forward-key/reset
// 重置转发 key（生成新 key 并落库；不自动写入 picoclaw）。
func (ctrl *Controller) ResetForwardKey(c *gin.Context) {
	key, err := ctrl.svc.ResetForwardKey()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("reset failed: "+err.Error()))
		return
	}
	// 热更新配置（转发 key 变化）
	UpdateServer(ctrl.svc.LoadConfig())
	c.JSON(http.StatusOK, response.OK(gin.H{"forwardKey": key}))
}

// WriteForwardKey POST /api/v1/llm-proxy/forward-key/write-picoclaw
// 把当前转发 key 写入本地 picoclaw devproxy.key 并重启 gateway。
func (ctrl *Controller) WriteForwardKey(c *gin.Context) {
	cfg := ctrl.svc.LoadConfig()
	if cfg.ForwardKey == "" {
		c.JSON(http.StatusBadRequest, response.Fail("forward key not generated"))
		return
	}
	if err := WriteForwardKeyToPicoclaw(cfg.ForwardKey); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("write failed: "+err.Error()))
		return
	}
	ctrl.svc.SetForwardKeyWritten()
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
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

// GetServiceStatus GET /api/v1/llm-proxy/service/status
// 返回 sophpicoclaw 服务状态（systemd 状态 + 端口 + 日志尾部）。
func (ctrl *Controller) GetServiceStatus(c *gin.Context) {
	st, err := GetSophpicoclawStatus()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(st))
}

// ServiceAction POST /api/v1/llm-proxy/service/action  body: {"action":"restart"}
// 对 sophpicoclaw 执行 start/stop/restart/enable/disable。
func (ctrl *Controller) ServiceAction(c *gin.Context) {
	var req struct {
		Action string `json:"action" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := ActionSophpicoclaw(req.Action); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "action " + req.Action + " executed"}))
}
