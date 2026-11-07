package main

// 一次性夹具生成器：用**改动前**的代码跑单索引查询，把 stdout 原样落盘为 golden，
// 供改动后的 TestSingleIndexOutputUnchanged 逐字节比对。不是回归测试，capture 由
// SE_RAG_CAPTURE_GOLDEN 环境变量控制，平时只做「golden 存在」的检查。

import (
	"os"
	"path/filepath"
	"regexp"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
)

// goldenDocs 单索引 golden 用的固定文档库（三个块，覆盖中英文与代码块）。
func goldenDocs(t *testing.T, dir string) string {
	t.Helper()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"network.md": "# SE9 网络配置\n\n## 双网口绑定\n\nSE9 的两个千兆网口用 netplan 配 bond，模式 802.3ad，上游需开 LACP。\n",
		"i2c-faq.md": "# SE9 I2C\n\n## 16-BP1-11 的 I2C 怎么接\n\nI2C0 复用 GPIO3/GPIO4，默认 100kHz，设备树 clock-frequency 改 400000 可跑高速。\n",
		"sdk.md":     "# BM1688 SDK\n\n## tpu-mlir 编译模型\n\n```bash\nmodel_deploy.py --chip bm1688\n```\n\n先用 model_transform.py 转 MLIR，再生成 bmodel。\n",
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(docsDir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return docsDir
}

// goldenRun 用改动前的 runQuery 跑一次查询并返回 stdout。
func goldenRun(t *testing.T, docsDir, indexDir, question string) string {
	t.Helper()
	rc := runCtx{
		docsDir:    docsDir,
		indexDir:   indexDir,
		product:    metaProductLabel,
		topN:       5,
		useBuiltin: true,
		embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
		rerankF:    func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
	}
	if err := runBuild(rc); err != nil {
		t.Fatalf("build: %v", err)
	}
	rc.query = question
	var err error
	out := captureStdout(t, func() { err = runQuery(rc) })
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	return out
}

// durationRe 归一化输出里的耗时字段（唯一不确定的字节，测试前被替换为固定占位）。
var durationRe = regexp.MustCompile(`total \d+ms`)

func TestCaptureGolden(t *testing.T) {
	if os.Getenv("SE_RAG_CAPTURE_GOLDEN") == "" {
		t.Skip("set SE_RAG_CAPTURE_GOLDEN=1 to regenerate testdata/golden")
	}
	dir := t.TempDir()
	docsDir := goldenDocs(t, dir)
	out := goldenRun(t, docsDir, filepath.Join(dir, "idx"), "SE9 网口 bond 怎么配")
	path := filepath.Join("testdata", "golden", "single-index-query.md")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(durationRe.ReplaceAllString(out, "total <MS>ms")), 0o644); err != nil {
		t.Fatal(err)
	}
	// 顺带记录 meta.json 的关键字段，供改动后确认单索引索引产物不变。
	meta, err := (&docstore.Store{IndexDir: filepath.Join(dir, "idx")}).ReadMeta(metaProductLabel)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("meta: product=%s fp=%s dim=%d chunks=%d strategy=%s mode=%s",
		meta.Product, meta.Fingerprint(), meta.Dim, meta.ChunkCount, meta.ChunkStrategy, meta.SearchMode)
}
