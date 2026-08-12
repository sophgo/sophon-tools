package docstore

import (
	"path/filepath"
	"testing"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
)

func TestFingerprintRoundTrip(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "index")
	s := &Store{IndexDir: dir}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 1024, nil)
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "abc", SourceFile: "a.md", LineStart: 1, LineEnd: 2}}
	// bm25 build
	bmi := bm25.Build([]string{"abc"}, []string{"c0"})
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, bmi, chunks); err != nil {
		t.Fatal(err)
	}
	got, err := s.FingerprintProduct("se7")
	if err != nil {
		t.Fatal(err)
	}
	want := meta.Fingerprint()
	if got != want {
		t.Errorf("fingerprint = %q want %q", got, want)
	}
}

func TestFingerprintCombinesProviderModelDim(t *testing.T) {
	m := Meta{EmbedderFingerprint: "siliconflow.BAAI/bge-m3", Dim: 1024}
	if m.Fingerprint() != "siliconflow.BAAI/bge-m3@1024" {
		t.Errorf("fp = %q", m.Fingerprint())
	}
}

func TestOpenRoundTrip(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "index")
	s := &Store{IndexDir: dir}
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "SE7 使用 BM1684X", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1}}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 2, chunks)
	bmi := bm25.Build([]string{"SE7 使用 BM1684X"}, []string{"c0"})
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, bmi, chunks); err != nil {
		t.Fatal(err)
	}
	l, err := s.Open("se7")
	if err != nil {
		t.Fatal(err)
	}
	if l.Meta.Product != "se7" || l.Meta.Dim != 2 {
		t.Errorf("meta = %+v", l.Meta)
	}
	if l.Vector.Search([]float32{1, 0}, 1)[0].ChunkID != "c0" {
		t.Error("vector not restored")
	}
	if l.BM25.Search("BM1684X", 1)[0].ChunkID != "c0" {
		t.Error("bm25 not restored")
	}
	if _, ok := l.ChunkByID["c0"]; !ok {
		t.Error("chunk index not restored")
	}
}
