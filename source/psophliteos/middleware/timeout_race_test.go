package middleware

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// TestTimeoutMiddlewareHeaderRaceDeterministic 稳定复现 MYS-2888 的响应头竞态。
//
// 场景：handler 先经 c.Writer.Header() 取到响应头引用，然后在超时 goroutine 写
// 超时响应之后（这里用超过超时窗口的 sleep 保证真实先后顺序，不依赖随机调度）继续
// 通过该引用与 gin render 修改 header map。旧实现里 Header() 返回的是底层真实
// map，超时 goroutine 与 handler 对同一张 map 的写之间没有任何 happens-before，
// `go test -race` 必然报 DATA RACE（另一侧栈为 gin render.writeContentType）；
// 修复后 handler 拿的是私有 map，超时 goroutine 只写底层 map，二者无共享内存。
func TestTimeoutMiddlewareHeaderRaceDeterministic(t *testing.T) {
	gin.SetMode(gin.TestMode)

	const timeout = 20 * time.Millisecond

	router := gin.New()
	router.Use(TimeoutMiddleware(timeout))
	router.GET("/race", func(c *gin.Context) {
		// handler 提前取得 header 引用（旧实现下即底层真实 map）
		h := c.Writer.Header()
		h.Set("X-Before", "1")

		// 等到超时 goroutine 已经写出超时响应之后，再用同一引用改 header
		time.Sleep(6 * timeout)

		h.Set("Content-Type", "application/json; charset=utf-8")
		h.Set("X-Handler-Late", "1")
		// gin render 写 body 前同样会 Header().Set("Content-Type")
		c.JSON(http.StatusOK, gin.H{"code": 0, "msg": "handler done"})
	})

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/race", nil))

	// 超时响应已经发出（handler 也已完成），响应体必须是超时响应且不含 handler 内容
	if !strings.Contains(w.Body.String(), "传输超时") {
		t.Fatalf("响应应为超时响应, got %q", w.Body.String())
	}
	if strings.Contains(w.Body.String(), "handler done") {
		t.Fatalf("超时后 handler 的写入不应出现在响应中: %q", w.Body.String())
	}
	if got := w.Header().Get("X-Handler-Late"); got != "" {
		t.Fatalf("超时后 handler 的 header 不应出现在响应中: %q", got)
	}
}

// TestTimeoutMiddlewareResponseHeadersPreserved 未超时请求的响应头/Content-Type/
// cookie 必须完整保留（header 改为 handler 私有 map 后不得丢失）。
func TestTimeoutMiddlewareResponseHeadersPreserved(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(func(c *gin.Context) { c.Header("X-Inherited", "outer") })
	router.Use(TimeoutMiddleware(2 * time.Second))
	router.GET("/headers", func(c *gin.Context) {
		if got := c.Writer.Header().Get("X-Inherited"); got != "outer" {
			t.Errorf("inherited header = %q, want outer", got)
		}
		c.Writer.Header().Del("X-Inherited")
		c.Header("Content-Type", "text/plain; charset=utf-8")
		c.Header("X-Custom", "custom-value")
		c.SetCookie("session", "abc123", 3600, "/", "", false, true)
		// 显式删除：提交前删除的 header 不得残留
		c.Header("X-Dropped", "temp")
		c.Writer.Header().Del("X-Dropped")
		_, _ = c.Writer.WriteString("part-1|")
		_, _ = c.Writer.Write([]byte("part-2"))
	})
	// 只设 header、不写 body 的路由：由中间件收尾 + gin 统一 WriteHeaderNow 提交
	router.GET("/headers-only", func(c *gin.Context) {
		c.Header("X-Only", "only-value")
		c.Writer.WriteHeader(http.StatusAccepted)
	})

	t.Run("写 body 的普通请求", func(t *testing.T) {
		w := httptest.NewRecorder()
		router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/headers", nil))

		if w.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", w.Code)
		}
		if got := w.Result().Header.Get("X-Inherited"); got != "" {
			t.Errorf("deleted inherited header remains: %q", got)
		}
		if got := w.Body.String(); got != "part-1|part-2" {
			t.Fatalf("body = %q, want part-1|part-2", got)
		}
		if got := w.Header().Get("Content-Type"); got != "text/plain; charset=utf-8" {
			t.Fatalf("Content-Type = %q, want text/plain; charset=utf-8", got)
		}
		if got := w.Header().Get("X-Custom"); got != "custom-value" {
			t.Fatalf("X-Custom = %q, want custom-value", got)
		}
		if got := w.Header().Get("X-Dropped"); got != "" {
			t.Fatalf("已删除的 header 残留: %q", got)
		}
		if got := w.Header().Get("Set-Cookie"); !strings.Contains(got, "session=abc123") {
			t.Fatalf("Set-Cookie = %q, want 含 session=abc123", got)
		}
	})

	t.Run("只设 header 的普通请求", func(t *testing.T) {
		w := httptest.NewRecorder()
		router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/headers-only", nil))

		if w.Code != http.StatusAccepted {
			t.Fatalf("status = %d, want 202", w.Code)
		}
		if got := w.Header().Get("X-Only"); got != "only-value" {
			t.Fatalf("X-Only = %q, want only-value（handler 返回后 header 丢失）", got)
		}
	})
}

// TestTimeoutMiddlewareStreamingFlush 流式响应：Flush 必须把此前的 handler header
// 一起提交，且多次 Write/Flush 的内容与顺序不受包装影响。
func TestTimeoutMiddlewareStreamingFlush(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(TimeoutMiddleware(2 * time.Second))
	router.GET("/stream", func(c *gin.Context) {
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		c.Writer.Flush() // 首帧前先提交响应头
		for _, chunk := range []string{"chunk-1\n", "chunk-2\n", "chunk-3\n"} {
			_, _ = c.Writer.WriteString(chunk)
			c.Writer.Flush()
		}
	})

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/stream", nil))

	if got := w.Body.String(); got != "chunk-1\nchunk-2\nchunk-3\n" {
		t.Fatalf("body = %q, want 三段顺序拼接", got)
	}
	if got := w.Header().Get("Content-Type"); got != "text/event-stream" {
		t.Fatalf("Content-Type = %q, want text/event-stream（Flush 前设置的 header 丢失）", got)
	}
	if got := w.Header().Get("Cache-Control"); got != "no-cache" {
		t.Fatalf("Cache-Control = %q, want no-cache", got)
	}
	if !w.Flushed {
		t.Fatal("Flush 未生效")
	}
}

// TestTimeoutMiddlewareTimeoutResponseIsPrompt 超时响应必须在 handler 返回前就
// 送达客户端（依赖超时路径的 Flush；不 Flush 时 chunked 响应会被缓冲到 handler
// 结束），客户端不必等到 handler 收尾才拿到超时内容。
func TestTimeoutMiddlewareTimeoutResponseIsPrompt(t *testing.T) {
	gin.SetMode(gin.TestMode)

	const (
		timeout     = 50 * time.Millisecond
		handlerTime = 1 * time.Second
	)

	router := gin.New()
	router.Use(TimeoutMiddleware(timeout))
	router.GET("/slow", func(c *gin.Context) {
		time.Sleep(handlerTime)
		c.String(http.StatusOK, "SLOW DONE")
	})

	srv := httptest.NewServer(router)
	defer srv.Close()

	start := time.Now()
	resp, err := http.Get(srv.URL + "/slow")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	// 读到首段已 flush 的数据即可判定"响应已可见"，不必等 handler 结束导致 EOF
	buf := make([]byte, 512)
	n, err := resp.Body.Read(buf)
	elapsed := time.Since(start)
	resp.Body.Close()
	if err != nil && n == 0 {
		t.Fatalf("read body: %v", err)
	}
	if elapsed >= handlerTime {
		t.Fatalf("首段响应耗时 %v，未在 handler 返回前送达", elapsed)
	}
	var parsed struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
	}
	if err := json.Unmarshal(buf[:n], &parsed); err != nil {
		t.Fatalf("invalid json %q: %v", string(buf[:n]), err)
	}
	if parsed.Code != -1 || parsed.Msg != "传输超时" {
		t.Fatalf("超时响应 = %+v, want code=-1 msg=传输超时", parsed)
	}
	if got := resp.Header.Get("Content-Type"); got != "application/json; charset=utf-8" {
		t.Fatalf("超时响应 Content-Type = %q", got)
	}
}

// TestTimeoutMiddlewareDiscardsWritesAfterTimeout 超时后 handler 的所有写入
// （header/WriteHeader/Write/WriteString/Flush）都必须丢弃，响应内容与状态码
// 保持超时响应本身，且不会产生 "superfluous WriteHeader" 式的二次提交。
func TestTimeoutMiddlewareDiscardsWritesAfterTimeout(t *testing.T) {
	gin.SetMode(gin.TestMode)

	const timeout = 20 * time.Millisecond

	done := make(chan struct{})
	router := gin.New()
	router.Use(TimeoutMiddleware(timeout))
	router.GET("/late", func(c *gin.Context) {
		defer close(done)
		time.Sleep(5 * timeout)
		c.Header("Content-Type", "text/plain")
		c.Header("X-Late", "1")
		c.Writer.WriteHeader(http.StatusCreated)
		c.Writer.WriteHeaderNow()
		_, _ = c.Writer.Write([]byte("LATE BODY"))
		_, _ = c.Writer.WriteString("LATE STRING")
		c.Writer.Flush()
	})

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/late", nil))
	<-done

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200（超时响应）", w.Code)
	}
	if got := w.Body.String(); strings.Contains(got, "LATE") || !strings.Contains(got, "传输超时") {
		t.Fatalf("超时后写入未丢弃: %q", got)
	}
	if got := w.Header().Get("Content-Type"); got != "application/json; charset=utf-8" {
		t.Fatalf("Content-Type = %q, 被超时后 handler 的 header 覆盖", got)
	}
	if got := w.Header().Get("X-Late"); got != "" {
		t.Fatalf("超时后 handler 的 header 出现在响应中: %q", got)
	}
}

// TestTimeoutMiddlewareNoTimerLeak handler 返回（含超时后返回）必须是"无存活 timer
// goroutine"：一轮请求前后 goroutine 数应回到基线，避免慢请求与瞬时请求交替时
// timer 协程堆积。
func TestTimeoutMiddlewareNoTimerLeak(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(TimeoutMiddleware(10 * time.Millisecond))
	router.GET("/fast", func(c *gin.Context) { c.String(http.StatusOK, "ok") })
	router.GET("/slow", func(c *gin.Context) {
		time.Sleep(30 * time.Millisecond)
		c.String(http.StatusOK, "slow")
	})

	serve := func(path string) {
		w := httptest.NewRecorder()
		router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
	}

	serve("/fast") // 预热：让 gin/日志等一次性初始化完成
	baseline := runtime.NumGoroutine()

	for i := 0; i < 20; i++ {
		serve("/fast")
		serve("/slow")
	}

	// timer 协程由中间件在 handler 返回前 join，因此应当立刻回到基线附近
	if got := runtime.NumGoroutine(); got > baseline+2 {
		t.Fatalf("请求结束后 goroutine = %d, 基线 %d（疑似 timer 协程泄漏）", got, baseline)
	}
}

// TestTimeoutMiddlewarePanicStillJoinsTimer handler panic 上抛（gin.Recovery 兜底）时
// 中间件也必须 join 超时协程，不能留下仍在写响应的 goroutine。
func TestTimeoutMiddlewarePanicStillJoinsTimer(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(TimeoutMiddleware(20 * time.Millisecond))
	router.GET("/panic", func(c *gin.Context) {
		c.Header("X-Before-Panic", "1")
		panic("boom")
	})

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/panic", nil))

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", w.Code)
	}
	if got := w.Header().Get("X-Before-Panic"); got != "1" {
		t.Fatalf("panic 前设置的 header 丢失: %q", got)
	}
}

// TestTimeoutMiddlewareReverseProxyStreaming 覆盖生产组合：TimeoutMiddleware +
// httputil.ReverseProxy。反向代理在 handler goroutine 里写响应头、并在写 body 时
// 由 flush 定时 goroutine 触发 Flush；用 SSE 上游（flushInterval=-1，每帧立即
// Flush）与带 trailer 的响应各跑一遍，验证：
//   - 流式内容逐帧透传，不因包装 writer 丢失或延迟；
//   - 上游响应头（含 Content-Type/trailer）在提交前就被镜像、不丢失；
//   - 无响应头竞态（go test -race 下必须无 DATA RACE）。
func TestTimeoutMiddlewareReverseProxyStreaming(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/sse":
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.WriteHeader(http.StatusOK)
			for _, f := range []string{"event: a\n\n", "event: b\n\n"} {
				_, _ = io.WriteString(w, f)
				w.(http.Flusher).Flush()
			}
		default:
			// 带 trailer 的普通响应：反代在 body 之后再写 header map
			w.Header().Set("Trailer", "X-Checksum")
			w.Header().Set("Content-Type", "text/plain")
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, "payload")
			w.Header().Set("X-Checksum", "abc123")
		}
	}))
	defer upstream.Close()

	target, err := url.Parse(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}

	router := gin.New()
	router.Use(TimeoutMiddleware(5 * time.Second))
	router.Any("/*any", func(c *gin.Context) {
		// 等价生产：router 里 `proxy.ServeHTTP(c.Writer, c.Request)`
		httputil.NewSingleHostReverseProxy(target).ServeHTTP(c.Writer, c.Request)
	})

	front := httptest.NewServer(router)
	defer front.Close()

	t.Run("SSE 流式逐帧透传", func(t *testing.T) {
		resp, err := http.Get(front.URL + "/sse")
		if err != nil {
			t.Fatalf("GET: %v", err)
		}
		defer resp.Body.Close()
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatalf("read: %v", err)
		}
		if got := string(body); got != "event: a\n\nevent: b\n\n" {
			t.Fatalf("body = %q", got)
		}
		if got := resp.Header.Get("Content-Type"); got != "text/event-stream" {
			t.Fatalf("Content-Type = %q, want text/event-stream", got)
		}
		if got := resp.Header.Get("Cache-Control"); got != "no-cache" {
			t.Fatalf("Cache-Control = %q, want no-cache", got)
		}
	})

	t.Run("响应头与 trailer 不丢失", func(t *testing.T) {
		resp, err := http.Get(front.URL + "/plain")
		if err != nil {
			t.Fatalf("GET: %v", err)
		}
		defer resp.Body.Close()
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatalf("read: %v", err)
		}
		if got := string(body); got != "payload" {
			t.Fatalf("body = %q, want payload", got)
		}
		if got := resp.Header.Get("Content-Type"); got != "text/plain" {
			t.Fatalf("Content-Type = %q, want text/plain", got)
		}
		if got := resp.Trailer.Get("X-Checksum"); got != "abc123" {
			t.Fatalf("trailer X-Checksum = %q, want abc123（finish 未补齐提交后 header）", got)
		}
	})
}
