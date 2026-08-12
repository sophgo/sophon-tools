package agentproxy

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/logger"
)

// SessionManager 管理 ACP 会话 ⇄ webchat 会话模型映射与持久化。
// 前端会话（localStorage id）在服务端有独立记录（agent_session 表）：
//   - ID = webchat 会话 uuid（前端 localStorage 同一 id）
//   - ACPSessionID = reasonix 侧 sessionId（session/new 返回值）
//
// 多会话语义对齐设计文档 §5：所有会话统一使用配置的工作区根 cwd。
type SessionManager struct {
	db  *gorm.DB
	cwd string

	mu       sync.Mutex
	sessions map[string]*WebchatSession // key = webchat id

	activeByACP map[string]string // acpSessionId → webchat id（会话恢复用）
}

// NewSessionManager 创建会话管理器。db 可为 nil（内存态）；cwd 为统一工作区根。
func NewSessionManager(db *gorm.DB, cwd string) *SessionManager {
	return &SessionManager{
		db:          db,
		cwd:         cwd,
		sessions:    make(map[string]*WebchatSession),
		activeByACP: make(map[string]string),
	}
}

// LoadAll 启动时从 DB 加载全量会话（内存缓存重建）。
func (sm *SessionManager) LoadAll() {
	if sm == nil || sm.db == nil {
		return
	}
	var rows []WebchatSession
	if err := sm.db.Find(&rows).Error; err != nil {
		logger.Warn("agentproxy: load sessions failed: %v", err)
		return
	}
	sm.mu.Lock()
	defer sm.mu.Unlock()
	for i := range rows {
		rows[i].Messages = decodeMessages(rows[i].MessagesJSON)
		sm.sessions[rows[i].ID] = &rows[i]
		if rows[i].ACPSessionID != "" {
			sm.activeByACP[rows[i].ACPSessionID] = rows[i].ID
		}
	}
}

// List 返回全部会话（按更新时间倒序，供前端会话列表）。
func (sm *SessionManager) List() []WebchatSession {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	out := make([]WebchatSession, 0, len(sm.sessions))
	for _, s := range sm.sessions {
		out = append(out, *s)
	}
	// 稳定排序：updated_at 倒序
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j].UpdatedAt.After(out[j-1].UpdatedAt); j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// Get 按 webchat id 取会话。
func (sm *SessionManager) Get(id string) (*WebchatSession, bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	s, ok := sm.sessions[id]
	if !ok {
		return nil, false
	}
	cp := *s
	return &cp, true
}

// New 创建新会话：先向 reasonix 申请 ACP sessionId，再落本地记录。
func (sm *SessionManager) New(ctx context.Context, client *Client, title string) (*WebchatSession, error) {
	acpID, err := client.NewSession(ctx, sm.cwd)
	if err != nil {
		return nil, fmt.Errorf("acp session/new: %w", err)
	}
	now := time.Now()
	s := &WebchatSession{
		ID:           newSessionID(),
		ACPSessionID: acpID,
		Title:        title,
		Cwd:          sm.cwd,
		Messages:     []ChatMessage{},
		State:        SessionActive,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	sm.mu.Lock()
	sm.sessions[s.ID] = s
	sm.activeByACP[acpID] = s.ID
	sm.mu.Unlock()
	sm.persist(s)
	return s, nil
}

// Load 加载已持久化的 ACP 会话（回放历史），返回映射后的 webchat 记录。
// 用于「重进页面恢复会话」：先 resume（会话可 prompt），可选 load 回放。
func (sm *SessionManager) Load(ctx context.Context, client *Client, acpID, title string) (*WebchatSession, error) {
	// 已在本地映射？直接复用
	if s, ok := sm.GetByACP(acpID); ok {
		if s.State == SessionClosed {
			if err := client.ResumeSession(ctx, acpID, sm.cwd); err != nil {
				return nil, err
			}
			s.State = SessionActive
			sm.persist(s)
		}
		return s, nil
	}
	if err := client.LoadSession(ctx, acpID, sm.cwd); err != nil {
		return nil, fmt.Errorf("acp session/load: %w", err)
	}
	now := time.Now()
	s := &WebchatSession{
		ID:           newSessionID(),
		ACPSessionID: acpID,
		Title:        title,
		Cwd:          sm.cwd,
		Messages:     []ChatMessage{},
		State:        SessionActive,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	sm.mu.Lock()
	sm.sessions[s.ID] = s
	sm.activeByACP[acpID] = s.ID
	sm.mu.Unlock()
	sm.persist(s)
	return s, nil
}

// Switch 切换会话：目标 ACP 会话已 close 则 resume；返回映射记录。
// 会话上下文在 reasonix 侧持久化，前端切换后直接 prompt。
func (sm *SessionManager) Switch(ctx context.Context, client *Client, webchatID string) (*WebchatSession, error) {
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	sm.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("session %s not found", webchatID)
	}
	if s.State == SessionClosed {
		if err := client.ResumeSession(ctx, s.ACPSessionID, sm.cwd); err != nil {
			return nil, fmt.Errorf("acp session/resume: %w", err)
		}
		s.State = SessionActive
		sm.persist(s)
	}
	return s, nil
}

// Close 关闭会话（ACP session/close，保留历史）。
func (sm *SessionManager) Close(ctx context.Context, client *Client, webchatID string) error {
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	sm.mu.Unlock()
	if !ok {
		return nil
	}
	if err := client.CloseSession(ctx, s.ACPSessionID); err != nil {
		logger.Warn("agentproxy: acp session/close failed: %v", err)
	}
	s.State = SessionClosed
	sm.persist(s)
	return nil
}

// Delete 删除会话（ACP session/delete + 本地记录删除）。
func (sm *SessionManager) Delete(ctx context.Context, client *Client, webchatID string) error {
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	if ok {
		delete(sm.sessions, webchatID)
		delete(sm.activeByACP, s.ACPSessionID)
	}
	sm.mu.Unlock()
	if !ok {
		return nil
	}
	if err := client.DeleteSession(ctx, s.ACPSessionID); err != nil {
		logger.Warn("agentproxy: acp session/delete failed: %v", err)
	}
	if sm.db != nil {
		if err := sm.db.Where("id = ?", webchatID).Delete(&WebchatSession{}).Error; err != nil {
			logger.Warn("agentproxy: delete session row failed: %v", err)
		}
	}
	return nil
}

// CloseAll 关闭全部 active 会话（优雅关闭时调用）。逐个尝试，失败不阻断。
func (sm *SessionManager) CloseAll(ctx context.Context, client *Client) {
	sm.mu.Lock()
	active := make([]*WebchatSession, 0)
	for _, s := range sm.sessions {
		if s.State == SessionActive {
			active = append(active, s)
		}
	}
	sm.mu.Unlock()
	for _, s := range active {
		if err := client.CloseSession(ctx, s.ACPSessionID); err != nil {
			logger.Warn("agentproxy: close session %s failed: %v", s.ACPSessionID, err)
		}
		s.State = SessionClosed
		sm.persist(s)
	}
}

// Restore 进程重启后恢复：对 DB 中 active 状态的会话逐个 resume（不回放）。
// 由 onReady（initialize 成功后）调用。
func (sm *SessionManager) Restore(ctx context.Context, client *Client) {
	sm.mu.Lock()
	active := make([]*WebchatSession, 0)
	for _, s := range sm.sessions {
		if s.State == SessionActive {
			active = append(active, s)
		}
	}
	sm.mu.Unlock()
	for _, s := range active {
		if err := client.ResumeSession(ctx, s.ACPSessionID, sm.cwd); err != nil {
			logger.Warn("agentproxy: restore session %s failed: %v", s.ACPSessionID, err)
		}
	}
}

// GetByACP 按 ACP sessionId 查本地记录。
func (sm *SessionManager) GetByACP(acpID string) (*WebchatSession, bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	wid, ok := sm.activeByACP[acpID]
	if !ok {
		return nil, false
	}
	s, ok := sm.sessions[wid]
	if !ok {
		return nil, false
	}
	cp := *s
	return &cp, true
}

// AppendMessage 追加一条消息历史快照并持久化。
func (sm *SessionManager) AppendMessage(webchatID string, msg ChatMessage) {
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	if !ok {
		sm.mu.Unlock()
		return
	}
	s.Messages = append(s.Messages, msg)
	s.UpdatedAt = time.Now()
	sm.mu.Unlock()
	sm.persist(s)
}

// Rename 设置会话标题并持久化（自定义标题）。
func (sm *SessionManager) Rename(webchatID, title string) bool {
	title = strings.TrimSpace(title)
	if title == "" {
		return false
	}
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	if ok {
		s.Title = title
		s.UpdatedAt = time.Now()
	}
	sm.mu.Unlock()
	if !ok {
		return false
	}
	sm.persist(s)
	return true
}

// EnsureTitle 若会话仍为默认标题，则用给定 fallback（通常为第一条用户消息）设置标题。
// 返回是否真正设置了。
// 规则（需求 3）：默认用用户第一个问题的前 8 个字作为标题。
func (sm *SessionManager) EnsureTitle(webchatID, fallback string) bool {
	title := defaultTitleFromText(fallback)
	if title == "" {
		return false
	}
	sm.mu.Lock()
	s, ok := sm.sessions[webchatID]
	if !ok || (s.Title != "" && s.Title != "新会话") {
		sm.mu.Unlock()
		return false
	}
	s.Title = title
	s.UpdatedAt = time.Now()
	sm.mu.Unlock()
	sm.persist(s)
	return true
}

// defaultTitleFromText 取文本前 8 个字符作为标题。
func defaultTitleFromText(text string) string {
	t := strings.Join(strings.Fields(strings.TrimSpace(text)), " ")
	if t == "" {
		return ""
	}
	runes := []rune(t)
	if len(runes) > 8 {
		return string(runes[:8])
	}
	return t
}

// persist 落库（失败仅告警，不阻断内存态）。
func (sm *SessionManager) persist(s *WebchatSession) {
	if sm.db == nil {
		return
	}
	s.MessagesJSON = encodeMessages(s.Messages)
	if err := sm.db.Save(s).Error; err != nil {
		logger.Warn("agentproxy: persist session %s failed: %v", s.ID, err)
	}
}

func encodeMessages(msgs []ChatMessage) string {
	b, err := json.Marshal(msgs)
	if err != nil {
		return "[]"
	}
	return string(b)
}

func decodeMessages(s string) []ChatMessage {
	if s == "" {
		return []ChatMessage{}
	}
	var msgs []ChatMessage
	if err := json.Unmarshal([]byte(s), &msgs); err != nil {
		return []ChatMessage{}
	}
	return msgs
}

// newSessionID 生成 webchat 会话 uuid（crypto/rand，标准库，不引入外部依赖）。
func newSessionID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	dst := make([]byte, 36)
	hex.Encode(dst[0:8], b[0:4])
	dst[8] = '-'
	hex.Encode(dst[9:13], b[4:6])
	dst[13] = '-'
	hex.Encode(dst[14:18], b[6:8])
	dst[18] = '-'
	hex.Encode(dst[19:23], b[8:10])
	dst[23] = '-'
	hex.Encode(dst[24:36], b[10:16])
	return string(dst)
}
