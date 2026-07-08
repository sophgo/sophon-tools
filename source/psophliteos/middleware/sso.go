// Package middleware 的 sso.go 实现单会话登录（单点登录）。
//
// sophliteos web 层维护一个全局"活跃会话"（username）。新用户登录且与活跃用户不同时，
// 踢掉旧会话（旧用户后续请求被 SSO 中间件拒为 401，前端跳回登录页）。
// 仅做会话路由，真正的 JWT 鉴权仍由 ssm 完成（请求经反代到 ssm 时 ssm 校验签名）。
// 不涉及 ssm 改动。
package middleware

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

var (
	ssoMu    sync.RWMutex
	ssoUser  string // 当前活跃会话用户名；空表示无在线会话（SSO 未启用）
	ssoToken string // 当前活跃会话 token（用于 logout 匹配 + 踢人比对）
)

// --- SSE 推送：被踢的旧会话主动通知 ----------------------------------------
// 旧端登录后建立 /api/sso/events?token=X 长连接；新登录 register 时，
// 服务端向旧 token 的所有 SSE 客户端推送 SESSION_OFFLINE，前端弹窗并登出，
// 无需等旧端下次请求才发现 401。
type ssoClient struct {
	ch chan string
}

var (
	ssoClients  = map[string]map[*ssoClient]struct{}{} // token -> 该 token 的所有 SSE 客户端（多标签页）
	ssoClientMu sync.Mutex
)

// ssoNotify 向指定 token 的所有 SSE 客户端推送一个事件（非阻塞）。
func ssoNotify(token, event string) {
	if token == "" {
		return
	}
	ssoClientMu.Lock()
	set := ssoClients[token]
	for c := range set {
		select {
		case c.ch <- event:
		default: // 客户端缓冲满，跳过（重连后会重新对齐状态）
		}
	}
	ssoClientMu.Unlock()
}

// SSOActive 返回当前在线用户名。ok=false 表示无在线会话。
func SSOActive() (username string, ok bool) {
	ssoMu.RLock()
	defer ssoMu.RUnlock()
	return ssoUser, ssoUser != ""
}

// SSORegister 注册会话为活跃会话（踢掉之前的会话）。
// 捕获旧 token 并通过 SSE 主动通知旧端（不用等旧端下次请求才发现 401）。
func SSORegister(username, token string) {
	ssoMu.Lock()
	oldToken := ssoToken
	ssoUser = username
	ssoToken = token
	ssoMu.Unlock()
	ssoNotify(oldToken, "SESSION_OFFLINE")
}

// SSOLogout 若 token 匹配活跃会话则清除，并通知该 token 的 SSE 客户端。
func SSOLogout(token string) {
	ssoMu.Lock()
	matched := token != "" && ssoToken == token
	if matched {
		ssoUser = ""
		ssoToken = ""
	}
	ssoMu.Unlock()
	if matched {
		ssoNotify(token, "SESSION_OFFLINE")
	}
}

// SSO 单会话中间件。受保护路由（/api/v1/* 除 login/password）校验：
// 请求 token 必须等于活跃 token（精确比对，同账号新登录也会顶掉旧会话）；
// 否则 401 SESSION_OFFLINE。无活跃会话时放行（sophliteos 刚重启，SSO 暂不生效）。
func SSO() gin.HandlerFunc {
	return func(c *gin.Context) {
		p := c.Request.URL.Path
		// login/password 无/旧 token，跳过；sso 自身端点（含 SSE）跳过
		if p == "/api/v1/login" || p == "/api/v1/password" || strings.HasPrefix(p, "/api/sso/") {
			c.Next()
			return
		}
		ssoMu.RLock()
		activeToken := ssoToken
		ssoMu.RUnlock()
		if activeToken == "" {
			c.Next()
			return
		}
		tok := requestToken(c)
		if tok != "" && tok == activeToken {
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
			"code":          "SESSION_OFFLINE",
			"error_message": "会话已下线，另一用户已登录",
		})
	}
}

// SSOEvents SSE 推送端点：旧端登录后建立长连接 ?token=X，
// 被新登录踢掉时服务端推 SESSION_OFFLINE 事件，前端弹窗并登出（无需刷新）。
func SSOEvents(c *gin.Context) {
	token := c.Query("token")
	if token == "" {
		c.Status(http.StatusUnauthorized)
		return
	}
	cl := &ssoClient{ch: make(chan string, 4)}
	ssoClientMu.Lock()
	if ssoClients[token] == nil {
		ssoClients[token] = map[*ssoClient]struct{}{}
	}
	ssoClients[token][cl] = struct{}{}
	ssoClientMu.Unlock()
	defer func() {
		ssoClientMu.Lock()
		if set := ssoClients[token]; set != nil {
			delete(set, cl)
			if len(set) == 0 {
				delete(ssoClients, token)
			}
		}
		ssoClientMu.Unlock()
	}()

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Writer.Flush()

	ctx := c.Request.Context()
	for {
		select {
		case <-ctx.Done():
			return
		case ev := <-cl.ch:
			fmt.Fprintf(c.Writer, "event: %s\ndata: {\"event\":\"%s\"}\n\n", ev, ev)
			c.Writer.Flush()
		case <-time.After(25 * time.Second):
			fmt.Fprintf(c.Writer, ": ping\n\n") // 心跳，防中间代理超时断连
			c.Writer.Flush()
		}
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
