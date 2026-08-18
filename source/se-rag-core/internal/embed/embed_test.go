package embed

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
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
	e, err := newSiliconflowEmbedder([]string{srv.URL}, "key", "BAAI/bge-m3", 2, true)
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
	if err := postJSON(context.Background(), []string{srv.URL}, "k", map[string]any{}, &out); err != nil {
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
	err := postJSON(context.Background(), []string{srv.URL}, "k", map[string]any{}, &out)
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
	r := &siliconflowReranker{baseURLs: []string{srv.URL}, apiKey: "k", model: "BAAI/bge-reranker-v2-m3"}
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

// Transport 必须配置 ResponseHeaderTimeout / TLSHandshakeTimeout（网关吞连接时不会无限挂起）。
func TestHTTPClientTimeouts(t *testing.T) {
	tr, ok := httpClient.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("httpClient.Transport = %T, want *http.Transport", httpClient.Transport)
	}
	if tr.ResponseHeaderTimeout <= 0 {
		t.Error("ResponseHeaderTimeout must be set (>0)")
	}
	if tr.TLSHandshakeTimeout <= 0 {
		t.Error("TLSHandshakeTimeout must be set (>0)")
	}
}

// 退避 sleep 感知 ctx：ctx 已取消时 postJSON 应立即返回，不走完 6 次指数退避。
func TestPostJSONRetryRespectsContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	start := time.Now()
	err := postJSON(ctx, []string{"http://127.0.0.1:1/v1/embeddings"}, "k", map[string]any{}, nil)
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, context.Canceled) {
		t.Errorf("want context.Canceled, got %v", err)
	}
	// 6 次退避累计约 5.1s；ctx 取消应立即返回
	if d := time.Since(start); d > 1*time.Second {
		t.Errorf("postJSON with canceled ctx took %v, want immediate return", d)
	}
}
