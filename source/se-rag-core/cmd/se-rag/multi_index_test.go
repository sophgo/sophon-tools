package main

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/retriever"
)

// 多索引检索的端到端验证（路径模式：`query -index-dir a -index-dir b,c`）。
// 用注入的计数假 provider 跑 runMultiSourceQuery，避免依赖 SE_RAG_FAKE_EMBED
// 那个不计次的假 reranker。

// countingReranker 计数假 reranker：保持原顺序，记录调用次数。
type countingReranker struct {
	mu    sync.Mutex
	calls int
}

func (c *countingReranker) Name() string { return "counting" }
func (c *countingReranker) Rerank(_ context.Context, _ string, docs []string, topN int) ([]int, error) {
	c.mu.Lock()
	c.calls++
	c.mu.Unlock()
	if topN > len(docs) {
		topN = len(docs)
	}
	perm := make([]int, topN)
	for i := range perm {
		perm[i] = i
	}
	return perm, nil
}

func (c *countingReranker) count() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.calls
}

// twoIndexes 建两个知识库索引（a / b），返回索引目录。
// offline=false 时用注入的 2 维 fake provider 建（不联网）。
func twoIndexes(t *testing.T, dir string, offline bool) (string, string) {
	t.Helper()
	docsA := filepath.Join(dir, "docsA")
	docsB := filepath.Join(dir, "docsB")
	files := map[string]string{
		filepath.Join(docsA, "a.md"): "# A\n\n## I2C\n\nI2C0 复用 GPIO3/GPIO4，默认 100kHz。\n",
		filepath.Join(docsB, "b.md"): "# B\n\n## I2C\n\ntpu-mlir 编译模型时指定 --chip。\n",
	}
	for p, body := range files {
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	idxA, idxB := filepath.Join(dir, "idxA"), filepath.Join(dir, "idxB")
	for _, c := range []struct{ docs, idx string }{{docsA, idxA}, {docsB, idxB}} {
		captureStdout(t, func() {
			if err := runBuild(runCtx{
				docsDir: c.docs, indexDir: c.idx, product: metaProductLabel,
				offline: offline, useBuiltin: true,
				embedF: func(config.Provider) (embed.Embedder, error) {
					if offline {
						t.Fatal("build -offline must not construct an embedder")
					}
					return embed.NewFakeEmbedder(2), nil
				},
				rerankF: func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
			}); err != nil {
				t.Fatalf("build %s: %v", c.docs, err)
			}
		})
	}
	return idxA, idxB
}

// 路径模式的多 -index-dir：支持重复传入与逗号分隔，合并两个索引的结果。
func TestQueryMultiIndexDirsPathMode(t *testing.T) {
	dir := t.TempDir()
	idxA, idxB := twoIndexes(t, dir, true)

	for _, args := range [][]string{
		{"query", "-offline", "-index-dir", idxA, "-index-dir", idxB, "I2C"},
		{"query", "-offline", "-index-dir", idxA + "," + idxB, "I2C"},
	} {
		out := captureStdout(t, func() {
			if rc := dispatch(args); rc != 0 {
				t.Fatalf("dispatch %v rc=%d", args, rc)
			}
		})
		if !strings.Contains(out, "`a.md:") || !strings.Contains(out, "`b.md:") {
			t.Errorf("dispatch %v should merge both indexes:\n%s", args, out)
		}
		// 路径模式没有实体信息，不得出现 ` [实体id]` 标注
		if regexp.MustCompile(`(?m)^### .*\] ` + "`[^`]+`" + ` \[[a-z]`).MatchString(out) {
			t.Errorf("path mode must not tag entity ids:\n%s", out)
		}
	}
}

// 多索引在线 query：合并结果、rerank 只调用一次。
func TestMultiIndexQueryReranksOnce(t *testing.T) {
	dir := t.TempDir()
	idxA, idxB := twoIndexes(t, dir, false)

	rr := &countingReranker{}
	out := captureStdout(t, func() {
		if err := runMultiSourceQuery(runCtx{
			query:      "I2C",
			topN:       5,
			useBuiltin: true,
			embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
			rerankF:    func(config.Provider) (embed.Reranker, error) { return rr, nil },
		}, []retriever.Source{
			{Store: &docstore.Store{IndexDir: idxA}, Product: metaProductLabel},
			{Store: &docstore.Store{IndexDir: idxB}, Product: metaProductLabel},
		}); err != nil {
			t.Fatalf("multi query: %v", err)
		}
	})

	if rr.count() != 1 {
		t.Errorf("reranker called %d times, want exactly 1 for a multi-index query", rr.count())
	}
	if !strings.Contains(out, "mode=hybrid") {
		t.Errorf("expected mode=hybrid:\n%s", out)
	}
	for _, want := range []string{"`a.md:", "`b.md:"} {
		if !strings.Contains(out, want) {
			t.Errorf("merged output missing %q:\n%s", want, out)
		}
	}
}

// 离线多索引：不构造 embedder / reranker，按各索引内排名做 RRF 合并。
func TestMultiIndexQueryOfflineRRF(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	idxA, idxB := twoIndexes(t, dir, true)

	out := captureStdout(t, func() {
		if err := runMultiSourceQuery(runCtx{
			query: "I2C 配置",
			topN:  5,
			// 离线：这两个工厂一旦被调用就让测试失败
			offline: true,
			embedF: func(config.Provider) (embed.Embedder, error) {
				t.Fatal("offline multi query must not construct an embedder")
				return nil, nil
			},
			rerankF: func(config.Provider) (embed.Reranker, error) {
				t.Fatal("offline multi query must not construct a reranker")
				return nil, nil
			},
		}, []retriever.Source{
			{Store: &docstore.Store{IndexDir: idxA}, Product: metaProductLabel},
			{Store: &docstore.Store{IndexDir: idxB}, Product: metaProductLabel},
		}); err != nil {
			t.Fatalf("offline multi query: %v", err)
		}
	})
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("offline multi query should report mode=bm25:\n%s", out)
	}
	if !strings.Contains(out, "offline mode") {
		t.Errorf("fallback should state the offline mode:\n%s", out)
	}
}

// 用法里要能看出 -offline 对 build 同样生效、-index-dir 可重复。
func TestUsageListsOfflineAndMultiIndex(t *testing.T) {
	out := captureStdout(t, printUsage)
	for _, want := range []string{"build", "query", "doctor", "build -offline", "可重复"} {
		if !strings.Contains(out, want) {
			t.Errorf("usage output missing %q:\n%s", want, out)
		}
	}
}
