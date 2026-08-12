package middleware

import (
	"net/http"
	"sophliteos/global"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"

	"github.com/gin-gonic/gin"
)

func BlockerMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		if global.BlockAllRequests {
			c.JSON(http.StatusServiceUnavailable, mvc.FailWithMsg(error2.Upgradeing, "服务器升级中，暂不可用"))
			// 前端已内嵌进二进制；如需升级页可改为从内嵌 FS 读取 updating.html（当前未启用）。
			c.Abort()
		}
	}
}
