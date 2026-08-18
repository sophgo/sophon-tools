package retriever

import (
	"context"
	"strings"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/embed"
)

// 端到端故障转移链（CF Worker → FC 网关 → 纯 BM25）：
// 用真实 siliconflow embedder 指向两个连接即拒的网关地址，模拟双网关均不可达，
// 验证检索不 panic、有界失败后降级纯 BM25 并返回结果。
func TestSearchBM25FallbackBothGatewaysDown(t *testing.T) {
	s := buildTestStore(t)
	// 127.0.0.1:1 / :2 本机无服务监听，连接立即被拒（模拟 CF 与 FC 网关都不可达）
	p := config.Provider{
		Type:            "siliconflow",
		Model:           "BAAI/bge-m3",
		Dim:             1024,
		BaseURL:         "http://127.0.0.1:1/v1",
		FallbackBaseURL: "http://127.0.0.1:2/v1",
	}
	emb, err := embed.NewEmbedder(p)
	if err != nil {
		t.Fatal(err)
	}
	r := &Retriever{Store: s, Embedder: emb, Reranker: &fakeRerank{}}
	out, err := r.Search(context.Background(), "BM1684X 芯片", "se7", 8)
	if err != nil {
		t.Fatalf("search must not error when both gateways down, got %v", err)
	}
	if out.Mode != "bm25" {
		t.Errorf("mode=%s want bm25 fallback", out.Mode)
	}
	if len(out.Results) == 0 {
		t.Fatal("expected bm25 results when both gateways down")
	}
	if out.FallbackReason == "" {
		t.Error("expected fallback reason carrying gateway failure detail")
	}
	if !strings.Contains(out.FallbackReason, "gateway") {
		t.Errorf("fallback reason should mention gateway failure, got %q", out.FallbackReason)
	}
}