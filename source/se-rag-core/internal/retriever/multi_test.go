package retriever

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
)

// countingReranker 记录调用次数，用来验证「多索引只 rerank 一次」。
type countingReranker struct {
	calls int
	// reverse=true 时把候选顺序倒过来，便于验证结果确实按 rerank 的顺序输出。
	reverse bool
	err     error
}

func (c *countingReranker) Name() string { return "counting" }
func (c *countingReranker) Rerank(_ context.Context, _ string, docs []string, topN int) ([]int, error) {
	c.calls++
	if c.err != nil {
		return nil, c.err
	}
	if topN > len(docs) {
		topN = len(docs)
	}
	perm := make([]int, 0, topN)
	if c.reverse {
		for i := len(docs) - 1; i >= 0 && len(perm) < topN; i-- {
			perm = append(perm, i)
		}
		return perm, nil
	}
	for i := 0; i < topN; i++ {
		perm = append(perm, i)
	}
	return perm, nil
}

// vectorEmbedder 查询向量固定为 {1,0}，让夹具索引里的向量可预期地排序。
type vectorEmbedder struct{ calls int }

func (v *vectorEmbedder) Name() string { return "vec" }
func (v *vectorEmbedder) Dim() int     { return 2 }
func (v *vectorEmbedder) Embed(_ context.Context, _ []string) ([][]float32, error) {
	v.calls++
	return [][]float32{{1, 0}}, nil
}

// sourceFixture 一个夹具索引：chunks 与向量一一对应（可为 nil 表示离线索引）。
type sourceFixture struct {
	label  string
	chunks []chunker.Chunk
	vecs   [][]float32
	// pathPrefix 非 nil 时模拟注册表模式（路径改写为相对技能根）。
	pathPrefix func(string) string
}

// writeSource 按夹具落一个索引目录，返回 Source。
func writeSource(t *testing.T, dir string, f sourceFixture) Source {
	t.Helper()
	store := &docstore.Store{IndexDir: dir}
	ids := make([]string, len(f.chunks))
	texts := make([]string, len(f.chunks))
	for i, c := range f.chunks {
		ids[i] = c.ChunkID
		texts[i] = c.Text
	}
	vecDim := 0
	if len(f.vecs) > 0 {
		vecDim = len(f.vecs[0])
	}
	meta := docstore.Meta{
		Product:       f.label,
		Dim:           vecDim,
		ChunkCount:    len(f.chunks),
		BuildVersion:  "1.0",
		ChunkStrategy: chunker.StrategyVersion,
	}
	if vecDim == 0 {
		meta.EmbedderFingerprint = docstore.FpBM25Only
		meta.SearchMode = docstore.SearchModeBM25
	} else {
		meta.EmbedderFingerprint = docstore.FpName("fake", "em")
		meta.SearchMode = docstore.SearchModeHybrid
	}
	bmi := bm25.Build(texts, ids)
	if err := store.SaveIndex(f.label, meta, f.vecs, ids, bmi, f.chunks); err != nil {
		t.Fatal(err)
	}
	return Source{Label: f.label, Store: store, Product: f.label, PathPrefix: f.pathPrefix}
}

func chunk(id, text, file string) chunker.Chunk {
	return chunker.Chunk{ChunkID: id, Text: text, SourceFile: file, LineStart: 1, LineEnd: 2}
}

// 两个在线索引：候选按各索引排名轮转合并（A1 B1 A2 B2 …），rerank 只调用一次。
func TestMultiSearchRoundRobinAndSingleRerank(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label: "se9",
		chunks: []chunker.Chunk{
			chunk("a1", "I2C 总线 配置 排针", "a1.md"),
			chunk("a2", "网络 bond 配置", "a2.md"),
			chunk("a3", "OTA 升级 镜像", "a3.md"),
		},
		vecs: [][]float32{{1, 0}, {1, 0}, {0, 1}},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label: "bm1688",
		chunks: []chunker.Chunk{
			chunk("b1", "tpu-mlir 编译 模型", "b1.md"),
			chunk("b2", "VPP 缩放 接口", "b2.md"),
			chunk("b3", "PCIe 带宽", "b3.md"),
		},
		vecs: [][]float32{{1, 0}, {1, 0}, {0, 1}},
	})

	rr := &countingReranker{}
	m := &MultiRetriever{Sources: []Source{a, b}, Embedder: &vectorEmbedder{}, Reranker: rr}
	out, err := m.Search(context.Background(), "I2C 配置", 4)
	if err != nil {
		t.Fatal(err)
	}
	if rr.calls != 1 {
		t.Errorf("reranker called %d times, want exactly 1 (single rerank over merged candidates)", rr.calls)
	}
	if out.Mode != "hybrid" {
		t.Errorf("mode = %q, want hybrid", out.Mode)
	}
	// 轮转顺序：a 的第 1 名、b 的第 1 名、a 的第 2 名、b 的第 2 名
	var gotLabels []string
	for _, r := range out.Results[:min(4, len(out.Results))] {
		gotLabels = append(gotLabels, r.Entity)
	}
	wantLabels := []string{"se9", "bm1688", "se9", "bm1688"}
	if !reflect.DeepEqual(gotLabels, wantLabels) {
		t.Errorf("result entity order = %v, want %v (round robin across indexes)", gotLabels, wantLabels)
	}
	// 每条结果都带实体标注
	for i, r := range out.Results {
		if r.Entity == "" {
			t.Errorf("result %d has no entity label: %+v", i, r)
		}
	}
}

// rerank 的顺序必须真正生效（而不是只验证调用次数）。
func TestMultiSearchHonorsRerankOrder(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md"), chunk("a2", "I2C 时序", "a2.md")},
		vecs:   [][]float32{{1, 0}, {1, 0}},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label:  "bm1688",
		chunks: []chunker.Chunk{chunk("b1", "I2C 控制器", "b1.md")},
		vecs:   [][]float32{{1, 0}},
	})
	m := &MultiRetriever{Sources: []Source{a, b}, Embedder: &vectorEmbedder{}, Reranker: &countingReranker{reverse: true}}
	out, err := m.Search(context.Background(), "I2C", 3)
	if err != nil {
		t.Fatal(err)
	}
	// 候选轮转顺序是 a1 b1 a2；倒序 rerank 后应当是 a2 b1 a1
	if len(out.Results) != 3 {
		t.Fatalf("got %d results, want 3", len(out.Results))
	}
	if out.Results[0].ChunkID != "a2" || out.Results[1].ChunkID != "b1" || out.Results[2].ChunkID != "a1" {
		t.Errorf("result order = %v, want [a2 b1 a1] (reversed rerank order)",
			[]string{out.Results[0].ChunkID, out.Results[1].ChunkID, out.Results[2].ChunkID})
	}
}

// rerank 失败：退化为按各索引内排名的 RRF 合并（不抛错、不重复调用）。
func TestMultiSearchRerankFailureFallsBackToRRF(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md")},
		vecs:   [][]float32{{1, 0}},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label:  "bm1688",
		chunks: []chunker.Chunk{chunk("b1", "I2C 控制器", "b1.md")},
		vecs:   [][]float32{{1, 0}},
	})
	rr := &countingReranker{err: errors.New("boom")}
	m := &MultiRetriever{Sources: []Source{a, b}, Embedder: &vectorEmbedder{}, Reranker: rr}
	out, err := m.Search(context.Background(), "I2C", 5)
	if err != nil {
		t.Fatalf("rerank failure must not fail the query, got %v", err)
	}
	if n := len(out.Results); n == 0 {
		t.Fatal("expected RRF-merged results after rerank failure")
	}
	// 向量检索已经做过，只是没精排：mode 仍是 hybrid，fallback 说明改用 RRF 合并。
	if out.Mode != "hybrid" {
		t.Errorf("mode = %q, want hybrid (vectors were used, only rerank failed)", out.Mode)
	}
	if !strings.Contains(out.FallbackReason, "rerank failed") {
		t.Errorf("fallback reason = %q, want it to explain the rerank failure", out.FallbackReason)
	}
}

// 离线多索引：按各索引内排名做 RRF(k=60) 合并，完全不碰 embedder。
func TestMultiSearchOfflineRRFMerge(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label: "se9",
		chunks: []chunker.Chunk{
			chunk("a1", "I2C 总线 配置", "a1.md"),
			chunk("a2", "网络 bond", "a2.md"),
		},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label: "bm1688",
		chunks: []chunker.Chunk{
			chunk("b1", "I2C 控制器 时序", "b1.md"),
		},
	})
	emb := &vectorEmbedder{}
	m := &MultiRetriever{Sources: []Source{a, b}, Embedder: emb}
	out, err := m.Search(context.Background(), "I2C", 5)
	if err != nil {
		t.Fatal(err)
	}
	if emb.calls != 0 {
		t.Errorf("embedder called %d times on bm25-only indexes, want 0", emb.calls)
	}
	if out.Mode != "bm25" {
		t.Errorf("mode = %q, want bm25", out.Mode)
	}
	if !strings.Contains(out.FallbackReason, "bm25-only") {
		t.Errorf("fallback reason = %q, want it to explain bm25-only indexes", out.FallbackReason)
	}
	// a2「网络 bond」不含查询词，BM25 得分为 0 因而不入结果（与单索引 BM25 行为一致）。
	if len(out.Results) != 2 {
		t.Fatalf("got %d results (%+v), want the 2 chunks containing I2C", len(out.Results), out.Results)
	}
	// RRF(k=60)：a1 与 b1 各在自己索引里排第 1（得分 1/61），同分按块 id 升序 → a1 在前。
	got := []string{out.Results[0].ChunkID, out.Results[1].ChunkID}
	want := []string{"a1", "b1"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("result order = %v, want %v (RRF k=60 over per-index rankings)", got, want)
	}
	for _, r := range out.Results {
		if r.Entity == "" {
			t.Errorf("offline merged result should still carry its entity label: %+v", r)
		}
	}
}

// 同一块出现在多个索引时，RRF 得分累加（排到更前面）。
func TestMultiSearchRRFAccumulatesAcrossIndexes(t *testing.T) {
	// 两个索引都含 chunk id "dup"（模拟同一份 SDK 文档被两个实体索引）
	dup := chunk("dup", "tpu-mlir 编译 模型", "sdk.md")
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label: "bm1684x", chunks: []chunker.Chunk{dup, chunk("a2", "其它 内容", "a2.md")},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label: "bm1688", chunks: []chunker.Chunk{dup, chunk("b2", "别的内容 二", "b2.md")},
	})
	m := &MultiRetriever{Sources: []Source{a, b}}
	out, err := m.Search(context.Background(), "tpu-mlir", 3)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Results) == 0 || out.Results[0].ChunkID != "dup" {
		t.Fatalf("chunk present in both indexes should rank first, got %+v", out.Results)
	}
}

// 每条结果都要带实体标注，且路径按 PathPrefix 改写（注册表模式相对技能根）。
func TestMultiSearchPathPrefixAndEntityLabel(t *testing.T) {
	prefix := func(src string) string { return "docs/products/se9/" + src }
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:      "se9",
		chunks:     []chunker.Chunk{chunk("a1", "I2C 配置", "faq/i2c.md")},
		pathPrefix: prefix,
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label:  "bm1688",
		chunks: []chunker.Chunk{chunk("b1", "I2C 控制器", "sdk/i2c.md")},
	})
	m := &MultiRetriever{Sources: []Source{a, b}}
	out, err := m.Search(context.Background(), "I2C", 5)
	if err != nil {
		t.Fatal(err)
	}
	byChunk := map[string]Result{}
	for _, r := range out.Results {
		byChunk[r.ChunkID] = r
	}
	if got := byChunk["a1"].SourceFile; got != "docs/products/se9/faq/i2c.md" {
		t.Errorf("a1 path = %q, want the rewritten registry-relative path", got)
	}
	if got := byChunk["b1"].SourceFile; got != "sdk/i2c.md" {
		t.Errorf("b1 path = %q, want it unchanged when no PathPrefix is set", got)
	}
	if byChunk["a1"].Entity != "se9" || byChunk["b1"].Entity != "bm1688" {
		t.Errorf("entity labels = %q/%q, want se9/bm1688", byChunk["a1"].Entity, byChunk["b1"].Entity)
	}
}

// 任一目标索引缺失 → 直接报错，不静默只查剩下的。
func TestMultiSearchMissingIndexErrors(t *testing.T) {
	present := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md")},
	})
	missing := Source{Label: "bm1688", Store: &docstore.Store{IndexDir: filepath.Join(t.TempDir(), "none")}, Product: "bm1688"}
	m := &MultiRetriever{Sources: []Source{present, missing}}
	_, err := m.Search(context.Background(), "I2C", 5)
	if err == nil {
		t.Fatal("missing index must error, not silently search the rest")
	}
	if !strings.Contains(err.Error(), "bm1688") {
		t.Errorf("error should name the missing entity, got: %v", err)
	}
}

// 只有一个源时也要能工作（CLI 单实体走的是 Retriever，这里覆盖 Multi 的退化情形）。
func TestMultiSearchSingleSource(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md"), chunk("a2", "网络", "a2.md")},
		vecs:   [][]float32{{1, 0}, {1, 0}},
	})
	m := &MultiRetriever{Sources: []Source{a}, Embedder: &vectorEmbedder{}, Reranker: &countingReranker{}}
	out, err := m.Search(context.Background(), "I2C", 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Results) == 0 {
		t.Fatal("expected results from a single source")
	}
	if out.Results[0].Entity != "se9" {
		t.Errorf("entity = %q, want se9", out.Results[0].Entity)
	}
}

// 向量维度不匹配（换了供应商/模型）→ 不能 panic、不能拿错维度的向量算相似度。
func TestMultiSearchDimMismatchFallsBack(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md")},
		vecs:   [][]float32{{1, 0, 0}},
	})
	b := writeSource(t, filepath.Join(t.TempDir(), "b"), sourceFixture{
		label:  "bm1688",
		chunks: []chunker.Chunk{chunk("b1", "I2C 控制器", "b1.md")},
		vecs:   [][]float32{{1, 0}},
	})
	// 查询向量是 2 维，索引 a 是 3 维 → 必须退化而不是 panic
	m := &MultiRetriever{Sources: []Source{a, b}, Embedder: &vectorEmbedder{}, Reranker: &countingReranker{}}
	out, err := m.Search(context.Background(), "I2C", 5)
	if err != nil {
		t.Fatalf("dim mismatch should degrade, not error: %v", err)
	}
	if out.Mode != "bm25" {
		t.Errorf("mode = %q, want bm25 after a dim mismatch", out.Mode)
	}
	if !strings.Contains(out.FallbackReason, "dim mismatch") {
		t.Errorf("fallback reason = %q, want it to mention the dim mismatch", out.FallbackReason)
	}
	if len(out.Results) == 0 {
		t.Error("expected bm25 results after falling back")
	}
}

// roundRobin 的截断行为：候选上限生效，且不因某个源提前耗尽而错位。
func TestRoundRobin(t *testing.T) {
	mk := func(ids ...string) []candidate {
		out := make([]candidate, len(ids))
		for i, id := range ids {
			out[i] = candidate{chunk: chunker.Chunk{ChunkID: id}}
		}
		return out
	}
	got := roundRobin([][]candidate{mk("a1", "a2", "a3"), mk("b1")}, 3)
	var ids []string
	for _, c := range got {
		ids = append(ids, c.chunk.ChunkID)
	}
	if want := []string{"a1", "b1", "a2"}; !reflect.DeepEqual(ids, want) {
		t.Errorf("roundRobin = %v, want %v", ids, want)
	}
	if got := roundRobin([][]candidate{mk("a1"), mk("b1")}, 10); len(got) != 2 {
		t.Errorf("len = %d, want 2 (exhausted sources stop the loop)", len(got))
	}
	if got := roundRobin(nil, 10); len(got) != 0 {
		t.Errorf("len = %d, want 0 for no sources", len(got))
	}
}

// 损坏的索引（缺 chunks.gob）也要报错，不返回空结果。
func TestMultiSearchCorruptIndexErrors(t *testing.T) {
	a := writeSource(t, filepath.Join(t.TempDir(), "a"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("a1", "I2C 配置", "a1.md")},
	})
	if err := os.Remove(filepath.Join(a.Store.IndexDir, "chunks.gob")); err != nil {
		t.Fatal(err)
	}
	m := &MultiRetriever{Sources: []Source{a}}
	if _, err := m.Search(context.Background(), "I2C", 5); err == nil {
		t.Fatal("corrupt index must error")
	}
}
