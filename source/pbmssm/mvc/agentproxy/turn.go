package agentproxy

import (
	"context"
)

// Turn 一次往返（message.send → agent 回复）的运行单元，与 WS 连接解耦。
// 关键点：回合的生命周期由 Module 持有，而非绑定到某个 conn——
// 浏览器关闭/切换页面/切换会话时，agent 仍在服务端继续干活（runTurn 的
// goroutine 独立于连接），回合结果最终落库，回来即可看到完整内容。
//
// 一个 ACP 会话同一时刻只有一个 Turn（发新消息会先取消旧回合）。
type Turn struct {
	acpID     string
	webchatID string
	round     int64
	adapter   *MessageAdapter // 模块级累积本回合 assistant（text/thought/tool_calls），与连接无关
	cancel    func() error
	done      chan struct{} // 回合结束（prompt 响应到达 / 被取消）后关闭
	started   bool          // 是否已启动 streaming 消费
}

// StartTurn 在模块级启动一次回合（连接无关，浏览器断开后仍继续执行）。
// 若该 ACP 会话已有在途回合，先取消旧回合（用户明确发新消息即打断）。
// 回合内容通过 hub 投递给当前绑定该会话的连接（可能有、可能无）。
func (m *Module) StartTurn(webchatID, acpID, content string) error {
	m.mu.Lock()
	if old := m.turns[acpID]; old != nil {
		m.mu.Unlock()
		// 取消旧回合（不阻塞等待其清理，避免持锁）
		if old.cancel != nil {
			_ = old.cancel()
		}
	} else {
		m.mu.Unlock()
	}

	client := m.Client()
	if client == nil {
		return errReasonixNotReady
	}
	updates, cancel, err := client.Prompt(context.Background(), acpID, content)
	if err != nil {
		return err
	}

	round := m.nextTurnRound()
	t := &Turn{
		acpID:     acpID,
		webchatID: webchatID,
		round:     round,
		adapter:   NewMessageAdapter(m.cfg.Model),
		cancel:    cancel,
		done:      make(chan struct{}),
		started:   true,
	}
	m.mu.Lock()
	m.turns[acpID] = t
	m.mu.Unlock()

	// 用户消息入历史；若还是默认标题，用第一条用户消息前 8 字设标题（需求 3）
	if m.sessions != nil {
		m.sessions.AppendMessage(webchatID, ChatMessage{Role: "user", Content: content})
		if m.sessions.EnsureTitle(webchatID, content) {
			// 标题变化：广播给订阅该会话的连接（前端即时更新侧栏标题）
			if m.hub != nil {
				if s, ok := m.sessions.Get(webchatID); ok {
					m.hub.BroadcastSession(acpID, WSFrame{Type: "session.updated", SessionID: webchatID, Payload: map[string]any{"title": s.Title}})
				}
			}
		}
	}
	// typing.start + busy 通知
	if m.hub != nil {
		m.hub.BroadcastSession(acpID, typingFrame(webchatID, true), busyFrame(webchatID, true))
	}

	go m.consumeTurn(t, updates)
	return nil
}

// consumeTurn 消费回合的流式更新（`updates` 通道），并把帧投递给当前订阅该会话的连接。
// 回合结束（通道关闭）后落库 assistant 全量、广播 typing.stop + busy=false。
func (m *Module) consumeTurn(t *Turn, updates <-chan *ACPSessionUpdate) {
	defer func() {
		close(t.done)
		m.mu.Lock()
		if m.turns[t.acpID] == t {
			delete(m.turns, t.acpID)
		}
		m.mu.Unlock()
	}()
	for ev := range updates {
		if ev == nil {
			continue
		}
		frames := t.adapter.OnACPEvent(ev, t.webchatID)
		if len(frames) > 0 && m.hub != nil {
			m.hub.Deliver(t.acpID, frames)
		}
	}
	// 回合结束：落库 assistant 全量（无论是否还有订阅连接）
	if m.sessions != nil {
		for _, am := range t.adapter.RoundAssistants() {
			m.sessions.AppendMessage(t.webchatID, am)
		}
	}
	// typing.stop + busy=false
	if m.hub != nil {
		m.hub.BroadcastSession(t.acpID, typingFrame(t.webchatID, false), busyFrame(t.webchatID, false))
	}
}

// CancelTurn 显式取消某 ACP 会话的在途回合（前端「停止」按钮）。
// 与 conn.close 无关——断线不会触发取消。
func (m *Module) CancelTurn(acpID string) {
	m.mu.Lock()
	t := m.turns[acpID]
	m.mu.Unlock()
	if t != nil && t.cancel != nil {
		_ = t.cancel()
	}
}

// HasTurn 返回某 ACP 会话是否有进行中的回合（前端忙碌指示用）。
func (m *Module) HasTurn(acpID string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	t := m.turns[acpID]
	if t == nil {
		return false
	}
	select {
	case <-t.done:
		return false
	default:
		return true
	}
}

// nextTurnRound 生成回合序号（模块级单调递增，避免旧回合覆盖新回合）。
func (m *Module) nextTurnRound() int64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.nextID++
	return m.nextID
}

// TurnAdapter 供消费端读取进行中回合的累积适配器（重连补进度用，预留）。
func (m *Module) TurnAdapter(acpID string) *MessageAdapter {
	m.mu.Lock()
	defer m.mu.Unlock()
	if t := m.turns[acpID]; t != nil {
		return t.adapter
	}
	return nil
}

// typingFrame 构造 typing 帧。
func typingFrame(webchatID string, on bool) WSFrame {
	typ := "typing.start"
	if !on {
		typ = "typing.stop"
	}
	return WSFrame{Type: typ, SessionID: webchatID}
}

// busyFrame 构造会话忙碌状态帧（前端转圈标记）。
func busyFrame(webchatID string, busy bool) WSFrame {
	return WSFrame{
		Type:      "session.busy",
		SessionID: webchatID,
		Payload:   map[string]any{"busy": busy},
	}
}

var errReasonixNotReady = errModuleNotStarted // reasonix 未就绪（与 conn prompt 原语义一致）
