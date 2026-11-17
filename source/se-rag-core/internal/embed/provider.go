package embed

import (
	"context"
	"fmt"

	"se-rag-core/internal/config"
)

// Embedder 向量化接口：返回每个文本的 embedding（原始，未归一化）。
type Embedder interface {
	Name() string
	Dim() int
	Embed(ctx context.Context, texts []string) ([][]float32, error)
}

// Reranker 精排接口：返回按相关度降序的 documents 下标。
type Reranker interface {
	Name() string
	Rerank(ctx context.Context, query string, docs []string, topN int) ([]int, error)
}

// NewEmbedder 按最终配置构造 embedder（默认网关策略）。
func NewEmbedder(cfg config.Provider) (Embedder, error) {
	return NewEmbedderWithGateway(cfg, config.DefaultConfig().Gateway)
}

// NewEmbedderWithGateway 按最终配置与网关策略构造 embedder。
//
// 网关策略（单次上限、总预算、明文兜底开关、两跳地址）只对内置 key 生效：
// 自备 key 是单地址直连，不套用单次上限、不做端口/明文降级，也不走故障转移。
func NewEmbedderWithGateway(cfg config.Provider, gw config.Gateway) (Embedder, error) {
	switch cfg.Type {
	case "siliconflow":
		return newSiliconflowEmbedder(cfg.EffectiveBaseURLs(gw), cfg.EffectiveKey(),
			cfg.Model, cfg.Dim, cfg.IsBuiltinKey(), gw)
	case "sophnet":
		return newSophnetEmbedder(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model, cfg.Dim)
	default:
		return nil, fmt.Errorf("unknown embedder type %q", cfg.Type)
	}
}

// NewReranker 按最终配置构造 reranker（默认网关策略）。
func NewReranker(cfg config.Provider) (Reranker, error) {
	return NewRerankerWithGateway(cfg, config.DefaultConfig().Gateway)
}

// NewRerankerWithGateway 按最终配置与网关策略构造 reranker。
func NewRerankerWithGateway(cfg config.Provider, gw config.Gateway) (Reranker, error) {
	switch cfg.Type {
	case "siliconflow":
		return newSiliconflowReranker(cfg.EffectiveBaseURLs(gw), cfg.EffectiveKey(), cfg.Model, gw)
	case "sophnet":
		return newSophnetReranker(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model)
	default:
		return nil, fmt.Errorf("unknown reranker type %q", cfg.Type)
	}
}
