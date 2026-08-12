package agentproxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// permissionHandler 构造一个模拟 reasonix 的 ACP 分发体：
// session/new 返回 acp-1；后继 prompt 或 request_permission 按需。
// 这里返回一个不自动处理的空 handler，让测试自由注入下行。
func rawPermissionHandler() string {
	return `
    session/new)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{"sessionId":"acp-perm-1"}}'
      ;;
    session/prompt)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{"stopReason":"end_turn"}}'
      ;;
`
}

// TestModulePermissionRequestRoutedToWS 端到端（模块+Hub+WS）：
// ACP 下行 session/request_permission → 模块记录待审批并投递 WS permission.request →
// WS 收到请求帧；WS 回 permission.respond(allow) → 模块应答 ACP（ResolvePermission）。
func TestModulePermissionRequestRoutedToWS(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	// 交互侧：session/new 先回 sid，随后收到权限应答帧
	go func() {
		sc := bufioNewScanner(tr.in)
		req, err := tr.readRequestErr(sc)
		if err != nil {
			return
		}
		if req.Method != "session/new" {
			t.Errorf("first request = %s, want session/new", req.Method)
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-perm-1"}})

		// 用户通过 WS 发送 message.send 会触发 session/prompt
		req2, err := tr.readRequestErr(sc)
		if err != nil || req2.Method != "session/prompt" {
			t.Errorf("second request = %v, want session/prompt", req2)
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})

		// 注入 agent 发起的 session/request_permission（带 JSON-RPC id=77）
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0", "id": 77, "method": "session/request_permission",
			"params": map[string]any{
				"sessionId": "acp-perm-1",
				"toolCall": map[string]any{
					"toolCallId": "gate-1", "title": "Bash", "kind": "bash", "status": "pending",
				},
				"options": []map[string]any{
					{"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
					{"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
				},
			},
		})

		// 等待 host 按 id=77 回 JSON-RPC 响应
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			line, err := tr.readRawLineErr(sc)
			if err != nil {
				return
			}
			var frame struct {
				ID     *int64         `json:"id"`
				Method string         `json:"method,omitempty"`
				Result json.RawMessage `json:"result,omitempty"`
			}
			if err := json.Unmarshal(line, &frame); err != nil {
				continue
			}
			// 找到 id=77 的响应
			if frame.ID != nil && *frame.ID == 77 && frame.Method == "" {
				if len(frame.Result) == 0 {
					t.Errorf("permission response missing result")
				}
				var res struct {
					Outcome struct {
						Outcome  string `json:"outcome"`
						OptionID string `json:"optionId"`
					} `json:"outcome"`
				}
				if err := json.Unmarshal(frame.Result, &res); err != nil {
					t.Errorf("parse permission response: %v (raw=%s)", err, frame.Result)
					return
				}
				if res.Outcome.Outcome != "selected" || res.Outcome.OptionID != "allow_once" {
					t.Errorf("permission allow response = %+v, want selected/allow_once", res.Outcome)
				}
				return
			}
		}
		t.Errorf("no permission response frame with id=77")
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")

	// 绑定会话：发一条 message.send
	_ = conn.WriteJSON(map[string]any{
		"type": "message.send", "payload": map[string]any{"content": "hi"},
	})

	// 等待 permission.request 帧
	var got permRequest
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "permission.request" {
			b, _ := json.Marshal(m["payload"])
			_ = json.Unmarshal(b, &got)
			if got.RequestID == 77 && got.ToolCall.Title == "Bash" {
				break
			}
		}
	}
	if got.RequestID != 77 {
		t.Fatalf("permission.request not received with request_id 77, got %+v", got)
	}

	// 用户允许：发 permission.respond
	_ = conn.WriteJSON(map[string]any{
		"type":        "permission.respond",
		"session_id":  got.SessionID,
		"payload":     map[string]any{"session_id": got.SessionID, "request_id": 77, "allow": true},
	})
	time.Sleep(200 * time.Millisecond)
}

// permRequest 供测试解析 permission.request 帧负载。
type permRequest struct {
	RequestID int64  `json:"request_id"`
	SessionID string `json:"session_id"`
	ToolCall  struct {
		Title string `json:"title"`
		Kind  string `json:"kind"`
	} `json:"tool_call"`
}

// TestModulePermissionDenyRoutes 端到端：用户拒绝 → host 应答 outcome=cancelled。
func TestModulePermissionDenyRoutes(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	go func() {
		sc := bufioNewScanner(tr.in)
		req, _ := tr.readRequestErr(sc)
		if req == nil || req.Method != "session/new" {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-deny-1"}})
		req2, _ := tr.readRequestErr(sc)
		if req2 == nil || req2.Method != "session/prompt" {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})

		// 注入 request_permission（id=88）
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0", "id": 88, "method": "session/request_permission",
			"params": map[string]any{
				"sessionId": "acp-deny-1",
				"toolCall":  map[string]any{"toolCallId": "gate-2", "title": "Bash", "kind": "bash", "status": "pending"},
			},
		})

		// 等待 id=88 的响应，期望 cancelled
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			line, err := tr.readRawLineErr(sc)
			if err != nil {
				return
			}
			var frame struct {
				ID     *int64          `json:"id"`
				Method string          `json:"method,omitempty"`
				Result json.RawMessage `json:"result,omitempty"`
			}
			if json.Unmarshal(line, &frame) != nil || frame.ID == nil || *frame.ID != 88 {
				continue
			}
			var res struct {
				Outcome struct {
					Outcome string `json:"outcome"`
				} `json:"outcome"`
			}
			if err := json.Unmarshal(frame.Result, &res); err != nil {
				t.Errorf("parse: %v", err)
				return
			}
			if res.Outcome.Outcome != "cancelled" {
				t.Errorf("deny response = %+v, want cancelled", res.Outcome)
			}
			return
		}
		t.Errorf("no deny response id=88")
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "hi"}})

	// 等 permission.request
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "permission.request" {
			var p struct {
				RequestID int64 `json:"request_id"`
			}
			b, _ := json.Marshal(m["payload"])
			_ = json.Unmarshal(b, &p)
			if p.RequestID == 88 {
				break
			}
		}
	}
	// 用户拒绝
	_ = conn.WriteJSON(map[string]any{
		"type":       "permission.respond",
		"session_id": "acp-deny-1",
		"payload":    map[string]any{"session_id": "acp-deny-1", "request_id": 88, "allow": false},
	})
	time.Sleep(200 * time.Millisecond)
}

// TestPermissionTimeoutAutoDeny 验证待审批超时（短设为 50ms）后自动拒绝。
func TestPermissionTimeoutAutoDeny(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	mod.cfg.PermissionTimeout = "50ms"
	h := newHub(mod, "key")
	mod.hub = h
	srv := httptest.NewServer(http.HandlerFunc(h.serveWS))
	t.Cleanup(srv.Close)
	mod.SetEventFn(h.HandleEvent)
	t.Cleanup(func() { mod.SetEventFn(nil) })

	go func() {
		sc := bufioNewScanner(tr.in)
		req, _ := tr.readRequestErr(sc)
		if req == nil || req.Method != "session/new" {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req.ID, "result": map[string]any{"sessionId": "acp-to-1"}})
		req2, _ := tr.readRequestErr(sc)
		if req2 == nil || req2.Method != "session/prompt" {
			return
		}
		_ = tr.reply(map[string]any{"jsonrpc": "2.0", "id": *req2.ID, "result": map[string]any{"stopReason": "end_turn"}})
		// request_permission（id=99），故意不响应 → 触发超时自动拒绝
		_ = tr.reply(map[string]any{
			"jsonrpc": "2.0", "id": 99, "method": "session/request_permission",
			"params": map[string]any{"sessionId": "acp-to-1", "toolCall": map[string]any{"toolCallId": "gate-3", "title": "Bash", "kind": "bash"}},
		})
		// 期望超时后收到 id=99 的 cancelled 响应
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			line, err := tr.readRawLineErr(sc)
			if err != nil {
				return
			}
			var frame struct {
				ID     *int64          `json:"id"`
				Result json.RawMessage `json:"result,omitempty"`
			}
			if json.Unmarshal(line, &frame) != nil || frame.ID == nil || *frame.ID != 99 {
				continue
			}
			var res struct {
				Outcome struct {
					Outcome string `json:"outcome"`
				} `json:"outcome"`
			}
			if json.Unmarshal(frame.Result, &res) != nil || res.Outcome.Outcome != "cancelled" {
				t.Errorf("timeout auto-deny = %+v, want cancelled", res.Outcome)
			}
			return
		}
		t.Errorf("no timeout auto-deny response id=99")
	}()

	conn := dialWS(t, wsURL(srv.URL)+wsPath, "token.key")
	_ = conn.WriteJSON(map[string]any{"type": "message.send", "payload": map[string]any{"content": "hi"}})
	// 等 permission.request 出现后不再响应，等待自动超时
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m := readFrame(t, conn)
		if m["type"] == "permission.request" {
			break
		}
	}
	// 不发送 respond，等超时在 goroutine 侧断言
	time.Sleep(400 * time.Millisecond)
}

// TestRespondPermissionByReqID 验证同一会话的多个待审批可按 reqID 独立应答
//（若按会话单选，后者会覆盖前者导致其 reqID 无人应答而悬挂）。
func TestRespondPermissionByReqID(t *testing.T) {
	mod, tr := mockModuleForWS(t)
	client := mod.Client()
	if client == nil {
		t.Fatal("no client")
	}
	// 注入两个 request_permission（同 session，不同 reqID）
	params := json.RawMessage(`{"sessionId":"acp-multi-1","toolCall":{"toolCallId":"gate-a","title":"bash a","kind":"execute","status":"pending"}}`)
	mod.dispatchPermissionRequest(11, params)
	mod.dispatchPermissionRequest(12, params)

	// 两个都在待审批（不互相覆盖）
	mod.mu.Lock()
	permLen := len(mod.perms)
	_, has11 := mod.perms[11]
	_, has12 := mod.perms[12]
	mod.mu.Unlock()
	if permLen != 2 || !has11 || !has12 {
		t.Fatalf("after dispatch: len=%d has11=%v has12=%v, want len=2 both present", permLen, has11, has12)
	}

	// 分别应答：11 allow、12 deny → 各自从待审批移除
	mod.RespondPermission(11, true)
	mod.RespondPermission(12, false)
	mod.mu.Lock()
	permLen2 := len(mod.perms)
	mod.mu.Unlock()
	if permLen2 != 0 {
		t.Fatalf("after resolve: perms len=%d, want 0", permLen2)
	}

	// 确认对 reasonix 的应答确实按 reqID 发出（11→selected, 12→cancelled）。
	sc := bufioNewScanner(tr.in)
	if err := client.ResolvePermission(11, true); err != nil {
		t.Fatalf("resolve 11: %v", err)
	}
	if err := client.ResolvePermission(12, false); err != nil {
		t.Fatalf("resolve 12: %v", err)
	}
	// tr.in 是真实管道文件；设读超时避免 Scan 永久阻塞
	_ = tr.in.SetReadDeadline(time.Now().Add(3 * time.Second))
	allowID, denyID := int64(0), int64(0)
	for {
		line, err := tr.readRawLineErr(sc)
		if err != nil {
			break
		}
		var frame struct {
			ID     *int64          `json:"id"`
			Result json.RawMessage `json:"result,omitempty"`
		}
		if json.Unmarshal(line, &frame) != nil || frame.ID == nil {
			continue
		}
		var res struct {
			Outcome struct {
				Outcome string `json:"outcome"`
			} `json:"outcome"`
		}
		if err := json.Unmarshal(frame.Result, &res); err != nil {
			continue
		}
		if res.Outcome.Outcome == "selected" {
			allowID = *frame.ID
		} else if res.Outcome.Outcome == "cancelled" {
			denyID = *frame.ID
		}
	}
	if allowID != 11 {
		t.Errorf("allow response id = %d, want 11", allowID)
	}
	if denyID != 12 {
		t.Errorf("deny response id = %d, want 12", denyID)
	}
}
