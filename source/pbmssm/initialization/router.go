package initialization

import (
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/middleware"
	"bmssm/router"
)

// Routers 构建 gin engine 并挂载中间件与路由。
func Routers() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.MaxMultipartMemory = 64 << 20 // 64 MiB for file uploads
	r.Use(middleware.Recovery())
	r.Use(middleware.AccessLog())
	r.Use(middleware.RateLimit(100, 10*time.Millisecond))
	router.Register(r)
	return r
}

// listenAddr 从配置读取监听地址。
func listenAddr() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()
	ip := v.GetString("server.listenIP")
	port := v.GetString("server.port")
	if port == "" {
		port = "9779"
	}
	return ip + ":" + port
}
