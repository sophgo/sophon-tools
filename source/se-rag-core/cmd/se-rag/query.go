package main

import (
	"context"
	"fmt"
	"os"

	"time"

	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/retriever"
)

// warnStaleIndex 索引落后（分块策略或 docs 内容）时向 stderr 提示重建（不影响查询结果输出）。
// docsDir 为空时只比对分块策略——调用方没给 docs 就无从判断内容是否漂移。
func warnStaleIndex(indexDir, product, docsDir string) {
	meta, err := (&docstore.Store{IndexDir: indexDir}).ReadMeta(product)
	if err != nil {
		return
	}
	if meta.StrategyStale() {
		fmt.Fprintf(os.Stderr, "warning: index chunk strategy %q is older than current %q; rebuild recommended: se-rag build --docs-dir <docs> -index-dir %s\n",
			meta.ChunkStrategy, chunker.StrategyVersion, indexDir)
		return
	}
	if docsDir == "" {
		return
	}
	chunkMap, err := chunker.NewDefaultChunker().ChunkDirectory(docsDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: cannot read docs dir %q: %v\n", docsDir, err)
		return
	}
	if want := chunker.HashDocs(docsDir, chunkMap); meta.DocsStale(want) {
		fmt.Fprintf(os.Stderr, "warning: index was built from different docs content; rebuild recommended: se-rag build --docs-dir %s -index-dir %s\n",
			docsDir, indexDir)
	}
}

func runQuery(rc runCtx) error {
	rc.ensureFactories()
	rc.applyFakeMode()
	if rc.product == "" {
		rc.product = metaProductLabel
	}
	warnStaleIndex(rc.indexDir, rc.product, rc.docsDir)
	if rc.offline {
		return runQueryOffline(rc)
	}
	// 先校验 key 配置（-builtin-key=false 缺 env key 属配置错误，优先报出）
	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	p.Name = rc.product
	if err := applyUserKeys(&p, rc.useBuiltin, true); err != nil {
		return err
	}
	if rc.query == "" {
		return fmt.Errorf("empty query")
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

// runQueryOffline 纯 BM25 检索：不构造 embedder / reranker，不发起任何网络请求，
// 因此也不校验 key。输出末行 mode=bm25，fallback 原因标明是主动离线。
// 索引过期提示由调用方 runQuery 统一发出，此处不再重复。
func runQueryOffline(rc runCtx) error {
	if rc.query == "" {
		return fmt.Errorf("empty query")
	}
	r := &retriever.Retriever{Store: &docstore.Store{IndexDir: rc.indexDir}}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	out, err := r.Search(ctx, rc.query, rc.product, rc.topN)
	if err != nil {
		return err
	}
	out.FallbackReason = "offline mode (-offline)"
	fmt.Print(retriever.FormatMarkdown(out))
	return nil
}
