package embed

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

// 以下测试覆盖网关故障转移链（CF Worker → 阿里云 FC 网关）：
// postJSON / siliconflow embedder 在首网关 5xx/连接失败时轮转到第二网关，两者都失败时有界退出。

func always500(url string, hits *atomic.Int64, fail int64) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if fail < 0 || hits.Load() <= fail {
			w.WriteHeader(500)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[]}`))
	}))
}

// 主网关 5xx 不可达 → 下一尝试轮转到 FC 网关并成功；两地址都被请求过。
func TestPostJSONFailoverToSecondURL(t *testing.T) {
	var cfHits, fcHits atomic.Int64
	cf := always500("cf", &cfHits, -1)
	defer cf.Close()
	fc := always500("fc", &fcHits, 0) // 首次即成功
	defer fc.Close()

	var out map[string]any
	if err := postJSON(context.Background(), []string{cf.URL, fc.URL}, "k", map[string]any{}, &out); err != nil {
		t.Fatalf("expected failover success, got %v", err)
	}
	if cfHits.Load() == 0 {
		t.Error("primary gateway was never attempted")
	}
	if fcHits.Load() == 0 {
		t.Error("fallback gateway was never attempted")
	}
}

// 连接层失败（非 HTTP 响应）同样触发轮转：首地址连接拒绝 → FC 成功。
func TestPostJSONFailoverOnConnRefused(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer srv.Close()
	// 127.0.0.1:1 连接立即被拒（无服务监听）
	var out map[string]any
	if err := postJSON(context.Background(), []string{"http://127.0.0.1:1/v1/embeddings", srv.URL + "/embeddings"}, "k", map[string]any{"model": "m", "input": []string{"hi"}}, &out); err != nil {
		t.Fatalf("expected failover on conn refused, got %v", err)
	}
}

// 两地址都 5xx → 有界失败（总尝试数 = maxAttempts，不无限挂起），报错指明多网关不可达。
func TestPostJSONAllGatewaysFailBounded(t *testing.T) {
	var hits atomic.Int64
	s1 := always500("s1", &hits, -1)
	defer s1.Close()
	var hits2 atomic.Int64
	s2 := always500("s2", &hits2, -1)
	defer s2.Close()

	var out map[string]any
	err := postJSON(context.Background(), []string{s1.URL, s2.URL}, "k", map[string]any{}, &out)
	if err == nil {
		t.Fatal("expected error when all gateways fail")
	}
	total := hits.Load() + hits2.Load()
	if total != maxAttempts {
		t.Errorf("total attempts = %d, want bounded %d", total, maxAttempts)
	}
	if !strings.Contains(err.Error(), "gateway") {
		t.Errorf("error should mention gateways, got %q", err)
	}
}

// siliconflow embedder 全链故障转移：CF 5xx → FC 正常返回 embedding。
func TestSiliconflowEmbedderFailover(t *testing.T) {
	var cfHits atomic.Int64
	cf := always500("cf", &cfHits, -1)
	defer cf.Close()
	fc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"index":0,"embedding":[1,0]}]}`))
	}))
	defer fc.Close()

	e, err := newSiliconflowEmbedder([]string{cf.URL, fc.URL}, "k", "BAAI/bge-m3", 2, false)
	if err != nil {
		t.Fatal(err)
	}
	vecs, err := e.Embed(context.Background(), []string{"SE7 芯片"})
	if err != nil {
		t.Fatalf("embedder failover failed: %v", err)
	}
	if len(vecs) != 1 || len(vecs[0]) != 2 {
		t.Fatalf("vecs = %v want 1x2", vecs)
	}
	if cfHits.Load() == 0 {
		t.Error("CF gateway was never attempted before failover")
	}
}

// reranker 同样带故障转移：CF 5xx → FC 返回精排结果。
func TestSiliconflowRerankerFailover(t *testing.T) {
	var cfHits atomic.Int64
	cf := always500("cf", &cfHits, -1)
	defer cf.Close()
	fc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"results":[{"index":0,"relevance_score":0.9}]}`))
	}))
	defer fc.Close()

	r, err := newSiliconflowReranker([]string{cf.URL, fc.URL}, "k", "BAAI/bge-reranker-v2-m3", false)
	if err != nil {
		t.Fatal(err)
	}
	order, err := r.Rerank(context.Background(), "q", []string{"a", "b"}, 1)
	if err != nil {
		t.Fatalf("reranker failover failed: %v", err)
	}
	if len(order) != 1 || order[0] != 0 {
		t.Fatalf("order = %v want [0]", order)
	}
	if cfHits.Load() == 0 {
		t.Error("CF gateway was never attempted before failover")
	}
}

// 4xx 快速失败不轮转：首网关 401 时不请求 FC（键/路径错误在任何网关都会复现）。
func TestPostJSONNoFailoverOn4xx(t *testing.T) {
	var cfHits, fcHits atomic.Int64
	cf := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cfHits.Add(1)
		w.WriteHeader(401)
	}))
	defer cf.Close()
	fc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fcHits.Add(1)
		w.WriteHeader(200)
	}))
	defer fc.Close()

	var out map[string]any
	err := postJSON(context.Background(), []string{cf.URL, fc.URL}, "k", map[string]any{}, &out)
	if err == nil {
		t.Fatal("expected auth error")
	}
	if fcHits.Load() != 0 {
		t.Errorf("fallback attempted %d times on 4xx, want 0", fcHits.Load())
	}
}