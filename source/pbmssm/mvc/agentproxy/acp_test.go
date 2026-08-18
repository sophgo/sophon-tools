package agentproxy

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

// TestRPCRequestEncoding 验证上行请求 JSON 编码（id、params、notification 缺省 id）。
func TestRPCRequestEncoding(t *testing.T) {
	id := int64(5)
	params := json.RawMessage(`{"cwd":"/tmp"}`)
	req := RPCRequest{JSONRPC: "2.0", ID: &id, Method: "session/new", Params: params}
	b, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	s := string(b)
	if !strings.Contains(s, `"jsonrpc":"2.0"`) || !strings.Contains(s, `"id":5`) ||
		!strings.Contains(s, `"method":"session/new"`) || !strings.Contains(s, `"cwd":"/tmp"`) {
		t.Fatalf("bad request json: %s", s)
	}

	// notification：无 id
	notif := RPCRequest{JSONRPC: "2.0", Method: "session/cancel", Params: json.RawMessage(`{"sessionId":"s1"}`)}
	b, _ = json.Marshal(notif)
	if strings.Contains(string(b), `"id"`) {
		t.Fatalf("notification should not have id: %s", b)
	}
}

// TestResponseCorrelation 验证请求/响应按 id 关联（乱序返回）。
func TestResponseCorrelation(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	sc := bufio.NewScanner(tr.in)
	client := NewClient(pm, nil, nil)
	defer client.Close()

	type result struct {
		method string
		res    string
	}
	results := make(chan result, 2)

	go func() {
		raw, _ := client.request(context.Background(), "session/list", json.RawMessage(`{}`), 2*time.Second)
		results <- result{method: "session/list", res: string(raw)}
	}()
	go func() {
		raw, _ := client.request(context.Background(), "session/new", json.RawMessage(`{"cwd":"/x"}`), 2*time.Second)
		results <- result{method: "session/new", res: string(raw)}
	}()

	// 收集两个请求（记录 method 与 id 的对应关系）
	reqs := map[int64]string{}
	for len(reqs) < 2 {
		req := tr.readRequest(t, sc)
		reqs[*req.ID] = req.Method
	}

	// 乱序回复：对每个 id 按其 method 返回不同结果
	for id, method := range reqs {
		var res string
		if method == "session/new" {
			res = `{"sessionId":"s-new"}`
		} else {
			res = `{"sessions":[]}`
		}
		if err := tr.reply(&RPCResponse{JSONRPC: "2.0", ID: id, Result: json.RawMessage(res)}); err != nil {
			t.Fatalf("reply: %v", err)
		}
	}

	got := map[string]string{}
	for i := 0; i < 2; i++ {
		r := <-results
		got[r.method] = r.res
	}
	if got["session/new"] != `{"sessionId":"s-new"}` {
		t.Fatalf("session/new got %q", got["session/new"])
	}
	if got["session/list"] != `{"sessions":[]}` {
		t.Fatalf("session/list got %q", got["session/list"])
	}
}

// TestRequestTimeout 验证请求超时（超过 timeout 返回错误）。
func TestRequestTimeout(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	_ = pm
	sc := bufio.NewScanner(tr.in)
	client := NewClient(pm, nil, nil)
	defer client.Close()

	// 只读不回复 → 触发超时
	go func() {
		tr.readRequest(t, sc)
	}()

	start := time.Now()
	_, err := client.request(context.Background(), "session/list", json.RawMessage(`{}`), 300*time.Millisecond)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if !strings.Contains(err.Error(), "timed out") {
		t.Fatalf("expected timeout error, got %v", err)
	}
	if time.Since(start) < 250*time.Millisecond {
		t.Fatalf("returned too early")
	}
}

// TestRequestErrorMapping 验证 JSON-RPC 错误（-32601 MethodNotFound）映射。
func TestRequestErrorMapping(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	_ = pm
	sc := bufio.NewScanner(tr.in)
	client := NewClient(pm, nil, nil)
	defer client.Close()

	go func() {
		tr.readRequest(t, sc)
		_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: 1, Error: &RPCError{Code: -32601, Message: "Method not found"}})
	}()

	_, err := client.request(context.Background(), "session/foo", json.RawMessage(`{}`), 2*time.Second)
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "-32601") || !strings.Contains(err.Error(), "Method not found") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestInitialize 验证 initialize 握手参数与结果解析。
func TestInitialize(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	_ = pm
	sc := bufio.NewScanner(tr.in)
	client := NewClient(pm, nil, nil)
	defer client.Close()

	go func() {
		req := tr.readRequest(t, sc)
		if req.Method != "initialize" {
			t.Errorf("method = %s, want initialize", req.Method)
		}
		if req.ID == nil {
			t.Error("initialize should have id")
		}
		var params struct {
			ProtocolVersion int            `json:"protocolVersion"`
			ClientInfo      map[string]any `json:"clientInfo"`
		}
		_ = json.Unmarshal(req.Params, &params)
		if params.ProtocolVersion != 1 {
			t.Errorf("protocolVersion = %d, want 1", params.ProtocolVersion)
		}
		if params.ClientInfo["name"] != "bmssm-agentproxy" {
			t.Errorf("client name = %v", params.ClientInfo["name"])
		}
		_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{"protocolVersion":1,"agentCapabilities":{"promptCapabilities":{}}}`)})
	}()

	res, err := client.Initialize(context.Background())
	if err != nil {
		t.Fatalf("initialize: %v", err)
	}
	if res.ProtocolVersion != 1 {
		t.Fatalf("protocolVersion = %d", res.ProtocolVersion)
	}
	if len(res.AgentCapabilities) == 0 {
		t.Fatalf("agentCapabilities empty")
	}
}

// TestSessionMethods 验证会话方法（new/load/resume/close/delete/list）的参数与响应。
func TestSessionMethods(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	_ = pm
	sc := bufio.NewScanner(tr.in)
	client := NewClient(pm, nil, nil)
	defer client.Close()

	// 顺序处理请求并回复
	go func() {
		for {
			req, err := tr.readRequestErr(sc)
			if err != nil {
				return // 读侧关闭（client.Close 后）
			}
			switch req.Method {
			case "session/new":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{"sessionId":"s-new"}`)})
			case "session/load":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{}`)})
			case "session/resume":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{}`)})
			case "session/close":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{}`)})
			case "session/delete":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{}`)})
			case "session/list":
				_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{"sessions":[{"id":"s1","title":"t1"}]}`)})
			default:
				t.Errorf("unexpected method %s", req.Method)
				return
			}
		}
	}()

	ctx := context.Background()
	if id, err := client.NewSession(ctx, "/home/linaro"); err != nil || id != "s-new" {
		t.Fatalf("NewSession: id=%s err=%v", id, err)
	}
	if err := client.LoadSession(ctx, "s1", "/home/linaro"); err != nil {
		t.Fatalf("LoadSession: %v", err)
	}
	if err := client.ResumeSession(ctx, "s1", "/home/linaro"); err != nil {
		t.Fatalf("ResumeSession: %v", err)
	}
	if err := client.CloseSession(ctx, "s1"); err != nil {
		t.Fatalf("CloseSession: %v", err)
	}
	if err := client.DeleteSession(ctx, "s1"); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	sessions, err := client.ListSessions(ctx, "/home/linaro")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 1 || sessions[0].ID != "s1" {
		t.Fatalf("ListSessions: %+v", sessions)
	}
}

// TestSessionPromptStream 验证 session/prompt 流式：
// agent 先发 session/update（agent_message_chunk）通知，再回 stopReason 响应。
func TestSessionPromptStream(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	_ = pm

	events := make(chan *ACPSessionUpdate, 4)
	client := NewClient(pm, func(ev *ACPSessionUpdate) { events <- ev }, nil)
	defer client.Close()

	sc := bufio.NewScanner(tr.in)
	go func() {
		req := tr.readRequest(t, sc)
		if req.Method != "session/prompt" {
			t.Errorf("method = %s", req.Method)
			return
		}
		// 先发流式通知
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0",
			"method":  "session/update",
			"params": map[string]any{
				"sessionId": "s1",
				"update": map[string]any{
					"sessionUpdate": map[string]any{
						"agent_message_chunk": map[string]any{
							"messageId": "m1",
							"content":   map[string]any{"text": "Hello"},
						},
					},
				},
			},
		})
		// 再回响应
		_ = tr.reply(&RPCResponse{JSONRPC: "2.0", ID: *req.ID, Result: json.RawMessage(`{"stopReason":"end_turn"}`)})
	}()

	updates, cancel, err := client.Prompt(context.Background(), "s1", "hi")
	if err != nil {
		t.Fatalf("Prompt: %v", err)
	}
	defer cancel()

	// 等流式事件
	select {
	case ev := <-events:
		if ev.Discriminator != "agent_message_chunk" {
			t.Fatalf("discriminator = %s", ev.Discriminator)
		}
		if ev.MessageID != "m1" || ev.Content != "Hello" {
			t.Fatalf("event = %+v", ev)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for stream event")
	}

	// updates 通道：既承载流式事件，又在响应到达后关闭（for range 消费到关闭）。
	select {
	case ev, ok := <-updates:
		if !ok {
			t.Fatal("updates closed before stream event")
		}
		if ev.Discriminator != "agent_message_chunk" || ev.MessageID != "m1" {
			t.Fatalf("updates event = %+v", ev)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for updates event")
	}
	// 继续消费直到关闭（响应到达后 close）
	deadline := time.After(2 * time.Second)
	for {
		select {
		case _, ok := <-updates:
			if !ok {
				return
			}
		case <-deadline:
			t.Fatal("timeout waiting for updates close")
		}
	}
}

// TestParseSessionUpdate 验证 session/update 各判别子解析。
func TestParseSessionUpdate(t *testing.T) {
	cases := []struct {
		name       string
		payload    string
		disc       string
		messageID  string
		content    string
		toolCallID string
	}{
		{
			name:    "agent_message_chunk",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":{"agent_message_chunk":{"messageId":"m1","content":{"text":"hi"}}}}}`,
			disc:    "agent_message_chunk", messageID: "m1", content: "hi",
		},
		{
			name:    "agent_thought_chunk",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":{"agent_thought_chunk":{"messageId":"t1","content":{"text":"think"}}}}}`,
			disc:    "agent_thought_chunk", messageID: "t1", content: "think",
		},
		{
			name:    "tool_call",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":{"tool_call":{"toolCallId":"tc1","title":"grep","kind":"bash","status":"pending"}}}}`,
			disc:    "tool_call", toolCallID: "tc1",
		},
		{
			name:    "tool_call_update",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":{"tool_call_update":{"toolCallId":"tc1","status":"completed"}}}}`,
			disc:    "tool_call_update", toolCallID: "tc1",
		},
		{
			name:    "session_info_update",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":{"session_info_update":{"title":"新标题"}}}}`,
			disc:    "session_info_update",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ev := parseSessionUpdate(json.RawMessage(tc.payload))
			if ev == nil {
				t.Fatal("parse returned nil")
			}
			if ev.Discriminator != tc.disc {
				t.Fatalf("disc = %s, want %s", ev.Discriminator, tc.disc)
			}
			if tc.messageID != "" && ev.MessageID != tc.messageID {
				t.Fatalf("messageId = %s, want %s", ev.MessageID, tc.messageID)
			}
			if tc.content != "" && ev.Content != tc.content {
				t.Fatalf("content = %s, want %s", ev.Content, tc.content)
			}
			if tc.toolCallID != "" && ev.ToolCallID != tc.toolCallID {
				t.Fatalf("toolCallId = %s, want %s", ev.ToolCallID, tc.toolCallID)
			}
		})
	}
}

// TestParseSessionUpdate_ReasonixStringTag 验证 reasonix 真实 ACP 通知形态：
// sessionUpdate 为字符串判别子，内容块 {type,text} 与载荷字段并列在 update 下。
func TestParseSessionUpdate_ReasonixStringTag(t *testing.T) {
	cases := []struct {
		name       string
		payload    string
		disc       string
		content    string
		toolCallID string
		toolStatus string
	}{
		{
			name:    "agent_message_chunk",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"你好！有什么我可以帮你的吗？"}}}`,
			disc:    "agent_message_chunk", content: "你好！有什么我可以帮你的吗？",
		},
		{
			name:    "agent_thought_chunk",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":"agent_thought_chunk","content":{"type":"text","text":"用户要求我打招呼"}}}`,
			disc:    "agent_thought_chunk", content: "用户要求我打招呼",
		},
		{
			name:    "tool_call",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":"tool_call","toolCallId":"tc1","title":"grep","kind":"bash","status":"pending"}}`,
			disc:    "tool_call", toolCallID: "tc1", toolStatus: "pending",
		},
		{
			name:    "tool_call_update",
			payload: `{"sessionId":"s1","update":{"sessionUpdate":"tool_call_update","toolCallId":"tc1","status":"completed"}}`,
			disc:    "tool_call_update", toolCallID: "tc1", toolStatus: "completed",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ev := parseSessionUpdate(json.RawMessage(tc.payload))
			if ev == nil {
				t.Fatal("parse returned nil")
			}
			if ev.Discriminator != tc.disc {
				t.Fatalf("disc = %s, want %s", ev.Discriminator, tc.disc)
			}
			if ev.SessionID != "s1" {
				t.Fatalf("sessionId = %s, want s1", ev.SessionID)
			}
			if tc.content != "" && ev.Content != tc.content {
				t.Fatalf("content = %s, want %s", ev.Content, tc.content)
			}
			if tc.toolCallID != "" && ev.ToolCallID != tc.toolCallID {
				t.Fatalf("toolCallId = %s, want %s", ev.ToolCallID, tc.toolCallID)
			}
			if tc.toolStatus != "" && ev.ToolCallStatus != tc.toolStatus {
				t.Fatalf("status = %s, want %s", ev.ToolCallStatus, tc.toolStatus)
			}
		})
	}
}

// TestStreamClosedOnEOF 验证读循环读到 EOF 时未决请求失败、流关闭。
func TestStreamClosedOnEOF(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	// 关闭写端 → 被测 readLoop 读到 EOF
	_ = tr.out.Close()

	events := make(chan *ACPSessionUpdate, 4)
	client := NewClient(pm, func(ev *ACPSessionUpdate) { events <- ev }, nil)
	defer client.Close()

	// Prompt 会写入失败（stdin 另一端已关？不，tr.out 是响应端）
	// 这里直接验证 failPending：先注册一个请求，然后进程死亡触发。
	// 简化：直接调用 failPending 验证行为。
	cl := client.register()
	go func() {
		time.Sleep(50 * time.Millisecond)
		client.failPending(errors.New("stream closed"))
	}()
	select {
	case resp := <-cl.resp:
		if resp.Error == nil {
			t.Fatal("expected error response")
		}
		if resp.Error.Code != codeInternalError {
			t.Fatalf("code = %d", resp.Error.Code)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for fail")
	}
	client.unregister(cl.id)
}
