package docstore

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
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

func TestOpenRejectsOversizedGob(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "index")
	s := &Store{IndexDir: dir}
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "x", SourceFile: "a.md", LineStart: 1, LineEnd: 1}}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 2, chunks)
	bmi := bm25.Build([]string{"x"}, []string{"c0"})
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, bmi, chunks); err != nil {
		t.Fatal(err)
	}
	// 篡改：把 chunks.gob 撑到超过上限（稀疏文件，不实际占磁盘）
	f, err := os.Create(filepath.Join(dir, "chunks.gob"))
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Truncate(maxChunksSize + 1); err != nil {
		t.Fatal(err)
	}
	f.Close()
	if _, err := s.Open("se7"); err == nil {
		t.Fatal("expected error for oversized chunks.gob")
	} else if !strings.Contains(err.Error(), "too large") {
		t.Fatalf("error should mention size limit, got: %v", err)
	}
}

// saveTestIndex 保存一套完整索引（meta/vectors/bm25/chunks + 完成标记）。
func saveTestIndex(t *testing.T, s *Store) {
	t.Helper()
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "SE7 使用 BM1684X", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1}}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 2, chunks)
	bmi := bm25.Build([]string{"SE7 使用 BM1684X"}, []string{"c0"})
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, bmi, chunks); err != nil {
		t.Fatal(err)
	}
}

// TestOpenMissingBM25Errors 模拟构建中途被 kill 留下的"缺 bm25.gob 的合法索引"
// （meta.json 已落盘但 bm25.gob 缺失）：Open 必须显式报 ErrIncomplete，而非静默返回 nil BM25。
func TestOpenMissingBM25Errors(t *testing.T) {
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	saveTestIndex(t, s)
	if err := os.Remove(filepath.Join(s.IndexDir, "bm25.gob")); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Open("se7"); !errors.Is(err, ErrIncomplete) {
		t.Fatalf("Open = %v, want ErrIncomplete (index missing bm25.gob)", err)
	}
}

// TestOpenMissingCompleteMarkErrors 完成标记缺失（半套写入的另一个信号）同样必须报错。
func TestOpenMissingCompleteMarkErrors(t *testing.T) {
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	saveTestIndex(t, s)
	if err := os.Remove(filepath.Join(s.IndexDir, completeMark)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Open("se7"); !errors.Is(err, ErrIncomplete) {
		t.Fatalf("Open = %v, want ErrIncomplete (completion mark missing)", err)
	}
}

// TestOpenNeverBuiltDirHintsRebuild 从未构建（目录不存在）报"先 build"提示，而非误报损坏。
func TestOpenNeverBuiltDirHintsRebuild(t *testing.T) {
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "no-such-index")}
	_, err := s.Open("se7")
	if err == nil {
		t.Fatal("Open on never-built dir should error")
	}
	if errors.Is(err, ErrIncomplete) {
		t.Errorf("Open = %v, want 'run build first' hint, not ErrIncomplete", err)
	}
}

// TestSaveIndexNilBM25Openable 保存时无 BM25 写入空 bm25 索引：Open 正常、四件套齐全、
// BM25.Search 返回空结果（vector-only 索引语义，且消除 nil 解引用可能）。
func TestSaveIndexNilBM25Openable(t *testing.T) {
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "SE7 使用 BM1684X", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1}}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 2, chunks)
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, nil, chunks); err != nil {
		t.Fatal(err)
	}
	l, err := s.Open("se7")
	if err != nil {
		t.Fatal(err)
	}
	if l.BM25 == nil {
		t.Fatal("BM25 should be non-nil (empty index)")
	}
	if got := l.BM25.Search("BM1684X", 1); len(got) != 0 {
		t.Errorf("empty bm25 index should return no results, got %+v", got)
	}
	if _, err := os.Stat(filepath.Join(s.IndexDir, "bm25.gob")); err != nil {
		t.Errorf("bm25.gob should exist after save: %v", err)
	}
}

// TestSaveIndexWritesCompleteSet 完整保存后：四件套 + 完成标记齐全，且不残留临时文件。
func TestSaveIndexWritesCompleteSet(t *testing.T) {
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	saveTestIndex(t, s)
	for _, name := range []string{"meta.json", "vectors.gob", "bm25.gob", "chunks.gob", completeMark} {
		if _, err := os.Stat(filepath.Join(s.IndexDir, name)); err != nil {
			t.Errorf("missing %s after SaveIndex: %v", name, err)
		}
	}
	entries, err := os.ReadDir(s.IndexDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.Name()[0] == '.' && e.Name() != completeMark {
			t.Errorf("stale temp file left: %s", e.Name())
		}
	}
}

// TestSaveFailureKeepsOldIndexIntact 保存中途失败（目录只读）不得破坏已存在的完整索引。
func TestSaveFailureKeepsOldIndexIntact(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("running as root: chmod 0500 does not block writes")
	}
	s := &Store{IndexDir: filepath.Join(t.TempDir(), "index")}
	saveTestIndex(t, s)
	if err := os.Chmod(s.IndexDir, 0o500); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(s.IndexDir, 0o755) //nolint:errcheck
	chunks := []chunker.Chunk{{ChunkID: "c0", Text: "SE7 使用 BM1684X", SourceFile: "sdk.md", LineStart: 1, LineEnd: 1}}
	meta := s.BuildMeta("se7", "siliconflow", "BAAI/bge-m3", 2, chunks)
	if err := s.SaveIndex("se7", meta, [][]float32{{1, 0}}, []string{"c0"}, nil, chunks); err == nil {
		t.Fatal("SaveIndex into read-only dir should fail")
	}
	// 旧索引仍然完整可读，未被半套数据污染
	l, err := s.Open("se7")
	if err != nil {
		t.Fatalf("old index lost after failed save: %v", err)
	}
	if l.BM25.Search("BM1684X", 1)[0].ChunkID != "c0" {
		t.Error("old bm25 data not intact")
	}
	if _, err := os.Stat(filepath.Join(s.IndexDir, completeMark)); err != nil {
		t.Errorf("completion mark removed by failed save: %v", err)
	}
}
