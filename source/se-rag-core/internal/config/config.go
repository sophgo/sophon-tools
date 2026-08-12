package config

// BuiltinSiliconflowKey 预制 siliconflow 免费 key（需求指定）。
// 使用它时必须限流：并发≤2、单次≤3段落；用户自备 key（APIKey 非空）时放开。
const BuiltinSiliconflowKey = "sk-cmljwbvgikztbawfjhhqxazetoasktbrjwifqbojjipiacrr"

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
	// UseBuiltinKey=true → 用内置 key 并启用限流（并发≤2、单次≤3）
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
	return BuiltinSiliconflowKey
}
