package config

import "time"

// 默认内置 key 是自建 Cloudflare Worker 网关（se-rag-gateway）分发的 throwaway 网关 key，
// 不落明文源码，采用 XOR(0x5A) 混淆字节存储，运行时解码。真硅基流动 key 只在网关侧持有，
// 该内置 key 即使泄露也仅能调用白名单的两个模型、蹭免费额度，不暴露源站 key。
// 使用内置 key 时强制限流（并发≤1、单次≤2 段落）；用户自备 key 时放开并直达其自备地址。
var builtinKeyMask = byte(0x5A)

var builtinKeyEnc = []byte{
	20, 17, 41, 20, 16, 62, 31, 3, 20, 29, 12, 110, 2, 27, 34, 0, 20, 11, 10, 44, 24, 21, 53, 14, 104, 61, 49, 109, 44, 34, 57, 56, 46, 56, 61, 32, 56, 22, 47, 22, 34, 2, 45, 34, 57, 57, 30, 108, 14, 3, 11, 28, 16, 14, 40, 45, 62, 9, 111, 109, 9, 0, 24, 61,
}

// BuiltinKey 返回默认内置网关 key（运行时从混淆字节解码）。
func BuiltinKey() string {
	b := make([]byte, len(builtinKeyEnc))
	for i, c := range builtinKeyEnc {
		b[i] = c ^ builtinKeyMask
	}
	return string(b)
}

// GatewayBaseURL 是内置网关第一跳：Cloudflare Worker（se-rag-gateway）。
// 默认顺序 CF → FC：CF 边缘覆盖最好，单次请求受 Gateway.AttemptTimeout（默认 6s）约束，
// 到点立即让位给 FC，不把预算耗在多个 CF 端口上。
// 白名单仅 BAAI/bge-m3、BAAI/bge-reranker-v2-m3；对 *.workers.dev DNS 污染走 IP 优先 + DoH 兜底拨号。
const GatewayBaseURL = "https://se-rag-gateway.zetao-zhang.workers.dev/v1"

// GatewayFCBaseURL 是内置网关第二跳：阿里云函数计算（FC3.0）上部署的同协议网关镜像，
// 国内直连免备案、无 DNS 污染问题，实测延迟 0.07s 级，作为 CF 超时后的快速回退。
// 与 CF 网关完全同协议：同 key / 同路径 / 同模型白名单，内置 key 零改动即可切换。
const GatewayFCBaseURL = "https://se-rag-gateway-chrzlcfiqt.cn-hangzhou.fcapp.run/v1"

// officialSiliconflowBaseURL 官方 SiliconFlow 地址：用户自备 key 且未提供 base_url 时使用。
const officialSiliconflowBaseURL = "https://api.siliconflow.cn/v1"

// 内置模型与维度：内置 key 的白名单只有这两个模型，-builtin-key=true 时强制使用。
const (
	BuiltinEmbeddingModel = "BAAI/bge-m3"
	BuiltinEmbeddingDim   = 1024
	BuiltinRerankModel    = "BAAI/bge-reranker-v2-m3"
)

// 网关超时默认值。
//
// AttemptTimeout 是「单次请求（含读完响应体）」的上限：CF 卡住时到点即转 FC，
// 而不是让一次尝试吃光全部预算（CF TLS 握手中位数 1.9s、最大 4.6s，6s 留出抖动余量）。
// FailoverBudget 是整条链（全部网关 + 全部重试 + 退避）的总时限，到点即认输降级 BM25，
// 降级答案快过沉默。两者都可由文件 gateway 段或环境变量覆盖。
const (
	DefaultAttemptTimeout = 6 * time.Second
	DefaultFailoverBudget = 18 * time.Second
)

// Gateway 内置网关故障转移链与传输约束（配置文件 gateway 段与 SE_RAG_* 环境变量的最终值）。
//
// 只对内置 key 生效：自备 key 直达其自备地址，不走这条链、也不参与 CF 端口/明文降级。
type Gateway struct {
	// PrimaryURL 第一跳，默认 CF Worker。
	PrimaryURL string
	// FallbackURL 第二跳，默认阿里云 FC；空表示显式单跳（禁用备用网关）。
	FallbackURL string
	// AttemptTimeout 单次请求（含响应体）上限；多跳链生效，单地址自备请求不受此限。
	AttemptTimeout time.Duration
	// FailoverBudget 全链总预算（含退避）。
	FailoverBudget time.Duration
	// AllowHTTPFallback 是否允许在 TLS 全端口失效时改走明文 HTTP 兜底。
	AllowHTTPFallback bool
}

// Chain 返回内置 key 的有序网关列表。备用地址为空、或与主地址相同（显式单跳）时只有一跳。
func (g Gateway) Chain() []string {
	primary := g.PrimaryURL
	if primary == "" {
		primary = GatewayBaseURL
	}
	if g.FallbackURL == "" || g.FallbackURL == primary {
		return []string{primary}
	}
	return []string{primary, g.FallbackURL}
}

// Provider 一家 embedding / reranker 供应商的最终配置。
//
// 字段含义按 key 归属区分，两类取值不混用：
//   - 内置 key（APIKey 为空）：地址取 Config.Gateway 的网关链，BaseURL 不生效；
//   - 自备 key（APIKey 非空）：地址取 BaseURL，未提供时沿用官方 SiliconFlow 默认地址。
type Provider struct {
	// Type 供应商类型：siliconflow（OpenAI 兼容 /embeddings + 现有 rerank 协议）| sophnet。
	Type string
	// APIKey 用户自备 key；空 = 使用内置 key（并启用内置限流）。
	APIKey string
	// Model embedding / rerank 模型名，同时写入索引指纹。
	Model string
	// BaseURL 自备 key 时的上游地址；空 = 官方 SiliconFlow 默认地址。
	BaseURL string
	// Dim embedding 维度（reranker 不适用，置 0），同时写入索引指纹。
	Dim int
}

// Product 一条知识库的文档与索引配置。product 只作 meta.json 元数据标签，不参与磁盘路径。
type Product struct {
	Name     string
	DocsDir  string
	IndexDir string
	Embedder Provider
	Reranker Provider
}

// Config 一次加载后的最终配置。
type Config struct {
	Products []Product
	Gateway  Gateway
}

// DefaultConfig 纯默认配置：不读文件、不读环境变量、不报错，供 Load 的起点与离线/测试使用。
func DefaultConfig() Config {
	return Config{
		Gateway: Gateway{
			PrimaryURL:        GatewayBaseURL,        // CF
			FallbackURL:       GatewayFCBaseURL,      // FC：CF 超时后的快速回退
			AttemptTimeout:    DefaultAttemptTimeout, // 6s
			FailoverBudget:    DefaultFailoverBudget, // 18s
			AllowHTTPFallback: true,
		},
		Products: []Product{{
			Name:    "se7",
			DocsDir: "docs/se7",
			Embedder: Provider{
				Type: "siliconflow", Model: BuiltinEmbeddingModel, Dim: BuiltinEmbeddingDim,
			},
			Reranker: Provider{
				Type: "siliconflow", Model: BuiltinRerankModel,
			},
		}},
	}
}

// IsBuiltinKey 该 provider 是否使用内置 key（决定是否启用内置限流）。
func (p Provider) IsBuiltinKey() bool { return p.APIKey == "" }

// EffectiveKey 实际使用的 key：自备优先，否则内置。
func (p Provider) EffectiveKey() string {
	if p.APIKey != "" {
		return p.APIKey
	}
	return BuiltinKey()
}

// EffectiveBaseURL 实际请求的上游地址（单地址场景；多跳请用 EffectiveBaseURLs）。
func (p Provider) EffectiveBaseURL(gw Gateway) string {
	return p.EffectiveBaseURLs(gw)[0]
}

// EffectiveBaseURLs 实际请求地址的有序列表。
//
// 自备 key → 单个地址：显式 BaseURL 优先，未提供时沿用官方 SiliconFlow 默认地址；
// 不经内置网关、不做故障转移，也不参与 CF 备用端口/明文降级。
// 内置 key → 网关链（默认 CF → FC），相同地址去重。
func (p Provider) EffectiveBaseURLs(gw Gateway) []string {
	if p.APIKey != "" {
		if p.BaseURL != "" {
			return []string{p.BaseURL}
		}
		return []string{officialSiliconflowBaseURL}
	}
	return gw.Chain()
}
