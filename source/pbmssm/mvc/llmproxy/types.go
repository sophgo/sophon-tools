// Package llmproxy 提供 LLM API 转发（OpenAI 兼容版）。
//
// 转发逻辑参考 llm-proxy（https://github.com/zzttzzmyswy/llm-proxy）：
// 客户端（如 PicoClaw）以任意模型名请求本模块内置的 OpenAI 兼容端点，
// 代理检测请求中是否含 image_url 分流到 VLM / LLM 配置的上游，
// 请求带非空 model 则保留，否则替换为对应配置的模型名后转发到上游 api_base。
//
// 入站 key 校验（MYS-171 放宽）：仅配置了 ForwardKey 且请求携带匹配 key 时视为已鉴权；
// 未配置 / 未携带 / 不匹配均放行，不强制拦截。转发时用 bmssm 内部存储的上游 key。
package llmproxy

import "time"

// ProviderConfig 单套上游模型配置（LLM / VLM 各一份）。
type ProviderConfig struct {
	ApiBase       string `json:"apiBase"`   // OpenAI 兼容 base，转发时拼 /chat/completions
	ApiKey        string `json:"-"`         // 上游供应商 key（不输出）
	ModelName     string `json:"modelName"` // 目标模型名（默认模型名称）
	Enabled       bool   `json:"enabled"`
	OverrideModel bool   `json:"overrideModel"` // 覆盖下游请求：转发时强制用默认模型名
}

// Config 数据库模型：LLM 转发配置（单例，ID 固定为 1）。
// LLM/VLM 各自独立的上游配置；ForwardKey 是客户端调用代理的凭据（独立于上游 key）。
type Config struct {
	ID                uint      `gorm:"column:id;primary_key" json:"-"`
	LLMApiBase        string    `gorm:"column:llm_api_base" json:"llmApiBase"`
	LLMApiKey         string    `gorm:"column:llm_api_key" json:"-"`
	LLMModel          string    `gorm:"column:llm_model" json:"llmModel"`
	LLMEnabled        bool      `gorm:"column:llm_enabled" json:"llmEnabled"`
	LLMOverride       bool      `gorm:"column:llm_override_model" json:"llmOverrideModel"`
	VLMApiBase        string    `gorm:"column:vlm_api_base" json:"vlmApiBase"`
	VLMApiKey         string    `gorm:"column:vlm_api_key" json:"-"`
	VLMModel          string    `gorm:"column:vlm_model" json:"vlmModel"`
	VLMEnabled        bool      `gorm:"column:vlm_enabled" json:"vlmEnabled"`
	VLMOverride       bool      `gorm:"column:vlm_override_model" json:"vlmOverrideModel"`
	ForwardKey        string    `gorm:"column:forward_key" json:"-"`
	ForwardKeyWritten bool      `gorm:"column:forward_key_written" json:"-"`
	UpdatedAt         time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

// TableName 指定表名。
func (Config) TableName() string { return "llm_proxy_config" }

// DefaultConfig 返回默认配置（sophnet 上游：LLM=deepseek，VLM=vl-flash）。
// ApiBase 为 OpenAI 兼容 base（转发时直接拼 /chat/completions）。
// LLMOverride/VLMOverride 默认开启「覆盖下游请求」：新装转发一律用默认模型名。
func DefaultConfig() Config {
	return Config{
		ID:          1,
		LLMApiBase:  "https://www.sophnet.com/api/open-apis/v1",
		LLMModel:    "sophnet-deepseek",
		LLMEnabled:  true,
		LLMOverride: true,
		VLMApiBase:  "https://www.sophnet.com/api/open-apis/v1",
		VLMModel:    "sophnet-vl-flash",
		VLMEnabled:  true,
		VLMOverride: true,
	}
}

// Provider 标识上游模型类型。
type Provider string

const (
	ProviderLLM Provider = "llm"
	ProviderVLM Provider = "vlm"
)

// LLM 返回 LLM 上游配置。
func (c Config) LLM() ProviderConfig {
	return ProviderConfig{ApiBase: c.LLMApiBase, ApiKey: c.LLMApiKey, ModelName: c.LLMModel, Enabled: c.LLMEnabled, OverrideModel: c.LLMOverride}
}

// VLM 返回 VLM 上游配置。
func (c Config) VLM() ProviderConfig {
	return ProviderConfig{ApiBase: c.VLMApiBase, ApiKey: c.VLMApiKey, ModelName: c.VLMModel, Enabled: c.VLMEnabled, OverrideModel: c.VLMOverride}
}

// Provider 按类型取上游配置。
func (c Config) Provider(kind Provider) ProviderConfig {
	if kind == ProviderVLM {
		return c.VLM()
	}
	return c.LLM()
}

// SaveRequest 保存配置请求体。
// 各 key 为空表示不修改（保留原值，前端脱敏不回传全量 key）。
type SaveRequest struct {
	LLMApiBase  string `json:"llmApiBase"`
	LLMApiKey   string `json:"llmApiKey"`
	LLMModel    string `json:"llmModel"`
	LLMEnabled  *bool  `json:"llmEnabled"`
	LLMOverride *bool  `json:"llmOverrideModel"`
	VLMApiBase  string `json:"vlmApiBase"`
	VLMApiKey   string `json:"vlmApiKey"`
	VLMModel    string `json:"vlmModel"`
	VLMEnabled  *bool  `json:"vlmEnabled"`
	VLMOverride *bool  `json:"vlmOverrideModel"`
}

// ConfigResponse 配置响应（各 key 脱敏为 hasKey 布尔；ForwardKey 明文返回供前端展示）。
type ConfigResponse struct {
	LLMApiBase      string    `json:"llmApiBase"`
	LLMModel        string    `json:"llmModel"`
	LLMEnabled      bool      `json:"llmEnabled"`
	LLMOverride     bool      `json:"llmOverrideModel"`
	LLMHasKey       bool      `json:"llmHasKey"`
	VLMApiBase      string    `json:"vlmApiBase"`
	VLMModel        string    `json:"vlmModel"`
	VLMEnabled      bool      `json:"vlmEnabled"`
	VLMOverride     bool      `json:"vlmOverrideModel"`
	VLMHasKey       bool      `json:"vlmHasKey"`
	ForwardKey      string    `json:"forwardKey"`
	ForwardKeyReady bool      `json:"forwardKeyReady"` // 是否已写入本地 picoclaw
	UpdatedAt       time.Time `json:"updatedAt"`
}

// ModelInfo 模型列表条目（供应商 openai 接口返回）。
type ModelInfo struct {
	ID string `json:"id"`
}

// DevProxyModel 兼容别名：客户端可用该名请求，代理不限制入站 model 名。
const DevProxyModel = "devproxy"
