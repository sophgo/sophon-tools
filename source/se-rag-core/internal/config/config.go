package config

// 默认内置 key 是自建 Cloudflare Worker 网关（se-rag-gateway）分发的 throwaway 网关 key，
// 不落明文源码，采用 XOR(0x5A) 混淆字节存储，运行时解码。真硅基流动 key 只在网关侧持有，
// 该内置 key 即使泄露也仅能调用白名单的两个模型、蹭免费额度，不暴露源站 key。
// 使用内置 key 时强制限流（并发≤1、单次≤2 段落）；用户自备 key（APIKey 非空）时放开并回落官方 SiliconFlow。
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

// GatewayBaseURL 是内置默认网关（se-rag-gateway Worker）地址，白名单仅 BAAI/bge-m3、BAAI/bge-reranker-v2-m3。
const GatewayBaseURL = "https://se-rag-gateway.zetao-zhang.workers.dev/v1"

// GatewayFCBaseURL 是内置网关故障转移第二跳：阿里云函数计算（FC3.0）上部署的同协议网关镜像，
// 国内直连（*.workers.dev 在该网络下不可达时使用）。与 CF 网关完全同协议：同 key / 同路径 /
// 同模型白名单，内置 key 零改动即可切换。
const GatewayFCBaseURL = "https://se-rag-gateway-chrzlcfiqt.cn-hangzhou.fcapp.run/v1"

// 官方 SiliconFlow 地址：用户自备 key 时回落直达，不再经网关中转。
const officialSiliconflowBaseURL = "https://api.siliconflow.cn/v1"

// Provider 一家 embedding / reranker 供应商。
// Type ∈ {siliconflow, sophnet}。
type Provider struct {
	Type    string // siliconflow | sophnet
	APIKey  string // 用户自备 key；空则用内置
	Model   string
	BaseURL string
	// FallbackBaseURL 内置 key 时故障转移的第二网关（默认 GatewayFCBaseURL）：
	// BaseURL（默认 CF Worker）不可达时自动切换；不适用于用户自备 key（直达官方 SiliconFlow）。
	// 置空自动取 GatewayFCBaseURL；想禁用故障转移时显式置为与 BaseURL 相同的值。
	FallbackBaseURL string
	Dim             int // embedding 维度（reranker 不适用，置 0）
}

// Product 一个产品的文档库与索引配置（se7 / se8 / se9...）。
type Product struct {
	Name     string
	DocsDir  string
	IndexDir string
	Embedder Provider
	Reranker Provider
	// UseBuiltinKey=true → 用内置 key 并启用限流（并发≤1、单次≤2）
	UseBuiltinKey bool
}

type Config struct {
	Products []Product
}

func DefaultConfig() Config {
	return Config{Products: []Product{
		{
			Name:    "se7",
			DocsDir: "docs/se7",
			Embedder: Provider{
				Type: "siliconflow", Model: "BAAI/bge-m3",
				BaseURL: GatewayBaseURL, Dim: 1024,
			},
			Reranker: Provider{
				Type: "siliconflow", Model: "BAAI/bge-reranker-v2-m3",
				BaseURL: GatewayBaseURL,
			},
			UseBuiltinKey: true,
		},
	}}
}

func (p Provider) IsBuiltinKey() bool { return p.APIKey == "" }

func (p Provider) EffectiveKey() string {
	if p.APIKey != "" {
		return p.APIKey
	}
	return BuiltinKey()
}

// EffectiveBaseURL 依 key 归属决定上游地址：
// 内置 key → 默认网关（Worker，白名单两模型）；用户自备 key → 回落官方 SiliconFlow，直达不被网关替换。
func (p Provider) EffectiveBaseURL() string {
	if p.APIKey != "" {
		return officialSiliconflowBaseURL
	}
	return p.BaseURL
}

// EffectiveBaseURLs 依 key 归属决定上游地址有序列表（网关故障转移链）：
// 内置 key → [BaseURL（默认 CF Worker），FallbackBaseURL（默认阿里云 FC 网关）]，CF 不可达
// 时自动切换 FC；相同地址去重。用户自备 key → 官方 SiliconFlow 直达，不经网关、无故障转移项。
func (p Provider) EffectiveBaseURLs() []string {
	if p.APIKey != "" {
		return []string{officialSiliconflowBaseURL}
	}
	primary := p.BaseURL
	if primary == "" {
		primary = GatewayBaseURL
	}
	fallback := p.FallbackBaseURL
	if fallback == "" {
		fallback = GatewayFCBaseURL
	}
	if fallback == primary {
		return []string{primary}
	}
	return []string{primary, fallback}
}
