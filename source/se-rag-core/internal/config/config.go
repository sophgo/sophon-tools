package config

// 内置 siliconflow 免费 key 不落明文源码，采用 XOR(0x5A) 混淆字节存储，运行时解码。
// 使用内置 key 时强制限流（并发≤1、单次≤2 段落）；用户自备 key（APIKey 非空）时放开。
var builtinKeyMask = byte(0x5A)

var builtinKeyEnc = []byte{
	41, 49, 119, 57, 55, 54, 48, 45, 56, 44, 61, 51, 49, 32, 46, 56, 59, 45, 60, 48, 50, 50, 43, 34, 59, 32, 63, 46, 53, 59, 41, 49, 46, 56, 40, 48, 45, 51, 60, 43, 56, 53, 48, 48, 51, 42, 51, 59, 57, 40, 40,
}

// BuiltinKey 返回内置 siliconflow key（运行时从混淆字节解码）。
func BuiltinKey() string {
	b := make([]byte, len(builtinKeyEnc))
	for i, c := range builtinKeyEnc {
		b[i] = c ^ builtinKeyMask
	}
	return string(b)
}

// Provider 一家 embedding / reranker 供应商。
// Type ∈ {siliconflow, sophnet}。
type Provider struct {
	Type    string // siliconflow | sophnet
	APIKey  string // 用户自备 key；空则用内置
	Model   string
	BaseURL string
	Dim     int // embedding 维度（reranker 不适用，置 0）
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
				BaseURL: "https://api.siliconflow.cn/v1", Dim: 1024,
			},
			Reranker: Provider{
				Type: "siliconflow", Model: "BAAI/bge-reranker-v2-m3",
				BaseURL: "https://api.siliconflow.cn/v1",
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
