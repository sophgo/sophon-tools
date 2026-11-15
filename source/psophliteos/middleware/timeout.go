package middleware

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"slices"
	"sync"
	"time"

	"sophliteos/logger"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

// timeoutWriter 包装 gin.ResponseWriter，解决超时 goroutine 与 handler 并发修改
// 同一张响应头 map 的竞态（MYS-2888）。
//
// 根因：gin 的 ResponseWriter.Header() 直接返回底层 http.ResponseWriter 的 header
// map，取到 map 后即解锁，调用方后续的 Header().Set/Del 落在锁外；超时 goroutine
// 写超时响应时同样经 Header().Set 写这张 map，于是与 handler 的 header 写入并发
// （`go test -race` 报 mapassign 竞争，另一侧栈为 gin render.writeContentType）。
//
// 修复是切分 header 归属，让两侧没有共享内存：
//   - handler 独占私有 map hdr，Header() 恒返回它，handler 的 Header().Set/Del/Add
//     不再碰底层 map；
//   - 在提交响应头的路径（WriteHeader/WriteHeaderNow/Write/WriteString/Flush/
//     Hijack）于 mu 内把 hdr 镜像到底层响应头，再调底层 writer；
//   - 超时 goroutine 只在 mu 内写底层响应头（超时响应自带 Content-Type），既不读
//     也不写 hdr；
//   - 超时标记后 handler 的写入（header、WriteHeader、Write、WriteString、Flush）
//     一律丢弃。
//
// 不变式：hdr 只由 handler goroutine 读写，且只在底层响应头尚未提交（gin 的
// Written() 为 false）时被镜像读取——底层一旦提交，header map 已随响应冻结，
// 再镜像无效果（handler 提交后追加的 header，如反向代理 trailer，由 finish 在
// handler goroutine 上补齐）。镜像不能在 gin 的 WriteHeader 处"只做一次"：gin 的
// WriteHeader 只记录状态码，c.JSON 先 Status() 再由 render 设 Content-Type，提前
// 封口会丢 Content-Type。
//
// 为什么其余 goroutine 不会读 hdr：Flush 是唯一可能被别的 goroutine 调用的写方法
// （ReverseProxy 的 flush 定时 goroutine），但它只在 ReverseProxy 已调用
// WriteHeader 之后才被创建：要么此时 handler 已把 hdr 镜像并提交（Written() 为 true，
// 跳过镜像），要么 handler goroutine 正阻塞在同一个 mu 上（hdr 处于静止状态）。
// proxy 的 trailer 写入发生在 mlw.stop() 之后，仍在 handler goroutine 上。
type timeoutWriter struct {
	gin.ResponseWriter

	mu       sync.Mutex          // 串行化底层 writer：提交响应头、写 body、超时响应
	hdr      http.Header         // handler 私有响应头，仅 handler goroutine 读写
	synced   map[string]struct{} // 已镜像到底层的 key，用于同步 handler 的删除
	timedOut bool
}

// mirrorHeadersLocked 把 handler 私有响应头完整镜像到底层响应头（调用方持 mu）。
func (w *timeoutWriter) mirrorHeadersLocked() {
	dst := w.ResponseWriter.Header()
	for k, vv := range w.hdr {
		w.synced[k] = struct{}{}
		if old, ok := dst[k]; ok && slices.Equal(old, vv) {
			continue
		}
		// 复制切片：不把 hdr 的切片共享给底层 map，避免 handler 之后对同 key 的
		// 原地 Append 改到底层已提交的内容。
		dst[k] = slices.Clone(vv)
	}
	for k := range w.synced {
		if _, ok := w.hdr[k]; !ok {
			delete(dst, k)
			delete(w.synced, k)
		}
	}
}

// commitHeadersLocked 在提交响应头之前镜像 handler header（调用方持 mu）。
// 底层已提交则跳过：镜像无效果，且可避免其它 goroutine（反向代理的 flush 定时
// goroutine 会调 Flush）读 handler 正在写的 map。
func (w *timeoutWriter) commitHeadersLocked() {
	if w.ResponseWriter.Written() {
		return
	}
	w.mirrorHeadersLocked()
}

// writeTimeoutResponse 在锁内标记超时并写出超时响应：handler 侧的写入需等待本锁，
// 看到 timedOut 后即被丢弃，因此对底层 ResponseWriter 的写不会与 handler 写入交错。
// Content-Type 在此显式设置：Go 仅在 handler 未显式 WriteHeader 时才嗅探 body，显式
// WriteHeader(200) 会锁定默认 text/plain。handler 私有 header 不参与超时响应（超时后
// handler 的 header 一律丢弃，不污染客户端拿到的响应）。
// 最后 Flush：chunked 响应体默认缓冲 4KB，不 Flush 客户端要等 handler 结束后才实际
// 收到超时响应。
func (w *timeoutWriter) writeTimeoutResponse(status int, body []byte) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.timedOut = true
	w.ResponseWriter.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.ResponseWriter.WriteHeader(status)
	_, _ = w.ResponseWriter.Write(body)
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// finish 在 handler 返回、超时 goroutine 已 join 之后由 handler goroutine 调用：
// 非超时响应无条件把 handler 私有 header 同步到底层，保证两点——
//  1. handler 只设 header 不写 body 时，gin 在中间件返回后统一 WriteHeaderNow 仍能
//     带上这些 header；
//  2. handler 在响应头提交之后追加的 header（ReverseProxy 的 trailer）不丢失。
func (w *timeoutWriter) finish() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.mirrorHeadersLocked()
}

// Header 返回 handler 私有响应头：handler 侧的 header 操作不会落到超时 goroutine
// 正在写的底层 map 上。gin render 在写 body 前会先 Header().Set("Content-Type", ...)，
// 该写入随后在 Write/WriteString 的锁内镜像到底层。
func (w *timeoutWriter) Header() http.Header {
	return w.hdr
}

func (w *timeoutWriter) WriteHeader(code int) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.commitHeadersLocked()
	w.ResponseWriter.WriteHeader(code)
}

func (w *timeoutWriter) WriteHeaderNow() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.commitHeadersLocked()
	w.ResponseWriter.WriteHeaderNow()
}

func (w *timeoutWriter) Write(data []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		// 超时后丢弃 handler 写入，防止与超时响应并发写
		return len(data), nil
	}
	w.commitHeadersLocked()
	return w.ResponseWriter.Write(data)
}

func (w *timeoutWriter) WriteString(s string) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return len(s), nil
	}
	w.commitHeadersLocked()
	return w.ResponseWriter.WriteString(s)
}

func (w *timeoutWriter) Flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timedOut {
		return
	}
	w.commitHeadersLocked()
	w.ResponseWriter.Flush()
}

// Status/Size/Written 读的是底层 gin writer 的 status/size 字段，超时 goroutine 写
// 超时响应时同样改这些字段（WriteHeader/Write/Hijack 都会动），因此一并串行化。
func (w *timeoutWriter) Status() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.ResponseWriter.Status()
}

func (w *timeoutWriter) Size() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.ResponseWriter.Size()
}

func (w *timeoutWriter) Written() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.ResponseWriter.Written()
}

// Hijack 同样串行化：gin ResponseWriter 的 Hijack 会改 size 字段，与超时响应的
// Write 竞争同一字段。Hijack 后连接归 handler，超时响应再写底层 writer 只会得到
// ErrHijacked，不会污染已接管的连接。
func (w *timeoutWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.commitHeadersLocked()
	return w.ResponseWriter.Hijack()
}

// Unwrap 让 http.ResponseController 能穿透本包装拿到底层 writer
// （SetReadDeadline/SetWriteDeadline/EnableFullDuplex 等连接级能力），
// 与 gin.ResponseWriter 原有的组合方式保持一致。
func (w *timeoutWriter) Unwrap() http.ResponseWriter {
	return w.ResponseWriter
}

func TimeoutMiddleware(timeOut time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		w := &timeoutWriter{
			ResponseWriter: c.Writer,
			hdr:            http.Header{},
			synced:         map[string]struct{}{},
		}
		c.Writer = w

		ctx, cancel := context.WithTimeout(c.Request.Context(), timeOut)
		defer cancel()

		c.Request = c.Request.WithContext(ctx)

		// handler 链继续在主 goroutine 上执行（c 单线程访问，无并发写 gin.Context）；
		// 辅助 goroutine 只做超时定时：超时后经 timeoutWriter 的锁标记丢弃并写超时
		// 响应。协程退出经 timerDone 通知，主 goroutine 收尾 join，为后续对响应的
		// 读取（测试断言、外层 gin.Recovery）建立 happens-before，避免响应读写竞争。
		// join 放在 defer：handler panic 上抛时同样不会留下仍在写响应的超时 goroutine。
		done := make(chan struct{})
		timerDone := make(chan struct{})
		defer func() {
			close(done)
			<-timerDone
			w.finish()
		}()

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
	}
}
