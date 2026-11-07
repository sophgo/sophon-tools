package main

import (
	"fmt"

	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/retriever"
)

// runDoctor 检查索引指纹 vs 当前配置（供应商/模型/维度完整比对），报告是否需要重建。
//
// 纯 BM25 索引（`build -offline` 产出，或旧索引 dim=0）不比对 embedding 指纹——
// 它本来就没有向量空间可比，报"需真实 embedding 指纹"只会误导。改为校验
// BM25 是否有内容，并输出检索模式与对应的重建命令。
func runDoctor(rc runCtx) (needRebuild bool, err error) {
	if rc.product == "" {
		rc.product = metaProductLabel
	}
	store := &docstore.Store{IndexDir: rc.indexDir}
	meta, err := store.ReadMeta(rc.product)
	if err != nil {
		return false, fmt.Errorf("read index at %s: %w", rc.indexDir, err)
	}
	mode := meta.EffectiveSearchMode()

	fmt.Printf("index  : %s\n", rc.indexDir)
	fmt.Printf("search mode  : %s\n", mode)
	fmt.Printf("index  fp    : %s\n", meta.Fingerprint())
	fmt.Printf("index  dim   : %d\n", meta.Dim)
	fmt.Printf("chunk count  : %d\n", meta.ChunkCount)

	if mode == docstore.SearchModeBM25 {
		fmt.Printf("current fp    : (none: bm25-only index has no embedding fingerprint)\n")
		if err := checkBM25Index(rc.indexDir, rc.product); err != nil {
			fmt.Printf("WARNING: %v\n", err)
			fmt.Printf("  -> 重新建索引: se-rag build -offline --docs-dir <docs> -index-dir %s\n", rc.indexDir)
			return true, nil
		}
		if meta.StrategyStale() {
			fmt.Printf("WARNING: index chunk strategy %q is older than current %q (FAQ docs are now split per Q&A)\n",
				meta.ChunkStrategy, chunker.StrategyVersion)
			fmt.Printf("  -> 重新建索引: se-rag build -offline --docs-dir <docs> -index-dir %s\n", rc.indexDir)
			return true, nil
		}
		if docsChanged(rc, meta, "se-rag build -offline") {
			return true, nil
		}
		fmt.Println("bm25 index OK: no rebuild needed (offline index, no embedding fingerprint to verify)")
		return false, nil
	}

	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	wantFp := docstore.FpFull(providerName(p.Embedder.Type), p.Embedder.Model, p.Embedder.Dim)
	fmt.Printf("current fp    : %s\n", wantFp)

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
	if docsChanged(rc, meta, "se-rag build") {
		return true, nil
	}
	fmt.Println("fingerprint OK: no rebuild needed")
	return false, nil
}

// docsChanged docs 内容绑定：显式传 --docs-dir 时才比对（不传则无从判断，跳过以免误报）。
// 混合索引与纯 BM25 索引同样适用；buildCmd 为对应模式的重建命令前缀。
func docsChanged(rc runCtx, meta *docstore.Meta, buildCmd string) bool {
	if rc.docsDir == "" {
		return false
	}
	wantHash := chunker.HashDocs(rc.docsDir, mustChunkMap(rc.docsDir))
	fmt.Printf("index  docs  : %s\n", shortHash(meta.DocsHash))
	fmt.Printf("current docs : %s\n", shortHash(wantHash))
	if !meta.DocsStale(wantHash) {
		return false
	}
	fmt.Printf("WARNING: index was built from different docs content (docs changed since last build)\n")
	fmt.Printf("  -> 重新建索引: %s --docs-dir %s -index-dir %s\n", buildCmd, rc.docsDir, rc.indexDir)
	return true
}

// checkBM25Index 纯 BM25 索引的健全性检查：BM25 有文档、chunks 非空。
// 空向量是合法的（离线索引本来就不存向量），但空 BM25 / 缺块等于没有可检索内容。
func checkBM25Index(indexDir, product string) error {
	loaded, err := (&docstore.Store{IndexDir: indexDir}).Open(product)
	if err != nil {
		return err
	}
	if loaded.BM25 == nil || loaded.BM25.DocCount() == 0 {
		return fmt.Errorf("bm25 index has no documents")
	}
	if len(loaded.Chunks) == 0 {
		return fmt.Errorf("index has no chunks")
	}
	if loaded.BM25.DocCount() != len(loaded.Chunks) {
		return fmt.Errorf("bm25 docs (%d) != chunks (%d): index is inconsistent",
			loaded.BM25.DocCount(), len(loaded.Chunks))
	}
	return nil
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
