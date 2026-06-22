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

	return &http.Server{
		Addr:         ":" + address,
		Handler:      router,
		ReadTimeout:  global.OtaTimeOut,
		WriteTimeout: global.OtaTimeOut,
	}
}
