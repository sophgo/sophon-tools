package main

import (
	"fmt"

	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/retriever"
)

// runDoctor 检查索引指纹 vs 当前配置（供应商/模型/维度完整比对），报告是否需要重建。
func runDoctor(rc runCtx) (needRebuild bool, err error) {
	if rc.product == "" {
		rc.product = metaProductLabel
	}
	store := &docstore.Store{IndexDir: rc.indexDir}
	meta, err := store.ReadMeta(rc.product)
	if err != nil {
		return false, fmt.Errorf("read index at %s: %w", rc.indexDir, err)
	}
	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	wantFp := docstore.FpFull(providerName(p.Embedder.Type), p.Embedder.Model, p.Embedder.Dim)

	fmt.Printf("index  : %s\n", rc.indexDir)
	fmt.Printf("index  fp    : %s\n", meta.Fingerprint())
	fmt.Printf("index  dim   : %d\n", meta.Dim)
	fmt.Printf("current fp    : %s\n", wantFp)
	fmt.Printf("chunk count  : %d\n", meta.ChunkCount)

	if err := retriever.CheckFingerprint(meta.Fingerprint(), wantFp); err != nil {
		fmt.Printf("WARNING: %v\n", err)
		fmt.Printf("  -> 重新建索引: se-rag build --docs-dir <docs> -index-dir %s\n", rc.indexDir)
		return true, nil
	}
	if meta.StrategyStale() {
		fmt.Printf("WARNING: index chunk strategy %q is older than current %q (FAQ docs are now split per Q&A)\n",
			meta.ChunkStrategy, chunker.StrategyVersion)
		fmt.Printf("  -> 重新建索引: se-rag build --docs-dir <docs> -index-dir %s\n", rc.indexDir)
		return true, nil
	}
	// docs 内容绑定：显式传 --docs-dir 时才比对（不传则无从判断，跳过以免误报）。
	if rc.docsDir != "" {
		wantHash := chunker.HashDocs(rc.docsDir, mustChunkMap(rc.docsDir))
		fmt.Printf("index  docs  : %s\n", shortHash(meta.DocsHash))
		fmt.Printf("current docs : %s\n", shortHash(wantHash))
		if meta.DocsStale(wantHash) {
			fmt.Printf("WARNING: index was built from different docs content (docs changed since last build)\n")
			fmt.Printf("  -> 重新建索引: se-rag build --docs-dir %s -index-dir %s\n", rc.docsDir, rc.indexDir)
			return true, nil
		}
	}
	fmt.Println("fingerprint OK: no rebuild needed")
	return false, nil
}

// mustChunkMap 计算 docs 的 chunkMap 以对齐 HashDocs 的文件集；失败时返回空 map
// （空 map 会产出一个与任何正常指纹都不相等的值，因而表现为「需要重建」）。
func mustChunkMap(docsDir string) map[string][]chunker.Chunk {
	m, err := chunker.NewDefaultChunker().ChunkDirectory(docsDir)
	if err != nil {
		fmt.Printf("WARNING: cannot read docs dir %s: %v\n", docsDir, err)
		return map[string][]chunker.Chunk{}
	}
	return m
}

// shortHash 展示用短指纹（空值显式标注，便于识别旧索引）。
func shortHash(h string) string {
	if h == "" {
		return "(none: legacy index)"
	}
	if len(h) > 12 {
		return h[:12]
	}
	return h
}
