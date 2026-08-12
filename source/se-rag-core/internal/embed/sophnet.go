package embed

import (
	"context"
	"fmt"
)

// sophnetEmbedder：sophnet OpenAPI 格式（对齐 Python faiss_index.py）。
type sophnetEmbedder struct {
	baseURL string
	apiKey  string
	model   string
	dim     int
}

func newSophnetEmbedder(baseURL, key, model string, dim int) (Embedder, error) {
	if baseURL == "" {
		baseURL = "https://www.sophnet.com/api"
	}
	return &sophnetEmbedder{baseURL: baseURL, apiKey: key, model: model, dim: dim}, nil
}

func (e *sophnetEmbedder) Name() string { return "sophnet." + e.model }
func (e *sophnetEmbedder) Dim() int     { return e.dim }

type snEmbedResp struct {
	Data []struct {
		Index     int       `json:"index"`
		Embedding []float32 `json:"embedding"`
	} `json:"data"`
}

func (e *sophnetEmbedder) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	payload := map[string]any{"model": e.model, "input_texts": texts, "dimensions": e.dim}
	url := e.baseURL + "/open-apis/projects/easyllms/embeddings"
	var resp snEmbedResp
	if err := postJSON(ctx, url, e.apiKey, payload, &resp); err != nil {
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

type sophnetReranker struct {
	baseURL string
	apiKey  string
	model   string
}

func newSophnetReranker(baseURL, key, model string) (Reranker, error) {
	if baseURL == "" {
		baseURL = "https://www.sophnet.com/api"
	}
	return &sophnetReranker{baseURL: baseURL, apiKey: key, model: model}, nil
}

func (r *sophnetReranker) Name() string { return "sophnet." + r.model }

type snRerankResp struct {
	Status int `json:"status"`
	Result []struct {
		Index int     `json:"index"`
		Score float32 `json:"score"`
	} `json:"result"`
}

func (r *sophnetReranker) Rerank(ctx context.Context, query string, docs []string, topN int) ([]int, error) {
	if len(docs) == 0 {
		return nil, nil
	}
	if topN <= 0 {
		topN = len(docs)
	}
	payload := map[string]any{"model": r.model, "query": query, "documents": docs, "top_n": topN}
	url := r.baseURL + "/open-apis/projects/rerank"
	var resp snRerankResp
	if err := postJSON(ctx, url, r.apiKey, payload, &resp); err != nil {
		return nil, err
	}
	if resp.Status != 0 {
		return nil, fmt.Errorf("sophnet rerank status=%d", resp.Status)
	}
	order := make([]int, 0, len(resp.Result))
	for _, rr := range resp.Result {
		order = append(order, rr.Index)
	}
	return order, nil
}
