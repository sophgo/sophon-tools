package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/registry"
	"se-rag-core/internal/retriever"
)

// 多索引 query 的端到端验证（用 runMultiSourceQuery 直接注入计数假 provider，
// 避免依赖 SE_RAG_FAKE_EMBED 的假 reranker —— 那个不计次）。

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

// twoHybridIndexes 在夹具注册表上建两个 fake-embedding 索引（se9 / bm1688），返回检索源。
func twoHybridIndexes(t *testing.T, dir string) ([]retriever.Source, *registry.Registry) {
	t.Helper()
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	srcs := make([]retriever.Source, 0, 2)
	for _, id := range []string{"se9", "bm1688"} {
		e, _ := reg.ByID(id)
		idx := reg.IndexPath(e)
		captureStdout(t, func() {
			if err := runBuild(runCtx{
				docsDir:    reg.DocsPath(e),
				indexDir:   idx,
				product:    id,
				offline:    false,
				useBuiltin: true,
				embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
				rerankF:    func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
			}); err != nil {
				t.Fatalf("build %s: %v", id, err)
			}
		})
		srcs = append(srcs, retriever.Source{
			Label:      id,
			Store:      &docstore.Store{IndexDir: idx},
			Product:    id,
			PathPrefix: func(src string) string { return reg.ChunkPath(e, src) },
		})
	}
	return srcs, reg
}

// 多索引在线 query：合并结果、标注实体、rerank 只调用一次。
func TestMultiIndexQueryReranksOnce(t *testing.T) {
	dir := testRegistryDir(t)
	srcs, _ := twoHybridIndexes(t, dir)

	rr := &countingReranker{}
	out := captureStdout(t, func() {
		if err := runMultiSourceQuery(runCtx{
			query:      "I2C 怎么接",
			topN:       5,
			useBuiltin: true,
			embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
			rerankF:    func(config.Provider) (embed.Reranker, error) { return rr, nil },
		}, srcs, nil); err != nil {
			t.Fatalf("multi query: %v", err)
		}
	})

	if rr.count() != 1 {
		t.Errorf("reranker called %d times, want exactly 1 for a multi-index query", rr.count())
	}
	if !strings.Contains(out, "mode=hybrid") {
		t.Errorf("expected mode=hybrid:\n%s", out)
	}
	for _, want := range []string{"[se9]", "[bm1688]", "`docs/products/se9/", "`docs/chips/bm1688/"} {
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
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	var srcs []retriever.Source
	for _, id := range []string{"se9", "bm1688"} {
		e, _ := reg.ByID(id)
		srcs = append(srcs, retriever.Source{
			Label: id, Store: &docstore.Store{IndexDir: reg.IndexPath(e)}, Product: id,
			PathPrefix: func(src string) string { return reg.ChunkPath(e, src) },
		})
	}

	out := captureStdout(t, func() {
		if err := runMultiSourceQuery(runCtx{
			query: "tpu-mlir 编译模型",
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
		}, srcs, nil); err != nil {
			t.Fatalf("offline multi query: %v", err)
		}
	})
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("offline multi query should report mode=bm25:\n%s", out)
	}
	if !strings.Contains(out, "[bm1688]") {
		t.Errorf("offline merged result should be tagged:\n%s", out)
	}
	if !strings.Contains(out, "offline mode") {
		t.Errorf("fallback should state the offline mode:\n%s", out)
	}
}

// --help 列出新命令并以 0 退出。
func TestHelpListsNewCommands(t *testing.T) {
	rc := dispatch([]string{"--help"})
	if rc != 0 {
		t.Errorf("--help rc=%d, want 0", rc)
	}
	out := captureStdout(t, func() { dispatch([]string{"-h"}) })
	for _, want := range []string{"list", "resolve", "build", "query", "doctor", "-registry", "-entity", "-with-related"} {
		if !strings.Contains(out, want) {
			t.Errorf("help output missing %q:\n%s", want, out)
		}
	}
}

// build -entity 逗号分隔：按顺序逐个建，meta.product 写各自实体 id。
func TestBuildEntitiesCommaSeparated(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	captureStdout(t, func() {
		rc = dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "se9,bm1688", "-offline"})
	})
	if rc != 0 {
		t.Fatalf("build -entity se9,bm1688 rc=%d", rc)
	}
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"se9", "bm1688"} {
		e, _ := reg.ByID(id)
		meta, err := (&docstore.Store{IndexDir: reg.IndexPath(e)}).ReadMeta(id)
		if err != nil {
			t.Fatalf("%s: %v", id, err)
		}
		if meta.Product != id {
			t.Errorf("%s: meta.product = %q, want %q", id, meta.Product, id)
		}
	}
	// se7 不在目标里，不该被建
	if _, err := os.Stat(filepath.Join(dir, "indexes", "product-se7", "meta.json")); err == nil {
		t.Error("se7 should not be built when only se9,bm1688 are requested")
	}
}
