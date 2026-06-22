package initialization

import (
	"net/http/httputil"
	"net/url"
	"sophliteos/config"
	"sophliteos/logger"
	"sophliteos/middleware"
	"sophliteos/router"

	"github.com/gin-gonic/gin"
)

// 初始化总路由

func Routers() *gin.Engine {
	gin.SetMode(gin.ReleaseMode) // 设置Gin的模式为release
	Router := gin.New()
	Router.Use(gin.Recovery())

	// Router := gin.Default()

	Router.MaxMultipartMemory = 64 << 20

	systemRouter := router.RouterGroupApp.System

	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	path := v.GetString("server.www")
	conf.Unlock()

	Router.StaticFile("/_app.config.js", path+"/_app.config.js")
	Router.StaticFile("/favicon.ico", path+"/favicon.ico")
	Router.StaticFile("/", path+"/index.html") // 前端网页入口页面
	Router.Static("/assets", path+"/assets")   // dist里面的静态资源
	Router.Static("/resource", path+"/resource")

	Router.Use(middleware.BlockerMiddleware())

	PublicGroup := Router.Group("")
	{
		systemRouter.InitBaseRouter(PublicGroup) // 注册基础功能路由 不做鉴权
		systemRouter.InitDownRouter(PublicGroup)
	}

	PrivateGroup := Router.Group("")
	PrivateGroup.Use(middleware.AuthMiddleware())
	{

		systemRouter.InitSsmUpgradeRouter(PrivateGroup)
		systemRouter.InitUpgradeRouter(PrivateGroup)
		systemRouter.InitVersionRouter(PrivateGroup)
		systemRouter.InitBasicRouter(PrivateGroup)
		systemRouter.InitResourceRouter(PrivateGroup)
		systemRouter.InitPasswordRouter(PrivateGroup)
		systemRouter.InitIpRouter(PrivateGroup)
		systemRouter.InitAlarmRouter(PrivateGroup)
		systemRouter.InitLogRouter(PrivateGroup)
		systemRouter.InitOtaRouter(PrivateGroup)

	}
	logger.Info("Router Init Ok")
	return Router
}

// NewProxy 创建一个反向代理
func NewProxy(target string) *httputil.ReverseProxy {
	url, _ := url.Parse(target)
	return httputil.NewSingleHostReverseProxy(url)
}
