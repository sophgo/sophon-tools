// Package middleware 的 jwt.go 实现 bmssm JWT 本地校验。
//
// sophliteos 不持有用户凭据：登录/签发全部由 bmssm 完成（/api/v1/* 反代）。
// 本地敏感路由（OTA/upgrade/metrics-selection/version）不经 bmssm，因此这里
// 用与 bmssm 相同的 HS256 secret 做本地 JWT 校验，保证只有持有有效 bmssm
// JWT 的请求才能调用，未认证请求无法自造"活跃会话"。
package middleware

import (
	"errors"
	"net/http"
	"os"
	"strings"

	"sophliteos/config"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// DefaultSecret 是开发默认 secret，与 bmssm pkg/auth.DefaultSecret 保持一致。
const DefaultSecret = "ssm-dev-secret"

// devSecrets 与 bmssm pkg/auth.DevSecrets 保持一致：这些占位值出现时视为未显式
// 配置，继续走持久化文件/开发默认值。
var devSecrets = map[string]bool{
	DefaultSecret:      true,
	"bmssm-dev-secret": true,
}

// jwtSecretFile 为 bmssm 持久化随机 secret 的文件路径（测试可覆盖）。
var jwtSecretFile = "/var/lib/bmssm/jwt_secret"

// SetJWTSecretFilePath 覆盖持久化 secret 文件路径（仅测试使用）。
func SetJWTSecretFilePath(p string) { jwtSecretFile = p }

// bmssmJWTSecret 解析当前生效的 bmssm JWT secret。
// 解析链与 bmssm 运行时口径一致（见 pkg/auth.EnsureSecret + EffectiveSecret）：
//  1. 本配置 bmssm.authSecret（非开发占位值）——仅当 bmssm 显式配置
//     server.authSecret 时需要一并配置；默认部署 bmssm 生成随机 secret 持久化，
//     无需设置。
//  2. bmssm 持久化随机 secret（/var/lib/bmssm/jwt_secret，默认部署）。
//  3. 开发默认值 ssm-dev-secret（bmssm EnsureSecret 失败时的回退，与之一致）。
func bmssmJWTSecret() string {
	configured := ""
	config.Conf.RLock()
	if v := config.Conf.GetViper(); v != nil { // 配置未加载（如单测）视为无配置
		configured = strings.TrimSpace(v.GetString("bmssm.authSecret"))
	}
	config.Conf.RUnlock()
	if configured != "" && !devSecrets[configured] {
		return configured
	}
	if data, err := os.ReadFile(jwtSecretFile); err == nil {
		if s := strings.TrimSpace(string(data)); s != "" {
			return s
		}
	}
	return DefaultSecret
}

// CheckBMSSMToken 校验 token 是否为 bmssm 签发的有效 JWT（签名 + 有效期），
// 成功返回 token 中的用户名（sub）与临时标志（temp，首次登录待改密）。
func CheckBMSSMToken(tokenString string) (username string, temp bool, err error) {
	token, err := jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(bmssmJWTSecret()), nil
	})
	if err != nil {
		return "", false, err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || !token.Valid {
		return "", false, errors.New("invalid token")
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", false, errors.New("token missing subject")
	}
	if t, ok := claims["temp"].(bool); ok {
		temp = t
	}
	return sub, temp, nil
}

// RequireBMSSMToken 本地敏感路由的 JWT 中间件：请求必须携带有效 bmssm JWT
// （Authorization: Bearer 或 ?token=，与 requestToken 口径一致）。
// 临时 token（首次登录待改密）一律 403，与 bmssm Auth 中间件的
// TEMP_TOKEN_RESTRICTED 口径一致。
func RequireBMSSMToken() gin.HandlerFunc {
	return func(c *gin.Context) {
		if requestToken(c) == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":  "MISSING_TOKEN",
				"error": "unauthorized",
			})
			return
		}
		username, temp, err := CheckBMSSMToken(requestToken(c))
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":  "INVALID_TOKEN",
				"error": "unauthorized",
			})
			return
		}
		if temp {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"code":  "TEMP_TOKEN_RESTRICTED",
				"error": "must change password first",
			})
			return
		}
		c.Set("user", username)
		c.Next()
	}
}
