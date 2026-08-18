package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
)

func TestProcessArgs(t *testing.T) {
	tt := []struct {
		args []string
		want string
	}{
		{[]string{"build", "-product", "se7", "-docs-dir", "/d", "-index-dir", "/i"}, "build"},
		{[]string{"query", "-product", "se7", "-top-n", "8", "问题"}, "query"},
		{[]string{"doctor", "-product", "se7"}, "doctor"},
	}
	for _, c := range tt {
		if got := processArgsRaw(c.args); got != c.want {
			t.Errorf("args=%v got=%q want=%q", c.args, got, c.want)
		}
	}
}

// fakeFactory 用固定 2 维 fake embedder/reranker，使 build/query/doctor 全链路可离线跑通。
func fakeFactory() runCtx {
	return runCtx{
		useBuiltin: true,
		indexDir:   filepath.Join(os.TempDir(), "se-rag-test-index"),
		product:    "se7",
		topN:       5,
		embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
		rerankF:    func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
	}
}

// keyTestCtx 返回带有效 docs/index/query 的 fake 上下文（供 key 校验测试，key 检查前的参数都能通过）。
func keyTestCtx(t *testing.T) runCtx {
	t.Helper()
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# SE7\n\n## 网络\n\n配置 netplan 使能 dhcp4。"), 0o644); err != nil {
		t.Fatal(err)
	}
	rc := fakeFactory()
	rc.useBuiltin = false
	rc.docsDir = docsDir
	rc.indexDir = filepath.Join(dir, "idx")
	rc.query = "网络配置"
	return rc
}

func TestBuiltinKeyFalseRequiresEnvKeys(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	rc := keyTestCtx(t)

	err := runBuild(rc)
	if err == nil {
		t.Fatal("build: expected error for -builtin-key=false without SE_RAG_EMBED_KEY")
	}
	if !strings.Contains(err.Error(), "SE_RAG_EMBED_KEY") {
		t.Fatalf("build: error should name the missing key, got: %v", err)
	}

	err = runQuery(rc)
	if err == nil {
		t.Fatal("query: expected error for -builtin-key=false without SE_RAG_EMBED_KEY")
	}

	// 只设 embed key：build 通过（不要求 rerank key），query 仍因缺少 rerank key 报错
	t.Setenv("SE_RAG_EMBED_KEY", "sk-test-embed")
	err = runBuild(rc)
	if err != nil {
		t.Fatalf("build with embed key only should pass, got: %v", err)
	}
	err = runQuery(rc)
	if err == nil {
		t.Fatal("query: expected error when SE_RAG_RERANK_KEY missing")
	}
	if !strings.Contains(err.Error(), "SE_RAG_RERANK_KEY") {
		t.Fatalf("query: error should name the missing rerank key, got: %v", err)
	}

	// 两个 key 齐备：build/query 均通过
	t.Setenv("SE_RAG_RERANK_KEY", "sk-test-rerank")
	if err := runBuild(rc); err != nil {
		t.Fatalf("build with both keys should pass, got: %v", err)
	}
	if err := runQuery(rc); err != nil {
		t.Fatalf("query with both keys should pass, got: %v", err)
	}
}

func TestBuiltinKeyFalseSkippedInFakeMode(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "1")
	rc := keyTestCtx(t)
	if err := runBuild(rc); err != nil {
		t.Fatalf("fake mode should skip key check, got: %v", err)
	}
	if err := runQuery(rc); err != nil {
		t.Fatalf("fake mode query should skip key check, got: %v", err)
	}
}

func TestCLIBuildQueryDoctorHappyPath(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 多段文档，验证内置限流下的 build 全量路径
	doc := "# SE7\n\n## 网络\n\n配置 netplan 使能 eth0 的 dhcp4。\n\n## SDK\n\nSE7 使用 BM1684X 芯片 运行 推理 任务。\n\n## FAQ\n\nOTA 升级 用于 更新 系统 镜像。\n\n## 补充\n\nWi-Fi 模块 需 安装 驱动 补丁 后 使用。\n\n## 参考\n\n参考 微服务器 SE7 产品使用手册。\n\n## 附录\n\n本附录 提供 更多 详细 配置 步骤 与 示例。"
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte(doc), 0o644); err != nil {
		t.Fatal(err)
	}

	idx := filepath.Join(dir, "idx")
	rc := fakeFactory()
	rc.docsDir = docsDir
	rc.indexDir = idx

	// build（索引直接落在 idx/ 下，无 product 子目录）
	if err := runBuild(rc); err != nil {
		t.Fatalf("build failed: %v", err)
	}
	for _, f := range []string{"meta.json", "vectors.gob", "bm25.gob", "chunks.gob", ".complete"} {
		if _, err := os.Stat(filepath.Join(idx, f)); err != nil {
			t.Errorf("expected %s at %s: %v", f, idx, err)
		}
	}

	// doctor：fake 是 2 维，与 config 的 1024 维不一致 → 应报告需重建（重读不误报）
	needRebuild, err := runDoctor(rc)
	if err != nil || !needRebuild {
		t.Errorf("doctor: err=%v needRebuild=%v; want rebuild-needed when dim mismatches", err, needRebuild)
	}
}

func TestCLIBuildNoDocsFails(t *testing.T) {
	rc := fakeFactory()
	rc.docsDir = filepath.Join(t.TempDir(), "missing")
	if err := runBuild(rc); err == nil {
		t.Fatal("expected error building from empty/missing docs dir")
	}
}

// ---- doctor 指纹：换 provider/model（维度相同）也应提示重建 ----

func TestDoctorFingerprintProviderMismatch(t *testing.T) {
	dir := t.TempDir()
	idx := filepath.Join(dir, "idx")
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# SE7\n\n## 网络\n\n配置 netplan 命令。"), 0o644); err != nil {
		t.Fatal(err)
	}
	rc := fakeFactory()
	rc.docsDir = docsDir
	rc.indexDir = idx
	if err := runBuild(rc); err != nil {
		t.Fatalf("build failed: %v", err)
	}

	writeMeta := func(fp string, dim int) {
		t.Helper()
		m := docstore.Meta{Product: "se7", EmbedderFingerprint: fp, Dim: dim, BuildVersion: "1.0"}
		b, err := json.MarshalIndent(m, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(idx, "meta.json"), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}

	// 场景 1：供应商/模型与当前配置不同、但维度相同（1024）→ 旧实现只比维度会误报 OK
	writeMeta("sophnet.other-model", 1024)
	needRebuild, err := runDoctor(rc)
	if err != nil {
		t.Fatalf("doctor err: %v", err)
	}
	if !needRebuild {
		t.Error("doctor: same dim but different provider/model fingerprint -> want rebuild-needed")
	}

	// 场景 2：指纹与维度都匹配当前配置 → 不应误报
	writeMeta("siliconflow.BAAI/bge-m3", 1024)
	needRebuild, err = runDoctor(rc)
	if err != nil {
		t.Fatalf("doctor err: %v", err)
	}
	if needRebuild {
		t.Error("doctor: matching fingerprint+dim -> want no rebuild")
	}

	// 场景 3：历史索引无 embedder_fingerprint 字段（legacy meta.json）→ 无法验证向量空间 → 提示重建
	legacy := `{"product":"se7","dim":1024,"chunk_count":1,"build_version":"1.0"}`
	if err := os.WriteFile(filepath.Join(idx, "meta.json"), []byte(legacy), 0o644); err != nil {
		t.Fatal(err)
	}
	needRebuild, err = runDoctor(rc)
	if err != nil {
		t.Fatalf("doctor err: %v", err)
	}
	if !needRebuild {
		t.Error("doctor: legacy index without fingerprint -> want rebuild-needed (cannot verify vector space)")
	}
}

// ---- build 向量逐元素校验 ----

// selectiveFake 按文本内容决定返回：含 DROPVEC 的段落返回 nil 向量（模拟上游缺向量），其余 2 维全 1。
type selectiveFake struct{}

func (f *selectiveFake) Name() string { return "selective" }
func (f *selectiveFake) Dim() int     { return 2 }
func (f *selectiveFake) Embed(_ context.Context, texts []string) ([][]float32, error) {
	out := make([][]float32, len(texts))
	for i, s := range texts {
		if strings.Contains(s, "DROPVEC") {
			out[i] = nil
			continue
		}
		out[i] = []float32{1, 1}
	}
	return out, nil
}

// mixedDimFake：含 MIXED 的段落返回 3 维，其余 2 维（模拟上游模型切换导致维度漂移）。
type mixedDimFake struct{}

func (f *mixedDimFake) Name() string { return "mixeddim" }
func (f *mixedDimFake) Dim() int     { return 2 }
func (f *mixedDimFake) Embed(_ context.Context, texts []string) ([][]float32, error) {
	out := make([][]float32, len(texts))
	for i, s := range texts {
		if strings.Contains(s, "MIXED") {
			out[i] = []float32{1, 1, 1}
			continue
		}
		out[i] = []float32{1, 1}
	}
	return out, nil
}

// 部分段落向量为 nil：告警跳过该 chunk 向量（BM25 仍覆盖），索引保持对齐、不静默入库坏向量。
func TestBuildSkipsNilVectors(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 两个文件 → 两个 chunk：a.md 正常，b.md 含 DROPVEC 模拟上游缺向量
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# SE7\n\n## 网络\n\n配置 netplan 使能 dhcp4。\n\n## SDK\n\nSE7 使用 BM1684X 芯片。"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "b.md"), []byte("# FAQ\n\n## 异常\n\n本段 DROPVEC 缺失向量 内容。"), 0o644); err != nil {
		t.Fatal(err)
	}

	rc := fakeFactory()
	rc.docsDir = docsDir
	rc.indexDir = filepath.Join(dir, "idx")
	rc.embedF = func(config.Provider) (embed.Embedder, error) { return &selectiveFake{}, nil }

	if err := runBuild(rc); err != nil {
		t.Fatalf("build should succeed with skipped vectors, got %v", err)
	}
	store := &docstore.Store{IndexDir: rc.indexDir}
	loaded, err := store.Open(rc.product)
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded.ChunkByID) != 2 {
		t.Fatalf("chunks: want 2, got %d", len(loaded.ChunkByID))
	}
	// 被跳过的 chunk 无向量（不在向量索引），但 BM25 仍覆盖
	droppedID := ""
	for id, c := range loaded.ChunkByID {
		if strings.Contains(c.Text, "DROPVEC") {
			droppedID = id
		}
	}
	if droppedID == "" {
		t.Fatal("failed to locate DROPVEC chunk")
	}
	for _, id := range loaded.Vector.ChunkIDs {
		if id == droppedID {
			t.Error("DROPVEC chunk must NOT be in vector index")
		}
	}
	if len(loaded.Vector.ChunkIDs) != 1 {
		t.Errorf("vector count: want 1, got %d", len(loaded.Vector.ChunkIDs))
	}
	if loaded.BM25.DocCount() != 2 {
		t.Errorf("bm25 docs: want 2 (all chunks), got %d", loaded.BM25.DocCount())
	}
	if loaded.Vector.Dim != 2 {
		t.Errorf("vector dim: want 2, got %d", loaded.Vector.Dim)
	}
}

// 维度漂移（同批出现不同维度）→ build 必须报错中止，不能静默入库。
func TestBuildDimMismatchErrors(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# SE7\n\n## 正常\n\n普通段落 内容。"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "b.md"), []byte("# FAQ\n\n## 异常\n\n本段 MIXED 维度 漂移 内容。"), 0o644); err != nil {
		t.Fatal(err)
	}

	rc := fakeFactory()
	rc.docsDir = docsDir
	rc.indexDir = filepath.Join(dir, "idx")
	rc.embedF = func(config.Provider) (embed.Embedder, error) { return &mixedDimFake{}, nil }

	err := runBuild(rc)
	if err == nil {
		t.Fatal("build must error on mixed embedding dims")
	}
	if !strings.Contains(err.Error(), "dim mismatch") {
		t.Errorf("error should mention dim mismatch, got: %v", err)
	}
}
