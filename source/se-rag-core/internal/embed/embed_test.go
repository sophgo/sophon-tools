package embed

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// 限流：单次最多3段的拆分（7 → 3+3+1 = 3 批）
func TestLimiterSplitsBatchesOfThree(t *testing.T) {
	l := NewEmbeddingLimiter(2)
	var calls atomic.Int64
	err := l.Do(context.Background(), 7, func() error { calls.Add(1); return nil })
	if err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 3 {
		t.Errorf("expected 3 call batches, got %d", calls.Load())
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
