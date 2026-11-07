package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/retriever"
)

// 多索引检索（路径模式）：`query -index-dir a -index-dir b,c`。
// 没有实体信息，因此不标注实体、路径保持原样；合并规则见 retriever.MultiRetriever。

// runQueryDirs 路径模式的多索引检索。
func runQueryDirs(base runCtx, dirs []string) error {
	if base.query == "" {
		return fmt.Errorf("empty query")
	}
	srcs := make([]retriever.Source, 0, len(dirs))
	for _, d := range dirs {
		srcs = append(srcs, retriever.Source{Store: &docstore.Store{IndexDir: d}, Product: base.product})
	}
	return runMultiSourceQuery(base, srcs)
}

// runMultiSourceQuery 多索引合并检索。
func runMultiSourceQuery(rc runCtx, srcs []retriever.Source) error {
	rc.ensureFactories()
	rc.applyFakeMode()

	m := &retriever.MultiRetriever{Sources: srcs}
	fallback := ""
	switch {
	case rc.offline:
		fallback = "offline mode (-offline)"
	case allBM25Only(srcs):
		fmt.Fprintf(os.Stderr, "note: all target indexes are bm25-only (built with -offline); query falls back to pure BM25, no text is sent out\n")
		fallback = "all indexes are bm25-only (built with build -offline)"
	default:
		cfg := config.DefaultConfig()
		p := cfg.Products[0]
		if err := applyUserKeys(&p, rc.useBuiltin, true); err != nil {
			return err
		}
		emb, err := rc.embedF(p.Embedder)
		if err != nil {
			return fmt.Errorf("embedder init: %w", err)
		}
		m.Embedder = emb
		if rr, rerr := rc.rerankF(p.Reranker); rerr == nil {
			m.Reranker = rr
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	out, err := m.Search(ctx, rc.query, rc.topN)
	if err != nil {
		return err
	}
	if fallback != "" {
		out.FallbackReason = fallback
	}
	fmt.Print(retriever.FormatMarkdown(out))
	return nil
}

// allBM25Only 目标索引是否全部为纯 BM25（离线建出的）索引；任一索引缺失时按"非 bm25"处理，
// 让 MultiRetriever 在 Open 阶段报出缺失错误。
func allBM25Only(srcs []retriever.Source) bool {
	for _, s := range srcs {
		meta, err := s.Store.ReadMeta(s.Product)
		if err != nil || !meta.BM25Only() {
			return false
		}
	}
	return true
}
