package main

import (
	"fmt"
	"os"

	"se-rag-core/internal/config"
	"se-rag-core/internal/embed"
)

// builtinKeyMode -builtin-key 的三种取值。
//
// 关键区别：默认（未写该 flag）与显式 true 语义不同。
//   - 默认：按最终配置自动判断——配了自备 key 就用自备，否则用内置；
//   - 显式 true：强制内置 key 及其内置模型/地址（仍保留网关链覆盖）；
//   - 显式 false：要求所需 provider 必须自备 key（build 只要 embed，query 还要 rerank）。
//
// 用 flag.Visit 区分「默认」与「显式」，不能只看 bool 值——默认值与显式 true 的
// 值相同，只凭值无法分辨。
type builtinKeyMode int

const (
	keyModeAuto builtinKeyMode = iota
	keyModeForceBuiltin
	keyModeRequireUser
)

func (m builtinKeyMode) String() string {
	switch m {
	case keyModeForceBuiltin:
		return "builtin"
	case keyModeRequireUser:
		return "user"
	default:
		return "auto"
	}
}

// builtinKeyModeFromFlag 由 flag 值 + 是否显式传入推导模式。
func builtinKeyModeFromFlag(value, explicitlySet bool) builtinKeyMode {
	if !explicitlySet {
		return keyModeAuto
	}
	if value {
		return keyModeForceBuiltin
	}
	return keyModeRequireUser
}

// resolveProviders 依 -builtin-key 模式与最终配置决定 embed/rerank 两个 provider 的实际取值。
//
// requireRerank：build 只需要 embed（rerank key 缺失不算错），query 需要 rerank。
// fakeMode（SE_RAG_FAKE_EMBED）：离线假 provider 不真正使用 key，跳过缺失校验。
//
// 显式 -builtin-key=true 时模型与维度回到内置值：内置 key 只被网关白名单放行那两个模型，
// 配上别的模型名只会拿到 403。网关地址覆盖仍然生效——那是链路问题，不是模型问题。
func resolveProviders(cfg config.Config, mode builtinKeyMode, requireRerank, fakeMode bool) (config.Product, error) {
	p := cfg.Products[0]
	switch mode {
	case keyModeForceBuiltin:
		p.Embedder.APIKey = ""
		p.Embedder.Model = config.BuiltinEmbeddingModel
		p.Embedder.Dim = config.BuiltinEmbeddingDim
		p.Reranker.APIKey = ""
		p.Reranker.Model = config.BuiltinRerankModel
		return p, nil
	case keyModeRequireUser:
		if fakeMode {
			return p, nil
		}
		if p.Embedder.APIKey == "" {
			return p, fmt.Errorf("%s requires a user key for the embedder (missing); "+
				"set OPENAI_API_KEY / SE_RAG_EMBED_KEY, provide api_key in the config file, or drop the flag", flagNameBuiltinKey)
		}
		if requireRerank && p.Reranker.APIKey == "" {
			return p, fmt.Errorf("%s requires a user key for the reranker (missing); "+
				"set OPENAI_API_KEY / SE_RAG_RERANK_KEY, provide api_key in the config file, or drop the flag", flagNameBuiltinKey)
		}
		return p, nil
	default: // keyModeAuto：按最终配置自动选择，无需额外旗标
		return p, nil
	}
}

// flagNameBuiltinKey flag 名（错误信息里引用，避免多处硬编码字符串不一致）。
const flagNameBuiltinKey = "-builtin-key=false"

// loadOnlineConfig 读取最终配置（在线命令用）。
//
// 只由在线路径（build / query / doctor）调用，且必须在发请求前完成——配置错误要在
// 联网之前报出来。offline / help / list / resolve 不依赖在线配置的有效性，
// 因此完全不调用它，损坏的配置文件不会让这些命令失败。
func loadOnlineConfig() (config.Config, error) {
	cfg, err := config.Load()
	if err != nil {
		return config.Config{}, fmt.Errorf("config: %w", err)
	}
	return cfg, nil
}

// embedFactory / rerankFactory 把网关策略带进 provider 构造。
func makeEmbedderFactory(gw config.Gateway) func(config.Provider) (embed.Embedder, error) {
	return func(p config.Provider) (embed.Embedder, error) {
		return embed.NewEmbedderWithGateway(p, gw)
	}
}

func makeRerankerFactory(gw config.Gateway) func(config.Provider) (embed.Reranker, error) {
	return func(p config.Provider) (embed.Reranker, error) {
		return embed.NewRerankerWithGateway(p, gw)
	}
}

// isFakeMode SE_RAG_FAKE_EMBED 是否开启（离线假 embedding，测试/离线验证用）。
func isFakeMode() bool { return os.Getenv("SE_RAG_FAKE_EMBED") != "" }
