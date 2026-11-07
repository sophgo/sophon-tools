package docstore

import (
	"path/filepath"
	"testing"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
)

// 离线索引的元信息：dim=0、search_mode=bm25、指纹 "bm25@0"，且明确不是 hybrid。
func TestOfflineMetaIsExplicitlyBM25(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "index")
	s := &Store{IndexDir: dir}
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "AS711 后视图 GE0 GE1 BMC", SourceFile: "catalog.md", LineStart: 1, LineEnd: 1}}
	meta := Meta{
		Product:             "default",
		EmbedderFingerprint: FpBM25Only,
		Dim:                 0,
		ChunkCount:          len(chunks),
		BuildVersion:        "1.0",
		ChunkStrategy:       chunker.StrategyVersion,
		SearchMode:          SearchModeBM25,
	}
	bmi := bm25.Build([]string{chunks[0].Text}, []string{"c0"})
	if err := s.SaveIndex("default", meta, nil, nil, bmi, chunks); err != nil {
		t.Fatal(err)
	}

	got, err := s.ReadMeta("default")
	if err != nil {
		t.Fatal(err)
	}
	if got.Fingerprint() != "bm25@0" {
		t.Errorf("fingerprint = %q, want bm25@0", got.Fingerprint())
	}
	if !got.BM25Only() || got.EffectiveSearchMode() != SearchModeBM25 {
		t.Errorf("meta should be bm25-only, got mode=%q", got.EffectiveSearchMode())
	}

	// 空向量合法：向量索引存在但没有任何向量
	l, err := s.Open("default")
	if err != nil {
		t.Fatalf("open offline index: %v", err)
	}
	if l.Vector == nil {
		t.Fatal("vector index should still be present (empty), not nil")
	}
	if l.Vector.Dim != 0 || len(l.Vector.Vecs) != 0 {
		t.Errorf("vector index should be empty, got dim=%d vecs=%d", l.Vector.Dim, len(l.Vector.Vecs))
	}
	// BM25 / chunks 仍必须与普通索引一致地完整
	if l.BM25.DocCount() != 1 || len(l.Chunks) != 1 {
		t.Errorf("bm25 docs=%d chunks=%d, want 1/1", l.BM25.DocCount(), len(l.Chunks))
	}
	if len(l.BM25.Search("GE0", 1)) != 1 {
		t.Error("bm25 search should hit the offline chunk")
	}
}

// search_mode 仅在接受的值上生效；旧索引（无该字段）按维度推断。
func TestEffectiveSearchModeFallsBackToDim(t *testing.T) {
	tt := []struct {
		name string
		meta Meta
		want string
	}{
		{"显式 bm25", Meta{SearchMode: SearchModeBM25, Dim: 0}, SearchModeBM25},
		{"显式 hybrid", Meta{SearchMode: SearchModeHybrid, Dim: 1024}, SearchModeHybrid},
		{"旧索引 dim>0", Meta{Dim: 1024}, SearchModeHybrid},
		{"旧索引 dim=0", Meta{Dim: 0}, SearchModeBM25},
		{"未知取值按维度", Meta{SearchMode: "something-new", Dim: 1024}, SearchModeHybrid},
	}
	for _, c := range tt {
		t.Run(c.name, func(t *testing.T) {
			if got := c.meta.EffectiveSearchMode(); got != c.want {
				t.Errorf("effective mode = %q, want %q", got, c.want)
			}
			if c.meta.BM25Only() != (c.want == SearchModeBM25) {
				t.Errorf("BM25Only() = %v, want %v", c.meta.BM25Only(), c.want == SearchModeBM25)
			}
		})
	}
}

// 空 BM25 不算完整索引：离线索引的向量可以为空，但 BM25 必须与 chunks 一致。
// 这里只验证"能落盘也能读回"这一层；判定逻辑（doctor 报重建）在 cmd 包测。
func TestOfflineIndexWithEmptyBM25RoundTrips(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "index")
	s := &Store{IndexDir: dir}
	meta := Meta{
		Product:             "default",
		EmbedderFingerprint: FpBM25Only,
		Dim:                 0,
		BuildVersion:        "1.0",
		ChunkStrategy:       chunker.StrategyVersion,
		SearchMode:          SearchModeBM25,
	}
	if err := s.SaveIndex("default", meta, nil, nil, bm25.Build(nil, nil), nil); err != nil {
		t.Fatal(err)
	}
	l, err := s.Open("default")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	// 四件套齐全且可读；空 BM25 能被读出来（是否可用由 doctor 判，不在这里 panic）
	if l.BM25 == nil {
		t.Fatal("BM25 should be non-nil (empty index)")
	}
	if l.BM25.DocCount() != 0 || len(l.Chunks) != 0 {
		t.Errorf("fixture should be empty, got bm25=%d chunks=%d", l.BM25.DocCount(), len(l.Chunks))
	}
	if l.Meta.Fingerprint() != "bm25@0" {
		t.Errorf("fingerprint = %q, want bm25@0", l.Meta.Fingerprint())
	}
}
