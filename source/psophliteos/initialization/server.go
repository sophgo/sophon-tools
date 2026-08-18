package initialization

import (
	"net/http"
	"sophliteos/config"
	"sophliteos/global"
	"sophliteos/logger"

	"github.com/gin-gonic/gin"
)

type server interface {
	ListenAndServe() error
}

func InitServer(router *gin.Engine) server {
	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	address := v.GetString("server.port")
	conf.Unlock()

	logger.Info("Starting HTTP service at %s", address)

	// 加固（MYS-382）：
	//   ReadHeaderTimeout  请求头读取有界（默认 10s）——慢速请求头攻击（slowloris）不会占用连接；
	//   Read/WriteTimeout  常规超时（默认 30s）——常规请求的读/写都有界；
	// OTA 上传、升级、SSE、反代流式长请求由路由层的 DeadlineMiddleware/心跳刷新延长（见 router/）。
	return &http.Server{
		Addr:              ":" + address,
		Handler:           router,
		ReadHeaderTimeout: global.ReadHeaderTimeOut,
		ReadTimeout:       global.TimeOut,
		WriteTimeout:      global.TimeOut,
	}
}
