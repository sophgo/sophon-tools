package main

import (
	"context"
	"errors"
	"fmt"
	"os"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/vector"
)

// runCtx 供 build/query/doctor 共享的参数 + 可注入的 provider 工厂（测试/离线 fake）。
// build 始终依据 docs 全量重建索引（docs 是唯一真源），无需 force 开关。
type runCtx struct {
	docsDir    string
	indexDir   string
	product    string
	topN       int
	query      string
	useBuiltin bool
	embedF     func(config.Provider) (embed.Embedder, error)
	rerankF    func(config.Provider) (embed.Reranker, error)
}

func realEmbed(p config.Provider) (embed.Embedder, error)  { return embed.NewEmbedder(p) }
func realRerank(p config.Provider) (embed.Reranker, error) { return embed.NewReranker(p) }

// buildCtx 默认工厂（未注入时）
func (rc *runCtx) ensureFactories() {
	if rc.embedF == nil {
		rc.embedF = realEmbed
	}
	if rc.rerankF == nil {
		rc.rerankF = realRerank
	}
}

// applyFakeMode 供离线端到端（SE_RAG_FAKE_EMBED=1）。
func (rc *runCtx) applyFakeMode() {
	if os.Getenv("SE_RAG_FAKE_EMBED") == "" {
		return
	}
	rc.embedF = func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil }
	rc.rerankF = func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil }
}

func runBuild(rc runCtx) error {
	rc.ensureFactories()
	rc.applyFakeMode()
	// product 仅作 meta 标签，不参与路径（不同知识库用不同 index-dir/docs-dir）
	if rc.product == "" {
		rc.product = metaProductLabel
	}
	if rc.docsDir == "" {
		return fmt.Errorf("docs-dir is empty")
	}
	if rc.indexDir == "" {
		return fmt.Errorf("index-dir is empty")
	}

	ch := chunker.NewDefaultChunker()
	chunkMap, err := ch.ChunkDirectory(rc.docsDir)
	if err != nil {
		return fmt.Errorf("chunk docs: %w", err)
	}
	var allChunks []chunker.Chunk
	var orders []string
	var docsText []string
	for _, file := range sortedKeys(chunkMap) {
		for _, c := range chunkMap[file] {
			allChunks = append(allChunks, c)
			orders = append(orders, c.ChunkID)
			docsText = append(docsText, c.Text)
		}
	}
	if len(allChunks) == 0 {
		return fmt.Errorf("no chunks from %s", rc.docsDir)
	}

	// embed
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

	ctx := context.Background()
	vecs := make([][]float32, 0, len(docsText))
	const batch = 10
	for i := 0; i < len(docsText); i += batch {
		end := i + batch
		if end > len(docsText) {
			end = len(docsText)
		}
		ev, err := emb.Embed(ctx, docsText[i:end])
		if err != nil {
			return fmt.Errorf("embed batch [%d:%d]: %w", i, end, err)
		}
		for j := range ev {
			vecs = append(vecs, vector.Normalize(ev[j]))
		}
	}
	if len(vecs) == 0 || vecs[0] == nil {
		return fmt.Errorf("embedding returned empty vectors")
	}
	dim := len(vecs[0])
	if dim == 0 {
		return errors.New("embedding returned 0-dim vectors")
	}

	// BM25
	bmi := bm25.Build(docsText, orders)

	// 指纹 + 落盘
	meta := docstore.Meta{
		Product:             rc.product,
		EmbedderFingerprint: docstore.FpName(providerName(p.Embedder.Type), p.Embedder.Model),
		Dim:                 dim,
		Model:               p.Embedder.Model,
		ChunkCount:          len(allChunks),
		BuildVersion:        "1.0",
	}
	store := &docstore.Store{IndexDir: rc.indexDir}
	if err := store.SaveIndex(rc.product, meta, vecs, orders, bmi, allChunks); err != nil {
		return err
	}
	fmt.Printf("index saved: label=%s chunks=%d dim=%d embed=%s -> %s\n",
		rc.product, len(allChunks), dim, emb.Name(), store.IndexPath())
	return nil
}

func providerName(t string) string {
	if t == "" {
		return "unknown"
	}
	return t
}

func sortedKeys(m map[string][]chunker.Chunk) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	// 插入排序（避免额外 import sort 之外的复杂度；小规模）
	for i := 1; i < len(keys); i++ {
		for j := i; j > 0 && keys[j] < keys[j-1]; j-- {
			keys[j], keys[j-1] = keys[j-1], keys[j]
		}
	}
	return keys
}
