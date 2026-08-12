package agentproxy

import (
	"context"
	"encoding/json"
	"os"
	"sync"
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/logger"
)

// Module 是 agentproxy 适配器的顶层装配：进程管理 + ACP 客户端 + 会话管理 + WS 端点。
// S3 起包含 WS 服务（ws.go Hub）：模块事件广播 → Hub 按连接路由 → 前端协议帧。
type Module struct {
	cfg      Config
	db       *gorm.DB
	pm       *ProcessManager
	client   *Client
	sessions *SessionManager
	hub      *Hub // WS 端点（S3）

	mu        sync.Mutex
	started   bool
	nextID    int64
	listeners map[int64]func(*ACPSessionUpdate) // 流式事件监听者（Hub 注册，广播分发）
	turns     map[string]*Turn                  // acpSessionID → 进行中的回合（连接无关）

	stopOnce sync.Once
}

// 全局单例（bmssm 生命周期内唯一；main.go shutdown 时 Shutdown()）。
var (
	globalMu  sync.Mutex
	globalMod *Module
)

// Start 启动 agentproxy 模块（初始化接线调用）。
func Start(cfg Config, db *gorm.DB) *Module {
	globalMu.Lock()
	defer globalMu.Unlock()
	if globalMod != nil {
		return globalMod
	}
	globalMod = NewModule(cfg, db, nil)
	if err := globalMod.Start(); err != nil {
		logger.Error("agentproxy: start failed: %v", err)
	}
	return globalMod
}

// Shutdown 优雅关闭全局模块（main.go shutdown 时调用）。
func Shutdown() {
	globalMu.Lock()
	m := globalMod
	globalMod = nil
	globalMu.Unlock()
	if m != nil {
		m.Shutdown()
	}
}

// NewModule 创建装配模块。eventFn 为流式事件监听者（可为 nil；多个监听者可用
// AddEventListener 注册，WS Hub 启动时自动注册）。
func NewModule(cfg Config, db *gorm.DB, eventFn func(*ACPSessionUpdate)) *Module {
	cfg.Normalize()
	m := &Module{
		cfg:       cfg,
		db:        db,
		listeners: make(map[int64]func(*ACPSessionUpdate)),
		turns:     make(map[string]*Turn),
	}
	if eventFn != nil {
		m.listeners[m.nextID] = eventFn
		m.nextID++
	}
	m.sessions = NewSessionManager(db, cfg.WorkDir)
	m.pm = NewProcessManager(cfg, m.onProcessReady)
	m.hub = newHub(m, forwardKey(db))
	return m
}

// Start 启动适配器：迁移（已由初始化调用）、加载会话、启动进程、拉起 WS 服务。
// 幂等。
func (m *Module) Start() error {
	m.mu.Lock()
	if m.started {
		m.mu.Unlock()
		return nil
	}
	m.started = true
	m.mu.Unlock()

	if m.cfg.WorkDir != "" {
		_ = ensureWorkDir(m.cfg.WorkDir)
	}
	m.sessions.LoadAll()
	// WS 服务随模块启动（与 enabled 无关：WebSocket 端点始终可连接，
	// 但 reasonix 未就绪时发送会返回错误帧）。
	if m.hub != nil {
		go func() {
			if err := m.hub.Start(); err != nil {
				logger.Error("agentproxy: ws hub start failed: %v", err)
			}
		}()
	}
	if !m.cfg.Enabled {
		logger.Info("agentproxy: disabled, reasonix acp not started")
		return nil
	}
	return m.pm.Start()
}

// Shutdown 优雅关闭：关闭 WS 服务与连接、所有活动会话，再停止进程与客户端。
func (m *Module) Shutdown() {
	m.stopOnce.Do(func() {
		if m.hub != nil {
			m.hub.Stop()
		}
		m.mu.Lock()
		client := m.client
		m.mu.Unlock()
		if client != nil {
			// 关闭活动会话（超时 3s 兜底）
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			m.sessions.CloseAll(ctx, client)
			cancel()
		}
		if m.pm != nil {
			m.pm.GracefulStop()
		}
		if client != nil {
			client.Close()
		}
	})
}

// Client 返回当前 ACP 客户端（未初始化则 nil）。
func (m *Module) Client() *Client {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.client
}

// Sessions 返回会话管理器。
func (m *Module) Sessions() *SessionManager {
	return m.sessions
}

// Process 返回进程管理器（健康检查/状态查询）。
func (m *Module) Process() *ProcessManager {
	return m.pm
}

// SetEnabled 持久化并应用 enabled 状态：
//   - true：启动 Reasonix 进程（若未运行）
//   - false：停止 Reasonix 进程（手动停止，supervise 不再自愈）；WS 端点仍可连接，
//     但发送会返回「reasonix 未就绪」错误帧。
// 供「启用」/服务管理开关调用。返回错误时进程状态可能未变更。
func (m *Module) SetEnabled(enabled bool) error {
	m.mu.Lock()
	m.cfg.Enabled = enabled
	m.mu.Unlock()
	if _, err := persistEnabled(m.db, enabled); err != nil {
		return err
	}
	if enabled {
		if err := m.pm.Start(); err != nil {
			return err
		}
		// 进程可能因手动停止处于 stopped；Start 会拉起。无需额外处理。
		return nil
	}
	// 禁用：停止进程，保持停止（runRequested=false → supervise 不再重启）
	m.pm.Stop()
	return nil
}

// AddEventListener 注册流式事件监听者，返回可注销的句柄。
// S3 Hub 启动时调用；多个监听者广播分发。
func (m *Module) AddEventListener(fn func(*ACPSessionUpdate)) (remove func()) {
	if fn == nil {
		return func() {}
	}
	m.mu.Lock()
	id := m.nextID
	m.nextID++
	m.listeners[id] = fn
	m.mu.Unlock()
	return func() {
		m.mu.Lock()
		delete(m.listeners, id)
		m.mu.Unlock()
	}
}

// SetEventFn 设置/清除唯一流式事件监听者（兼容旧用法；清除传 nil）。
func (m *Module) SetEventFn(fn func(*ACPSessionUpdate)) {
	m.mu.Lock()
	m.listeners = make(map[int64]func(*ACPSessionUpdate))
	if fn != nil {
		m.listeners[m.nextID] = fn
		m.nextID++
	}
	m.mu.Unlock()
}

// dispatchEvent 收到 session/update 解析结果，广播给所有监听者。
func (m *Module) dispatchEvent(ev *ACPSessionUpdate) {
	if ev == nil {
		return
	}
	m.mu.Lock()
	fns := make([]func(*ACPSessionUpdate), 0, len(m.listeners))
	for _, fn := range m.listeners {
		fns = append(fns, fn)
	}
	m.mu.Unlock()
	for _, fn := range fns {
		fn(ev)
	}
}

// onProcessReady 每次 reasonix 进程成功启动后被回调：
// 重建 client → initialize 握手 → 恢复会话。
func (m *Module) onProcessReady() {
	m.mu.Lock()
	old := m.client
	m.mu.Unlock()
	if old != nil {
		old.Close()
	}

	m.mu.Lock()
	m.client = NewClient(m.pm, m.dispatchEvent, m.dispatchNotify)
	m.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	initResult, err := m.client.Initialize(ctx)
	if err != nil {
		logger.Error("agentproxy: initialize failed: %v", err)
		m.pm.MarkInitFailed()
		// stderr 提示 reasonix setup
		if s := m.pm.StderrSnapshot(512); s != "" {
			logger.Info("agentproxy: reasonix stderr: %s", s)
		}
		return
	}
	m.pm.MarkInitOK()
	logger.Info("agentproxy: initialize ok protocolVersion=%d", initResult.ProtocolVersion)

	// 恢复 active 会话
	if m.sessions != nil {
		m.sessions.Restore(ctx, m.client)
	}
}

// dispatchNotify 收到未识别下行通知/agent 请求。
// 当前仅记日志；S3 协议层可扩展（permission.request 等）。
func (m *Module) dispatchNotify(method string, params json.RawMessage) {
	logger.Info("agentproxy: downlink notify %s", method)
}

// Status 返回适配器状态（健康检查/管理接口用）。
func (m *Module) Status() map[string]any {
	m.mu.Lock()
	clientReady := m.client != nil
	m.mu.Unlock()
	return map[string]any{
		"enabled":      m.cfg.Enabled,
		"process":      string(m.pm.State()),
		"alive":        m.pm.Alive(),
		"healthy":      m.pm.Healthy(),
		"clientReady":  clientReady,
		"pid":          m.pm.Pid(),
		"sessionCount": len(m.sessions.List()),
		"stderr":       m.pm.StderrSnapshot(512),
	}
}

// ensureWorkDir 确保工作区目录存在（reasonix 会话 cwd）。
func ensureWorkDir(dir string) error {
	if dir == "" {
		return nil
	}
	if st, err := os.Stat(dir); err == nil && st.IsDir() {
		return nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		logger.Warn("agentproxy: create workdir %s failed: %v", dir, err)
		return err
	}
	return nil
}

// forwardKey 读取转发 key（WS 子协议 token.<key> 认证凭据）。
// 复用 llm_proxy_config.forward_key（与 pico 模式完全一致，前端 PicoWS 零改动）。
// 读失败返回空串（认证放行——对齐 MYS-171 放宽策略）。
func forwardKey(db *gorm.DB) string {
	if db == nil {
		return ""
	}
	var cfg struct {
		ForwardKey string `gorm:"column:forward_key"`
	}
	if err := db.Table("llm_proxy_config").Where("id = 1").Scan(&cfg).Error; err != nil {
		return ""
	}
	return cfg.ForwardKey
}
