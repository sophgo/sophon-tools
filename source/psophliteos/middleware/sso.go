// Package middleware 的 sso.go 实现单会话登录（单点登录）。
//
// sophliteos web 层维护一个全局"活跃会话"（username + token）。新用户登录且与活跃用户不同时，
// 踢掉旧会话（旧用户后续请求被 SSO 中间件拒为 401，前端跳回登录页）。
// 无活跃会话时所有受保护路由一律 401，未认证请求无法访问任何受保护数据
// （MYS-378；重启后全员重登为有意行为）。
// 仅做会话路由，真正的 JWT 鉴权由 bmssm 完成（反代路径）或由本包 jwt.go 本地校验
// （本地敏感路径）。不涉及 ssm 改动。
//
// 令牌出网方式（MYS-383 收紧）：
//   - 普通请求：仅 Authorization: Bearer 头，不再接受任意路径 ?token= 兜底；
//   - 下载/终端 WS 等无法携带请求头的传输：前端先以 Authorization 头换取
//     一次性票据（POST /api/sso/ticket），真实请求带 ?ticket=<票据>，中间件
//     在白名单路径严格校验（一次性 + 60s TTL + 绑定当前活跃会话）后改写为
//     ?token=<活跃JWT> 再转发 bmssm（bmssm 侧鉴权依赖该 query，保持不变）；
//   - SSE 长连接：仅接受 Authorization 头且必须等于活跃会话 token，并对
//     单 token / 全局连接数及每 IP 连接频率做上限，防长连接耗尽。
package middleware

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"sophliteos/logger"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

var (
	ssoMu    sync.RWMutex
	ssoUser  string // 当前活跃会话用户名；空表示无在线会话（SSO 未启用）
	ssoToken string // 当前活跃会话 token（用于 logout 匹配 + 踢人比对）
)

// --- SSE 推送：被踢的旧会话主动通知 ----------------------------------------
// 旧端登录后建立 /api/sso/events（Authorization: Bearer）长连接；新登录 register 时，
// 服务端向旧 token 的所有 SSE 客户端推送 SESSION_OFFLINE，前端弹窗并登出，
// 无需等旧端下次请求才发现 401。
//
// 连接生命周期（MYS-2885）：
//   - 客户端句柄由 ssoClientMu 统一保护，ssoConnTotal 记录**真实连接数**（不是 token 桶数）；
//   - SESSION_OFFLINE 是终止事件：写出后服务端主动结束该流并回收名额；
//   - 写失败/缓冲满同样结束流，不再让失效连接长期占用名额；
//   - 会话校验与订阅在同一临界区（ssoMu）内完成，杜绝"校验用旧会话、订阅在切换之后"
//     的漏通知窗口。锁序固定为 ssoMu → sseConnTimesMu → ssoClientMu，无反向获取。
type ssoClient struct {
	ch   chan string
	once sync.Once
}

// send 非阻塞投递事件；缓冲满返回 false（调用方应据此终止该连接）。
func (c *ssoClient) send(event string) bool {
	select {
	case c.ch <- event:
		return true
	default:
		return false
	}
}

// close 关闭事件通道，令 handler 的接收分支立即退出（可重复调用）。
func (c *ssoClient) close() {
	c.once.Do(func() { close(c.ch) })
}

var (
	ssoClients   = map[string]map[*ssoClient]struct{}{} // token -> 该 token 的所有 SSE 客户端（多标签页）
	ssoConnTotal int                                    // 当前真实 SSE 连接数（全局上限依据）
	ssoClientMu  sync.Mutex

	// ssoOfflineTotal 累计成功投递的终止事件数（诊断/并发冒烟观测用，不影响判定）。
	ssoOfflineTotal int64
)

// SSEOfflineNotified 返回累计成功投递的终止事件数（诊断/并发冒烟观测用）。
func SSEOfflineNotified() int64 { return atomic.LoadInt64(&ssoOfflineTotal) }

// ssoConnCount 返回当前真实 SSE 连接数（诊断/测试用）。
func ssoConnCount() int {
	ssoClientMu.Lock()
	defer ssoClientMu.Unlock()
	return ssoConnTotal
}

// ssoNotify 向指定 token 的所有 SSE 客户端推送一个终止事件（非阻塞）。
// 无法投递（缓冲满）的客户端直接摘除并关闭，由 handler 退出后回收连接名额。
func ssoNotify(token, event string) {
	if token == "" {
		return
	}
	ssoClientMu.Lock()
	set := ssoClients[token]
	var dead []*ssoClient
	for c := range set {
		if !c.send(event) {
			dead = append(dead, c)
			continue
		}
		atomic.AddInt64(&ssoOfflineTotal, 1)
	}
	for _, c := range dead {
		delete(set, c)
		ssoConnTotal--
		c.close()
	}
	if len(set) == 0 {
		delete(ssoClients, token)
	}
	ssoClientMu.Unlock()
}

// SSOActive 返回当前在线用户名。ok=false 表示无在线会话。
func SSOActive() (username string, ok bool) {
	ssoMu.RLock()
	defer ssoMu.RUnlock()
	return ssoUser, ssoUser != ""
}

// SSOActiveToken 返回当前活跃会话 token。ok=false 表示无在线会话。
func SSOActiveToken() (token string, ok bool) {
	ssoMu.RLock()
	defer ssoMu.RUnlock()
	return ssoToken, ssoToken != ""
}

// SSORegister 注册会话为活跃会话（踢掉之前的会话）。
// 捕获旧 token 并通过 SSE 主动通知旧端（不用等旧端下次请求才发现 401）。
//
// 幂等保护（MYS-2885）：同一 (username, token) 重复注册视为同一会话的重连/刷新，
// 不重新踢自己 —— 否则前端每次重连都会把当前有效会话的 SSE 长连接踢掉，
// 形成"自踢-重连"抖动。会话实质变化（换人或换 token）才通知旧会话下线。
func SSORegister(username, token string) {
	ssoMu.Lock()
	oldToken := ssoToken
	sameSession := token != "" && token == ssoToken && username == ssoUser
	ssoUser = username
	ssoToken = token
	ssoMu.Unlock()
	if sameSession {
		return
	}
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

// --- 一次性票据：URL 无法携带 Authorization 头的传输（<a download>、WebSocket） ---
// 浏览器在这些场景下无法设置 Authorization 头，历史上直接以 ?token=<JWT> 传令牌，
// 令牌因此进入 URL/访问日志（MYS-383）。改为：前端先带 Authorization 头换取一次性
// 票据，再以 ?ticket=<票据> 发起真实请求；中间件对白名单路径做严格票据校验，
// 通过后改写为 ?token=<活跃JWT> 再转发 bmssm（bmssm 侧鉴权不变）。
// 票据一次性、60s 过期、且必须绑定"当前活跃会话"的 token，即使泄露进日志也无法复用。

const ssoTicketTTL = 60 * time.Second

type ssoTicket struct {
	token     string // 签发时的活跃 token；消费时须仍等于当前活跃 token
	expiresAt time.Time
}

var (
	ssoTickets  = map[string]*ssoTicket{}
	ssoTicketMu sync.Mutex
)

// queryTicketPaths 允许 ?ticket= 的一次性票据白名单路径。
// 除这些无法携带 Authorization 头的传输外，其余路径一律只认 Authorization 头。
var queryTicketPaths = map[string]bool{
	"/api/v1/files/download":    true, // <a download> 流式下载
	"/api/v1/logs/download":     true, // 系统日志 <a download> 流式下载（同 files/download）
	"/api/v1/hardware/terminal": true, // 浏览器 WebSocket 终端
}

// SSOIssueTicket 为调用方（须已通过活跃会话校验）签发一次性短时票据。
func SSOIssueTicket(token string) string {
	if token == "" {
		return ""
	}
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return ""
	}
	id := hex.EncodeToString(b)
	ssoTicketMu.Lock()
	now := time.Now()
	for t, v := range ssoTickets { // 顺带清理过期票据，防止 map 无限增长
		if now.After(v.expiresAt) {
			delete(ssoTickets, t)
		}
	}
	ssoTickets[id] = &ssoTicket{token: token, expiresAt: now.Add(ssoTicketTTL)}
	ssoTicketMu.Unlock()
	return id
}

// consumeTicket 一次性消费票据：不存在/过期/未绑定当前活跃 token 均拒绝。
// 无论结果如何票据立即作废（防重放）。
func consumeTicket(ticket, activeToken string) bool {
	ssoTicketMu.Lock()
	t, ok := ssoTickets[ticket]
	if ok {
		delete(ssoTickets, ticket)
	}
	ssoTicketMu.Unlock()
	if !ok || time.Now().After(t.expiresAt) {
		return false
	}
	return t.token != "" && t.token == activeToken
}

// resolveQueryTicket 处理白名单路径的 ?ticket=：校验通过后把 query 改写成
// ?token=<活跃JWT>（bmssm 依赖该参数鉴权），并返回该 token 供 SSO 中间件放行。
func resolveQueryTicket(c *gin.Context) string {
	ticket := strings.TrimSpace(c.Query("ticket"))
	if ticket == "" {
		return ""
	}
	ssoMu.RLock()
	activeToken := ssoToken
	ssoMu.RUnlock()
	if activeToken == "" || !consumeTicket(ticket, activeToken) {
		return ""
	}
	q := c.Request.URL.Query()
	q.Del("ticket")
	q.Set("token", activeToken)
	c.Request.URL.RawQuery = q.Encode()
	return activeToken
}

// SSO 单会话中间件。受保护路由（/api/v1/* 除 login/password，以及本地敏感路由）校验：
// SSOUserByToken 返回活跃会话的用户名：仅当 token 精确匹配当前活跃会话时
// 才可解析。操作审计（SaveOptLog）用它在本地无 user 表（鉴权在 bmssm）的
// 情况下把请求归因到已登录用户（MYS-382）；token 不匹配/无会话返回 ok=false。
func SSOUserByToken(token string) (string, bool) {
	ssoMu.RLock()
	defer ssoMu.RUnlock()
	if token == "" || ssoToken == "" || token != ssoToken {
		return "", false
	}
	return ssoUser, true
}

// 请求 token 必须等于活跃 token（精确比对，同账号新登录也会顶掉旧会话）；
// 否则 401 SESSION_OFFLINE。无活跃会话时一律 401（MYS-378：未认证客户端不得访问
// 任何受保护数据，必须先经 /api/v1/login 登录并 /api/sso/register 建立会话）。
// token 只从 Authorization: Bearer 头取（MYS-383：不再接受任意路径的 ?token= 兜底）；
// 无法携带头的白名单路径（下载/终端）经 queryTicketPaths 的一次性票据放行。
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
			// 无活跃会话：sophliteos 刚启动/会话被清空。持有效 bmssm JWT 的客户端
			// 也无法直接访问（vs 旧行为放行），需先经 /api/v1/login 重新登录
			// register 建立会话。重启后全员重登是本次修复的有意行为。
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"code":          "NO_SESSION",
				"error_message": "会话已失效，请重新登录",
			})
			return
		}
		tok := requestToken(c)
		if tok == "" && queryTicketPaths[p] {
			tok = resolveQueryTicket(c)
		}
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

// SSE 长连接防护上限（防连接/goroutine 耗尽）。
// 以可变量维护便于测试覆盖（同 api/v1/system 的 OTA 限额），生产取值不变：
// 单 token 8（多标签页上限）、全局 32 真实连接、同 IP 每分钟 10 次新建。
var (
	sseMaxClientsPerToken  = 8
	sseMaxClientsGlobal    = 32
	sseMaxConnsPerIPPerMin = 10
)

var (
	sseConnTimes   = map[string][]time.Time{} // ip -> 最近成功建立连接的时间戳（限流）
	sseConnTimesMu sync.Mutex
)

// sseAllowConnect 按 IP 限流：每分钟最多 sseMaxConnsPerIPPerMin 次新建连接。
func sseAllowConnect(ip string) bool {
	now := time.Now()
	cutoff := now.Add(-time.Minute)
	sseConnTimesMu.Lock()
	defer sseConnTimesMu.Unlock()
	ts := sseConnTimes[ip]
	kept := ts[:0]
	for _, t := range ts {
		if t.After(cutoff) {
			kept = append(kept, t)
		}
	}
	if len(kept) >= sseMaxConnsPerIPPerMin {
		sseConnTimes[ip] = kept
		return false
	}
	sseConnTimes[ip] = append(kept, now)
	return true
}

// sseRegisterClient 原子完成"会话校验 + 频率限流 + 容量检查 + 订阅"：
// 四步在同一临界区内完成（锁序 ssoMu → sseConnTimesMu → ssoClientMu，无反向获取），
// 因此不会出现"校验通过 → 此时被新登录顶掉 → 才订阅"从而漏收 SESSION_OFFLINE 的窗口，
// 也不会因并发建连而短暂超出上限。
//
// 鉴权先于每 IP 限流：与旧实现一致，未认证请求不消耗该 IP 的新建连接预算
// （否则同 IP 的匿名洪泛会挤掉合法客户端的重连额度）。
func sseRegisterClient(token, ip string) (cl *ssoClient, status int) {
	ssoMu.RLock()
	if ssoToken == "" || token != ssoToken {
		ssoMu.RUnlock()
		return nil, http.StatusUnauthorized
	}
	if !sseAllowConnect(ip) {
		ssoMu.RUnlock()
		return nil, http.StatusTooManyRequests
	}
	// 持 ssoMu 读锁期间 register 无法切换会话，订阅到的是"校验时那个会话"的订阅表。
	ssoClientMu.Lock()
	if ssoConnTotal >= sseMaxClientsGlobal || len(ssoClients[token]) >= sseMaxClientsPerToken {
		ssoClientMu.Unlock()
		ssoMu.RUnlock()
		return nil, http.StatusTooManyRequests
	}
	cl = &ssoClient{ch: make(chan string, 4)}
	if ssoClients[token] == nil {
		ssoClients[token] = map[*ssoClient]struct{}{}
	}
	ssoClients[token][cl] = struct{}{}
	ssoConnTotal++
	ssoClientMu.Unlock()
	ssoMu.RUnlock()
	return cl, http.StatusOK
}

// sseUnregisterClient 摘除订阅并回收连接名额（幂等：已被 ssoNotify 摘除时不重复扣减）。
func sseUnregisterClient(token string, cl *ssoClient) {
	ssoClientMu.Lock()
	if set := ssoClients[token]; set != nil {
		if _, ok := set[cl]; ok {
			delete(set, cl)
			ssoConnTotal--
		}
		if len(set) == 0 {
			delete(ssoClients, token)
		}
	}
	ssoClientMu.Unlock()
	cl.close()
}

// SSOEvents SSE 推送端点：登录后建立长连接（Authorization Bearer 鉴权），
// 被新登录踢掉时服务端推 SESSION_OFFLINE 事件，前端弹窗并登出（无需刷新）。
//
// SESSION_OFFLINE 为终止事件：写出后立即结束该流并回收连接名额。
// 旧实现在推送后继续挂在循环里等待心跳，被踢的旧连接永不释放，长连接会持续累积。
func SSOEvents(c *gin.Context) {
	// 严格校验：必须等于当前活跃会话 token；无活跃会话或令牌不匹配一律 401
	// （MYS-383：不再仅凭 ?token= 非空即建连，也不再把令牌放 URL）。
	token := requestToken(c)
	if token == "" {
		c.Status(http.StatusUnauthorized)
		return
	}
	cl, status := sseRegisterClient(token, c.ClientIP())
	if status != http.StatusOK {
		c.Status(status)
		return
	}
	defer sseUnregisterClient(token, cl)

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Writer.Flush()

	ctx := c.Request.Context()
	for {
		// 常规 WriteTimeout（默认 30s）对长连接式 SSE 过短：每轮循环（含 25s 心跳）
		// 前刷新写 deadline 到 now+2m，超时窗口有界且始终覆盖下一次心跳（MYS-382）。
		if err := http.NewResponseController(c.Writer).SetWriteDeadline(time.Now().Add(2 * time.Minute)); err != nil {
			logger.Debug("sse set write deadline failed: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case ev, ok := <-cl.ch:
			if !ok {
				// 通道被关闭（会话下线/容量摘除）：握手已建立，正常结束即可
				return
			}
			if _, err := fmt.Fprintf(c.Writer, "event: %s\ndata: {\"event\":\"%s\"}\n\n", ev, ev); err != nil {
				logger.Debug("sse write event failed: %v", err)
				return
			}
			c.Writer.Flush()
			if isTerminalSSEEvent(ev) {
				// 终止事件已写出：结束流，连接名额由 defer 回收
				return
			}
		case <-time.After(25 * time.Second):
			if _, err := fmt.Fprintf(c.Writer, ": ping\n\n"); err != nil { // 心跳，防中间代理超时断连
				logger.Debug("sse write ping failed: %v", err)
				return
			}
			c.Writer.Flush()
		}
	}
}

// isTerminalSSEEvent 判断事件写出后是否应结束服务端推送流。
func isTerminalSSEEvent(ev string) bool {
	return ev == sseEventSessionOffline
}

const sseEventSessionOffline = "SESSION_OFFLINE"

// requestToken 只取 Authorization: Bearer 头。
// MYS-383：历史上作为 query ?token= 兜底会被打进 URL/访问日志，已移除；
// 需要 URL 传凭据的传输改走 queryTicketPaths 的一次性票据（resolveQueryTicket）。
func requestToken(c *gin.Context) string {
	if h := c.GetHeader("Authorization"); h != "" {
		return strings.TrimSpace(strings.TrimPrefix(h, "Bearer "))
	}
	return ""
}

// SSORequestToken 导出版本，供路由层（如 logout 端点）取当前请求 token。
func SSORequestToken(c *gin.Context) string { return requestToken(c) }
