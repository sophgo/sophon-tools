package embed

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// 限流：8 段文本按单次≤2 段拆 → 2+2+2+2 四批
func TestLimiterSplitsBatchesOfTwo(t *testing.T) {
	l := NewEmbeddingLimiter(1)
	var sizes []int
	_, err := l.Embed(context.Background(), []string{"a", "b", "c", "d", "e", "f", "g", "h"},
		func(batch []string) ([][]float32, error) {
			sizes = append(sizes, len(batch))
			out := make([][]float32, len(batch))
			for i := range batch {
				out[i] = []float32{float32(i)}
			}
			return out, nil
		})
	if err != nil {
		t.Fatal(err)
	}
	want := []int{2, 2, 2, 2}
	if fmt.Sprint(sizes) != fmt.Sprint(want) {
		t.Errorf("batch sizes = %v, want %v", sizes, want)
	}
}

// 内置 key 下，HTTP 服务端收到的每个 embedding 载荷段落数必须 ≤2
func TestSiliconflowEmbedderBatchLeq2(t *testing.T) {
	var maxPayload atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Input []string `json:"input"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if n := int64(len(req.Input)); n > maxPayload.Load() {
			maxPayload.Store(n)
		}
		w.Header().Set("Content-Type", "application/json")
		// 逐段返回 embedding，index 对齐
		var data []map[string]any
		for i := range req.Input {
			data = append(data, map[string]any{"index": i, "embedding": []float32{1, 0}})
		}
		b, _ := json.Marshal(map[string]any{"data": data})
		w.Write(b)
	}))
	defer srv.Close()

	// 用内置 key 模式构造（useBuiltinKey=true → 启用限流）
	e, err := newSiliconflowEmbedder(srv.URL, "key", "BAAI/bge-m3", 2, true)
	if err != nil {
		t.Fatal(err)
	}
	texts := []string{"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
	vecs, err := e.Embed(context.Background(), texts)
	if err != nil {
		t.Fatal(err)
	}
	if int(maxPayload.Load()) > 2 {
		t.Errorf("server received payload of %d paragraphs (>2) under builtin key", maxPayload.Load())
	}
	if len(vecs) != len(texts) {
		t.Errorf("got %d vectors want %d", len(vecs), len(texts))
	}
}

// 服务端 500 → 重试成功
func TestPostJSONRetries(t *testing.T) {
	var n atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if n.Add(1) < 3 {
			w.WriteHeader(500)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[]}`))
	}))
	defer srv.Close()
	var out map[string]any
	if err := postJSON(context.Background(), srv.URL, "k", map[string]any{}, &out); err != nil {
		t.Fatalf("expected retry success, got %v", err)
	}
}

// 4xx 不重试
func TestPostJSONNoRetryOn4xx(t *testing.T) {
	var n atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
		w.WriteHeader(401)
	}))
	defer srv.Close()
	var out map[string]any
	err := postJSON(context.Background(), srv.URL, "k", map[string]any{}, &out)
	if err == nil {
		t.Fatal("expected auth error")
	}
	if n.Load() != 1 {
		t.Errorf("expected no retry on 4xx, calls=%d", n.Load())
	}
}

func TestSiliconflowEmbedder(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer srv.Close()
	e, err := NewSiliconflowEmbedderFromURL(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	vecs, err := e.Embed(context.Background(), []string{"SE7 芯片"})
	if err != nil {
		t.Fatal(err)
	}
	if len(vecs) != 1 || len(vecs[0]) != 2 {
		t.Fatalf("vecs = %v want 1x2", vecs)
	}
}

func TestSiliconflowReranker(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.5}]}`))
	}))
	defer srv.Close()
	r := &siliconflowReranker{baseURL: srv.URL, apiKey: "k", model: "BAAI/bge-reranker-v2-m3"}
	got, err := r.Rerank(context.Background(), "q", []string{"a", "b"}, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != 1 {
		t.Fatalf("rerank order = %v want [1 0]", got)
	}
}

func TestSophnetEmbedder(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"index":0,"embedding":[0,1]}]}`))
	}))
	defer srv.Close()
	e := &sophnetEmbedder{baseURL: srv.URL, apiKey: "k", model: "bge-m3", dim: 2}
	vecs, err := e.Embed(context.Background(), []string{"hi"})
	if err != nil {
		t.Fatal(err)
	}
	if len(vecs) != 1 || vecs[0][1] != 1 {
		t.Fatalf("sophnet vecs = %v", vecs)
	}
}

var _ = json.Marshal
