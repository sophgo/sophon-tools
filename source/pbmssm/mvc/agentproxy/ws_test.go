package agentproxy

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// startTestHub 启动一个测试 Hub（不绑定固定端口，用 httptest 服务器暴露）。
// 返回 Hub、服务器 URL 与转发 key。
func startTestHub(t *testing.T, module *Module, key string) *Hub {
	t.Helper()
	h := newHub(module, key)
	// 手动注册事件回调（Start 里也会做；测试直接复用 serveWS）
	module.SetEventFn(h.HandleEvent)

	mux := http.NewServeMux()
	mux.HandleFunc(wsPath, h.serveWS)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	t.Cleanup(func() { h.Stop() })

	t.Cleanup(func() {
		// 恢复模块事件回调，避免影响其他测试
		module.SetEventFn(nil)
	})
	return h
}

// wsURL 把 httptest http URL 转为 ws URL。
func wsURL(u string) string {
	return "ws" + strings.TrimPrefix(u, "http")
}

// dialWS 建立测试 WS 连接（带可选子协议）。
func dialWS(t *testing.T, url, subproto string) *websocket.Conn {
	t.Helper()
	d := websocket.Dialer{}
	if subproto != "" {
		d.Subprotocols = []string{subproto}
	}
	conn, resp, err := d.Dial(url, nil)
	if err != nil {
		if resp != nil {
			t.Fatalf("dial %s: %v (status %d)", url, err, resp.StatusCode)
		}
		t.Fatalf("dial %s: %v", url, err)
	}
	t.Cleanup(func() { conn.Close() })
	return conn
}

// readFrame 读一条 WS 帧并解析为 map。
func readFrame(t *testing.T, conn *websocket.Conn) map[string]any {
	t.Helper()
	_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("read frame: %v", err)
	}
	var m map[string]any
	if err := jsonUnmarshal(data, &m); err != nil {
		t.Fatalf("parse frame %s: %v", string(data), err)
	}
	return m
}

func jsonUnmarshal(b []byte, v any) error {
	return json.Unmarshal(b, v)
}

func bufioNewScanner(r io.Reader) *bufio.Scanner {
	return bufio.NewScanner(r)
}

// MYS-379 后续裁定：/agent/ws 与 18080 一致"不需要 key"——
// 无论是否配置转发 key，客户端携带任意子协议（或完全不带）均可建立连接；
// 服务端保留对所选子协议的回显（浏览器强制要求，否则握手失败）。
func TestWSNoKeyRequired(t *testing.T) {
	mod := NewModule(DefaultConfig(), nil, nil)
	h := newHub(mod, "secret-key-123") // 模拟已配置转发 key
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	// 正确子协议 → 升级成功 + 回显
	d := websocket.Dialer{Subprotocols: []string{"token.secret-key-123"}}
	conn, resp, err := d.Dial(wsURL(srv.URL)+wsPath, nil)
	if err != nil {
		t.Fatalf("valid subproto dial failed: %v", err)
	}
	conn.Close()
	if got := resp.Header.Get("Sec-Websocket-Protocol"); got != "token.secret-key-123" {
		t.Fatalf("echoed subproto = %q, want token.secret-key-123", got)
	}

	// 错误子协议 → 仍升级成功（不再校验 key）
	d2 := websocket.Dialer{Subprotocols: []string{"token.wrong"}}
	conn2, _, err := d2.Dial(wsURL(srv.URL)+wsPath, nil)
	if err != nil {
		t.Fatalf("wrong subproto must still connect without key check: %v", err)
	}
	conn2.Close()

	// 无子协议 → 仍升级成功（不再校验 key）
	d3 := websocket.Dialer{}
	conn3, _, err := d3.Dial(wsURL(srv.URL)+wsPath, nil)
	if err != nil {
		t.Fatalf("no subproto must still connect without key check: %v", err)
	}
	conn3.Close()
}

func TestWSAuthEmptyKeyAllowsAll(t *testing.T) {
	// key 为空 → 认证放行
	mod := NewModule(DefaultConfig(), nil, nil)
	h := newHub(mod, "")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	conn, _, err := websocket.DefaultDialer.Dial(wsURL(srv.URL)+wsPath, nil)
	if err != nil {
		t.Fatalf("empty key dial failed: %v", err)
	}
	conn.Close()
}

// TestHubKeyRotation 验证 MYS-387 轮换同步：SetKey 后旧子协议立即失效（403），
// 新子协议放行——无需重启 bmssm。
// TestHubKeyRotation MYS-379 裁定后 key 不再参与 WS 鉴权：
// 轮换转发 key 不影响 /agent/ws 连接（任何子协议/无子协议均可建立），
// SetKey 仅保留轮换同步语义（前端 PicoWs 子协议回显兼容）。
func TestHubKeyRotation(t *testing.T) {
	mod := NewModule(DefaultConfig(), nil, nil)
	h := newHub(mod, "old-key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	// 轮换前：任意子协议均可连接
	d0 := websocket.Dialer{Subprotocols: []string{"token.old-key"}}
	conn0, _, err := d0.Dial(wsURL(srv.URL)+wsPath, nil)
	if err != nil {
		t.Fatalf("pre-rotation old key dial failed: %v", err)
	}
	conn0.Close()

	// 轮换：新 key 生效（不再影响鉴权，仅同步状态）
	h.SetKey("new-key")

	// 已轮换掉的旧 key → 仍可连接（不再校验），子协议原样回显
	d1 := websocket.Dialer{Subprotocols: []string{"token.old-key"}}
	conn1, resp1, err1 := d1.Dial(wsURL(srv.URL)+wsPath, nil)
	if err1 != nil {
		t.Fatalf("old key after rotation must still connect (no key check): %v", err1)
	}
	conn1.Close()
	if got := resp1.Header.Get("Sec-Websocket-Protocol"); got != "token.old-key" {
		t.Fatalf("echoed subproto = %q, want token.old-key", got)
	}

	// 新 key → 连接成功 + 回显
	d2 := websocket.Dialer{Subprotocols: []string{"token.new-key"}}
	conn2, resp2, err2 := d2.Dial(wsURL(srv.URL)+wsPath, nil)
	if err2 != nil {
		t.Fatalf("new key dial failed: %v", err2)
	}
	conn2.Close()
	if resp2.Header.Get("Sec-Websocket-Protocol") != "token.new-key" {
		t.Fatalf("echoed subproto = %q, want token.new-key", resp2.Header.Get("Sec-Websocket-Protocol"))
	}

	// 无子协议 → 仍可连接（不再校验 key）
	d3 := websocket.Dialer{}
	conn3, _, err3 := d3.Dial(wsURL(srv.URL)+wsPath, nil)
	if err3 != nil {
		t.Fatalf("no subproto must still connect without key check: %v", err3)
	}
	conn3.Close()
}

// mockModuleForWS 构造一个带 ACP client 的模块（Client() 可交互）。
// client 的事件回调链到模块 dispatchEvent（与真实装配一致），
// Hub 通过 SetEventFn 注入后事件可路由到连接。
func mockModuleForWS(t *testing.T) (*Module, *stdIOTransport) {
	t.Helper()
	tr, pm := newStdIOTransport(t)
	mod := &Module{
		cfg:      Config{Enabled: true, Model: "test-model", Port: DefaultPort},
		sessions: NewSessionManager(nil, t.TempDir()),
		pm:       pm,
		hub:      nil,
		turns:    make(map[string]*Turn),
	}
	client := NewClient(pm, mod.dispatchEvent, mod.dispatchNotify)
	mod.client = client
	return mod, tr
}

// TestWSMessageSendStreaming 集成测试：
// 客户端 WS 发送 message.send → 服务端调 ACP session/new + session/prompt →
// mock 回 agent_message_chunk → WS 收到 message.create / message.update → typing.stop。
func TestWSMessageSendStreaming(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h // 回合通过 hub 投递帧
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	// 构造 ACP 交互：session/new 返回 sid，prompt 流式返回。
	go func() {
		sc := bufioNewScanner(tr.in)
		// 首次请求应为 session/new
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		if req.Method != "session/new" {
			t.Errorf("first request = %s, want session/new", req.Method)
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-1"}})

		// 第二个请求：session/prompt
		req2, err := tr.readRequestErr(sc)
		if err != nil || req2.Method != "session/prompt" {
			t.Errorf("second request = %v, want session/prompt", req2)
			return
		}
		// prompt 必须是 ContentBlock 数组（ACP v1 / reasonix 要求），非裸字符串
		var p2 struct {
			Prompt []map[string]string `json:"prompt"`
		}
		if err := json.Unmarshal(req2.Params, &p2); err != nil || len(p2.Prompt) != 1 ||
			p2.Prompt[0]["type"] != "text" || p2.Prompt[0]["text"] != "你好" {
			t.Errorf("session/prompt params = %s, want content-block array", req2.Params)
			return
		}
		// 流式通知 + 响应
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0", "method": "session/update",
			"params": map[string]any{
				"sessionId": "acp-1",
				"update":    map[string]any{"sessionUpdate": map[string]any{"agent_message_chunk": map[string]any{"messageId": "m1", "content": map[string]any{"text": "你好"}}}},
			},
		})
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")

	// 发送 message.send
	_ = conn.WriteJSON(map[string]any{
		"type":    "message.send",
		"payload": map[string]any{"content": "你好"},
	})

	// 期望收到：typing.start → message.create → message.update（或直接 create）→ typing.stop
	var gotCreate, gotUpdate, gotTypingStop bool
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		switch m["type"] {
		case "typing.start":
		case "message.create":
			gotCreate = true
			p := m["payload"].(map[string]any)
			if p["kind"] != "text" {
				t.Errorf("create kind = %v, want text", p["kind"])
			}
			if p["content"] != "你好" {
				t.Errorf("create content = %v, want 你好", p["content"])
			}
			if p["message_id"] != "m1" {
				t.Errorf("create message_id = %v, want m1", p["message_id"])
			}
		case "message.update":
			gotUpdate = true
		case "typing.stop":
			gotTypingStop = true
		}
		if gotCreate && gotTypingStop {
			break
		}
	}
	if !gotCreate {
		t.Fatal("no message.create received")
	}
	if !gotTypingStop {
		t.Fatal("no typing.stop received")
	}
	_ = gotUpdate
}

// TestWSDisconnectCleansUp 断线清理：关闭连接后，事件不再投递给该连接。
func TestWSDisconnectCleansUp(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-1"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "hi"}})

	// 等会话创建完成
	waitFor(t, 3*time.Second, "session created", func() bool {
		h.mu.Lock()
		defer h.mu.Unlock()
		return len(h.byACP) == 1
	})

	conn.Close()
	// 等待清理
	waitFor(t, 3*time.Second, "conn cleaned", func() bool {
		h.mu.Lock()
		defer h.mu.Unlock()
		return len(h.byACP) == 0
	})
}

// TestWSNewSessionBinding 验证 session.new 帧类型绑定（首个 message.send 自动建会话）。
func TestWSNewSessionBinding(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-9"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "开始"}})

	// 期望收到 typing.start 前有 session.create（绑定 webchat id）
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "session.create" {
			sid, _ := m["session_id"].(string)
			if sid == "" {
				t.Fatal("session.create without session_id")
			}
			return
		}
	}
	t.Fatal("no session.create received")
}

// TestWSUnknownTypeIgnored 未知帧类型不导致连接关闭。
func TestWSUnknownTypeIgnored(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-ign"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "foo.bar", "payload": map[string]any{"x": 1}})

	// 连接仍存活：发一个 session.new 应能收到 session.create
	_ = conn.WriteJSON(map[string]any{"type": "session.new"})
	_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("connection should stay alive after unknown frame: %v", err)
	}
	if !strings.Contains(string(data), "session.create") {
		t.Errorf("after session.new got %s, want session.create", string(data))
	}
}

// TestHubDeliverRouting 验证 Hub.Deliver 把已格式化帧按 ACP sessionId 路由到绑定连接。
// （duplicate 回归：内容流式现由 turn 的 consumeTurn→Deliver 单一来源投递，
//
//	HandleEvent 已为 no-op，不再走 conn.adapter 双重转发。）
func TestHubDeliverRouting(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-route"}})
		req2, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "hi"}})

	// 等会话绑定
	waitFor(t, 3*time.Second, "bind", func() bool {
		h.mu.Lock()
		defer h.mu.Unlock()
		return len(h.byACP) == 1
	})

	// 模拟 turn 把预格式化帧经 Deliver 投递
	h.Deliver("acp-route", []WSFrame{{
		Type:      "message.create",
		SessionID: "web-c0",
		Payload:   map[string]any{"content": "路由成功", "kind": "text", "message_id": "m1"},
	}})

	deadline := time.Now().Add(3 * time.Second)
	found := false
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "message.create" {
			p := m["payload"].(map[string]any)
			if p["content"] == "路由成功" {
				found = true
				break
			}
		}
	}
	if !found {
		t.Fatal("frame not routed to connection via Deliver")
	}
}

// TestWSMultiSession 多会话验证：
//   - 同一连接连续发送两条消息 → 复用同一 ACP 会话（只创建一个 session/new）
//   - 新连接发送 → 创建新的 ACP 会话（第二个 session/new）
//
// sessionSummaries 从 session.list 帧提取摘要列表。
func sessionSummaries(t *testing.T, conn *websocket.Conn) []map[string]any {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.list" {
			continue
		}
		raw, ok := m["payload"].(map[string]any)["sessions"].([]any)
		if !ok {
			t.Fatalf("session.list payload.sessions not array: %v", m["payload"])
		}
		out := make([]map[string]any, 0, len(raw))
		for _, item := range raw {
			mm, ok := item.(map[string]any)
			if !ok {
				t.Fatalf("session.list item not object: %v", item)
			}
			out = append(out, mm)
		}
		return out
	}
	t.Fatal("no session.list frame received")
	return nil
}

func TestWSSessionList(t *testing.T) {
	mod, _ := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	// 预置两个服务端会话（直接写 SessionManager，不经过 ACP）
	sm := mod.sessions
	first := &WebchatSession{ID: "web-1", ACPSessionID: "acp-1", Title: "标题A", Messages: []ChatMessage{{Role: "user", Content: "hi"}}}
	second := &WebchatSession{ID: "web-2", ACPSessionID: "acp-2", Title: "标题B", Messages: []ChatMessage{}}
	sm.mu.Lock()
	sm.sessions["web-1"] = first
	sm.sessions["web-2"] = second
	sm.mu.Unlock()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "session.list"})

	list := sessionSummaries(t, conn)
	if len(list) != 2 {
		t.Fatalf("session.list len = %d, want 2: %v", len(list), list)
	}
	found := map[string]bool{}
	for _, s := range list {
		found[s["id"].(string)] = true
		if s["title"] == "标题A" && s["messageCount"].(float64) != 1 {
			t.Errorf("标题A messageCount = %v, want 1", s["messageCount"])
		}
	}
	if !found["web-1"] || !found["web-2"] {
		t.Errorf("session.list missing ids: %v", list)
	}
}

func TestWSSessionHistory(t *testing.T) {
	mod, _ := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	sm := mod.sessions
	sm.mu.Lock()
	sm.sessions["web-9"] = &WebchatSession{
		ID: "web-9", ACPSessionID: "acp-9", Title: "历史",
		Messages: []ChatMessage{
			{Role: "user", Content: "你好"},
			{Role: "assistant", Kind: "text", Content: "很高兴", Model: "m1"},
			{Role: "assistant", Kind: "thought", Content: "思考中"},
		},
	}
	sm.mu.Unlock()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-9"})

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.history" {
			continue
		}
		p := m["payload"].(map[string]any)
		if p["session_id"] != "web-9" {
			t.Fatalf("history echoed session_id = %v, want web-9", p["session_id"])
		}
		raw, _ := p["messages"].([]any)
		if len(raw) != 3 {
			t.Fatalf("history messages len = %d, want 3", len(raw))
		}
		msg1, _ := raw[1].(map[string]any)
		if msg1["kind"] != "text" || msg1["content"] != "很高兴" {
			t.Errorf("msg[1] = %v, want kind=text content=很高兴", msg1)
		}
		return
	}
	t.Fatal("no session.history frame received")
}

func TestWSMultiSession(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	var newCalls int32
	go func() {
		sc := bufioNewScanner(tr.in)
		for {
			req, err := tr.readRequestErr(sc)
			if err != nil {
				return
			}
			// notification（无 id，如 session/cancel）不回复
			if req.ID == nil {
				continue
			}
			switch req.Method {
			case "session/new":
				atomic.AddInt32(&newCalls, 1)
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-" + strconv.FormatInt(*req.ID, 10)}})
			case "session/prompt":
				// 静默返回 stopReason（无流式通知，避免事件路由干扰）
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"stopReason": "end_turn"}})
			default:
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "error": map[string]any{"code": -32601, "message": "Method not found"}})
			}
		}
	}()

	// 连接 1：两条连续消息
	conn1 := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn1.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "第一条"}})
	// 等 session.create
	waitFrame := func(t *testing.T, conn *websocket.Conn, wantType string) {
		t.Helper()
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			m := readFrame(t, conn)
			if m["type"] == wantType {
				return
			}
		}
		t.Fatalf("no %s frame", wantType)
	}
	waitFrame(t, conn1, "session.create")
	waitFrame(t, conn1, "typing.start")

	_ = conn1.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "第二条"}})
	waitFrame(t, conn1, "typing.start")

	// 连接 2：新会话
	conn2 := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn2.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "新连接"}})
	waitFrame(t, conn2, "session.create")

	// 等待所有 session/new 处理完
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && atomic.LoadInt32(&newCalls) < 2 {
		time.Sleep(20 * time.Millisecond)
	}
	if got := atomic.LoadInt32(&newCalls); got != 2 {
		t.Errorf("session/new calls = %d, want 2 (connection1 reuses session, connection2 creates new)", got)
	}
}

func TestWSPersistAssistantOnRoundEnd(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		if req.Method != "session/new" {
			t.Errorf("first = %s, want session/new", req.Method)
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-p1"}})
		req2, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0", "method": "session/update",
			"params": map[string]any{"sessionId": "acp-p1", "update": map[string]any{"sessionUpdate": map[string]any{"agent_message_chunk": map[string]any{"messageId": "a1", "content": map[string]any{"text": "回答"}}}}},
		})
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "问题"}})
	// 一直读到 typing.stop（round 结束）
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "typing.stop" {
			break
		}
	}
	// round 落库后校验：Messages = [user问题, assistant回答]
	waitFor(t, 3*time.Second, "assistant persisted", func() bool {
		for _, s := range mod.sessions.List() {
			if s.ACPSessionID == "acp-p1" && len(s.Messages) == 2 {
				return s.Messages[1].Role == "assistant" && s.Messages[1].Content == "回答"
			}
		}
		return false
	})
}

func TestWSSendResumeExistingSession(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	// 预置已有会话（含 ACP session id，state=closed 才会触发 resume）
	sm := mod.sessions
	sm.mu.Lock()
	sm.sessions["web-r1"] = &WebchatSession{ID: "web-r1", ACPSessionID: "acp-r1", Title: "续聊", State: SessionClosed}
	sm.mu.Unlock()

	var mu sync.Mutex
	var calls []string
	go func() {
		sc := bufioNewScanner(tr.in)
		for {
			req, err := tr.readRequestErr(sc)
			if err != nil {
				return
			}
			if req.ID == nil {
				continue
			}
			mu.Lock()
			calls = append(calls, req.Method)
			mu.Unlock()
			switch req.Method {
			case "session/resume":
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{}})
			case "session/prompt":
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"stopReason": "end_turn"}})
			default:
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "error": map[string]any{"code": -32601, "message": "Method not found"}})
			}
		}
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	// 携带 webchat id 发送 → 应 resume 而非 session/new
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "session_id": "web-r1", "payload": map[string]any{"content": "继续"}})

	// 等待 prompt 发生
	waitFor(t, 3*time.Second, "prompt called", func() bool {
		mu.Lock()
		defer mu.Unlock()
		for _, m := range calls {
			if m == "session/prompt" {
				return true
			}
		}
		return false
	})
	var sawNew, sawResume bool
	mu.Lock()
	for _, m := range calls {
		if m == "session/new" {
			sawNew = true
		}
		if m == "session/resume" {
			sawResume = true
		}
	}
	mu.Unlock()
	if sawNew {
		t.Error("unexpected session/new: existing webchat id should resume, not create")
	}
	if !sawResume {
		t.Error("expected session/resume for existing webchat session")
	}
}

// TestWSTurnSurvivesDisconnect 回归：浏览器断开（关页/切页/切会话）时，进行中的
// 回合不得被取消，agent 在服务端继续干活并把结果落库。
// 旧实现：conn.close 取消 prompt → 断开即中断；新实现：回合独立于连接（module.StartTurn），
// 断线后不发送 session/cancel，回合随 prompt 自然结束，用户消息已持久化。
func TestWSTurnSurvivesDisconnect(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	var cancelSeen bool
	var mu sync.Mutex
	// 模拟端：session/new → 建会话；session/prompt → 返回结果。记录是否出现取消帧。
	go func() {
		sc := bufioNewScanner(tr.in)
		for {
			req, err := tr.readRequestErr(sc)
			if err != nil {
				return
			}
			if req.ID == nil {
				// notification（session/cancel 为无 id 通知）
				if req.Method == "session/cancel" {
					mu.Lock()
					cancelSeen = true
					mu.Unlock()
				}
				continue
			}
			switch req.Method {
			case "session/new":
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-s1"}})
			case "session/prompt":
				_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"stopReason": "end_turn"}})
			}
		}
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "问题"}})
	// 等 session.create（会话已建，prompt 已发起）
	waitFor(t, 3*time.Second, "session create", func() bool { return len(mod.sessions.List()) > 0 })

	// 立即关闭连接（模拟浏览器关闭 / 切页 / 切会话断线）
	_ = conn.Close()

	// 断言：断线后未发送 session/cancel（回合未被连接关闭取消）
	mu.Lock()
	cancelled := cancelSeen
	mu.Unlock()
	if cancelled {
		t.Fatal("turn was cancelled on disconnect (session/cancel sent) — must survive")
	}
	// 用户消息已持久化（回合真正完成并落库）
	waitFor(t, 3*time.Second, "user msg persisted", func() bool {
		for _, s := range mod.sessions.List() {
			if s.ACPSessionID == "acp-s1" && len(s.Messages) >= 1 && s.Messages[0].Role == "user" {
				return true
			}
		}
		return false
	})
}

// TestWSNoDuplicateFrames 回归（duplicate 输出）：一个流式 chunk 只投递一次，
// 不因 turn(consumeTurn) 与 HandleEvent 双通道各发一份而重复。
func TestWSNoDuplicateFrames(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		if req.Method != "session/new" {
			t.Errorf("first = %s, want session/new", req.Method)
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-n1"}})
		req2, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		// 单个 stream chunk（同一 messageId 只发一次 update）
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "method": "session/update", "params": map[string]any{"sessionId": "acp-n1", "update": map[string]any{"sessionUpdate": map[string]any{"agent_message_chunk": map[string]any{"messageId": "dup-1", "content": map[string]any{"text": "唯一"}}}}}})
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "问"}})

	// 收集 message.create 帧（同一 message_id 应精确一次）
	creates := 0
	allFrames := []string{}
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		allFrames = append(allFrames, m["type"].(string))
		if m["type"] == "message.create" {
			creates++
			p := m["payload"].(map[string]any)
			if mid := p["message_id"]; mid != "dup-1" {
				t.Fatalf("unexpected message_id: %v", mid)
			}
		}
		// 收到回合结束的 typing.stop 后，再读一点点确认没有多余 create
		if m["type"] == "typing.stop" && creates > 0 {
			// 已见 create + 回合结束，稍作稳定再停止读取
			time.Sleep(200 * time.Millisecond)
			break
		}
		if m["type"] == "session.busy" && creates > 0 {
			break
		}
	}
	t.Logf("all frames: %v", allFrames)
	if creates != 1 {
		t.Fatalf("message.create delivered %d times, want exactly 1 (duplicate bug)", creates)
	}
}

// TestWSHistoryBindsACP MYS-632 (P0-1)：拉取某会话历史即绑定 byACP 订阅其实时流。
// 重连后前端只发 session.list + session.history,若不绑定,该会话在途回合的
// message.create/typing.stop/busy=false 帧会经 Deliver 查询落空被丢弃。
func TestWSHistoryBindsACP(t *testing.T) {
	mod, _ := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	sm := mod.sessions
	sm.mu.Lock()
	sm.sessions["web-h"] = &WebchatSession{
		ID: "web-h", ACPSessionID: "acp-h", Title: "绑定",
		Messages: []ChatMessage{{Role: "user", Content: "hi"}},
	}
	sm.mu.Unlock()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	// 重连场景：新连接不发 message.send,只发 session.history
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-h"})

	// 先消费 session.history 响应帧（读到为止）
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "session.history" {
			break
		}
	}

	// 拉历史后 byACP 已绑定到本连接 → Deliver 在途帧可达
	h.Deliver("acp-h", []WSFrame{{
		Type:      "message.create",
		SessionID: "web-h",
		Payload:   map[string]any{"content": "在途答案", "kind": "text", "message_id": "mh"},
	}})

	deadline = time.Now().Add(3 * time.Second)
	found := false
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "message.create" && m["payload"].(map[string]any)["content"] == "在途答案" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("in-flight turn frames dropped after history-only reconnect (byACP not bound)")
	}
}

// TestWSPingFrame 客户端应用层 ping 帧不产生回包、不关闭连接,可继续收发。
func TestWSPingFrame(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-p"}})
		req2, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "method": "session/update", "params": map[string]any{"sessionId": "acp-p", "update": map[string]any{"sessionUpdate": map[string]any{"agent_message_chunk": map[string]any{"messageId": "mp", "content": map[string]any{"text": "ping后仍有回复"}}}}}})
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	// 发送应用层 ping
	_ = conn.WriteJSON(map[string]any{"type": "ping"})
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "问"}})

	// ping 后消息仍能正常收发（连接未被 ping 帧关闭/无回包干扰）
	deadline := time.Now().Add(4 * time.Second)
	gotCreate, gotTypingStop := false, false
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		switch m["type"] {
		case "ping":
			t.Fatal("server must not echo client ping frame")
		case "message.create":
			gotCreate = true
		case "typing.stop":
			gotTypingStop = true
		}
		if gotCreate && gotTypingStop {
			break
		}
	}
	if !gotCreate || !gotTypingStop {
		t.Fatalf("after ping: gotCreate=%v gotTypingStop=%v, want both", gotCreate, gotTypingStop)
	}
}

// TestWSMessageSendUnknownWidOnBoundConn MYS-635 (P1-3)：本连接已绑定会话却携带
// 未知 wid → 回 session_not_found,不再静默新建。防「已发送没回」+ 幽灵「新会话」。
func TestWSMessageSendUnknownWidOnBoundConn(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		// 首次 message.send(无 wid) → session/new 创建会话
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-ok"}})
		req2, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "method": "session/update", "params": map[string]any{"sessionId": "acp-ok", "update": map[string]any{"sessionUpdate": map[string]any{"agent_message_chunk": map[string]any{"messageId": "m1", "content": map[string]any{"text": "第一条"}}}}}})
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	// 首次正常发消息,连接绑定到会话
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "hi"}})
	waitFor(t, 3*time.Second, "session bound", func() bool {
		h.mu.Lock()
		defer h.mu.Unlock()
		return len(h.byACP) == 1
	})

	// 绑定后发送未知 wid(会话已被删/清库)→ 期望 session_not_found,而非新建
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "session_id": "deleted-session-xyz", "payload": map[string]any{"content": "hello", "session_id": "deleted-session-xyz"}})

	deadline := time.Now().Add(3 * time.Second)
	gotErr := false
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "error" {
			p := m["payload"].(map[string]any)
			if p["code"] == "session_not_found" {
				gotErr = true
				break
			}
		}
	}
	if !gotErr {
		t.Fatal("unknown wid on bound conn: expected session_not_found error, got none")
	}
}

// TestWSHistoryPagination MYS-635 (P1-4)：session.history 支持 limit/before 分页,
// 返回最近 limit 条 + hasMore;before 往前翻页。
func TestWSHistoryPagination(t *testing.T) {
	mod, _ := mockModuleForWS(t)
	h := newHub(mod, "key")
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)

	sm := mod.sessions
	sm.mu.Lock()
	msgs := make([]ChatMessage, 0, 25)
	for i := 0; i < 25; i++ {
		msgs = append(msgs, ChatMessage{Role: "user", Content: "m" + strconv.Itoa(i)})
	}
	sm.sessions["web-page"] = &WebchatSession{
		ID: "web-page", ACPSessionID: "acp-page", Title: "分页",
		Messages: msgs,
	}
	sm.mu.Unlock()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")

	// 第一页：limit=10,期望返回最后 10 条,hasMore=true
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-page", "payload": map[string]any{"limit": 10}})
	deadline := time.Now().Add(3 * time.Second)
	var gotHasMore bool
	var firstLen int
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.history" {
			continue
		}
		p := m["payload"].(map[string]any)
		firstLen = len(p["messages"].([]any))
		if b, ok := p["hasMore"].(bool); ok && b {
			gotHasMore = true
		}
		// 最后一条应为 m24
		msgsAny := p["messages"].([]any)
		last := msgsAny[len(msgsAny)-1].(map[string]any)
		if last["content"] != "m24" {
			t.Fatalf("first page last = %v, want m24", last["content"])
		}
		break
	}
	if firstLen != 10 {
		t.Fatalf("first page len = %d, want 10", firstLen)
	}
	if !gotHasMore {
		t.Fatal("first page hasMore = false, want true")
	}

	// 第二页：before=10(跳过尾部 10 条),再往前取 10 条(m5..m14),hasMore=true
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-page", "payload": map[string]any{"limit": 10, "before": 10}})
	deadline = time.Now().Add(3 * time.Second)
	var secondFirst, secondLast string
	var secondLen int
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.history" {
			continue
		}
		p := m["payload"].(map[string]any)
		msgsAny := p["messages"].([]any)
		secondLen = len(msgsAny)
		secondFirst = msgsAny[0].(map[string]any)["content"].(string)
		secondLast = msgsAny[len(msgsAny)-1].(map[string]any)["content"].(string)
		break
	}
	if secondLen != 10 {
		t.Fatalf("second page len = %d, want 10", secondLen)
	}
	if secondFirst != "m5" || secondLast != "m14" {
		t.Fatalf("second page range = %s..%s, want m5..m14 (before=跳过尾部N条)", secondFirst, secondLast)
	}

	// 第三页：before=20,剩余前 5 条(m0..m4),hasMore=false
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-page", "payload": map[string]any{"limit": 10, "before": 20}})
	deadline = time.Now().Add(3 * time.Second)
	var lastHasMore *bool
	var thirdFirst, thirdLast string
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.history" {
			continue
		}
		p := m["payload"].(map[string]any)
		msgsAny := p["messages"].([]any)
		thirdFirst = msgsAny[0].(map[string]any)["content"].(string)
		thirdLast = msgsAny[len(msgsAny)-1].(map[string]any)["content"].(string)
		b := p["hasMore"].(bool)
		lastHasMore = &b
		break
	}
	if thirdFirst != "m0" || thirdLast != "m4" {
		t.Fatalf("third page range = %s..%s, want m0..m4", thirdFirst, thirdLast)
	}
	if lastHasMore == nil || *lastHasMore {
		t.Fatalf("third page hasMore = %v, want false", lastHasMore)
	}

	// 不带 limit → 全量(向后兼容)
	_ = conn.WriteJSON(map[string]any{"type": "session.history", "session_id": "web-page"})
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] != "session.history" {
			continue
		}
		p := m["payload"].(map[string]any)
		if n := len(p["messages"].([]any)); n != 25 {
			t.Fatalf("no-limit history len = %d, want 25 (backward compat)", n)
		}
		break
	}
}
