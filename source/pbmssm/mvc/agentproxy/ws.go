package agentproxy

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"bmssm/logger"
)

// wsPath WebSocket 端点路径（对齐设计文档 §6.3）。
const wsPath = "/agent/ws"

// wsIdleTimeout 连接无任何消息(含客户端应用层 ping)即关闭。
// MYS-632:原 30 分钟过长,半开连接最长假死 30 分钟;缩短到 3 分钟,
// 配合 25s 客户端 ping 与服务端 30s 控制帧 ping,数次错过即可判定死连接。
const wsIdleTimeout = 3 * time.Minute

// wsPingInterval 服务端控制帧心跳间隔。
const wsPingInterval = 30 * time.Second

// clientFrame 客户端（webchatUI）发来的 WS 帧。
// 与 pico 协议对齐：message.send / session.switch / session.delete / session.cancel / session.new。
type clientFrame struct {
	Type      string         `json:"type"`
	Payload   map[string]any `json:"payload,omitempty"`
	SessionID string         `json:"session_id,omitempty"` // 顶层（兼容 ws.js）
}

// clientMessage 从 message.send payload 提取的内容。
type clientMessage struct {
	Content string `json:"content,omitempty"`
}

// conn 一条 WS 连接：绑定一个 webchat 会话模型，独立流式累积。
//
// 锁约定（避免死锁）：
//   - Hub.mu 保护 conns/byACP 索引；Hub.HandleEvent 持 hub.mu 调 c.enqueue（c.mu）。
//   - 锁顺序：hub.mu 先于 c.mu。close() 不持 c.mu 同时拿 hub.mu（先关 done，再清理）。
//   - c.mu 保护 session/adapter/promptCancel。handleFrame 持 c.mu 处理各 handle*，
//     内部不再重复加锁。
type conn struct {
	ws        *websocket.Conn
	writeMu   sync.Mutex // gorilla 不允许并发写
	send      chan []WSFrame
	done      chan struct{}
	closeOnce sync.Once
	addr      string

	hub    *Hub
	module *Module

	mu      sync.Mutex
	session *WebchatSession
	adapter *MessageAdapter
}

// Hub 管理全部 WS 连接，并把模块级 ACP 事件路由到对应连接。
//
// 事件路由：Module.dispatchEvent（ACP session/update 解析结果）→ Hub.HandleEvent(ev)。
// 事件带 ACP sessionId；Hub 维护 acpSessionID → conn 索引，精确投递。
type Hub struct {
	module *Module
	keyMu  sync.RWMutex
	key    string // 转发 key（子协议 token.<key> 认证；空 = 放行）

	mu       sync.Mutex
	conns    map[*conn]bool
	byACP    map[string]*conn // acpSessionID -> conn
	started  bool
	unlisten func() // 模块事件监听注销句柄（Start 注册，Stop 调用）
}

// newHub 创建 Hub。key 为转发 key（对齐 llm_proxy_config.forward_key）。
func newHub(module *Module, key string) *Hub {
	return &Hub{
		module: module,
		key:    key,
		conns:  make(map[*conn]bool),
		byACP:  make(map[string]*conn),
	}
}

// SetKey 热更新转发 key（MYS-387 轮换同步）：llm-proxy ResetForwardKey 轮换后
// 调用，新连接立即按新 key 认证，旧 key 失效（无需重启 bmssm）。
func (h *Hub) SetKey(key string) {
	h.keyMu.Lock()
	h.key = key
	h.keyMu.Unlock()
}

// getKey 原子读当前转发 key。
func (h *Hub) getKey() string {
	h.keyMu.RLock()
	defer h.keyMu.RUnlock()
	return h.key
}

// Start 启动 Hub：注册模块事件监听。不再拉起独立 WS http.Server —— agent WS 端点
// 由 bmssm 主 gin server 挂载（AgentWSHandler），见 router 注册 /agent/ws。
func (h *Hub) Start() error {
	h.mu.Lock()
	if h.started {
		h.mu.Unlock()
		return nil
	}
	h.started = true
	// 注意：不再注册 HandleEvent 作为流式监听。回合（prompt）的流式内容由
	// turn.go 的 consumeTurn 从 `updates` 通道消费并经 Deliver 投递，是唯一来源。
	// 若仍注册 raw 事件 → conn.enqueue 会与 consumeTurn 双重递送，导致前端重复输出。
	h.mu.Unlock()

	return nil
}

// AgentWSHandler 供 bmssm 主 gin server 挂载 agent WS 端点（/agent/ws）。
// 路径匹配由 router 的路由决定；serveWS 内部不再校验路径。
func (h *Hub) AgentWSHandler(w http.ResponseWriter, r *http.Request) {
	h.serveWS(w, r)
}

// Stop 关闭 Hub：注销事件监听、关闭全部连接。
func (h *Hub) Stop() {
	h.mu.Lock()
	if !h.started {
		h.mu.Unlock()
		return
	}
	h.started = false
	if h.unlisten != nil {
		h.unlisten()
		h.unlisten = nil
	}
	conns := make([]*conn, 0, len(h.conns))
	for c := range h.conns {
		conns = append(conns, c)
	}
	h.conns = make(map[*conn]bool)
	h.byACP = make(map[string]*conn)
	h.mu.Unlock()

	for _, c := range conns {
		c.close()
	}
}

// HandleEvent 模块事件回调（保留兼容签名，现为 no-op）。
// 回合（prompt）的流式内容由 turn.go 的 consumeTurn 从 `updates` 通道消费并经
// Deliver 投递，是唯一来源。此方法不再转发 raw 事件，避免与 consumeTurn 双重递送
// 导致前端重复输出。
func (h *Hub) HandleEvent(ev *ACPSessionUpdate) {
	_ = ev
}

// Deliver 把已格式化好的帧投递给绑定该 ACP 会话的连接（可能有，也可能无——
// 浏览器断开时无人订阅，Turn 仍继续并在落库时持久化）。
func (h *Hub) Deliver(acpID string, frames []WSFrame) {
	if len(frames) == 0 {
		return
	}
	h.mu.Lock()
	c := h.byACP[acpID]
	h.mu.Unlock()
	if c == nil {
		return
	}
	c.enqueueFrames(frames)
}

// BroadcastSession 把帧投递给绑定该 ACP 会话的连接（会话级广播，通常恰一个）。
func (h *Hub) BroadcastSession(acpID string, frames ...WSFrame) {
	h.mu.Lock()
	c := h.byACP[acpID]
	h.mu.Unlock()
	if c == nil || len(frames) == 0 {
		return
	}
	c.enqueueFrames(frames)
}

// serveWS WebSocket 升级 + 连接生命周期。
// MYS-379 后续裁定：/agent/ws 属设备内部自用，与 18080 转发一致"不需要 key"——
// 不再校验子协议 token.<key>；仍回显客户端所选子协议（浏览器强制要求回显
// Sec-WebSocket-Protocol，否则握手失败），前端 PicoWs 携带 token.<forward_key>
// 的行为保持兼容。
func (h *Hub) serveWS(w http.ResponseWriter, r *http.Request) {
	upgrader := websocket.Upgrader{
		ReadBufferSize:  4096,
		WriteBufferSize: 4096,
		CheckOrigin:     func(r *http.Request) bool { return true },
		// 回显客户端请求的子协议（token.<key>），浏览器强制要求服务端回显
		// Sec-WebSocket-Protocol，否则握手失败。
		// 子协议只用于回显，不再做 key 校验（见函数头注释）。
		Subprotocols: websocket.Subprotocols(r),
	}
	wsConn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	c := &conn{
		ws:      wsConn,
		send:    make(chan []WSFrame, 128),
		done:    make(chan struct{}),
		addr:    r.RemoteAddr,
		hub:     h,
		module:  h.module,
		adapter: NewMessageAdapter(h.module.cfg.Model),
	}
	h.mu.Lock()
	h.conns[c] = true
	h.mu.Unlock()

	logger.Info("agentproxy: ws connected from %s", c.addr)
	go c.writeLoop()
	c.readLoop()
}

// enqueueFrames 投递一组已格式化好的帧（来自模块级回合），异步，无 adapter 转换。
func (c *conn) enqueueFrames(frames []WSFrame) {
	c.pushFrames(frames)
}

// pushFrames 把帧写入发送缓冲（带缓冲满保护）。
func (c *conn) pushFrames(frames []WSFrame) {
	select {
	case c.send <- frames:
	case <-c.done:
	default:
		// 发送缓冲满：慢消费者，关闭连接防内存膨胀
		logger.Warn("agentproxy: ws send buffer full, closing %s", c.addr)
		go c.close()
	}
}

// readLoop 主循环：读客户端帧，按类型处理；含心跳与空闲超时。
func (c *conn) readLoop() {
	defer c.close()

	// 心跳：定期 ping；写失败说明对端已半开/TCP 已坏，立即关闭连接，不再静默忽略。
	ticker := time.NewTicker(wsPingInterval)
	defer ticker.Stop()
	go func() {
		for {
			select {
			case <-ticker.C:
				if err := c.writePing(); err != nil {
					logger.Warn("agentproxy: ws ping write failed, closing %s: %v", c.addr, err)
					c.close()
					return
				}
			case <-c.done:
				return
			}
		}
	}()

	_ = c.ws.SetReadDeadline(time.Now().Add(wsIdleTimeout))
	c.ws.SetPongHandler(func(string) error {
		return c.ws.SetReadDeadline(time.Now().Add(wsIdleTimeout))
	})
	c.ws.SetPingHandler(func(string) error {
		return c.ws.SetReadDeadline(time.Now().Add(wsIdleTimeout))
	})

	for {
		msgType, data, err := c.ws.ReadMessage()
		if err != nil {
			return
		}
		if msgType != websocket.TextMessage {
			continue
		}
		// 任何客户端消息(含应用层 ping)都刷新读空闲超时,防半开误杀。
		_ = c.ws.SetReadDeadline(time.Now().Add(wsIdleTimeout))
		var frame clientFrame
		if err := json.Unmarshal(data, &frame); err != nil {
			logger.Warn("agentproxy: invalid ws frame from %s: %v", c.addr, err)
			continue
		}
		if frame.Type == "" {
			continue
		}
		c.handleFrame(frame)
	}
}

// handleFrame 处理一条客户端帧（持 c.mu）。
func (c *conn) handleFrame(frame clientFrame) {
	c.mu.Lock()
	defer c.mu.Unlock()

	switch frame.Type {
	case "ping":
		// 应用层心跳（MYS-632）：客户端 PicoWs 周期发 ping 探测连接是否真正可用，
		// 半开连接下发送会失败触发前端重连。服务端无需回包，readLoop 已刷新读超时。
	case "message.send":
		c.handleMessageSendLocked(frame)
	case "session.switch":
		c.handleSessionSwitchLocked(frame)
	case "session.delete":
		c.handleSessionDeleteLocked(frame)
	case "session.list":
		c.handleSessionListLocked()
	case "session.history":
		c.handleSessionHistoryLocked(frame)
	case "session.cancel":
		c.handleSessionCancelLocked()
	case "session.new":
		c.handleSessionNewLocked()
	case "session.rename":
		c.handleSessionRenameLocked(frame)
	case "session.autoapprove":
		c.handleSessionAutoapproveLocked(frame)
	case "permission.respond":
		c.handlePermissionRespondLocked(frame)
	default:
		logger.Warn("agentproxy: unknown ws frame type %s from %s", frame.Type, c.addr)
	}
}

// handleMessageSendLocked message.send：新建/复用会话 → prompt。
// 前置：持 c.mu。
func (c *conn) handleMessageSendLocked(frame clientFrame) {
	var msg clientMessage
	if b, err := json.Marshal(frame.Payload); err == nil {
		_ = json.Unmarshal(b, &msg)
	}
	content := strings.TrimSpace(msg.Content)
	if content == "" {
		return
	}
	// 携带已存在 webchat 会话 id → 先绑定并 resume 该会话（跨连接/跨浏览器续聊）
	wid := frame.SessionID
	if wid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			wid = p
		}
	}
	if wid != "" {
		if _, ok := c.module.Sessions().Get(wid); ok {
			ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
			defer cancel()
			client := c.module.Client()
			if client == nil {
				c.enqueueErrorLocked("reasonix 未就绪", "prompt")
				return
			}
			sw, err := c.module.Sessions().Switch(ctx, client, wid)
			if err != nil {
				c.enqueueErrorLocked("恢复会话失败："+err.Error(), "session_resume")
				return
			}
			c.resumeSessionLocked(sw)
		} else if c.session != nil {
			// MYS-635 (P1-3): 本连接已绑定会话却收到未知 wid(会话被另一标签页删除/
			// 服务端清库)→ 回错误帧,不再静默新建。否则新会话 id 与前端已 serverBound
			// 的本地 id 不一致,回包被会话隔离过滤,用户看到「已发送没回」+ 幽灵「新会话」。
			c.enqueueErrorLocked("会话不存在,可能已被删除", "session_not_found")
			return
		}
		// wid 存在但 Get 未命中 → 未知会话;若本连接尚未绑定任何会话(全新连接/前端
		// 本地新会话首消息,服务端尚无该 id),落回新建分支创建(向后兼容)。
	}
	if c.session == nil {
		if err := c.ensureSessionLocked(); err != nil {
			c.enqueueErrorLocked("无法创建会话："+err.Error(), "session_new")
			return
		}
	} else {
		c.adapter.ResetRound()
	}

	// 回合交由模块级 StartTurn 执行（连接无关：浏览器断开后 agent 继续干活，结果落库）。
	if err := c.module.StartTurn(c.session.ID, c.session.ACPSessionID, content); err != nil {
		c.enqueueErrorLocked("发送失败："+err.Error(), "prompt")
	}
}

// resumeSessionLocked 把连接绑定到已存在的 webchat 会话（resume 后绑定并注册事件路由）。
// 前置：持 c.mu。
func (c *conn) resumeSessionLocked(s *WebchatSession) {
	c.bindSessionLocked(s)
	c.hub.mu.Lock()
	c.hub.byACP[s.ACPSessionID] = c
	c.hub.mu.Unlock()
}

// ensureSessionLocked 确保连接已绑定 webchat 会话（首次发送时自动创建）。
// 前置：持 c.mu。
func (c *conn) ensureSessionLocked() error {
	if c.session != nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
	defer cancel()
	client := c.module.Client()
	if client == nil {
		return fmt.Errorf("reasonix 未就绪")
	}
	s, err := c.module.Sessions().New(ctx, client, "新会话")
	if err != nil {
		return err
	}
	c.bindSessionLocked(s)
	// 绑定 ACP sessionId → 本连接，事件路由生效
	c.hub.mu.Lock()
	c.hub.byACP[s.ACPSessionID] = c
	c.hub.mu.Unlock()
	return nil
}

// bindSessionLocked 绑定会话并通知前端。前置：持 c.mu。
func (c *conn) bindSessionLocked(s *WebchatSession) {
	c.session = s
	select {
	case c.send <- c.adapter.OnSessionCreate(s.ID):
	case <-c.done:
	}
}

// handleSessionNewLocked 显式新建会话（前端「+ 新对话」）。前置：持 c.mu。
func (c *conn) handleSessionNewLocked() {
	if err := c.ensureSessionLocked(); err != nil {
		c.enqueueErrorLocked("无法创建会话："+err.Error(), "session_new")
	}
}

// handleSessionSwitchLocked 切换会话。前置：持 c.mu。
// 前端切换会话已重开连接（协议约束：会话绑定连接生命周期），本连接只绑定当前会话。
func (c *conn) handleSessionSwitchLocked(frame clientFrame) {
	sid := frame.SessionID
	if sid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			sid = p
		}
	}
	if sid == "" {
		return
	}
	if _, ok := c.module.Sessions().Get(sid); !ok {
		c.enqueueErrorLocked("会话不存在", "session_not_found")
		return
	}
	c.enqueueErrorLocked("切换会话需重新连接", "switch_reconnect")
}

// handleSessionListLocked session.list：返回服务端全部会话摘要（不含全量消息）。
// 前置：持 c.mu。
func (c *conn) handleSessionListLocked() {
	summaries := make([]map[string]any, 0, 16)
	for _, s := range c.module.Sessions().List() {
		summaries = append(summaries, map[string]any{
			"id":           s.ID,
			"title":        s.Title,
			"acpSessionId": s.ACPSessionID,
			"updatedAt":    s.UpdatedAt,
			"messageCount": len(s.Messages),
			// 自动审批开关（跨浏览器/设备持久化，随会话保存）
			"autoApprove": s.AutoApprove,
			// 需求 2：会话是否有进行中的回合（前端忙碌转圈标记）
			"running": c.module.HasTurn(s.ACPSessionID),
		})
	}
	f := WSFrame{Type: "session.list", Payload: map[string]any{"sessions": summaries}}
	select {
	case c.send <- []WSFrame{f}:
	case <-c.done:
	}
}

// handleSessionHistoryLocked session.history：返回指定 webchat 会话的消息。
// 支持分页：payload.limit 限制返回条数(最近 N 条),payload.before 传已加载的
// 最早消息索引(从后往前第 N 条起再往前取),返回附带 hasMore 供前端判断上翻可续。
// 不带 limit/before 时保持旧行为返回全量(向前兼容旧前端/测试)。前置：持 c.mu。
func (c *conn) handleSessionHistoryLocked(frame clientFrame) {
	sid := frame.SessionID
	if sid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			sid = p
		}
	}
	if sid == "" {
		return
	}
	s, ok := c.module.Sessions().Get(sid)
	if !ok {
		c.enqueueErrorLocked("会话不存在", "session_not_found")
		return
	}
	// MYS-632 (P0-1): 拉取某会话历史即表示关注其实时流——重连后前端只发
	// session.list + session.history 来恢复,若不绑定 byACP,该会话在途回合的
	// message.create/typing.stop/session.busy=false 帧会经 Deliver 查询落空被丢弃,
	// 表现为「切走切回后本回合回答丢失,需刷新才能恢复」。这里绑定即可重新订阅流。
	// 只更新 byACP 路由,不动 c.session(连接的业务会话仍由 message.send 语义管理);
	// 也不发 session.create 帧,避免与新建会话帧语义混淆。
	c.hub.mu.Lock()
	c.hub.byACP[s.ACPSessionID] = c
	c.hub.mu.Unlock()

	// MYS-635 (P1-4): 分页窗口。history 一次全量传输在长会话(数百条)下拖慢重连/切换;
	// 前端滚动懒加载窗口按 limit 取最近 N 条,before=已载的最早索引时继续往前取。
	messages := s.Messages
	hasMore := false
	if limit, ok := intFromPayload(frame.Payload, "limit"); ok && limit > 0 {
		total := len(messages)
		end := total // 截断终点(不含)
		if before, ok := intFromPayload(frame.Payload, "before"); ok && before > 0 && before <= total {
			end = total - before
		}
		start := end - limit
		if start < 0 {
			start = 0
		}
		hasMore = start > 0 // 前面还有更早消息
		messages = messages[start:end]
	}
	f := WSFrame{
		Type:      "session.history",
		SessionID: sid,
		Payload: map[string]any{
			"session_id": sid,
			"messages":   messages,
			"title":      s.Title,
			// 自动审批开关（跨浏览器/设备持久化）
			"autoApprove": s.AutoApprove,
			"running":     c.module.HasTurn(s.ACPSessionID),
			"hasMore":     hasMore, // MYS-635 P1-4: 是否还有更早消息可翻页
		},
	}
	select {
	case c.send <- []WSFrame{f}:
	case <-c.done:
	}
}

// intFromPayload 从 map 读取 int 型字段(容忍 float64/int 两种 JSON 解码形态)。
func intFromPayload(payload map[string]any, key string) (int, bool) {
	if payload == nil {
		return 0, false
	}
	switch v := payload[key].(type) {
	case float64:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	default:
		return 0, false
	}
}

// handleSessionRenameLocked session.rename：自定义会话标题（需求 3）。
// 前置：持 c.mu。
func (c *conn) handleSessionRenameLocked(frame clientFrame) {
	sid := frame.SessionID
	if sid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			sid = p
		}
	}
	if sid == "" {
		return
	}
	title := ""
	if p, ok := frame.Payload["title"].(string); ok {
		title = p
	}
	if !c.module.Sessions().Rename(sid, title) {
		c.enqueueErrorLocked("重命名失败或标题为空", "rename")
		return
	}
	// 回执标题更新
	select {
	case c.send <- []WSFrame{{Type: "session.updated", SessionID: sid, Payload: map[string]any{"title": title}}}:
	case <-c.done:
	}
}

// handleSessionAutoapproveLocked session.autoapprove：设置会话自动审批开关（跨浏览器/设备持久化）。
// payload：{session_id, autoApprove: bool}。前置：持 c.mu。
func (c *conn) handleSessionAutoapproveLocked(frame clientFrame) {
	sid := frame.SessionID
	if sid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			sid = p
		}
	}
	if sid == "" {
		return
	}
	on := false
	if b, ok := frame.Payload["autoApprove"].(bool); ok {
		on = b
	}
	if !c.module.Sessions().SetAutoApprove(sid, on) {
		c.enqueueErrorLocked("会话不存在", "session_not_found")
		return
	}
	// 回执（供同一会话的其他订阅端/重连同步）
	select {
	case c.send <- []WSFrame{{Type: "session.updated", SessionID: sid, Payload: map[string]any{"autoApprove": on}}}:
	case <-c.done:
	}
}

// handleSessionDeleteLocked 删除会话。前置：持 c.mu。
// 前端当前不发该帧（switch/delete 为本地操作 + 重连），保留协议兼容：
// 若删除的是本连接绑定的会话，同步解绑事件路由。
func (c *conn) handleSessionDeleteLocked(frame clientFrame) {
	sid := frame.SessionID
	if sid == "" {
		if p, ok := frame.Payload["session_id"].(string); ok {
			sid = p
		}
	}
	if sid == "" {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
	defer cancel()
	if err := c.module.Sessions().Delete(ctx, c.module.Client(), sid); err != nil {
		logger.Warn("agentproxy: delete session %s failed: %v", sid, err)
	}
	if c.session != nil && c.session.ID == sid {
		acpID := c.session.ACPSessionID
		c.hub.mu.Lock()
		if c.hub.byACP[acpID] == c {
			delete(c.hub.byACP, acpID)
		}
		c.hub.mu.Unlock()
		c.session = nil
	}
}

// handleSessionCancelLocked 取消当前会话的在途回合（前端「停止」按钮）。
// 仅显式取消；连接断开不会触发（回合独立于连接继续执行）。前置：持 c.mu。
func (c *conn) handleSessionCancelLocked() {
	if c.session != nil {
		c.module.CancelTurn(c.session.ACPSessionID)
	}
}

// handlePermissionRespondLocked 处理用户对工具权限审批的回执（permission.respond）。
// payload：{session_id, request_id, allow: bool, option_id?: string}，
// 按 request_id 精确应答；option_id 可选，ask 决策时回显用户所选 optionId。前置：持 c.mu。
func (c *conn) handlePermissionRespondLocked(frame clientFrame) {
	allow := false
	if a, ok := frame.Payload["allow"].(bool); ok {
		allow = a
	}
	optionID := ""
	if o, ok := frame.Payload["option_id"].(string); ok {
		optionID = o
	}
	reqID, ok := frame.Payload["request_id"].(float64)
	if !ok {
		// 兼容旧客户端：无 request_id 时回退按会话关联（仅当该会话恰一个待审批）
		logger.Warn("agentproxy: permission.respond without request_id, ignore")
		return
	}
	c.module.RespondPermissionOption(int64(reqID), allow, optionID)
}

// enqueueErrorLocked 发送错误帧。前置：持 c.mu。
func (c *conn) enqueueErrorLocked(message, code string) {
	f := WSFrame{Type: "error", Payload: map[string]any{"message": message, "code": code}}
	if c.session != nil {
		f.SessionID = c.session.ID
	}
	select {
	case c.send <- []WSFrame{f}:
	case <-c.done:
	}
}

// writeLoop 串行写下行帧（gorilla 不允许并发写）。
func (c *conn) writeLoop() {
	for {
		select {
		case frames := <-c.send:
			for _, f := range frames {
				if err := c.writeJSON(f); err != nil {
					c.close()
					return
				}
			}
		case <-c.done:
			return
		}
	}
}

func (c *conn) writeJSON(v any) error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	_ = c.ws.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.ws.WriteJSON(v)
}

func (c *conn) writePing() error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	_ = c.ws.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.ws.WriteMessage(websocket.PingMessage, nil)
}

// close 关闭连接并清理绑定。
// 锁顺序：先 close(done)（触发 writeLoop/心跳 goroutine 退出），
// 再 c.mu 清理本地状态（不碰 hub），最后 hub.mu 解绑——避免 c.mu→hub.mu 与
// HandleEvent 的 hub.mu→c.mu 成环。
//
// 重要：连接关闭【不取消】任何进行中的回合。回合由模块级 StartTurn 持有，
// 浏览器关闭/切页/切会话时 agent 仍在服务端继续干活，结果最终落库；
// 用户在途消息不受断线影响。
func (c *conn) close() {
	c.closeOnce.Do(func() {
		close(c.done)

		c.mu.Lock()
		s := c.session
		c.session = nil
		c.mu.Unlock()

		c.hub.mu.Lock()
		if s != nil && c.hub.byACP[s.ACPSessionID] == c {
			delete(c.hub.byACP, s.ACPSessionID)
		}
		delete(c.hub.conns, c)
		c.hub.mu.Unlock()

		// 连接断开：本会话待审批的权限请求无人可批，自动拒绝，避免 agent 永久等待。
		if s != nil {
			c.module.denyPermissionsForSession(s.ACPSessionID)
		}

		_ = c.ws.Close()
		logger.Info("agentproxy: ws closed from %s", c.addr)
	})
}
