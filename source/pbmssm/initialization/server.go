package initialization

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/logger"
)

// InitServer 构造 *http.Server。
func InitServer(r *gin.Engine) *http.Server {
	addr := listenAddr()
	logger.Info("HTTP listen on %s", addr)
	return &http.Server{
		Addr:         addr,
		Handler:      r,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
	}
}
