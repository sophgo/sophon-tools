package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// timeoutWriter 包装 gin.ResponseWriter：超时被标记后，handler 的后续写入
// （WriteHeader/Write/WriteString/WriteHeaderNow/Flush）全部丢弃，避免超时响应
// 发出后 handler 仍在后台写 ResponseWriter，产生 "superfluous WriteHeader" 与
// 响应字节交错。检查+写入在 mu 内原子完成，与 writeTimeoutResponse 的标记+写严格串行。
type timeoutWriter struct {
	gin.ResponseWriter
	mu        sync.Mutex // 保护 timedOut 标记，并串行化写入与标记
	timedOut  bool
	discarded http.Header // 超时标记后的占位 header：写入丢弃，不指向真实响应 header map
}

// writeTimeoutResponse 在锁内标记超时并写出超时响应：
// handler 侧的写入需等待本锁，看到 timedOut 后即被丢弃，因此对底层
// ResponseWriter 的写不会与 handler 写入交错。
// Content-Type 在此显式设置：Go 仅在 handler 未显式 WriteHeader 时才嗅探 body，
// 显式 WriteHeader(200) 会锁定默认 text/plain；锁内设置避免与 handler 侧的
// header map 写竞争（handler 在超时后经 Header() 拿到的是丢弃 map）。
// 最后 Flush：chunked 响应体默认缓冲 4KB，不 Flush 客户端要等 handler 结束后
// 才实际收到超时响应。
func (w *timeoutWriter) writeTimeoutResponse(status int, body []byte) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.timedOut = true
	w.ResponseWriter.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.ResponseWriter.WriteHeader(status)
	_, _ = w.ResponseWriter.Write(body)
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// Header 在超时标记后返回丢弃用 header：gin render 在写 body 前会先
// Header().Set("Content-Type", ...)，若不隔离，handler 在超时后仍会在真实
// 响应 header map 上写，与超时响应的写（Clone/遍历 map）竞争。
func (w *timeoutWriter) Header() http.Header {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return w.discarded
	}
	return w.ResponseWriter.Header()
}

func (w *timeoutWriter) WriteHeader(code int) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *timeoutWriter) WriteHeaderNow() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.ResponseWriter.WriteHeaderNow()
}

func (w *timeoutWriter) Write(data []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		// 超时后丢弃 handler 写入，防止与超时响应并发写
		return len(data), nil
	}
	return w.ResponseWriter.Write(data)
}

func (w *timeoutWriter) WriteString(s string) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return len(s), nil
	}
	return w.ResponseWriter.WriteString(s)
}

func (w *timeoutWriter) Flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.ResponseWriter.Flush()
}

func TimeoutMiddleware(timeOut time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		originWriter := c.Writer
		w := &timeoutWriter{ResponseWriter: originWriter, discarded: http.Header{}}
		c.Writer = w

		ctx, cancel := context.WithTimeout(c.Request.Context(), timeOut)
		defer cancel()

		c.Request = c.Request.WithContext(ctx)

		// handler 链继续在主 goroutine 上执行（c 单线程访问，无并发写 gin.Context）；
		// 辅助 goroutine 只做超时定时：超时后经 timeoutWriter 的锁标记丢弃并写超时
		// 响应。协程退出经 timerDone 通知，主 goroutine 收尾 join，为后续对响应的
		// 读取（含测试断言）建立 happens-before，避免响应读写竞争。
		done := make(chan struct{})
		timerDone := make(chan struct{})
		go func() {
			defer close(timerDone)
			timer := time.NewTimer(timeOut)
			defer timer.Stop()
			select {
			case <-done:
				// handler 在超时前完成，不干预
			case <-timer.C:
				// 请求超时，执行超时逻辑
				logger.Error("timeout on %s %s", c.Request.Method, c.Request.URL.Path)

				// 超时响应经包装 writer 在锁内写出：此后 handler 的写入（含
				// Header().Set）被丢弃，不会与超时响应交错。
				body, _ := json.Marshal(mvc.FailWithMsg(-1, "传输超时"))
				w.writeTimeoutResponse(http.StatusOK, body)
			}
		}()

		// 注意：请求的处理时间由 handler 决定（超时响应已按时发出，但当前 goroutine
		// 要等 handler 返回后才归还连接）；handler 如能响应 ctx.Done 可提前返回。
		c.Next()
		close(done)
		<-timerDone
	}
}
