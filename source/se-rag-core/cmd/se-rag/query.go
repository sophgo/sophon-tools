package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/retriever"
)

func runQuery(rc runCtx) error {
	rc.ensureFactories()
	rc.applyFakeMode()
	if rc.product == "" {
		rc.product = metaProductLabel
	}
	if rc.query == "" {
		return fmt.Errorf("empty query")
	}

	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	p.Name = rc.product
	if !rc.useBuiltin {
		p.Embedder.APIKey = os.Getenv("SE_RAG_EMBED_KEY")
		p.Reranker.APIKey = os.Getenv("SE_RAG_RERANK_KEY")
	}
	emb, err := rc.embedF(p.Embedder)
	if err != nil {
		return fmt.Errorf("embedder init: %w", err)
	}
	var rr embed.Reranker
	if ret, rerr := rc.rerankF(p.Reranker); rerr == nil {
		rr = ret
	}

	r := &retriever.Retriever{Store: &docstore.Store{IndexDir: rc.indexDir}, Embedder: emb, Reranker: rr}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	out, err := r.Search(ctx, rc.query, rc.product, rc.topN)
	if err != nil {
		return err
	}
	fmt.Print(retriever.FormatMarkdown(out))
	return nil
}
