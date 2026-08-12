package main

import (
	"fmt"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/retriever"
)

// runDoctor 检查索引指纹 vs 当前配置，报告是否需要重建。
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
	wantDim := p.Embedder.Dim

	fmt.Printf("index  : %s\n", rc.indexDir)
	fmt.Printf("index  fp    : %s\n", meta.Fingerprint())
	fmt.Printf("index  dim   : %d\n", meta.Dim)
	fmt.Printf("current dim  : %d\n", wantDim)
	fmt.Printf("chunk count  : %d\n", meta.ChunkCount)

	if err := retriever.CheckFingerprint(meta.Dim, wantDim); err != nil {
		fmt.Printf("WARNING: %v\n", err)
		fmt.Printf("  -> 重新建索引: se-rag build --docs-dir <docs> -index-dir %s\n", rc.indexDir)
		return true, nil
	}
	fmt.Println("fingerprint OK: no rebuild needed")
	return false, nil
}
