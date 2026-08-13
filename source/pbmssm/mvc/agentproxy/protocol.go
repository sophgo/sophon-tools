package agentproxy

import (
	"fmt"
	"strings"
	"sync"
)

// WSFrame 一条发给 webchatUI 的 WS 帧（对齐 pico 协议，前端 web-client/js/chat.js 消费）。
//
// 帧结构（与 pico 一致）：
//
//	{ "type": "message.create", "session_id": "<webchat-id>",
//	  "payload": { "message_id": "...", "content": "...", "kind": "text", "model_name": "..." } }
//
// type 取值：message.create / message.update / typing.start / typing.stop / session.create / error。
type WSFrame struct {
	Type      string         `json:"type"`
	SessionID string         `json:"session_id,omitempty"`
	Payload   map[string]any `json:"payload,omitempty"`
}

// ToolCallState tool_call / tool_call_update 的聚合状态（折叠块累积用）。
type ToolCallState struct {
	ID     string `json:"toolCallId"`
	Title  string `json:"title,omitempty"`
	Kind   string `json:"kind,omitempty"`
	Status string `json:"status,omitempty"`
}

// streamedContent 一条流式消息（text/thought）的聚合状态，含渲染 kind。
type streamedContent struct {
	Kind string // text / thought
	Text string
}

// StreamState 连接级流式累积状态：一个 WS 连接一个实例。
// 同一 messageId 的内容按 ACP chunk 增量累积，发送全量（前端 accumulate 前缀替换语义）。
type StreamState struct {
	mu        sync.Mutex
	created   map[string]bool            // messageId / toolCallId -> 已发 message.create
	content   map[string]streamedContent // messageId -> 当前完整内容（含 kind）
	toolCalls map[string]*ToolCallState  // toolCallId -> 聚合
	order     []string                   // 本回合 messageId / toolCallId 首次到达顺序（落库合并需保持发言时序）
	typingOn  bool                       // 当前回合是否仍显示「输入中…」
}

// NewStreamState 创建流状态。
func NewStreamState() *StreamState {
	return &StreamState{
		created:   make(map[string]bool),
		content:   make(map[string]streamedContent),
		toolCalls: make(map[string]*ToolCallState),
		order:     []string{},
		typingOn:  true,
	}
}

// MessageAdapter 协议适配层：把 ACP session/update 事件映射为 webchatUI 的 WS 帧。
// 无 I/O（不直接写 WS），连接层负责把返回的帧写入连接。
type MessageAdapter struct {
	state *StreamState
	model string // message.create 的 model_name（取配置 model，空则 Reasonix）

	mu      sync.Mutex
	nextSeq int // messageId 缺失时的顺序兜底
}

// NewMessageAdapter 创建协议适配器。
func NewMessageAdapter(model string) *MessageAdapter {
	return &MessageAdapter{state: NewStreamState(), model: model}
}

// ResetRound 开始新回合（message.send 后）：清空累积状态、重置 typing 指示。
// 同一连接多轮对话时每轮独立。
func (a *MessageAdapter) ResetRound() {
	a.mu.Lock()
	a.state = NewStreamState()
	a.mu.Unlock()
}

// OnSessionCreate 新建会话绑定回包：通知前端把服务端 webchat id 绑到本地会话。
func (a *MessageAdapter) OnSessionCreate(webchatID string) []WSFrame {
	return []WSFrame{{Type: "session.create", SessionID: webchatID}}
}

// OnPromptStart 回合开始（message.send 后）：发 typing.start。
func (a *MessageAdapter) OnPromptStart(webchatID string) []WSFrame {
	return []WSFrame{{Type: "typing.start", SessionID: webchatID}}
}

// OnPromptEnd 回合结束（prompt 响应 stopReason 到达）：若仍显示「输入中」则发 typing.stop。
func (a *MessageAdapter) OnPromptEnd(webchatID string) []WSFrame {
	a.state.mu.Lock()
	on := a.state.typingOn
	a.state.typingOn = false
	a.state.mu.Unlock()
	if on {
		return []WSFrame{{Type: "typing.stop", SessionID: webchatID}}
	}
	return nil
}

// OnError 构造错误帧（前端 handleError 展示）。
func (a *MessageAdapter) OnError(webchatID, message, code string) []WSFrame {
	payload := map[string]any{"message": message}
	if code != "" {
		payload["code"] = code
	}
	return []WSFrame{{Type: "error", SessionID: webchatID, Payload: payload}}
}

// OnACPEvent ACP session/update 事件 → WS 帧列表。
// 映射规则（agentproxy-design.md §6.1）：
//   - agent_message_chunk  → message.create / message.update（kind:text）
//   - agent_thought_chunk  → message.create / message.update（kind:thought，折叠块）
//   - tool_call            → message.create（kind:tool_calls，折叠块）
//   - tool_call_update     → message.update（kind:tool_calls）
//   - plan / user_message_chunk / usage_update / session_info_update → 忽略（前端无对应组件）
func (a *MessageAdapter) OnACPEvent(ev *ACPSessionUpdate, webchatID string) []WSFrame {
	if ev == nil {
		return nil
	}
	switch ev.Discriminator {
	case "agent_message_chunk":
		return a.messageChunk(ev, webchatID, "text")
	case "agent_thought_chunk":
		return a.messageChunk(ev, webchatID, "thought")
	case "tool_call":
		return a.toolCall(ev, webchatID, false)
	case "tool_call_update":
		return a.toolCall(ev, webchatID, true)
	default:
		// plan / user_message_chunk / usage_update / session_info_update 等：
		// 前端无对应组件，记日志忽略。
		return nil
	}
}

// messageChunk 处理文本/思考增量 chunk：累积内容，按 messageId 决定 create 或 update。
// 首个内容 chunk 到达时停止「输入中」指示器。
func (a *MessageAdapter) messageChunk(ev *ACPSessionUpdate, webchatID, kind string) []WSFrame {
	id := ev.MessageID
	a.mu.Lock()
	if id == "" {
		a.nextSeq++
		id = fmt.Sprintf("%s-%d", kind, a.nextSeq)
	}
	a.mu.Unlock()

	a.state.mu.Lock()
	sc := a.state.content[id]
	var merged string
	if sc.Kind == "" {
		// 首个 chunk：记 kind（text/thought），内容即本段，并记录到达顺序
		sc.Kind = kind
		merged = ev.Content
		a.state.order = appendOrder(a.state.order, id)
	} else {
		// 后续 chunk：增量累积
		merged = sc.Text + ev.Content
	}
	sc.Text = merged
	a.state.content[id] = sc
	already := a.state.created[id]
	a.state.created[id] = true
	typing := a.state.typingOn
	a.state.typingOn = false
	a.state.mu.Unlock()

	frames := make([]WSFrame, 0, 2)
	if typing {
		frames = append(frames, WSFrame{Type: "typing.stop", SessionID: webchatID})
	}
	if !already {
		frames = append(frames, WSFrame{
			Type:      "message.create",
			SessionID: webchatID,
			Payload: map[string]any{
				"message_id": id,
				"content":    merged,
				"kind":       kind,
				"model_name": a.modelName(),
			},
		})
	} else {
		frames = append(frames, WSFrame{
			Type:      "message.update",
			SessionID: webchatID,
			Payload: map[string]any{
				"message_id": id,
				"content":    merged,
				"kind":       kind,
			},
		})
	}
	return frames
}

// toolCall 处理工具调用事件：折叠块按 toolCallId 累积状态。
// tool_call 首次到达 → message.create（kind:tool_calls）；状态更新 → message.update。
func (a *MessageAdapter) toolCall(ev *ACPSessionUpdate, webchatID string, update bool) []WSFrame {
	id := ev.ToolCallID
	if id == "" {
		return nil
	}
	tc := &ToolCallState{ID: id, Title: ev.ToolCallTitle, Kind: ev.ToolCallKind, Status: ev.ToolCallStatus}

	a.state.mu.Lock()
	if !update {
		// 首次 tool_call：若已存在（重复通知），按 update 处理
		_, exists := a.state.toolCalls[id]
		if exists {
			update = true
		}
	}
	if prev, ok := a.state.toolCalls[id]; ok {
		if tc.Title == "" {
			tc.Title = prev.Title
		}
		if tc.Kind == "" {
			tc.Kind = prev.Kind
		}
		if tc.Status == "" {
			tc.Status = prev.Status
		}
	}
	a.state.toolCalls[id] = tc
	already := a.state.created[id]
	a.state.created[id] = true
	if !already {
		a.state.order = appendOrder(a.state.order, id)
	}
	typing := a.state.typingOn
	a.state.typingOn = false
	a.state.mu.Unlock()

	frames := make([]WSFrame, 0, 2)
	if typing {
		frames = append(frames, WSFrame{Type: "typing.stop", SessionID: webchatID})
	}
	content := toolCallSummary(tc)
	if !update && !already {
		frames = append(frames, WSFrame{
			Type:      "message.create",
			SessionID: webchatID,
			Payload: map[string]any{
				"message_id": id,
				"content":    content,
				"kind":       "tool_calls",
				"model_name": a.modelName(),
				"tool_calls": []*ToolCallState{tc},
			},
		})
	} else {
		frames = append(frames, WSFrame{
			Type:      "message.update",
			SessionID: webchatID,
			Payload: map[string]any{
				"message_id": id,
				"content":    content,
				"kind":       "tool_calls",
			},
		})
	}
	return frames
}

// RoundAssistants 返回本回合已聚合的 assistant 消息（落库用），并清空聚合状态后重开。
// text/thought 按 messageId 归并全文，kind 保留；tool_call 按 toolCallId 归并为折叠块摘要。
//
// 需求（MYS-212）：reasonix 会把一个连续回答拆成多个不同 messageId 的 text 分片
// （如同一句被拆成 text-12/text-13）。按 order（到达顺序）遍历，把**相邻的纯 text
// 分片合并为一条**，遇 thought / tool_calls 才另起，避免落库历史出现「一句话被拆
// 成两个气泡」。
//
// 调用时机：回合结束（prompt stopReason 到达），由连接层追加进会话历史。
func (a *MessageAdapter) RoundAssistants() []ChatMessage {
	a.state.mu.Lock()
	defer a.state.mu.Unlock()
	out := make([]ChatMessage, 0, len(a.state.order))
	for _, id := range a.state.order {
		if sc, ok := a.state.content[id]; ok {
			if sc.Kind == "text" && len(out) > 0 && out[len(out)-1].Kind == "text" {
				// 相邻纯文本分片：合并进上一条（同一连续回答）
				out[len(out)-1].Content += sc.Text
			} else {
				out = append(out, ChatMessage{Role: "assistant", Kind: sc.Kind, Content: sc.Text, ID: id})
			}
		} else if tc, ok := a.state.toolCalls[id]; ok {
			out = append(out, ChatMessage{Role: "assistant", Kind: "tool_calls", Content: toolCallSummary(tc), ID: id})
		}
	}
	// 清空聚合状态但保留同一把锁（不能整体替换 a.state——会换掉正在持有的 mutex）。
	a.state.content = make(map[string]streamedContent)
	a.state.toolCalls = make(map[string]*ToolCallState)
	a.state.created = make(map[string]bool)
	a.state.order = []string{}
	a.state.typingOn = true
	return out
}

// appendOrder 把 id 追加到顺序表（幂等：已存在则跳过）。
// 由于锁内调用，直接用线性查找即可（每条回复 messageId 数量级很小）。
func appendOrder(order []string, id string) []string {
	for _, o := range order {
		if o == id {
			return order
		}
	}
	return append(order, id)
}

// modelName 返回 message.create 的 model_name。
func (a *MessageAdapter) modelName() string {
	if strings.TrimSpace(a.model) != "" {
		return a.model
	}
	return "Reasonix"
}

// toolCallSummary 生成工具折叠块的文本摘要（前端 collapse body 直接渲染）。
func toolCallSummary(tc *ToolCallState) string {
	parts := make([]string, 0, 3)
	if tc.Title != "" {
		parts = append(parts, tc.Title)
	} else if tc.ID != "" {
		parts = append(parts, tc.ID)
	}
	if tc.Kind != "" {
		parts = append(parts, tc.Kind)
	}
	if tc.Status != "" {
		parts = append(parts, tc.Status)
	}
	if len(parts) == 0 {
		return tc.ID
	}
	return strings.Join(parts, " · ")
}
