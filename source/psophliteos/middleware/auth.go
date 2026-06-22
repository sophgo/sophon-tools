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
				if now.Before(user.ExpireTime) {
					if user.ExpireTime.After(user.ExpireTime.Add(time.Minute * 10)) {
						user.ExpireTime = now.Add(time.Hour * 2)
						database.UpdateUser(user)
					}
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
