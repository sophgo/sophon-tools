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
			// c.File("/var/lib/sophliteos/dist/updating.html")
			c.Abort()
		}
	}
}
