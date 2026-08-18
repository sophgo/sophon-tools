package middleware

import (
	"net/http"
	"sophliteos/logger"
	"time"

	"github.com/gin-gonic/gin"
)

// DeadlineMiddleware 把当前请求所占用连接的读写 deadline 延长到 now+d。
//
// 服务器层已用常规 ReadTimeout/WriteTimeout（默认 30s）对所有请求做了有界约束
// （MYS-382），但 OTA 分片上传（50MB/片）与固件升级在慢速链路上需要更长窗口；
// 本中间件借助 Go 1.20+ 的 http.NewResponseController 在请求处理前延长连接
// deadline，实现"升级相关超时与常规读超时分离、慢速连接有界"。
func DeadlineMiddleware(d time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		rc := http.NewResponseController(c.Writer)
		dl := time.Now().Add(d)
		if err := rc.SetReadDeadline(dl); err != nil {
			logger.Debug("extend read deadline failed on %s: %v", c.Request.URL.Path, err)
		}
		if err := rc.SetWriteDeadline(dl); err != nil {
			logger.Debug("extend write deadline failed on %s: %v", c.Request.URL.Path, err)
		}
		c.Next()
	}
}
