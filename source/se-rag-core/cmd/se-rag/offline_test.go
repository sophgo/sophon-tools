package main

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/retriever"
)

// offlineDoc 写一篇含图片目录（image-catalog.md）的最小文档库，模拟 AS71X 目录结构。
func offlineDoc(t *testing.T, dir string) string {
	t.Helper()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(filepath.Join(docsDir, "01-product"), 0o755); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"01-product/as711-spec.md": "# AS711 规格书\n\n## AI 内存\n\n总容量 1024GB LPDDR5x，总带宽 2184GB/s。\n",
		"01-product/as713-spec.md": "# AS713 规格书\n\n## AI 内存\n\n总容量 512GB LPDDR5x，总带宽 2184GB/s。\n",
		"image-catalog.md":         "# AS71X 图片目录\n\n## 后面板接口\n\n后视图 GE0/GE1 BMC 网口，HDMI，Type-C，UID 按钮。\n",
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(docsDir, filepath.FromSlash(name)), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return docsDir
}

// failEmbedderFactory embedder 工厂：离线路径一旦调用它就让测试失败。
func failEmbedderFactory(t *testing.T, what string) func(config.Provider) (embed.Embedder, error) {
	t.Helper()
	return func(config.Provider) (embed.Embedder, error) {
		t.Fatalf("%s must not construct an embedder", what)
		return nil, nil
	}
}

// failRerankerFactory reranker 工厂：同上。
func failRerankerFactory(t *testing.T, what string) func(config.Provider) (embed.Reranker, error) {
	t.Helper()
	return func(config.Provider) (embed.Reranker, error) {
		t.Fatalf("%s must not construct a reranker", what)
		return nil, nil
	}
}

// captureStdout 捕获函数执行期间的 stdout（runBuild / runQuery 直接打印）。
func captureStdout(t *testing.T, f func()) string {
	t.Helper()
	old := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdout = w
	done := make(chan string, 1)
	go func() {
		buf, _ := io.ReadAll(r)
		done <- string(buf)
	}()
	f()
	w.Close()
	os.Stdout = old
	return <-done
}

// build -offline：不构造 embedder/reranker、不读 key，落盘 dim=0、search_mode=bm25 的索引。
func TestBuildOfflineNoEmbedderNoKey(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")

	dir := t.TempDir()
	rc := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		// 故意设 -builtin-key=false 且不给 key：离线构建也不该因此报错（它不需要 key）
		useBuiltin: false,
		offline:    true,
		embedF:     failEmbedderFactory(t, "build -offline"),
		rerankF:    failRerankerFactory(t, "build -offline"),
	}
	var err error
	out := captureStdout(t, func() { err = runBuild(rc) })
	if err != nil {
		t.Fatalf("build -offline: %v", err)
	}
	if !strings.Contains(out, "search_mode=bm25") {
		t.Errorf("build -offline output should state search_mode=bm25, got %q", out)
	}

	store := &docstore.Store{IndexDir: rc.indexDir}
	meta, err := store.ReadMeta(metaProductLabel)
	if err != nil {
		t.Fatal(err)
	}
	if meta.SearchMode != docstore.SearchModeBM25 {
		t.Errorf("search_mode = %q, want %q", meta.SearchMode, docstore.SearchModeBM25)
	}
	if meta.Dim != 0 {
		t.Errorf("dim = %d, want 0 (no vectors in offline index)", meta.Dim)
	}
	if meta.EmbedderFingerprint != docstore.FpBM25Only {
		t.Errorf("embedder_fingerprint = %q, want %q", meta.EmbedderFingerprint, docstore.FpBM25Only)
	}
	if meta.Fingerprint() != "bm25@0" {
		t.Errorf("fingerprint = %q, want %q", meta.Fingerprint(), "bm25@0")
	}
	if meta.ChunkCount != 3 {
		t.Errorf("chunk_count = %d, want 3", meta.ChunkCount)
	}

	loaded, err := store.Open(metaProductLabel)
	if err != nil {
		t.Fatalf("open offline index: %v", err)
	}
	if loaded.Vector == nil || loaded.Vector.Dim != 0 || len(loaded.Vector.Vecs) != 0 {
		t.Errorf("offline index must carry an empty vector index, got %+v", loaded.Vector)
	}
	if loaded.BM25.DocCount() != 3 {
		t.Errorf("bm25 docs = %d, want all 3 chunks", loaded.BM25.DocCount())
	}
	// image-catalog.md 与普通文档一样走完整 chunker，落在 BM25 里可检索
	hits := loaded.BM25.Search("后面板 GE0", 5)
	if len(hits) == 0 {
		t.Error("image-catalog.md content should be searchable in the bm25 index")
	}
}

// build -offline 的 flag 写在位置参数之后也生效。
func TestDispatchBuildOfflineFlagAnywhere(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	docsDir := offlineDoc(t, dir)
	cases := []struct {
		args []string
		idx  string
	}{
		{[]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", filepath.Join(dir, "idx1")}, filepath.Join(dir, "idx1")},
		{[]string{"build", "--docs-dir", docsDir, "-index-dir", filepath.Join(dir, "idx2"), "-offline"}, filepath.Join(dir, "idx2")},
		{[]string{"build", "--docs-dir", docsDir, "-offline", "-index-dir", filepath.Join(dir, "idx3")}, filepath.Join(dir, "idx3")},
	}
	for _, c := range cases {
		var rc int
		captureStdout(t, func() { rc = dispatch(c.args) })
		if rc != 0 {
			t.Fatalf("dispatch %v rc=%d, want 0", c.args, rc)
		}
		m, err := (&docstore.Store{IndexDir: c.idx}).ReadMeta(metaProductLabel)
		if err != nil {
			t.Fatalf("dispatch %v: read meta: %v", c.args, err)
		}
		if m.SearchMode != docstore.SearchModeBM25 {
			t.Errorf("dispatch %v: search_mode = %q, want bm25", c.args, m.SearchMode)
		}
	}
}

// build -offline 遇空/不存在 docs 目录仍然报错（空 BM25 不是合法索引）。
func TestBuildOfflineNoDocsFails(t *testing.T) {
	rc := runCtx{
		docsDir:  filepath.Join(t.TempDir(), "missing"),
		indexDir: filepath.Join(t.TempDir(), "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	if err := runBuild(rc); err == nil {
		t.Fatal("build -offline on missing docs dir should fail")
	}
	// 目录存在但没有 .md：同样是空索引，必须报错而不是写出一套空 BM25
	empty := t.TempDir()
	rc.docsDir = empty
	if err := runBuild(rc); err == nil {
		t.Fatal("build -offline on empty docs dir should fail")
	}
}

// doctor 对离线索引：不报"需真实 embedding 指纹"，输出检索模式与重建命令。
func TestDoctorOfflineIndexNeedsNoRebuild(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	rc := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(rc); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})

	rc.offline = false
	var needRebuild bool
	var err error
	out := captureStdout(t, func() { needRebuild, err = runDoctor(rc) })
	if err != nil {
		t.Fatalf("doctor: %v", err)
	}
	if needRebuild {
		t.Errorf("doctor on a fresh offline index must not ask for a rebuild\noutput:\n%s", out)
	}
	for _, want := range []string{"search mode  : bm25", "bm25 index OK"} {
		if !strings.Contains(out, want) {
			t.Errorf("doctor output missing %q\noutput:\n%s", want, out)
		}
	}
	if strings.Contains(out, "fingerprint mismatch") {
		t.Errorf("doctor must not complain about embedding fingerprint for a bm25 index\noutput:\n%s", out)
	}

	// 索引不完整（删掉 bm25.gob）时 doctor 仍要报重建，不能因为"离线"就放行
	if err := os.Remove(filepath.Join(rc.indexDir, "bm25.gob")); err != nil {
		t.Fatal(err)
	}
	out = captureStdout(t, func() { needRebuild, err = runDoctor(rc) })
	if err != nil {
		t.Fatalf("doctor on broken offline index: %v", err)
	}
	if !needRebuild {
		t.Errorf("doctor on incomplete offline index must report rebuild\noutput:\n%s", out)
	}
	if !strings.Contains(out, "build -offline") {
		t.Errorf("doctor rebuild hint should be the offline command\noutput:\n%s", out)
	}
}

// 在线 query 读到离线索引：自动降级纯 BM25，不构造 embedder/reranker、不要求 key。
func TestOnlineQueryOnOfflineIndexStaysLocal(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	build := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(build); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})

	rc := runCtx{
		indexDir: build.indexDir,
		product:  metaProductLabel,
		query:    "AS713 AI 内存",
		topN:     5,
		// 在线模式，但索引只能 BM25 → 绝不能构造 embedder
		embedF:  failEmbedderFactory(t, "online query on offline index"),
		rerankF: failRerankerFactory(t, "online query on offline index"),
	}
	var err error
	out := captureStdout(t, func() { err = runQuery(rc) })
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("output should be bm25 mode\noutput:\n%s", out)
	}
	if !strings.Contains(out, "bm25-only") {
		t.Errorf("fallback reason should explain the index is bm25-only\noutput:\n%s", out)
	}
	if !strings.Contains(out, "as713-spec.md") {
		t.Errorf("expected AS713 spec in results\noutput:\n%s", out)
	}
}

// retriever 层兜底：即使调用方传了 embedder，bm25-only 索引也不构造查询向量。
func TestRetrieverNeverEmbedsOnBM25OnlyIndex(t *testing.T) {
	dir := t.TempDir()
	rc := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(rc); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})

	counting := &countingEmbedder{}
	r := &retriever.Retriever{
		Store:    &docstore.Store{IndexDir: rc.indexDir},
		Embedder: counting,
	}
	out, err := r.Search(context.Background(), "AS711 AI 内存", metaProductLabel, 5)
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if counting.calls != 0 {
		t.Errorf("embedder called %d times on a bm25-only index, want 0 (query text must not leave the process)", counting.calls)
	}
	if out.Mode != "bm25" {
		t.Errorf("mode = %q, want bm25", out.Mode)
	}
	if len(out.Results) == 0 {
		t.Error("expected bm25 results")
	}
}

type countingEmbedder struct{ calls int }

func (c *countingEmbedder) Name() string { return "counting" }
func (c *countingEmbedder) Dim() int     { return 2 }
func (c *countingEmbedder) Embed(_ context.Context, texts []string) ([][]float32, error) {
	c.calls++
	out := make([][]float32, len(texts))
	for i := range out {
		out[i] = []float32{1, 0}
	}
	return out, nil
}

// 旧在线索引（meta 无 search_mode）继续按 hybrid 处理，行为不变。
func TestLegacyOnlineIndexStillHybrid(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	rc := fakeFactory()
	rc.docsDir = offlineDoc(t, dir)
	rc.indexDir = filepath.Join(dir, "idx")
	if err := runBuild(rc); err != nil {
		t.Fatalf("build: %v", err)
	}
	// 抹掉 search_mode，模拟 4.3.0 之前写出的索引
	stripSearchMode(t, rc.indexDir)

	meta, err := (&docstore.Store{IndexDir: rc.indexDir}).ReadMeta(rc.product)
	if err != nil {
		t.Fatal(err)
	}
	if meta.SearchMode != "" {
		t.Fatalf("search_mode should be empty for the legacy fixture, got %q", meta.SearchMode)
	}
	if !meta.BM25Only() == false {
		t.Fatalf("legacy index with dim>0 must not be bm25-only (dim=%d)", meta.Dim)
	}
	if meta.EffectiveSearchMode() != docstore.SearchModeHybrid {
		t.Errorf("effective mode = %q, want hybrid", meta.EffectiveSearchMode())
	}

	// 在线 query 仍走 embedder（fake 2 维向量与索引一致）
	called := 0
	rc.embedF = func(config.Provider) (embed.Embedder, error) {
		called++
		return embed.NewFakeEmbedder(2), nil
	}
	rc.query = "AS711 AI 内存"
	captureStdout(t, func() {
		if err := runQuery(rc); err != nil {
			t.Fatalf("query: %v", err)
		}
	})
	if called != 1 {
		t.Errorf("embedder constructed %d times, want 1 (legacy online index keeps hybrid path)", called)
	}
}

// stripSearchMode 把 meta.json 的 search_mode 去掉，构造旧格式索引。
func stripSearchMode(t *testing.T, indexDir string) {
	t.Helper()
	store := &docstore.Store{IndexDir: indexDir}
	meta, err := store.ReadMeta(metaProductLabel)
	if err != nil {
		t.Fatal(err)
	}
	meta.SearchMode = ""
	b, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(indexDir, "meta.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
}

// 空 BM25 不是合法离线索引：doctor 必须报重建（"空向量合法、空 BM25 不合法"的判据落在这里）。
func TestDoctorEmptyBM25OfflineIndexNeedsRebuild(t *testing.T) {
	dir := t.TempDir()
	indexDir := filepath.Join(dir, "idx")
	if err := os.MkdirAll(indexDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 手工造一套 search_mode=bm25 但 BM25 为空的索引
	meta := docstore.Meta{
		Product:             metaProductLabel,
		EmbedderFingerprint: docstore.FpBM25Only,
		Dim:                 0,
		BuildVersion:        "1.0",
		ChunkStrategy:       chunker.StrategyVersion,
		SearchMode:          docstore.SearchModeBM25,
	}
	store := &docstore.Store{IndexDir: indexDir}
	if err := store.SaveIndex(metaProductLabel, meta, nil, nil, bm25.Build(nil, nil), nil); err != nil {
		t.Fatal(err)
	}

	var needRebuild bool
	var err error
	out := captureStdout(t, func() { needRebuild, err = runDoctor(runCtx{indexDir: indexDir, product: metaProductLabel}) })
	if err != nil {
		t.Fatalf("doctor: %v", err)
	}
	if !needRebuild {
		t.Errorf("doctor on an offline index with empty bm25 must report rebuild\noutput:\n%s", out)
	}
	if !strings.Contains(out, "no documents") {
		t.Errorf("doctor should say the bm25 index has no documents\noutput:\n%s", out)
	}
	if !strings.Contains(out, "build -offline") {
		t.Errorf("rebuild hint should be the offline command\noutput:\n%s", out)
	}
}

// 离线索引损坏（缺 chunks.gob）时 query 与 doctor 都要报错，不能静默返回空结果。
func TestOfflineIndexCorruptionStillErrors(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	build := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(build); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})
	if err := os.Remove(filepath.Join(build.indexDir, "chunks.gob")); err != nil {
		t.Fatal(err)
	}

	q := runCtx{indexDir: build.indexDir, product: metaProductLabel, query: "AS711", topN: 3, offline: true}
	func() {
		defer func() {
			if p := recover(); p != nil {
				t.Fatalf("offline query panicked on corrupt index: %v", p)
			}
		}()
		if err := runQuery(q); err == nil {
			t.Fatal("offline query on index missing chunks.gob should error")
		}
	}()
	// doctor 对半套索引：报需要重建（不 panic、不误判为 OK）
	needRebuild, derr := runDoctor(runCtx{indexDir: build.indexDir, product: metaProductLabel})
	if derr != nil {
		t.Fatalf("doctor should report rebuild-needed rather than error, got %v", derr)
	}
	if !needRebuild {
		t.Fatal("doctor on index missing chunks.gob must report rebuild-needed")
	}
}

// 上游 1.4.0 的 docs 内容绑定对 `build -offline` 索引同样生效：离线索引写入 docs_hash，
// docs 变更后 doctor --docs-dir 报重建，且重建提示是离线命令。
func TestOfflineIndexBoundToDocsContent(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	rc := runCtx{
		docsDir:  offlineDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(rc); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})
	meta, err := (&docstore.Store{IndexDir: rc.indexDir}).ReadMeta(rc.product)
	if err != nil {
		t.Fatal(err)
	}
	if meta.DocsHash == "" {
		t.Fatal("build -offline must record docs_hash in meta")
	}

	var needRebuild bool
	out := captureStdout(t, func() { needRebuild, err = runDoctor(rc) })
	if err != nil || needRebuild {
		t.Fatalf("doctor on fresh offline index: rebuild=%v err=%v\noutput:\n%s", needRebuild, err, out)
	}

	if err := os.WriteFile(filepath.Join(rc.docsDir, "01-product", "as711-spec.md"),
		[]byte("# AS711 规格书\n\n## AI 内存\n\n总容量 2048GB。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	out = captureStdout(t, func() { needRebuild, err = runDoctor(rc) })
	if err != nil {
		t.Fatalf("doctor: %v", err)
	}
	if !needRebuild {
		t.Errorf("doctor must report rebuild after docs changed\noutput:\n%s", out)
	}
	if !strings.Contains(out, "se-rag build -offline --docs-dir") {
		t.Errorf("rebuild hint for a bm25 index should be the offline command\noutput:\n%s", out)
	}

	// 不传 --docs-dir 时无从比对，不误报
	rc.docsDir = ""
	out = captureStdout(t, func() { needRebuild, err = runDoctor(rc) })
	if err != nil || needRebuild {
		t.Errorf("doctor without --docs-dir must not flag docs drift: rebuild=%v err=%v\noutput:\n%s", needRebuild, err, out)
	}
}
