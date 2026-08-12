package initialization

import (
	"io/fs"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sophliteos/config"
	"sophliteos/logger"
	"sophliteos/middleware"
	"sophliteos/router"
	"strings"

	"github.com/gin-gonic/gin"
)

// 初始化总路由
// webFS 为内嵌的前端构建产物（package main 的 go:embed dist），
// 单文件二进制自带整套静态前端，运行时不再依赖磁盘上的 web 目录。

func Routers(webFS fs.FS) *gin.Engine {
	gin.SetMode(gin.ReleaseMode) // 设置Gin的模式为release
	Router := gin.New()
	Router.Use(gin.Recovery())

	Router.MaxMultipartMemory = 64 << 20

	systemRouter := router.RouterGroupApp.System

	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	bmssmServer := v.GetString("bmssm.server")
	conf.Unlock()

	if bmssmServer == "" {
		bmssmServer = "127.0.0.1:9779"
	}

	// 静态前端全部取自内嵌 FS：以 http.FileServer 挂到 NoRoute 兜底，
	// 统一提供 index.html/_app.config.js/favicon.ico 及 assets、resource 等子目录资源。
	// 业务/API 路由显式注册在前，gin 命中优先于 NoRoute，未匹配的 /api/* 与非 GET 则会落此兜底。
	webFSHandler := http.FileServer(http.FS(webFS))
	Router.NoRoute(func(c *gin.Context) {
		if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
			c.Status(http.StatusNotFound)
			return
		}
		webFSHandler.ServeHTTP(c.Writer, c.Request)
	})

	Router.Use(middleware.BlockerMiddleware())

	// 单点登录（单会话）本地端点：查询活跃会话 / 注册新会话（踢旧）/ 注销。
	// 不反代到 bmssm，仅 sophliteos web 层维护。
	Router.GET("/api/sso/active", func(c *gin.Context) {
		u, ok := middleware.SSOActive()
		c.JSON(http.StatusOK, gin.H{"active": ok, "username": u})
	})
	Router.POST("/api/sso/register", func(c *gin.Context) {
		var req struct {
			Username string `json:"username"`
			Token    string `json:"token"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Username == "" || req.Token == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
			return
		}
		middleware.SSORegister(req.Username, req.Token)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	Router.POST("/api/sso/logout", func(c *gin.Context) {
		middleware.SSOLogout(middleware.SSORequestToken(c))
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	// SSE 推送：旧端长连接，被新登录踢掉时主动收 SESSION_OFFLINE
	Router.GET("/api/sso/events", middleware.SSOEvents)

	// /api/v1/* 反代到 bmssm（鉴权由 bmssm 处理）；前置 SSO 单会话校验
	bmssmTarget, err := url.Parse("http://" + bmssmServer)
	if err == nil {
		proxy := httputil.NewSingleHostReverseProxy(bmssmTarget)
		// WebSocket 升级支持
		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalDirector(req)
			// 保留 Host 便于 bmssm 识别
			req.Host = bmssmTarget.Host
		}
		proxy.Transport = &http.Transport{
			// 长连接支持（含 WebSocket）
			MaxIdleConns: 100,
		}
		Router.Any("/api/v1/*any", middleware.SSO(), func(c *gin.Context) {
			proxy.ServeHTTP(c.Writer, c.Request)
		})
	} else {
		logger.Error("bmssm server url parse error: %v", err)
	}

	// 本地 sophliteos 功能路由（无本地 user 系统，依赖 ssm 反代鉴权后的同源访问）
	LocalGroup := Router.Group("")
	{
		systemRouter.InitOtaRouter(LocalGroup)
		systemRouter.InitVersionRouter(LocalGroup)
		systemRouter.InitUpgradeRouter(LocalGroup)
		systemRouter.InitMetricsSelRouter(LocalGroup)
		systemRouter.InitAiAgentRouter(LocalGroup)
	}

	logger.Info("Router Init Ok")
	return Router
}

// NewProxy 创建一个反向代理
func NewProxy(target string) *httputil.ReverseProxy {
	u, _ := url.Parse(target)
	return httputil.NewSingleHostReverseProxy(u)
}

// isWebSocketRequest 判断是否为 WebSocket 升级请求。
func isWebSocketRequest(r *http.Request) bool {
	return strings.EqualFold(r.Header.Get("Connection"), "upgrade") &&
		strings.EqualFold(r.Header.Get("Upgrade"), "websocket")
}
