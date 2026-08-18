package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/vector"
)

// buildTimeout build 全量 embedding 的整体 deadline（query 单次为 120s；build 覆盖全部批次，取 5min）。
// 网关吞连接（Worker 失联）时保证 build 有限时退出，不无限挂起。
const buildTimeout = 5 * time.Minute

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

// applyUserKeys 按 -builtin-key 语义设置供应商 key：
// useBuiltin=true（默认）交给内置 key 逻辑；false 时 key 必须来自环境变量，
// 缺失即显式报错（不再静默回落内置 key + 限流）。SE_RAG_FAKE_EMBED=1 离线
// 模式不校验（fake provider 不真正使用 key）。requireRerank 仅 query 需要。
func applyUserKeys(p *config.Product, useBuiltin, requireRerank bool) error {
	if useBuiltin {
		return nil
	}
	p.Embedder.APIKey = os.Getenv("SE_RAG_EMBED_KEY")
	p.Reranker.APIKey = os.Getenv("SE_RAG_RERANK_KEY")
	if os.Getenv("SE_RAG_FAKE_EMBED") != "" {
		return nil
	}
	if p.Embedder.APIKey == "" {
		return fmt.Errorf("-builtin-key=false requires SE_RAG_EMBED_KEY (missing); set env or drop the flag")
	}
	if requireRerank && p.Reranker.APIKey == "" {
		return fmt.Errorf("-builtin-key=false requires SE_RAG_RERANK_KEY (missing); set env or drop the flag")
	}
	return nil
}

// realEmbed 真实 embedding 工厂（测试可注入 fake）。
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
	// 先校验 key 配置（-builtin-key=false 缺 env key 属配置错误，优先报出）
	cfg := config.DefaultConfig()
	p := cfg.Products[0]
	p.Name = rc.product
	if err := applyUserKeys(&p, rc.useBuiltin, false); err != nil {
		return err
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
	emb, err := rc.embedF(p.Embedder)
	if err != nil {
		return fmt.Errorf("embedder init: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), buildTimeout)
	defer cancel()
	vecs := make([][]float32, 0, len(docsText))
	vecIDs := make([]string, 0, len(docsText)) // 与 vecs 对齐的 chunkID（与 bm25/chunks 全量分开）
	const batch = 10
	var dim int
	skipped := 0
	for i := 0; i < len(docsText); i += batch {
		end := i + batch
		if end > len(docsText) {
			end = len(docsText)
		}
		ev, err := emb.Embed(ctx, docsText[i:end])
		if err != nil {
			return fmt.Errorf("embed batch [%d:%d]: %w", i, end, err)
		}
		if len(ev) != end-i {
			return fmt.Errorf("embed batch [%d:%d]: got %d vectors, want %d", i, end, len(ev), end-i)
		}
		for j := range ev {
			// 逐元素校验：nil/空向量 → 明确告警并跳过该 chunk 的向量（BM25 仍覆盖该 chunk）；
			// 维度与已确定的第一维不一致 → 系统性漂移，直接报错中止。
			v := ev[j]
			if v == nil || len(v) == 0 {
				fmt.Fprintf(os.Stderr, "WARNING: chunk %s returned empty embedding; vector skipped (BM25 fallback still covers it)\n", orders[i+j])
				skipped++
				continue
			}
			if dim == 0 {
				dim = len(v)
			} else if len(v) != dim {
				return fmt.Errorf("embedding dim mismatch: chunk %s has %d dims, expected %d", orders[i+j], len(v), dim)
			}
			vecs = append(vecs, vector.Normalize(v))
			vecIDs = append(vecIDs, orders[i+j])
		}
	}
	if len(vecs) == 0 {
		return fmt.Errorf("embedding returned no valid vectors (skipped %d chunks)", skipped)
	}
	if skipped > 0 {
		fmt.Printf("embedded: chunks=%d vectors=%d dim=%d (%d chunks skipped: empty embedding)\n",
			len(allChunks), len(vecs), dim, skipped)
	} else {
		fmt.Printf("embedded: chunks=%d vectors=%d dim=%d\n", len(allChunks), len(vecs), dim)
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
	if err := store.SaveIndex(rc.product, meta, vecs, vecIDs, bmi, allChunks); err != nil {
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
