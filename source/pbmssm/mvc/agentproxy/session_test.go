package agentproxy

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
)

// newTestDB 创建内存 sqlite（测试专用）。
func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	if err := db.AutoMigrate(&WebchatSession{}).Error; err != nil {
		t.Fatalf("migrate: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// newTestClient 用 mock 进程创建可用 client。
func newTestClient(t *testing.T, pm *ProcessManager) *Client {
	t.Helper()
	client := NewClient(pm, nil, nil)
	t.Cleanup(client.Close)
	return client
}

// TestSessionNewMapping 验证 New：创建 ACP 会话并映射 webchat 记录。
func TestSessionNewMapping(t *testing.T) {
	db := newTestDB(t)
	path := mockReasonixPath(t, promptHandler())
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()
	client := newTestClient(t, pm)

	sm := NewSessionManager(db, "/home/linaro")
	ctx := context.Background()
	s, err := sm.New(ctx, client, "会话1")
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if s.ID == "" {
		t.Fatal("no webchat id")
	}
	if s.ACPSessionID == "" {
		t.Fatal("no acp session id")
	}
	if s.State != SessionActive {
		t.Fatalf("state = %s", s.State)
	}

	// 映射可查
	if got, ok := sm.GetByACP(s.ACPSessionID); !ok || got.ID != s.ID {
		t.Fatalf("GetByACP failed: %+v ok=%v", got, ok)
	}
	// 列表包含
	if len(sm.List()) != 1 {
		t.Fatalf("list len = %d", len(sm.List()))
	}
}

// TestSessionPersistReload 验证持久化：写库后重新 LoadAll 可恢复。
func TestSessionPersistReload(t *testing.T) {
	db := newTestDB(t)
	sm := NewSessionManager(db, "/home/linaro")

	// 直接插入记录（模拟已有会话）
	s := &WebchatSession{
		ID:           "web-1",
		ACPSessionID: "acp-1",
		Title:        "已存会话",
		Cwd:          "/home/linaro",
		Messages:     []ChatMessage{{Role: "user", Content: "你好"}},
		State:        SessionActive,
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}
	sm.mu.Lock()
	sm.sessions[s.ID] = s
	sm.activeByACP[s.ACPSessionID] = s.ID
	sm.mu.Unlock()
	sm.persist(s)

	// 重建 manager（模拟重启），LoadAll 恢复
	sm2 := NewSessionManager(db, "/home/linaro")
	sm2.LoadAll()
	if len(sm2.List()) != 1 {
		t.Fatalf("after reload list len = %d", len(sm2.List()))
	}
	got, ok := sm2.Get("web-1")
	if !ok {
		t.Fatal("session not found after reload")
	}
	if got.ACPSessionID != "acp-1" {
		t.Fatalf("acp id = %s", got.ACPSessionID)
	}
	if got.State != SessionActive {
		t.Fatalf("state = %s", got.State)
	}
	if len(got.Messages) != 1 || got.Messages[0].Content != "你好" {
		t.Fatalf("messages = %+v", got.Messages)
	}
}

// TestSessionDelete 验证删除：ACP delete + 本地记录移除。
func TestSessionDelete(t *testing.T) {
	db := newTestDB(t)
	path := mockReasonixPath(t, promptHandler())
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()
	client := newTestClient(t, pm)

	sm := NewSessionManager(db, "/home/linaro")
	ctx := context.Background()
	s, _ := sm.New(ctx, client, "待删")
	if err := sm.Delete(ctx, client, s.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, ok := sm.Get(s.ID); ok {
		t.Fatal("session still present after delete")
	}
	// 数据库行也删了
	var count int
	db.Model(&WebchatSession{}).Where("id = ?", s.ID).Count(&count)
	if count != 0 {
		t.Fatalf("db row count = %d", count)
	}
}

// TestSessionSwitchResume 验证 Switch：closed 会话 resume 后 active。
func TestSessionSwitchResume(t *testing.T) {
	db := newTestDB(t)
	path := mockReasonixPath(t, promptHandler())
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()
	client := newTestClient(t, pm)

	sm := NewSessionManager(db, "/home/linaro")
	ctx := context.Background()
	s, _ := sm.New(ctx, client, "会话A")

	// close 后 active→closed
	if err := sm.Close(ctx, client, s.ID); err != nil {
		t.Fatalf("Close: %v", err)
	}
	if got, _ := sm.Get(s.ID); got.State != SessionClosed {
		t.Fatalf("state after close = %s", got.State)
	}

	// switch 恢复
	if _, err := sm.Switch(ctx, client, s.ID); err != nil {
		t.Fatalf("Switch: %v", err)
	}
	if got, _ := sm.Get(s.ID); got.State != SessionActive {
		t.Fatalf("state after switch = %s", got.State)
	}
}

// TestSessionAppendMessage 验证消息历史追加与持久化。
func TestSessionAppendMessage(t *testing.T) {
	db := newTestDB(t)
	sm := NewSessionManager(db, "/home/linaro")
	s := &WebchatSession{
		ID:           "web-msg",
		ACPSessionID: "acp-msg",
		State:        SessionActive,
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}
	sm.mu.Lock()
	sm.sessions[s.ID] = s
	sm.mu.Unlock()

	sm.AppendMessage(s.ID, ChatMessage{Role: "user", Content: "问题"})
	sm.AppendMessage(s.ID, ChatMessage{Role: "assistant", Content: "回答"})

	got, _ := sm.Get(s.ID)
	if len(got.Messages) != 2 {
		t.Fatalf("messages len = %d", len(got.Messages))
	}
	// 持久化校验：重读 DB
	var row WebchatSession
	if err := db.Where("id = ?", s.ID).First(&row).Error; err != nil {
		t.Fatalf("db read: %v", err)
	}
	var msgs []ChatMessage
	_ = json.Unmarshal([]byte(row.MessagesJSON), &msgs)
	if len(msgs) != 2 {
		t.Fatalf("db messages len = %d", len(msgs))
	}
}

// TestNewSessionID 验证 uuid 生成格式。
func TestNewSessionID(t *testing.T) {
	id := newSessionID()
	if len(id) != 36 {
		t.Fatalf("uuid len = %d: %s", len(id), id)
	}
	if id[14] != '4' {
		t.Fatalf("not version 4: %s", id)
	}
	// 唯一性
	seen := map[string]bool{}
	for i := 0; i < 100; i++ {
		got := newSessionID()
		if seen[got] {
			t.Fatalf("duplicate uuid %s", got)
		}
		seen[got] = true
	}
}

// TestSessionTitle (需求 3)：默认用第一问题前 8 字，且可自定义重命名。
func TestSessionTitle(t *testing.T) {
	sm := NewSessionManager(nil, t.TempDir())
	// 预置一个会话（默认标题）
	sm.sessions["s1"] = &WebchatSession{ID: "s1", ACPSessionID: "acp-1", Title: "新会话", Messages: []ChatMessage{}}

	// EnsureTitle：第一条用户消息前 8 字
	name := "请帮我查看系统日志看看最近设备在做什么"
	if !sm.EnsureTitle("s1", name) {
		t.Fatal("EnsureTitle should set title on first message")
	}
	got := sm.sessions["s1"].Title
	// EnsureTitle 用 defaultTitleFromText：第一条用户消息前 8 个字
	exp := defaultTitleFromText(name)
	if got != exp {
		t.Fatalf("title = %q, want %q", got, exp)
	}
	if got == "" || len([]rune(got)) > 8 {
		t.Fatalf("title wrong length: %q", got)
	}
	// 自定义标题
	if !sm.Rename("s1", "我的自定义标题") {
		t.Fatal("Rename should succeed")
	}
	if sm.sessions["s1"].Title != "我的自定义标题" {
		t.Fatalf("after rename title = %q", sm.sessions["s1"].Title)
	}
	// 已有自定义标题后 EnsureTitle 不再改
	if sm.EnsureTitle("s1", "新问题") {
		t.Fatal("EnsureTitle should not overwrite custom title")
	}
	if sm.sessions["s1"].Title != "我的自定义标题" {
		t.Fatalf("custom title overwritten: %q", sm.sessions["s1"].Title)
	}
}

// TestSessionTitlePersist 标题随 DB 持久化。
func TestSessionTitlePersist(t *testing.T) {
	db := newTestDB(t)
	sm := NewSessionManager(db, t.TempDir())
	sm.sessions["p1"] = &WebchatSession{ID: "p1", ACPSessionID: "acp-p", Title: "新会话", Messages: []ChatMessage{}}
	sm.EnsureTitle("p1", "第一个问题是什么来着很长的")
	if !sm.Rename("p1", "自定义标题") {
		t.Fatal("rename failed")
	}
	// 重建后标题保留
	sm2 := NewSessionManager(db, t.TempDir())
	sm2.LoadAll()
	s, ok := sm2.Get("p1")
	if !ok || s.Title != "自定义标题" {
		t.Fatalf("title not persisted: %+v", s)
	}
}
