package agentproxy

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"bmssm/logger"
)

// JSON-RPC 2.0 错误码（ACP v1 对齐）。
const (
	codeParseError     = -32700
	codeInvalidRequest = -32600
	codeMethodNotFound = -32601
	codeInvalidParams  = -32602
	codeInternalError  = -32603
	codeCancelled      = -32800
)

// RPCError JSON-RPC 2.0 错误对象。
type RPCError struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

func (e *RPCError) Error() string {
	return fmt.Sprintf("acp rpc error %d: %s", e.Code, e.Message)
}

// RPCRequest 上行请求/通知（host → agent）。
type RPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      *int64          `json:"id,omitempty"` // 通知缺省
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// RPCResponse 上行响应（agent → host），按 id 与请求关联。
type RPCResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      int64           `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *RPCError       `json:"error,omitempty"`
}

// RPCDownlink 下行消息（agent → host）：无 id 为 notification；
// 有 id 且有 method 为 agent 发起的 request；有 id 无 method 为响应（由 RPCResponse 承载）。
type RPCDownlink struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      *int64          `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// InitResult initialize 握手结果。
type InitResult struct {
	ProtocolVersion int             `json:"protocolVersion"`
	AgentCapabilities json.RawMessage `json:"agentCapabilities"`
}

// SessionInfo session/list 返回项。
type SessionInfo struct {
	ID        string `json:"id"`
	Title     string `json:"title,omitempty"`
	Cwd       string `json:"cwd,omitempty"`
	CreatedAt string `json:"createdAt,omitempty"`
	UpdatedAt string `json:"updatedAt,omitempty"`
}

// Client ACP JSON-RPC 2.0 客户端。
// 依赖 ProcessManager 提供 stdin/stdout 传输；读循环 + 分发 goroutine。
type Client struct {
	pm   *ProcessManager
	next atomic.Int64

	mu      sync.Mutex
	pending map[int64]*call // 上行请求关联表
	onEvent func(*ACPSessionUpdate)
	// onNotify 收到其他下行通知/agent 发起的 request。reqID 非 nil 表示这是
	// agent 发起的 request（如 session/request_permission），host 需用
	// RespondRequest 按 reqID 回一个 JSON-RPC 响应。
	onNotify func(method string, params json.RawMessage, reqID *int64)

	closed chan struct{}
	once   sync.Once
}

// call 一次上行请求的等待记录。updates 仅在 Prompt 时非 nil（流式更新通道）。
// sessionID 仅 Prompt 时非空，用于把 session/update 通知匹配到对应 prompt 的流。
type call struct {
	id        int64
	sessionID string
	resp      chan *RPCResponse
	updates   chan *ACPSessionUpdate
}

// NewClient 创建 ACP 客户端。onEvent 收到 session/update 解析结果；
// onNotify 收到其他下行通知/agent 发起的 request（附凭 reqID 应答的 id）。
func NewClient(pm *ProcessManager, onEvent func(*ACPSessionUpdate), onNotify func(string, json.RawMessage, *int64)) *Client {
	c := &Client{
		pm:       pm,
		pending:  make(map[int64]*call),
		onEvent:  onEvent,
		onNotify: onNotify,
		closed:   make(chan struct{}),
	}
	go c.readLoop()
	return c
}

// Close 停止读循环并等待结束。
func (c *Client) Close() {
	c.once.Do(func() { close(c.closed) })
}

// Initialize 执行 initialize 握手，返回能力声明。
func (c *Client) Initialize(ctx context.Context) (*InitResult, error) {
	params, _ := json.Marshal(map[string]any{
		"protocolVersion":   1,
		"clientCapabilities": map[string]any{},
		"clientInfo": map[string]any{
			"name":    "bmssm-agentproxy",
			"title":   "bmssm Reasonix Adapter",
			"version": "1.0.0",
		},
	})
	raw, err := c.request(ctx, "initialize", params, requestTimeout)
	if err != nil {
		return nil, err
	}
	var res InitResult
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, fmt.Errorf("parse initialize result: %w", err)
	}
	return &res, nil
}

// NewSession 创建新 ACP 会话。
func (c *Client) NewSession(ctx context.Context, cwd string) (string, error) {
	params, _ := json.Marshal(map[string]any{"cwd": cwd})
	raw, err := c.request(ctx, "session/new", params, requestTimeout)
	if err != nil {
		return "", err
	}
	var res struct {
		SessionID string `json:"sessionId"`
	}
	if err := json.Unmarshal(raw, &res); err != nil || res.SessionID == "" {
		return "", fmt.Errorf("session/new: missing sessionId (raw=%s)", string(raw))
	}
	return res.SessionID, nil
}

// LoadSession 加载（回放）已持久化会话。
func (c *Client) LoadSession(ctx context.Context, id, cwd string) error {
	params, _ := json.Marshal(map[string]any{"sessionId": id, "cwd": cwd, "loadSession": true})
	_, err := c.request(ctx, "session/load", params, requestTimeout)
	return err
}

// ResumeSession 恢复已关闭会话（不回放历史）。
func (c *Client) ResumeSession(ctx context.Context, id, cwd string) error {
	params, _ := json.Marshal(map[string]any{"sessionId": id, "cwd": cwd, "loadSession": false})
	_, err := c.request(ctx, "session/resume", params, requestTimeout)
	return err
}

// CloseSession 关闭会话（保留持久化历史）。
func (c *Client) CloseSession(ctx context.Context, id string) error {
	params, _ := json.Marshal(map[string]any{"sessionId": id})
	_, err := c.request(ctx, "session/close", params, requestTimeout)
	return err
}

// DeleteSession 删除会话（停止并删除持久化历史）。
func (c *Client) DeleteSession(ctx context.Context, id string) error {
	params, _ := json.Marshal(map[string]any{"sessionId": id})
	_, err := c.request(ctx, "session/delete", params, requestTimeout)
	return err
}

// ListSessions 列出持久化会话。
func (c *Client) ListSessions(ctx context.Context, cwd string) ([]SessionInfo, error) {
	params, _ := json.Marshal(map[string]any{"cwd": cwd})
	raw, err := c.request(ctx, "session/list", params, requestTimeout)
	if err != nil {
		return nil, err
	}
	var res struct {
		Sessions []SessionInfo `json:"sessions"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, fmt.Errorf("parse session/list: %w", err)
	}
	return res.Sessions, nil
}

// Prompt 发起 session/prompt（长驻请求）。返回更新流与取消函数。
// 不设普通超时；用 promptTimeout（10min）防悬挂。
// promptBlocks 按 ACP v1 把纯文本编码为 ContentBlock 数组（reasonix 要求
// session/prompt.prompt 是 []acp.ContentBlock，非裸字符串）。
func promptBlocks(text string) []map[string]string {
	return []map[string]string{{"type": "text", "text": text}}
}

func (c *Client) Prompt(ctx context.Context, id, text string) (<-chan *ACPSessionUpdate, func() error, error) {
	params, _ := json.Marshal(map[string]any{"sessionId": id, "prompt": promptBlocks(text)})
	// 注册 pending，不阻塞等待（响应即 stopReason）
	call := c.register()
	if err := c.pm.WriteRequest(mustMarshal(RPCRequest{
		JSONRPC: "2.0",
		ID:      &call.id,
		Method:  "session/prompt",
		Params:  params,
	})); err != nil {
		c.unregister(call.id)
		return nil, nil, err
	}
	updates := make(chan *ACPSessionUpdate, 64)
	c.mu.Lock()
	call.sessionID = id
	call.updates = updates
	c.mu.Unlock()

	cancel := func() error {
		c.notify("session/cancel", mustMarshal(map[string]any{"sessionId": id}))
		return nil
	}
	return updates, cancel, nil
}

// Cancel 发送 session/cancel notification（停止生成）。
func (c *Client) Cancel(ctx context.Context, id string) error {
	params, _ := json.Marshal(map[string]any{"sessionId": id})
	c.notify("session/cancel", params)
	return nil
}

// RespondRequest 回应 agent 发起的 request（如 session/request_permission）。
// reasonix 的 ACP 是 JSON-RPC：agent 发 request 带 id，host 必须按该 id 回
// 一个 result 帧，否则 agent 永久等待。
func (c *Client) RespondRequest(reqID int64, result json.RawMessage) error {
	return c.pm.WriteRequest(mustMarshal(RPCResponse{
		JSONRPC: "2.0",
		ID:      reqID,
		Result:  result,
	}))
}

// ResolvePermission 回应 agent 发起的 session/request_permission 审批请求。
// allow=true 回 selected + optionId=allow_once（本次放行）；false 回 cancelled。
// reqID 为下行 request 的 JSON-RPC id（来自 onNotify 的 reqID）。
// 响应结构对齐 reasonix PermissionRequestResult：{"outcome":{outcome,optionId}}。
func (c *Client) ResolvePermission(reqID int64, allow bool) error {
	inner := map[string]any{"outcome": "cancelled"}
	if allow {
		inner = map[string]any{"outcome": "selected", "optionId": "allow_once"}
	}
	result, _ := json.Marshal(map[string]any{"outcome": inner})
	return c.RespondRequest(reqID, result)
}

// Steer 回合中引导（_reasonix.io/session/steer，可选）。
func (c *Client) Steer(ctx context.Context, id, text string) (*SteerResult, error) {
	params, _ := json.Marshal(map[string]any{"sessionId": id, "prompt": text})
	raw, err := c.request(ctx, "_reasonix.io/session/steer", params, requestTimeout)
	if err != nil {
		return nil, err
	}
	var res SteerResult
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, fmt.Errorf("parse steer result: %w", err)
	}
	return &res, nil
}

// SteerResult steer 返回值。
type SteerResult struct {
	// 字段以实际响应为准；当前仅透传原始结果
	Raw json.RawMessage `json:"-"`
}

// register 注册一次上行请求，返回待关联的 id。
func (c *Client) register() *call {
	id := c.next.Add(1)
	cl := &call{id: id, resp: make(chan *RPCResponse, 1)}
	c.mu.Lock()
	c.pending[id] = cl
	c.mu.Unlock()
	return cl
}

func (c *Client) unregister(id int64) {
	c.mu.Lock()
	delete(c.pending, id)
	c.mu.Unlock()
}

// request 发一次上行请求并等待响应（带超时）。
func (c *Client) request(ctx context.Context, method string, params json.RawMessage, timeout time.Duration) (json.RawMessage, error) {
	cl := c.register()
	if err := c.pm.WriteRequest(mustMarshal(RPCRequest{
		JSONRPC: "2.0",
		ID:      &cl.id,
		Method:  method,
		Params:  params,
	})); err != nil {
		c.unregister(cl.id)
		return nil, err
	}
	select {
	case resp := <-cl.resp:
		c.unregister(cl.id)
		if resp.Error != nil {
			return nil, resp.Error
		}
		return resp.Result, nil
	case <-ctx.Done():
		c.unregister(cl.id)
		return nil, ctx.Err()
	case <-time.After(timeout):
		c.unregister(cl.id)
		return nil, fmt.Errorf("acp request %s timed out after %s", method, timeout)
	case <-c.closed:
		c.unregister(cl.id)
		return nil, errors.New("acp client closed")
	}
}

// notify 发一次 notification（无响应）。
func (c *Client) notify(method string, params json.RawMessage) {
	_ = c.pm.WriteRequest(mustMarshal(RPCRequest{JSONRPC: "2.0", Method: method, Params: params}))
}

// readLoop 持续读 stdout 行，按类型分发。
// 下行消息分类：
//   - 有 id 且无 method → 响应，关联 pending
//   - 有 id 且有 method → agent 发起的 request（如 request_permission），转 onNotify
//   - 无 id → notification（session/update 等）
func (c *Client) readLoop() {
	for {
		line, err := c.pm.ReadLine()
		if err != nil {
			// 进程退出或客户端关闭：未决请求全部失败
			c.failPending(errors.New("acp stream closed"))
			// 进程崩溃后由 onReady 重建 client 并重连；本 loop 在读到
			// EOF 后等待关闭信号。若进程重启且 client 未重建（连接丢失），
			// 退避重试读，避免空转忙循环。
			c.retryRead()
		}
		if len(line) == 0 {
			continue
		}
		c.dispatch(line)
	}
}

// retryRead 在读到 EOF 后等待：客户端关闭则退出循环，否则短暂退避后重试。
func (c *Client) retryRead() {
	select {
	case <-c.closed:
		runtime.Goexit()
	default:
	}
	select {
	case <-c.closed:
		runtime.Goexit()
	case <-time.After(500 * time.Millisecond):
	}
}

// dispatch 解析一行 NDJSON 并分发。
func (c *Client) dispatch(line []byte) {
	var msg struct {
		ID     *int64          `json:"id"`
		Method string          `json:"method"`
		Result json.RawMessage `json:"result"`
		Error  *RPCError       `json:"error"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal(line, &msg); err != nil {
		logger.Warn("agentproxy: invalid acp line: %v", err)
		return
	}

	switch {
	case msg.ID != nil && msg.Method == "":
		// 响应
		resp := &RPCResponse{JSONRPC: "2.0", ID: *msg.ID, Result: msg.Result, Error: msg.Error}
		c.mu.Lock()
		cl, ok := c.pending[*msg.ID]
		if ok {
			delete(c.pending, *msg.ID)
			cl.resp <- resp
			if cl.updates != nil {
				close(cl.updates)
			}
		}
		c.mu.Unlock()
	case msg.ID != nil && msg.Method != "":
		// agent 发起的 request（如 session/request_permission、$/cancel_request）。
		// 需把 request 的 id 透传，host 才能按 id 回应（否则 agent 永久等待）。
		if c.onNotify != nil {
			c.onNotify(msg.Method, msg.Params, msg.ID)
		}
	default:
		// notification
		switch msg.Method {
		case "session/update":
			ev := parseSessionUpdate(msg.Params)
			if ev == nil {
				return
			}
			// 模块级路由（S3 Hub 按 ACP sessionId 分发到 WS 连接）
			if c.onEvent != nil {
				c.onEvent(ev)
			}
			// Prompt 的流式通道：把该会话的更新推给对应在途 prompt（驱动 typing.stop）。
			// 无匹配 prompt（如 load 回放）时跳过。
			c.mu.Lock()
			for _, cl := range c.pending {
				if cl.updates != nil && cl.sessionID != "" && cl.sessionID == ev.SessionID {
					select {
					case cl.updates <- ev:
					default:
						// 流缓冲满：丢弃（慢消费者由连接层关闭，不阻塞读循环）
					}
				}
			}
			c.mu.Unlock()
		default:
			if c.onNotify != nil {
				c.onNotify(msg.Method, msg.Params, nil)
			}
		}
	}
}

// failPending 关闭所有未决请求的等待通道。
func (c *Client) failPending(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for id, cl := range c.pending {
		cl.resp <- &RPCResponse{JSONRPC: "2.0", ID: id, Error: &RPCError{Code: codeInternalError, Message: err.Error()}}
		if cl.updates != nil {
			close(cl.updates)
		}
		delete(c.pending, id)
	}
}

// parseSessionUpdate 解析 session/update 通知为通用结构。
//
// reasonix 的 ACP v1 通知形如（sessionUpdate 为字符串判别子，载荷字段并列其下）：
//
//	{"sessionId":"...","update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"..."}}}
//	{"sessionId":"...","update":{"sessionUpdate":"tool_call","toolCallId":"...","title":"...","status":"..."}}
//
// 兼容旧式嵌套对象（判别子作为 sessionUpdate 对象的首键）：
//
//	{"sessionId":"...","update":{"sessionUpdate":{"agent_message_chunk":{"messageId":"...","content":{"text":"..."}}}}}
func parseSessionUpdate(raw json.RawMessage) *ACPSessionUpdate {
	if len(raw) == 0 {
		return nil
	}
	var outer struct {
		SessionID string          `json:"sessionId"`
		Update    json.RawMessage `json:"update"`
	}
	if err := json.Unmarshal(raw, &outer); err != nil {
		return nil
	}
	if len(outer.Update) == 0 {
		return nil
	}
	ev := parseUpdateBody(outer.Update)
	if ev == nil {
		return nil
	}
	if ev.SessionID == "" {
		ev.SessionID = outer.SessionID
	}
	return ev
}

// parseUpdateBody 从 update 对象提取判别子与公共字段。update 可能是
// reasonix 的字符串判别子形态（recommend），也可能是旧式嵌套对象形态：
//
//	{"sessionUpdate":"agent_message_chunk","content":{...}}   // 字符串形态
//	{"sessionUpdate":{"agent_message_chunk":{...}}}           // 嵌套对象形态
func parseUpdateBody(raw json.RawMessage) *ACPSessionUpdate {
	// 先探测是否为字符串判别子形态：update.sessionUpdate 是字符串，载荷字段并列。
	var str struct {
		SessionUpdate string          `json:"sessionUpdate"`
		Content       json.RawMessage `json:"content"`
		MessageID     string          `json:"messageId"`
		ToolCallID    string          `json:"toolCallId"`
		Title         string          `json:"title"`
		Kind          string          `json:"kind"`
		Status        string          `json:"status"`
		Entries       json.RawMessage `json:"entries"`
	}
	if json.Unmarshal(raw, &str) == nil && str.SessionUpdate != "" {
		ev := &ACPSessionUpdate{Discriminator: str.SessionUpdate, Raw: map[string]any{}}
		_ = json.Unmarshal(raw, &ev.Raw)
		// content 可能是单块 {type,text} 或数组；text 取单块文本。
		if len(str.Content) > 0 {
			var block struct {
				Type string `json:"type"`
				Text string `json:"text"`
			}
			if json.Unmarshal(str.Content, &block) == nil {
				ev.Content = block.Text
			}
		}
		ev.MessageID = str.MessageID
		ev.ToolCallID = str.ToolCallID
		ev.ToolCallTitle = str.Title
		ev.ToolCallKind = str.Kind
		ev.ToolCallStatus = str.Status
		return ev
	}
	// 兼容旧式嵌套对象形态：判别子作为 sessionUpdate 对象的首键。
	var m map[string]json.RawMessage
	if json.Unmarshal(raw, &m) == nil {
		if inner, ok := m["sessionUpdate"]; ok {
			return parseFlatUpdate(inner)
		}
		return parseFlatUpdate(raw)
	}
	return nil
}

// parseFlatUpdate 从旧式嵌套对象提取判别子与公共字段（保留向后兼容与既有单测）。
func parseFlatUpdate(raw json.RawMessage) *ACPSessionUpdate {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil
	}
	// 判别子：首个非公共字段
	disc := ""
	common := map[string]bool{"sessionId": true}
	for k := range m {
		if !common[k] {
			disc = k
			break
		}
	}
	if disc == "" {
		return nil
	}
	ev := &ACPSessionUpdate{Discriminator: disc, Raw: map[string]any{}}
	_ = json.Unmarshal(raw, &ev.Raw)

	switch disc {
	case "agent_message_chunk", "agent_thought_chunk":
		var body struct {
			MessageID string `json:"messageId"`
			Content   struct {
				Text string `json:"text"`
			} `json:"content"`
		}
		_ = json.Unmarshal(m[disc], &body)
		ev.MessageID = body.MessageID
		ev.Content = body.Content.Text
	case "tool_call":
		var body struct {
			ToolCallID string `json:"toolCallId"`
			Title      string `json:"title"`
			Kind       string `json:"kind"`
			Status     string `json:"status"`
		}
		_ = json.Unmarshal(m[disc], &body)
		ev.ToolCallID = body.ToolCallID
		ev.ToolCallTitle = body.Title
		ev.ToolCallKind = body.Kind
		ev.ToolCallStatus = body.Status
	case "tool_call_update":
		var body struct {
			ToolCallID string `json:"toolCallId"`
			Status     string `json:"status"`
		}
		_ = json.Unmarshal(m[disc], &body)
		ev.ToolCallID = body.ToolCallID
		ev.ToolCallStatus = body.Status
	case "session_info_update":
		var body struct {
			Title string `json:"title"`
		}
		_ = json.Unmarshal(m[disc], &body)
		ev.Title = body.Title
	}
	return ev
}

// promptTimeout 长驻请求的读保护超时（防悬挂）。
const promptTimeout = 10 * time.Minute

// requestTimeout 普通请求超时。
const requestTimeout = 30 * time.Second

// mustMarshal 序列化 RPCRequest；失败返回空对象（不应发生）。
func mustMarshal(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		return json.RawMessage(`{}`)
	}
	return b
}
