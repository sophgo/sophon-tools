package middleware

import (
	"net/http"
	"sophliteos/database"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/i18n"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

func AuthMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		token := mvc.Token(c.Request)
		if token != "" {
			user := mvc.GetUser(token)
			if user != nil {
				now := time.Now()
				// 距过期不足 10 分钟则续期 2 小时（修复原恒 false 判断：
				// t.After(t.Add(10m)) 对任何 t 都为 false）。
				if now.After(user.ExpireTime) {
					user.ExpireTime = now.Add(time.Hour * 2)
					database.UpdateUser(user)
				} else if user.ExpireTime.Sub(now) < 10*time.Minute {
					user.ExpireTime = now.Add(time.Hour * 2)
					database.UpdateUser(user)
				}
				if mvc.IsMultiPartRequest(c.Request) {
					err := c.Request.ParseMultipartForm(32 << 20)
					if err != nil {
						logger.Error("multipart/form-data请求读取失败：%s %s", c.Request.RequestURI, err.Error())
						c.AbortWithStatusJSON(http.StatusInternalServerError, i18n.GetString(mvc.GetLang(c.Request), error2.Err))
						return
					}
				}
				c.Next()
				return
			}
		}

		if strings.Contains(c.Request.RequestURI, "chunked") {
			if mvc.IsMultiPartRequest(c.Request) {
				err := c.Request.ParseMultipartForm(32 << 20)
				if err != nil {
					logger.Error("multipart/form-data请求读取失败：%s %s", c.Request.RequestURI, err.Error())
					c.AbortWithStatusJSON(http.StatusInternalServerError, i18n.GetString(mvc.GetLang(c.Request), error2.Err))
					return
				}
			}
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusUnauthorized, i18n.GetString(mvc.GetLang(c.Request), error2.InvalidToken))

	}
}
