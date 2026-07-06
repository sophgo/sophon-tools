package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/pkg/auth"
)

// Auth 返回 JWT 认证中间件。
// 从 Authorization: Bearer <token> 提取 token，ParseToken 校验，
// 失败返回 401；成功将 username 写入 c.Set("user", username)。
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		conf := &config.Conf
		conf.RLock()
		secret := conf.GetViper().GetString("server.authSecret")
		if secret == "" {
			secret = "ssm-dev-secret"
		}
		conf.RUnlock()

		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized", "code": "MISSING_TOKEN"})
			c.Abort()
			return
		}

		if !strings.HasPrefix(authHeader, "Bearer ") {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized", "code": "INVALID_TOKEN_FORMAT"})
			c.Abort()
			return
		}

		tokenStr := authHeader[7:] // 去掉 "Bearer "

		username, err := auth.ParseToken(tokenStr, secret)
		if err != nil {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized", "code": "INVALID_TOKEN"})
			c.Abort()
			return
		}

		c.Set("user", username)
		c.Next()
	}
}
