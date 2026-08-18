package retriever

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/vector"
)

type fakeEmbed struct {
	fail bool
	vec  []float32
}

func (f *fakeEmbed) Name() string { return "fake.em" }
func (f *fakeEmbed) Dim() int     { return 2 }
func (f *fakeEmbed) Embed(_ context.Context, _ []string) ([][]float32, error) {
	if f.fail {
		return nil, errEmbed
	}
	return [][]float32{f.vec}, nil
}

var errEmbed = &errSentinel{}

type errSentinel struct{}

func (e *errSentinel) Error() string { return "embed failed" }

type fakeRerank struct{}

func (f *fakeRerank) Name() string { return "fake.rr" }
func (f *fakeRerank) Rerank(_ context.Context, _ string, docs []string, topN int) ([]int, error) {
	if topN > len(docs) {
		topN = len(docs)
	}
	idxs := make([]int, topN)
	for i := range idxs {
		idxs[i] = i
	}
	return idxs, nil
}

func buildTestStore(t *testing.T) *docstore.Store {
	t.Helper()
	s := &docstore.Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	chunks := []chunker.Chunk{
		{ChunkID: "a", Text: "SE7 使用 BM1684X 芯片 运行 推理 任务", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1},
		{ChunkID: "b", Text: "OTA 升级 更新 系统 镜像", SourceFile: "faq.md", LineStart: 3, LineEnd: 3},
	}
	vecs := [][]float32{{1, 0}, {0, 1}}
	meta := s.BuildMeta("se7", "fake", "em", 2, chunks)
	ids := []string{"a", "b"}
	bmi := bm25.Build([]string{chunks[0].Text, chunks[1].Text}, ids)
	if err := s.SaveIndex("se7", meta, vecs, ids, bmi, chunks); err != nil {
		t.Fatal(err)
	}
	return s
}

func TestSearchHybrid(t *testing.T) {
	s := buildTestStore(t)
	r := &Retriever{Store: s, Embedder: &fakeEmbed{vec: []float32{1, 0}}, Reranker: &fakeRerank{}}
	out, err := r.Search(context.Background(), "BM1684X 芯片", "se7", 8)
	if err != nil {
		t.Fatal(err)
	}
	if out.Mode != "hybrid" {
		t.Errorf("mode=%s want hybrid", out.Mode)
	}
	if len(out.Results) == 0 {
		t.Fatal("expected results")
	}
	// 包含命中芯片的 chunk a
	hasA := false
	for _, rr := range out.Results {
		if rr.ChunkID == "a" {
			hasA = true
		}
	}
	if !hasA {
		t.Errorf("expected chunk a in results: %+v", out.Results)
	}
}

func TestSearchFallbackBM25(t *testing.T) {
	s := buildTestStore(t)
	r := &Retriever{Store: s, Embedder: &fakeEmbed{fail: true}, Reranker: &fakeRerank{}}
	out, err := r.Search(context.Background(), "BM1684X 芯片", "se7", 8)
	if err != nil {
		t.Fatal(err)
	}
	if out.Mode != "bm25" {
		t.Errorf("mode=%s want bm25", out.Mode)
	}
	if len(out.Results) == 0 {
		t.Fatal("expected bm25 results")
	}
}

// CheckFingerprint 比较完整指纹串（provider.model@dim）；空指纹跳过比较（旧索引无指纹字段）。
func TestCheckFingerprint(t *testing.T) {
	if err := CheckFingerprint("siliconflow.BAAI/bge-m3@1024", "siliconflow.BAAI/bge-m3@1024"); err != nil {
		t.Errorf("matching fingerprint should pass, got %v", err)
	}
	// 同 provider 同维度但维度不同 → 不匹配
	if err := CheckFingerprint("siliconflow.BAAI/bge-m3@512", "siliconflow.BAAI/bge-m3@1024"); err == nil {
		t.Error("dim mismatch should error")
	}
	// 同维度但 provider/model 不同 → 不匹配（换供应商/模型检测）
	if err := CheckFingerprint("sophnet.bge-m3@1024", "siliconflow.BAAI/bge-m3@1024"); err == nil {
		t.Error("provider/model mismatch should error")
	}
	// 空指纹（历史索引无 embedder_fingerprint 字段）→ 无法验证 → 提示重建（安全优先）
	if err := CheckFingerprint("", "siliconflow.BAAI/bge-m3@1024"); err == nil {
		t.Error("empty index fingerprint should error (rebuild needed, safety first)")
	}
}

// TestSearchIncompleteIndexNoPanic 模拟缺 bm25.gob 的半套索引目录：
// Open 显式报错（ErrIncomplete），query 返回错误而绝不 panic（回归 MYS-391 的 nil 解引用崩溃）。
func TestSearchIncompleteIndexNoPanic(t *testing.T) {
	s := buildTestStore(t)
	if err := os.Remove(filepath.Join(s.IndexDir, "bm25.gob")); err != nil {
		t.Fatal(err)
	}
	r := &Retriever{Store: s, Embedder: &fakeEmbed{vec: []float32{1, 0}}, Reranker: &fakeRerank{}}
	if _, err := r.Search(context.Background(), "BM1684X 芯片", "se7", 8); err == nil {
		t.Fatal("Search on incomplete index should error, got nil")
	}
}

// TestHybridNilBM25VectorOnly 防御：loaded.BM25 为 nil 时 hybrid 退化为纯向量融合，不 panic。
func TestHybridNilBM25VectorOnly(t *testing.T) {
	v := &vector.Index{Dim: 2}
	v.Add([]float32{1, 0}, "a")
	v.Add([]float32{0, 1}, "b")
	loaded := &docstore.Loaded{
		Vector: v,
		ChunkByID: map[string]chunker.Chunk{
			"a": {ChunkID: "a", Text: "SE7 芯片", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1},
			"b": {ChunkID: "b", Text: "OTA 升级", SourceFile: "faq.md", LineStart: 3, LineEnd: 3},
		},
	}
	r := &Retriever{}
	res := r.hybrid(context.Background(), loaded, "SE7", []float32{1, 0}, 8)
	if len(res) == 0 {
		t.Fatal("expected vector-only results, got none")
	}
	if res[0].ChunkID != "a" {
		t.Errorf("res[0] = %q, want pure vector hit %q", res[0].ChunkID, "a")
	}
}

// TestBm25FallbackNilBM25Error 防御：loaded.BM25 为 nil 时兜底路径返回显式错误，不 panic。
func TestBm25FallbackNilBM25Error(t *testing.T) {
	loaded := &docstore.Loaded{ChunkByID: map[string]chunker.Chunk{}}
	r := &Retriever{}
	out, err := r.bm25Fallback(loaded, "SE7", 8, &SearchOutcome{}, time.Now())
	if err == nil {
		t.Fatal("bm25Fallback with nil BM25 should error, got nil")
	}
	if out != nil {
		t.Errorf("out = %+v, want nil on error", out)
	}
}
