package retriever

import (
	"context"
	"path/filepath"
	"testing"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
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

func TestCheckFingerprintDimension(t *testing.T) {
	if err := CheckFingerprint(3, 3); err != nil {
		t.Errorf("matching dim should pass, got %v", err)
	}
	if err := CheckFingerprint(3, 1024); err == nil {
		t.Error("dim mismatch should error")
	}
}
