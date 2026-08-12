// Package agentproxy 实现 bmssm 的「Reasonix ACP 适配器」核心：
// reasonix acp 进程管理 + ACP JSON-RPC 2.0 客户端 + 会话管理。
//
// 只通过 `reasonix acp` 进程的 ACP v1 协议（NDJSON over stdin/stdout）交互，
// 不修改 Reasonix 源码。WS 端点与前端适配由后续任务（MYS-168/S3）实现。
package agentproxy

import "time"

// 默认值。
const (
	DefaultPort      = 18990
	DefaultWorkDir   = "/home/linaro"
	DefaultBinary    = "reasonix"
	DefaultBackoffMax = 30 * time.Second
)

// Config agentproxy 运行配置（sqlite 单例 + viper 兜底）。
// 字段对齐 agentproxy-design.md §7.1。
type Config struct {
	Enabled           bool   `json:"enabled"`
	ListenIP          string `json:"listenIP"`
	Port              int    `json:"port"`
	BinaryPath        string `json:"binaryPath"`
	WorkDir           string `json:"workDir"`
	Model             string `json:"model"`
	RestartBackoffMax string `json:"restartBackoffMax,omitempty"` // 人类可读；解析失败用默认
	PermissionTimeout string `json:"permissionTimeout,omitempty"` // 工具审批超时（人类可读，如 60s）；空=60s，0=不超时
}

// ProcessState reasonix 进程生命周期状态。
type ProcessState string

const (
	StateStopped  ProcessState = "stopped"
	StateStarting ProcessState = "starting"
	StateRunning  ProcessState = "running"
	StateDegraded ProcessState = "degraded" // 连续初始化失败，仍周期性重试
)

// SessionState webchat 会话模型状态。
type SessionState string

const (
	SessionActive SessionState = "active" // ACP 会话可被 prompt
	SessionClosed SessionState = "closed" // 已 close，可 resume 恢复
)

// WebchatSession webchatUI 会话模型（sqlite 持久化）。
type WebchatSession struct {
	ID            string       `json:"id"`   // uuid 主键（前端 localStorage 同一 id）
	ACPSessionID  string       `json:"acpSessionId"`
	Title         string       `json:"title"`
	Cwd           string       `json:"cwd"`
	Messages      []ChatMessage `json:"messages,omitempty" gorm:"-"` // 历史快照（JSON 存 MessagesJSON）
	MessagesJSON  string       `json:"-"`                            // sqlite 存储用
	State         SessionState `json:"state"`
	CreatedAt     time.Time    `json:"createdAt"`
	UpdatedAt     time.Time    `json:"updatedAt"`
}

// TableName 指定表名。
func (WebchatSession) TableName() string { return "agent_session" }

// ChatMessage 会话历史消息快照（渲染用；reasonix 侧 transcript 是权威上下文）。
// Role 取值：user / assistant。Kind 区分渲染形态：text / thought / tool_calls
//（user 消息 Kind 一般留空）。Model 记录 assistant 文本来源模型名。
type ChatMessage struct {
	Role     string `json:"role"`     // user / assistant
	Content  string `json:"content"`  // 文本或折叠块摘要
	Kind     string `json:"kind,omitempty"`     // text / thought / tool_calls
	Model    string `json:"model,omitempty"`    // assistant 模型名
	ID       string `json:"id,omitempty"`       // 消息/工具 id（messageId / toolCallId）
}

// ACPSessionUpdate ACP session/update 通知的通用载荷（判别子见 Discriminator）。
type ACPSessionUpdate struct {
	SessionID         string            `json:"sessionId,omitempty"`
	Discriminator     string            `json:"discriminator,omitempty"`
	MessageID         string            `json:"messageId,omitempty"`
	Content           string            `json:"content,omitempty"`
	ToolCallID        string            `json:"toolCallId,omitempty"`
	ToolCallTitle     string            `json:"toolCallTitle,omitempty"`
	ToolCallKind      string            `json:"toolCallKind,omitempty"`
	ToolCallStatus    string            `json:"toolCallStatus,omitempty"`
	StopReason        string            `json:"stopReason,omitempty"`
	Title             string            `json:"title,omitempty"`
	Raw               map[string]any    `json:"-"`
}
