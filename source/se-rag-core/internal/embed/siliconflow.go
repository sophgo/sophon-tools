package embed

import (
	"context"

	"se-rag-core/internal/config"
)

// siliconflowEmbedder：OpenAI 兼容 /embeddings 接口，内置 key 时对 Embed 整体限流。
// baseURLs 为有序网关地址列表（默认 CF → FC），请求按网关链故障转移，首个可用网关命中。
type siliconflowEmbedder struct {
	baseURLs []string
	apiKey   string
	model    string
	dim      int
	limiter  *EmbeddingLimiter
	gw       config.Gateway
	rec      gwRecorder
}

func newSiliconflowEmbedder(baseURLs []string, key, model string, dim int, useBuiltinKey bool, gw config.Gateway) (Embedder, error) {
	if len(baseURLs) == 0 || baseURLs[0] == "" {
		baseURLs = []string{"https://api.siliconflow.cn/v1"}
	}
	e := &siliconflowEmbedder{baseURLs: baseURLs, apiKey: key, model: model, dim: dim, gw: gw}
	if useBuiltinKey {
		e.limiter = NewEmbeddingLimiter(1) // 内置 key 并发仅 1
	}
	return e, nil
}

func (e *siliconflowEmbedder) Name() string { return "siliconflow." + e.model }
func (e *siliconflowEmbedder) Dim() int     { return e.dim }

// Gateway 返回最近一次实际服务本次进程的网关地址（可观测性：能看出当前走的是主网关还是备网关）。
func (e *siliconflowEmbedder) Gateway() string { return e.rec.LastGateway() }

type sfEmbedResp struct {
	Data []struct {
		Index     int       `json:"index"`
		Embedding []float32 `json:"embedding"`
	} `json:"data"`
}

func (e *siliconflowEmbedder) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	if e.limiter != nil {
		// 内置 key：把 texts 拆成 ≤perCall 一段的子批逐批调用，真正限制单次载荷≤perCall 段落
		return e.limiter.Embed(ctx, texts, func(batch []string) ([][]float32, error) {
			return e.embedBatch(ctx, batch)
		})
	}
	return e.embedBatch(ctx, texts)
}

func (e *siliconflowEmbedder) embedBatch(ctx context.Context, texts []string) ([][]float32, error) {
	payload := map[string]any{"model": e.model, "input": texts}
	var resp sfEmbedResp
	served, err := postJSONWithPolicy(ctx, joinPaths(e.baseURLs, "/embeddings"), e.apiKey, payload, &resp, e.gw)
	if err != nil {
		return nil, err
	}
	e.rec.set(served)
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
	return newSiliconflowEmbedder([]string{baseURL}, "test-key", "BAAI/bge-m3", 1024, false,
		config.DefaultConfig().Gateway)
}

// ---- siliconflow reranker ----

type siliconflowReranker struct {
	baseURLs []string
	apiKey   string
	model    string
	gw       config.Gateway
	rec      gwRecorder
}

func newSiliconflowReranker(baseURLs []string, key, model string, gw config.Gateway) (Reranker, error) {
	if len(baseURLs) == 0 || baseURLs[0] == "" {
		baseURLs = []string{"https://api.siliconflow.cn/v1"}
	}
	return &siliconflowReranker{baseURLs: baseURLs, apiKey: key, model: model, gw: gw}, nil
}

func (r *siliconflowReranker) Name() string { return "siliconflow." + r.model }

// Gateway 返回最近一次实际服务本次请求的网关地址。
func (r *siliconflowReranker) Gateway() string { return r.rec.LastGateway() }

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
	// 注：rerank 单次调用段数由调用方控制，内置 key 暂不作额外限流
	served, err := postJSONWithPolicy(ctx, joinPaths(r.baseURLs, "/rerank"), r.apiKey, payload, &resp, r.gw)
	if err != nil {
		return nil, err
	}
	r.rec.set(served)
	order := make([]int, 0, len(resp.Results))
	for _, rr := range resp.Results {
		order = append(order, rr.Index)
	}
	return order, nil
}
