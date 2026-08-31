package initialization

import (
	"io/fs"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sophliteos/config"
	"sophliteos/global"
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

	// 单点登录（单会话）本地端点：查询活跃会话 / 注册新会话（踢旧，需有效 bmssm JWT）/ 注销。
	// 不反代到 bmssm，仅 sophliteos web 层维护；register 由 middleware.CheckBMSSMToken 本地校验。
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
		// 鉴权：token 必须是 bmssm 签发的有效 JWT，且其 sub 与请求的 username 一致，
		// 防止未认证请求用任意 username/token 自造活跃会话（伪造活跃会话可顶掉合法
		// 用户 → 登录 DoS）。sub 取自 bmssm 登录签发，与前端登录输入一致。
		sub, temp, err := middleware.CheckBMSSMToken(req.Token)
		if err != nil || sub != req.Username {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
			return
		}
		// 临时 token（默认密码首登、待改密）不得建立活跃会话：临时 token 人人可取
		// （默认凭据公开），放行会允许任意人顶掉已登录管理员（会话 DoS）。首登用户
		// 必须先在 bmssm 完成改密、以正式 token 重新登录。前端收到 change_pass_required
		// 后转入改密引导（temp token 可调 /api/v1/password 改密）。
		if temp {
			c.JSON(http.StatusForbidden, gin.H{"error": "temporary token, change password required", "change_pass_required": true})
			return
		}
		middleware.SSORegister(req.Username, req.Token)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	Router.POST("/api/sso/logout", func(c *gin.Context) {
		middleware.SSOLogout(middleware.SSORequestToken(c))
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	// 一次性票据：下载/终端 WS 无法携带 Authorization 头，前端先带 Bearer 换票据，
	// 真实请求以 ?ticket=<票据> 发起（SSO 中间件白名单路径校验并改写为 ?token= 转发）。
	// 票据一次性 + 60s 过期，即使落入 URL/访问日志也无法复用。
	Router.POST("/api/sso/ticket", func(c *gin.Context) {
		act, ok := middleware.SSOActiveToken()
		if !ok {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "no active session"})
			return
		}
		// 请求必须以 Authorization 头携带当前活跃 token 才能换票（防任意换票）
		if middleware.SSORequestToken(c) != act {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid token"})
			return
		}
		ticket := middleware.SSOIssueTicket(act)
		if ticket == "" {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to issue ticket"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"ticket": ticket})
	})
	// SSE 推送：登录后长连接（Authorization Bearer 校验，见 middleware.SSOEvents 的
	// 活跃会话校验与连接数/频率限制），被新登录踢掉时主动收 SESSION_OFFLINE
	Router.GET("/api/sso/events", middleware.SSOEvents)

	// /api/v1/* 反代到 bmssm（鉴权由 bmssm 处理）；前置 SSO 单会话校验。
	// DeadlineMiddleware 把连接 deadline 延长到 ota-timeout：LLM 流式响应/
	// 长文件下载经反代回流的耗时可能远超常规 30s（MYS-382 超时分离）。
	bmssmTarget, err := url.Parse("http://" + bmssmServer)
	if err == nil {
		proxy := httputil.NewSingleHostReverseProxy(bmssmTarget)
		// WebSocket 升级支持
		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalDirector(req)
			// /api/v1/*：把 Host 指到 bmssm 上游，便于 bmssm 识别自身。
			if req.URL.Path != "/agent/ws" {
				req.Host = bmssmTarget.Host
				return
			}
			// /agent/ws：必须保留浏览器原始 Host——bmssm serveWS 的 CSWSH CheckOrigin
			// 用 Origin.Host == r.Host 做同源校验，反代一旦把 Host 改成 127.0.0.1:9779，
			// 任何浏览器（含同源页面）都会被 403 拒于握手之前；保留原始 Host 后
			// 同源页面通过、跨站 Origin 仍被拒（CSWSH 语义不变）。
		}
		proxy.Transport = &http.Transport{
			// 长连接支持（含 WebSocket）
			MaxIdleConns: 100,
		}
		Router.Any("/api/v1/*any",
			middleware.SSO(),
			// P2-7：不再对全路由放大 deadline 到 OTA 超时（慢速连接可占连接 12 分钟），
			// 仅长窗口路径（长文件下载、OTA 固件下载、LLM 配置/测试、日志打包下载）
			// 命中前缀才延长；其余保持服务器层 30s 读/写超时边界。LLM 流式走
			// /agent/ws（下挂 DeadlineMiddleware），不依赖此处。
			middleware.LongPathDeadline(
				[]string{
					"/api/v1/files/download",
					"/api/v1/logs/download",
					"/api/v1/ota/download",
					"/api/v1/llm-proxy",
				},
				global.OtaTimeOut,
			),
			func(c *gin.Context) {
				proxy.ServeHTTP(c.Writer, c.Request)
			})
		// Reasonix agent WS：同源 8080 → bmssm 主 server /agent/ws。
		// 复用同一 proxy（其 Director/Transport 已支持 WebSocket 升级）。
		// 注意：不加 SSO 中间件。WS 升级请求来自同源页面，前端 PicoWs 以
		// 子协议 token.<forward_key> 鉴权（bmssm serveWS 校验），不携带 SSO 所需的
		// Authorization Bearer 或 ?token=；SSO() 会因拿不到 token 而 401 中断升级。
		// DeadlineMiddleware 延长 WS 数据期连接 deadline，避免空闲链路被常规超时掐断。
		Router.Any("/agent/ws",
			middleware.DeadlineMiddleware(global.OtaTimeOut),
			func(c *gin.Context) {
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
		systemRouter.InitMetricsFwdRouter(LocalGroup)
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
