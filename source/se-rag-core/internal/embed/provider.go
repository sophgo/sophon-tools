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

// NewEmbedder 按配置构造 embedder。
func NewEmbedder(cfg config.Provider) (Embedder, error) {
	switch cfg.Type {
	case "siliconflow":
		return newSiliconflowEmbedder(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model, cfg.Dim, cfg.IsBuiltinKey())
	case "sophnet":
		return newSophnetEmbedder(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model, cfg.Dim)
	default:
		return nil, fmt.Errorf("unknown embedder type %q", cfg.Type)
	}
}

// NewReranker 按配置构造 reranker。
func NewReranker(cfg config.Provider) (Reranker, error) {
	switch cfg.Type {
	case "siliconflow":
		return newSiliconflowReranker(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model, cfg.IsBuiltinKey())
	case "sophnet":
		return newSophnetReranker(cfg.BaseURL, cfg.EffectiveKey(), cfg.Model)
	default:
		return nil, fmt.Errorf("unknown reranker type %q", cfg.Type)
	}
}
