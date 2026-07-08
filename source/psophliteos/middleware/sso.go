// Package middleware 的 sso.go 实现单会话登录（单点登录）。
//
// sophliteos web 层维护一个全局"活跃会话"（username）。新用户登录且与活跃用户不同时，
// 踢掉旧会话（旧用户后续请求被 SSO 中间件拒为 401，前端跳回登录页）。
// 仅做会话路由，真正的 JWT 鉴权仍由 ssm 完成（请求经反代到 ssm 时 ssm 校验签名）。
// 不涉及 ssm 改动。
package middleware

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
)

var (
	ssoMu    sync.RWMutex
	ssoUser  string // 当前活跃会话用户名；空表示无在线会话（SSO 未启用）
	ssoToken string // 当前活跃会话 token（用于 logout 匹配）
)

// SSOActive 返回当前在线用户名。ok=false 表示无在线会话。
func SSOActive() (username string, ok bool) {
	ssoMu.RLock()
	defer ssoMu.RUnlock()
	return ssoUser, ssoUser != ""
}

// SSORegister 注册会话为活跃会话（踢掉之前的会话）。同用户重复注册视为刷新。
func SSORegister(username, token string) {
	ssoMu.Lock()
	defer ssoMu.Unlock()
	ssoUser = username
	ssoToken = token
}

// SSOLogout 若 token 匹配活跃会话则清除。
func SSOLogout(token string) {
	ssoMu.Lock()
	defer ssoMu.Unlock()
	if token != "" && ssoToken == token {
		ssoUser = ""
		ssoToken = ""
	}
}

// SSO 单会话中间件。受保护路由（/api/v1/* 除 login/password）校验：
// 请求 token 的 sub(用户名) 必须等于活跃用户名；否则 401 SESSION_OFFLINE。
// 无活跃会话时放行（sophliteos 刚重启未有人登录，SSO 暂不生效）。
func SSO() gin.HandlerFunc {
	return func(c *gin.Context) {
		p := c.Request.URL.Path
		// login/password 无/旧 token，跳过；sso 自身端点跳过
		if p == "/api/v1/login" || p == "/api/v1/password" || strings.HasPrefix(p, "/api/sso/") {
			c.Next()
			return
		}
		ssoMu.RLock()
		active := ssoUser
		ssoMu.RUnlock()
		if active == "" {
			c.Next()
			return
		}
		sub := jwtSub(requestToken(c))
		if sub != "" && sub == active {
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
			"code":          "SESSION_OFFLINE",
			"error_message": "会话已下线，另一用户已登录",
		})
	}
}

// requestToken 取 Authorization Bearer 或 query ?token=（download/terminal 用 query）。
func requestToken(c *gin.Context) string {
	if h := c.GetHeader("Authorization"); h != "" {
		return strings.TrimSpace(strings.TrimPrefix(h, "Bearer "))
	}
	return strings.TrimSpace(c.Query("token"))
}

// SSORequestToken 导出版本，供路由层（如 logout 端点）取当前请求 token。
func SSORequestToken(c *gin.Context) string { return requestToken(c) }

// jwtSub 不验签地从 JWT payload 取 sub（用户名）。仅用于 SSO 会话比对，
// 真实鉴权由 ssm 完成；伪造 sub 的无效签名 JWT 会被 ssm 拒。
func jwtSub(token string) string {
	parts := strings.Split(token, ".")
	if len(parts) < 2 {
		return ""
	}
	seg := parts[1]
	payload, err := base64.RawURLEncoding.DecodeString(seg)
	if err != nil {
		if pad := (4 - len(seg)%4) % 4; pad > 0 {
			seg += strings.Repeat("=", pad)
		}
		payload, err = base64.URLEncoding.DecodeString(seg)
		if err != nil {
			return ""
		}
	}
	var m map[string]any
	if err := json.Unmarshal(payload, &m); err != nil {
		return ""
	}
	if s, ok := m["sub"].(string); ok {
		return s
	}
	return ""
}
