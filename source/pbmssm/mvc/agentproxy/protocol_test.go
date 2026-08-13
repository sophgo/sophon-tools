package agentproxy

import (
	"encoding/json"
	"strings"
	"testing"
)

// collectFrames 把 OnACPEvent 输出拼成字符串（测试断言用）。
func collectFrames(frames []WSFrame) []map[string]any {
	out := make([]map[string]any, 0, len(frames))
	for _, f := range frames {
		m := map[string]any{"type": f.Type, "session_id": f.SessionID, "payload": f.Payload}
		out = append(out, m)
	}
	return out
}

func payloadOf(t *testing.T, frames []WSFrame, wantType string) map[string]any {
	t.Helper()
	for _, f := range frames {
		if f.Type == wantType {
			return f.Payload
		}
	}
	t.Fatalf("no %s frame in %v", wantType, frames)
	return nil
}

func TestMessageChunkCreateThenUpdate(t *testing.T) {
	a := NewMessageAdapter("test-model")

	// 首个 chunk → message.create（带 typing.stop，因 typingOn 初始 true）
	ev1 := &ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "m1", Content: "你好"}
	f1 := a.OnACPEvent(ev1, "ws1")
	if len(f1) != 2 {
		t.Fatalf("first chunk frames = %d, want 2 (typing.stop + create)", len(f1))
	}
	if f1[0].Type != "typing.stop" {
		t.Errorf("f1[0].type = %s, want typing.stop", f1[0].Type)
	}
	if f1[1].Type != "message.create" {
		t.Fatalf("f1[1].type = %s, want message.create", f1[1].Type)
	}
	p := f1[1].Payload
	if p["message_id"] != "m1" {
		t.Errorf("message_id = %v, want m1", p["message_id"])
	}
	if p["content"] != "你好" {
		t.Errorf("content = %v, want 你好", p["content"])
	}
	if p["kind"] != "text" {
		t.Errorf("kind = %v, want text", p["kind"])
	}
	if p["model_name"] != "test-model" {
		t.Errorf("model_name = %v, want test-model", p["model_name"])
	}
	if f1[1].SessionID != "ws1" {
		t.Errorf("session_id = %s, want ws1", f1[1].SessionID)
	}

	// 后续 chunk → message.update（增量累积）
	ev2 := &ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "m1", Content: "，Reasonix！"}
	f2 := a.OnACPEvent(ev2, "ws1")
	if len(f2) != 1 || f2[0].Type != "message.update" {
		t.Fatalf("second chunk frames = %v, want single message.update", collectFrames(f2))
	}
	if f2[0].Payload["content"] != "你好，Reasonix！" {
		t.Errorf("accumulated content = %v, want 你好，Reasonix！", f2[0].Payload["content"])
	}
}

func TestThoughtChunkMapsToCollapse(t *testing.T) {
	a := NewMessageAdapter("")

	ev := &ACPSessionUpdate{Discriminator: "agent_thought_chunk", MessageID: "t1", Content: "思考中"}
	f := a.OnACPEvent(ev, "ws1")
	create := payloadOf(t, f, "message.create")
	if create["kind"] != "thought" {
		t.Errorf("kind = %v, want thought", create["kind"])
	}
	// model 为空时回退 Reasonix
	if create["model_name"] != "Reasonix" {
		t.Errorf("model_name = %v, want Reasonix", create["model_name"])
	}

	// thought 增量 → update
	ev2 := &ACPSessionUpdate{Discriminator: "agent_thought_chunk", MessageID: "t1", Content: "继续"}
	f2 := a.OnACPEvent(ev2, "ws1")
	up := payloadOf(t, f2, "message.update")
	if up["kind"] != "thought" {
		t.Errorf("update kind = %v, want thought", up["kind"])
	}
	if up["content"] != "思考中继续" {
		t.Errorf("update content = %v, want 思考中继续", up["content"])
	}
}

func TestToolCallCreateAndUpdate(t *testing.T) {
	a := NewMessageAdapter("test-model")

	// tool_call → message.create kind:tool_calls + tool_calls 数组
	ev1 := &ACPSessionUpdate{Discriminator: "tool_call", ToolCallID: "tc1", ToolCallTitle: "grep", ToolCallKind: "bash", ToolCallStatus: "pending"}
	f1 := a.OnACPEvent(ev1, "ws1")
	create := payloadOf(t, f1, "message.create")
	if create["kind"] != "tool_calls" {
		t.Errorf("kind = %v, want tool_calls", create["kind"])
	}
	if create["message_id"] != "tc1" {
		t.Errorf("message_id = %v, want tc1", create["message_id"])
	}
	tcs, ok := create["tool_calls"].([]*ToolCallState)
	if !ok || len(tcs) != 1 || tcs[0].ID != "tc1" {
		t.Errorf("tool_calls = %v, want [{ID:tc1}]", create["tool_calls"])
	}

	// tool_call_update → message.update
	ev2 := &ACPSessionUpdate{Discriminator: "tool_call_update", ToolCallID: "tc1", ToolCallStatus: "completed"}
	f2 := a.OnACPEvent(ev2, "ws1")
	up := payloadOf(t, f2, "message.update")
	if up["kind"] != "tool_calls" {
		t.Errorf("update kind = %v, want tool_calls", up["kind"])
	}
}

func TestUnknownEventIgnored(t *testing.T) {
	a := NewMessageAdapter("")
	cases := []*ACPSessionUpdate{
		{Discriminator: "plan"},
		{Discriminator: "user_message_chunk", MessageID: "u1", Content: "用户"},
		{Discriminator: "usage_update"},
		{Discriminator: "session_info_update", Title: "新标题"},
	}
	for _, ev := range cases {
		if frames := a.OnACPEvent(ev, "ws1"); len(frames) != 0 {
			t.Errorf("discriminator %s produced frames %v, want none", ev.Discriminator, collectFrames(frames))
		}
	}
}

func TestOnPromptStartEnd(t *testing.T) {
	a := NewMessageAdapter("")

	f1 := a.OnPromptStart("ws1")
	if len(f1) != 1 || f1[0].Type != "typing.start" {
		t.Fatalf("prompt start = %v, want typing.start", collectFrames(f1))
	}

	// 无内容时 prompt end → typing.stop（因为 typingOn 仍 true）
	f2 := a.OnPromptEnd("ws1")
	if len(f2) != 1 || f2[0].Type != "typing.stop" {
		t.Fatalf("prompt end = %v, want typing.stop", collectFrames(f2))
	}

	// 第二次 end → 无帧
	if f3 := a.OnPromptEnd("ws1"); len(f3) != 0 {
		t.Errorf("second prompt end = %v, want none", collectFrames(f3))
	}
}

func TestOnError(t *testing.T) {
	a := NewMessageAdapter("")
	f := a.OnError("ws1", "出错了", "ERR1")
	if len(f) != 1 || f[0].Type != "error" {
		t.Fatalf("error frames = %v", collectFrames(f))
	}
	if f[0].Payload["message"] != "出错了" || f[0].Payload["code"] != "ERR1" {
		t.Errorf("error payload = %v", f[0].Payload)
	}
}

func TestMessageMissingIDGetsSequence(t *testing.T) {
	a := NewMessageAdapter("")
	ev := &ACPSessionUpdate{Discriminator: "agent_message_chunk", Content: "无 id"}
	f := a.OnACPEvent(ev, "ws1")
	create := payloadOf(t, f, "message.create")
	id, ok := create["message_id"].(string)
	if !ok || id == "" {
		t.Errorf("message_id missing: %v", create["message_id"])
	}
}

func TestFrameSerialization(t *testing.T) {
	// 验证 WSFrame 序列化为前端可消费的 JSON（字段名对齐 pico 协议）
	a := NewMessageAdapter("m1")
	ev := &ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "m1", Content: "hi"}
	frames := a.OnACPEvent(ev, "ws-abc")
	if len(frames) == 0 {
		t.Fatal("no frames")
	}
	b, err := json.Marshal(frames[len(frames)-1])
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if m["type"] != "message.create" {
		t.Errorf("json type = %v", m["type"])
	}
	if m["session_id"] != "ws-abc" {
		t.Errorf("json session_id = %v", m["session_id"])
	}
	if _, ok := m["payload"]; !ok {
		t.Errorf("json payload missing")
	}
}

func TestRoundAssistants(t *testing.T) {
	a := NewMessageAdapter("m")
	// 模拟一次 round 的 ACP 事件流：两条 text chunk 归并为一条，一个 thought，一个 tool_call
	sid := "web-1"
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "m1", Content: "你"}, sid)
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "m1", Content: "好"}, sid)
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_thought_chunk", MessageID: "t1", Content: "思考"}, sid)
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "tool_call", ToolCallID: "tc1", ToolCallTitle: "bash", ToolCallKind: "execute", ToolCallStatus: "completed"}, sid)

	msgs := a.RoundAssistants()
	byKind := map[string]int{}
	var textContent, toolSummary string
	for _, m := range msgs {
		byKind[m.Kind]++
		switch m.Kind {
		case "text":
			textContent = m.Content
		case "tool_calls":
			toolSummary = m.Content
		}
	}
	if byKind["text"] != 1 || byKind["thought"] != 1 || byKind["tool_calls"] != 1 {
		t.Fatalf("RoundAssistants kinds = %+v, want text=1 thought=1 tool_calls=1", byKind)
	}
	if textContent != "你好" {
		t.Errorf("text content = %q, want 你好 (chunks merged)", textContent)
	}
	if !strings.Contains(toolSummary, "bash") {
		t.Errorf("tool summary = %q, want contains bash", toolSummary)
	}
	for _, m := range msgs {
		if m.Role != "assistant" {
			t.Errorf("role = %q, want assistant", m.Role)
		}
	}
}

// 需求（MYS-212）：reasonix 会把一个连续回答拆成多个不同 messageId 的
// agent_message_chunk（测试机「为我检查这台设备」会话落库中可见：同一句
// 「## 当前进展总结」被 reasonix 拆成 text-1='##' 与 text-2=' 当前进展…' 两条
// 相邻 text 分片）。后端落库时应在回合结束把**相邻的纯 text 分片合并为一条**，
// 遇 thought / tool_calls 才另起，避免历史里出现「一句话被拆成两个气泡」。
func TestRoundAssistantsMergesAdjacentTextWithDifferentIDs(t *testing.T) {
	a := NewMessageAdapter("m")
	sid := "web-1"
	// 真实取证：同一句被 reasonix 切成两个不同 messageId 的相邻 text 分片
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "text-1", Content: "##"}, sid)
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "text-2", Content: " 当前进展总结"}, sid)
	// 一个 thought（应中断 text 合并，独立成条）
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_thought_chunk", MessageID: "thought-1", Content: "思考"}, sid)
	// thought 后新的相邻 text 分片（不应并入前面的 text-1/text-2）
	_ = a.OnACPEvent(&ACPSessionUpdate{Discriminator: "agent_message_chunk", MessageID: "text-3", Content: "下一步：升级脚本"}, sid)

	msgs := a.RoundAssistants()
	var texts []string
	var thoughts int
	for _, m := range msgs {
		switch m.Kind {
		case "text":
			texts = append(texts, m.Content)
		case "thought":
			thoughts++
		}
	}
	// text-1 与 text-2 相邻纯文本 → 合并为一条；text-3 在 thought 后 → 独立一条
	if len(texts) != 2 {
		t.Fatalf("text messages = %d, want 2 (merged ##/当前进展分片 + thought 后的 text-3)", len(texts))
	}
	if texts[0] != "## 当前进展总结" {
		t.Errorf("merged text[0] = %q, want %q", texts[0], "## 当前进展总结")
	}
	if texts[1] != "下一步：升级脚本" {
		t.Errorf("text[1] = %q, want %q", texts[1], "下一步：升级脚本")
	}
	if thoughts != 1 {
		t.Errorf("thought messages = %d, want 1", thoughts)
	}
}
