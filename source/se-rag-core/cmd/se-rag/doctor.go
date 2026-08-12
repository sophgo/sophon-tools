package main

import (
	"fmt"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/retriever"
)

// runDoctor 检查产品索引指纹 vs 当前配置，报告是否需要重建。
func runDoctor(rc runCtx) (needRebuild bool, err error) {
	if rc.product == "" {
		rc.product = "se7"
	}
	store := &docstore.Store{IndexDir: rc.indexDir}
	meta, err := store.ReadMeta(rc.product)
	if err != nil {
		return false, fmt.Errorf("read index for %s: %w", rc.product, err)
	}
	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	wantDim := p.Embedder.Dim

	fmt.Printf("product      : %s\n", rc.product)
	fmt.Printf("index  fp    : %s\n", meta.Fingerprint())
	fmt.Printf("index  dim   : %d\n", meta.Dim)
	fmt.Printf("current dim  : %d\n", wantDim)
	fmt.Printf("chunk count  : %d\n", meta.ChunkCount)

	if err := retriever.CheckFingerprint(meta.Dim, wantDim); err != nil {
		fmt.Printf("WARNING: %v\n", err)
		fmt.Printf("  -> run: se-rag build -product %s --docs-dir <docs> -index-dir %s --force\n",
			rc.product, rc.indexDir)
		return true, nil
	}
	fmt.Println("fingerprint OK: no rebuild needed")
	return false, nil
}
