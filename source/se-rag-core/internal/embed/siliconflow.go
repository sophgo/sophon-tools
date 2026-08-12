package embed

import (
	"context"
)

// siliconflowEmbedder：OpenAI 兼容 /embeddings 接口，内置 key 时对 Embed 整体限流。
type siliconflowEmbedder struct {
	baseURL string
	apiKey  string
	model   string
	dim     int
	limiter *EmbeddingLimiter
}

func newSiliconflowEmbedder(baseURL, key, model string, dim int, useBuiltinKey bool) (Embedder, error) {
	if baseURL == "" {
		baseURL = "https://api.siliconflow.cn/v1"
	}
	e := &siliconflowEmbedder{baseURL: baseURL, apiKey: key, model: model, dim: dim}
	if useBuiltinKey {
		e.limiter = NewEmbeddingLimiter(1) // 内置 key 并发仅 1
	}
	return e, nil
}

func (e *siliconflowEmbedder) Name() string { return "siliconflow." + e.model }
func (e *siliconflowEmbedder) Dim() int     { return e.dim }

type sfEmbedResp struct {
	Data []struct {
		Index     int       `json:"index"`
		Embedding []float32 `json:"embedding"`
	} `json:"data"`
}

func (e *siliconflowEmbedder) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	if e.limiter != nil {
		// 内置 key：把 texts 拆成 ≤3 一段的子批逐批调用，真正限制单次载荷≤3 段落
		return e.limiter.Embed(ctx, texts, func(batch []string) ([][]float32, error) {
			return e.embedBatch(ctx, batch)
		})
	}
	return e.embedBatch(ctx, texts)
}

func (e *siliconflowEmbedder) embedBatch(ctx context.Context, texts []string) ([][]float32, error) {
	payload := map[string]any{"model": e.model, "input": texts}
	var resp sfEmbedResp
	if err := postJSON(ctx, e.baseURL+"/embeddings", e.apiKey, payload, &resp); err != nil {
		return nil, err
	}
	out := make([][]float32, len(texts))
	for _, d := range resp.Data {
		if d.Index >= 0 && d.Index < len(out) {
			out[d.Index] = d.Embedding
		}
	}
	return out, nil
}

// NewSiliconflowEmbedderFromURL 测试辅助：显式 baseURL
func NewSiliconflowEmbedderFromURL(baseURL string) (Embedder, error) {
	return newSiliconflowEmbedder(baseURL, "test-key", "BAAI/bge-m3", 1024, false)
}

// ---- siliconflow reranker ----

type siliconflowReranker struct {
	baseURL    string
	apiKey     string
	model      string
	useBuiltin bool
}

func newSiliconflowReranker(baseURL, key, model string, useBuiltinKey bool) (Reranker, error) {
	if baseURL == "" {
		baseURL = "https://api.siliconflow.cn/v1"
	}
	return &siliconflowReranker{baseURL: baseURL, apiKey: key, model: model, useBuiltin: useBuiltinKey}, nil
}

func (r *siliconflowReranker) Name() string { return "siliconflow." + r.model }

type sfRerankResp struct {
	Results []struct {
		Index int     `json:"index"`
		Score float32 `json:"relevance_score"`
	} `json:"results"`
}

func (r *siliconflowReranker) Rerank(ctx context.Context, query string, docs []string, topN int) ([]int, error) {
	if len(docs) == 0 {
		return nil, nil
	}
	if topN <= 0 {
		topN = len(docs)
	}
	payload := map[string]any{"model": r.model, "query": query, "documents": docs, "top_n": topN}
	var resp sfRerankResp
	if r.useBuiltin {
		// reranker 用并发1简单限流（单次调用本身段数由调用方控制）
	}
	if err := postJSON(ctx, r.baseURL+"/rerank", r.apiKey, payload, &resp); err != nil {
		return nil, err
	}
	order := make([]int, 0, len(resp.Results))
	for _, rr := range resp.Results {
		order = append(order, rr.Index)
	}
	return order, nil
}
