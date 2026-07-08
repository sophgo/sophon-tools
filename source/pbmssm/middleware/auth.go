package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/pkg/auth"
)

// PasswordChangePath 是临时 token 唯一允许访问的路径。
const PasswordChangePath = "/api/v1/password"

// Auth 返回 JWT 认证中间件。
// 从 Authorization: Bearer <token> 提取 token，ParseToken 校验，
// 失败返回 401；成功将 username 写入 c.Set("user", username)、temp 写入 c.Set("temp", temp)。
// 临时 token（temp=true）只允许访问 PasswordChangePath，其余端点返回 403。
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		conf := &config.Conf
		conf.RLock()
		secret := conf.GetViper().GetString("server.authSecret")
		if secret == "" {
			secret = auth.DefaultSecret
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

		username, temp, err := auth.ParseToken(tokenStr, secret)
		if err != nil {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized", "code": "INVALID_TOKEN"})
			c.Abort()
			return
		}

		// 临时 token 仅允许改密码
		if temp && c.Request.URL.Path != PasswordChangePath {
			c.JSON(http.StatusForbidden, gin.H{"error": "must change password first", "code": "TEMP_TOKEN_RESTRICTED"})
			c.Abort()
			return
		}

		c.Set("user", username)
		c.Set("temp", temp)
		c.Next()
	}
}
