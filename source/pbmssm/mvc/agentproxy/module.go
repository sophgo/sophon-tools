package agentproxy

import (
	"context"
	"encoding/json"
	"os"
	"sync"
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/logger"
	"bmssm/mvc/llmproxy"
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
	perms     map[int64]*pendingPermission      // reqID → 待审批请求（连接无关）

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
	// 注册 LLM 配置保存 → 重写 reasonix 上下文（sophnet 200K / 本地 20K）。
	llmproxy.RegisterContextWindowApplier(ApplyReasonixContextWindow)
	// 注册转发 key 轮换监听（MYS-387）：ResetForwardKey 后 Hub 换用新 key，
	// 前端 WS 子协议 token 同步轮换，旧 token 立即失效（无需重启 bmssm）。
	// 不重启 reasonix：转发 server 宽松校验（MYS-171 语义），其 env 中的
	// 旧 key 不会造成鉴权失败。
	llmproxy.RegisterForwardKeyListener(func(key string) {
		if globalMod == nil || globalMod.hub == nil {
			return
		}
		globalMod.hub.SetKey(key)
	})
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
		perms:     make(map[int64]*pendingPermission),
	}
	if eventFn != nil {
		m.listeners[m.nextID] = eventFn
		m.nextID++
	}
	m.sessions = NewSessionManager(db, cfg.WorkDir)
	m.pm = NewProcessManager(cfg, m.onProcessReady)
	// reasonix 经 127.0.0.1:18080 访问 llm-proxy 转发 server（config.toml
	// api_key_env=DEEPSEEK_API_KEY）。启动 reasonix 进程时注入
	// DEEPSEEK_API_KEY=当前 forward key（每次启动动态读取 DB：轮换后
	// 崩溃自愈重启即带最新值；转发 server 为宽松校验，不携带也无碍）。
	m.pm.SetEnvInjector(func() []string {
		key := forwardKey(db)
		if key == "" {
			return nil
		}
		return []string{"DEEPSEEK_API_KEY=" + key}
	})
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
	// WS 端点由 bmssm 主 gin server 挂载 /agent/ws（HubHandler() → AgentWSHandler），
	// 不再在此拉起独立 18990 http.Server。
	// 需求(MYS-210)：agent 服务默认关闭，且 bmssm 重启后保持默认关闭。
	// 这里不据 m.cfg.Enabled 自动拉起 reasonix 进程（即使配置 enabled=true）——
	// 仅当用户在「Agent 服务管理」手动 start（SetEnabled(true)）才启动；手动启动会
	// 持久化 enabled 供页面刷新保持显示，但 bmssm 重启后回到默认关闭。
	return nil
}

// Shutdown 优雅关闭：关闭 WS 服务与连接、所有活动会话，再停止进程与客户端。
func (m *Module) Shutdown() {
	m.stopOnce.Do(func() {
		if m.hub != nil {
			m.hub.Stop()
		}
		// 清空待审批（模块关闭，定时器/应答都不再需要）
		m.clearPendingPermissions()
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
//   - true：启动 Reasonix 进程（若未运行），并联动确保 llm-proxy 转发 server 就绪
//     （Reasonix 的 LLM 上游走本机 18080，须一起起，需求 MYS-212）。
//   - false：停止 Reasonix 进程（手动停止，supervise 不再自愈），并联动停止
//     llm-proxy 转发 server；WS 端点仍可连接，但发送会返回「reasonix 未就绪」错误帧。
//
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
		// 需求(MYS-212)：reasonix 与 llm-proxy 一起开 —— 启用 Agent 服务时确保
		// LLM 上游转发 server 就绪，避免 reasonix 起来却打不通 LLM 一直转圈。
		if err := llmproxy.SyncServerFromDB(m.db); err != nil {
			logger.Warn("agentproxy: sync llm-proxy server failed: %v", err)
		}
		return nil
	}
	// 禁用：停止进程，保持停止（runRequested=false → supervise 不再重启）
	m.pm.Stop()
	// 需求(MYS-212)：与 llm-proxy 一起关。
	if err := llmproxy.SyncServerFromDB(m.db); err != nil {
		logger.Warn("agentproxy: sync llm-proxy server failed: %v", err)
	}
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

	// reasonix 进程已重建：旧 stream 上待审批的权限请求已失效，直接清空（防悬挂定时器）。
	m.clearPendingPermissions()

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

// dispatchNotify 收到未识别下行通知/agent 发起的 request。
// reqID 非 nil 表示是 agent 发起的 request（如 session/request_permission），
// host 必须按 reqID 回 JSON-RPC 响应，否则 agent 永久等待。
func (m *Module) dispatchNotify(method string, params json.RawMessage, reqID *int64) {
	if method == "session/request_permission" && reqID != nil {
		m.dispatchPermissionRequest(*reqID, params)
		return
	}
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

// forwardKey 读取转发 key（供前端 PicoWs 携带子协议 token.<key> 使用）。
// 复用 llm_proxy_config.forward_key（与 pico 模式完全一致，前端 PicoWS 零改动）。
// MYS-379 后续裁定：/agent/ws 不再校验该 key（与 18080 转发一致"不需要 key"），
// 此处仅保持兼容下发；读失败返回空串，不影响连接。
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
