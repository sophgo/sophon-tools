package main

import (
	"context"
	"errors"
	"flag"
	"io"
	"reflect"
	"strings"
	"testing"
	"time"

	"se-rag-core/internal/config"
	"se-rag-core/internal/embed"
)

func newTestFlagSet() (*flag.FlagSet, *int, *bool) {
	fs := flag.NewFlagSet("query", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	topN := fs.Int("top-n", 8, "")
	builtin := fs.Bool("builtin-key", true, "")
	return fs, topN, builtin
}

// flag 写在位置参数之后也必须生效（标准库 flag.Parse 会在第一个位置参数处停止）。
func TestParseInterspersed(t *testing.T) {
	tt := []struct {
		name        string
		args        []string
		wantPos     []string
		wantTopN    int
		wantBuiltin bool
	}{
		{"flag 在前", []string{"-top-n", "3", "-builtin-key=false", "问题"}, []string{"问题"}, 3, false},
		{"flag 在后", []string{"问题", "-top-n", "3", "-builtin-key=false"}, []string{"问题"}, 3, false},
		{"flag 前后夹击", []string{"-top-n", "3", "问题", "-builtin-key=false"}, []string{"问题"}, 3, false},
		{"无 flag", []string{"问题"}, []string{"问题"}, 8, true},
		{"多位置参数保序", []string{"a", "-top-n", "2", "b"}, []string{"a", "b"}, 2, true},
		{"-- 之后原样当位置参数", []string{"-top-n", "2", "--", "-builtin-key=false"}, []string{"-builtin-key=false"}, 2, true},
		{"空参数", nil, nil, 8, true},
	}
	for _, c := range tt {
		t.Run(c.name, func(t *testing.T) {
			fs, topN, builtin := newTestFlagSet()
			got := parseInterspersed(fs, c.args)
			if !reflect.DeepEqual(got, c.wantPos) && !(len(got) == 0 && len(c.wantPos) == 0) {
				t.Errorf("pos=%v want %v", got, c.wantPos)
			}
			if *topN != c.wantTopN || *builtin != c.wantBuiltin {
				t.Errorf("topN=%d builtin=%v want %d %v", *topN, *builtin, c.wantTopN, c.wantBuiltin)
			}
		})
	}
}

// 回归：`query -index-dir X "问题" -builtin-key=false` 里的 flag 之前被静默忽略，
// 仍走内置 key 联网；修复后应按 -builtin-key=false 校验 env key，缺失即报错（返回 1，且不发网络请求）。
func TestDispatchBuiltinKeyFalseAfterQuery(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	if rc := dispatch([]string{"query", "-index-dir", t.TempDir(), "网络", "-builtin-key=false"}); rc != 1 {
		t.Fatalf("flag after positional should be honored (missing key → rc=1), got rc=%d", rc)
	}
}

// -offline：不构造 embedder / reranker（不联网、不要求 key），纯 BM25 返回结果。
func TestQueryOfflineNeverTouchesNetwork(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	rc := keyTestCtx(t)
	rc.useBuiltin = true
	if err := runBuild(rc); err != nil {
		t.Fatalf("build: %v", err)
	}

	rc.offline = true
	rc.embedF = func(config.Provider) (embed.Embedder, error) {
		t.Fatal("offline query must not construct an embedder")
		return nil, nil
	}
	rc.rerankF = func(config.Provider) (embed.Reranker, error) {
		t.Fatal("offline query must not construct a reranker")
		return nil, nil
	}
	if err := runQuery(rc); err != nil {
		t.Fatalf("offline query: %v", err)
	}
	rc.query = ""
	if err := runQuery(rc); err == nil {
		t.Fatal("offline query with empty question should fail")
	}
}

func TestDispatchQueryOfflineFlagAnywhere(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	rc := keyTestCtx(t)
	rc.useBuiltin = true
	if err := runBuild(rc); err != nil {
		t.Fatalf("build: %v", err)
	}
	for _, args := range [][]string{
		{"query", "-offline", "-index-dir", rc.indexDir, "网络配置"},
		{"query", "-index-dir", rc.indexDir, "网络配置", "-offline"},
	} {
		if rc := dispatch(args); rc != 0 {
			t.Errorf("dispatch %v rc=%d, want 0", args, rc)
		}
	}
}

type flakyEmbedder struct {
	failFirst int
	calls     int
}

func (f *flakyEmbedder) Name() string { return "flaky" }
func (f *flakyEmbedder) Dim() int     { return 2 }
func (f *flakyEmbedder) Embed(_ context.Context, texts []string) ([][]float32, error) {
	f.calls++
	if f.calls <= f.failFirst {
		return nil, errors.New(`http 400: {"code":20015,"message":"The parameter is invalid. Please check again."}`)
	}
	out := make([][]float32, len(texts))
	for i := range out {
		out[i] = []float32{1, 1}
	}
	return out, nil
}

func TestEmbedWithRetryRecoversFromTransientError(t *testing.T) {
	embedBackoff = func(int) time.Duration { return time.Millisecond }
	f := &flakyEmbedder{failFirst: 2}
	if _, err := embedWithRetry(context.Background(), f, []string{"a"}); err != nil {
		t.Fatalf("2 transient failures should be retried away, got %v", err)
	}
	if f.calls != 3 {
		t.Errorf("calls=%d, want 3", f.calls)
	}
}

func TestEmbedWithRetryGivesUpOnPersistentError(t *testing.T) {
	embedBackoff = func(int) time.Duration { return time.Millisecond }
	f := &flakyEmbedder{failFirst: 99}
	_, err := embedWithRetry(context.Background(), f, []string{"a"})
	if err == nil || !strings.Contains(err.Error(), "20015") {
		t.Fatalf("persistent error must surface unchanged, got %v", err)
	}
	if f.calls != embedRetries+1 {
		t.Errorf("calls=%d, want %d", f.calls, embedRetries+1)
	}
}
