package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// TestTimeoutMiddlewareSlowHandler 验证超时行为：
// handler 超过超时时间仍慢速执行时，中间件返回超时响应且状态码为 200（与 mvc 约定一致），
// 同时 handler 在超时后写入的响应不得出现在返回体中（写入被丢弃）。
func TestTimeoutMiddlewareSlowHandler(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// handlerDone 保证断言发生在 handler（超时后）真正完成写入之后，
	// 避免因时序侥幸得到"看似正确"的结果。
	handlerDone := make(chan struct{})
	router := gin.New()
	router.Use(TimeoutMiddleware(50 * time.Millisecond))
	router.GET("/slow", func(c *gin.Context) {
		time.Sleep(200 * time.Millisecond)
		c.String(http.StatusOK, "SLOW DONE")
		close(handlerDone)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/slow", nil)
	router.ServeHTTP(w, req)
	<-handlerDone

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%q)", w.Code, w.Body.String())
	}
	if strings.Contains(w.Body.String(), "SLOW DONE") {
		t.Fatalf("超时后 handler 的写入不应出现在响应中: %q", w.Body.String())
	}
	var resp struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid json %q: %v", w.Body.String(), err)
	}
	if resp.Code != -1 || resp.Msg != "传输超时" {
		t.Fatalf("超时响应 = %+v, want code=-1 msg=传输超时", resp)
	}
}

// TestTimeoutMiddlewareFastHandler 验证未超时请求正常放行，响应不被改动。
func TestTimeoutMiddlewareFastHandler(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(TimeoutMiddleware(200 * time.Millisecond))
	router.GET("/fast", func(c *gin.Context) {
		c.String(http.StatusOK, "FAST DONE")
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/fast", nil)
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%q)", w.Code, w.Body.String())
	}
	if got := w.Body.String(); got != "FAST DONE" {
		t.Fatalf("body = %q, want %q", got, "FAST DONE")
	}
}

// TestTimeoutMiddlewareHandlerWriteHeaderDiscarded 验证超时后 handler 的 WriteHeader/Write
// 均被丢弃：即使 handler 在超时后写自定义状态码，客户端收到的仍是超时响应。
func TestTimeoutMiddlewareHandlerWriteHeaderDiscarded(t *testing.T) {
	gin.SetMode(gin.TestMode)

	handlerDone := make(chan struct{})
	router := gin.New()
	router.Use(TimeoutMiddleware(30 * time.Millisecond))
	router.GET("/late", func(c *gin.Context) {
		time.Sleep(150 * time.Millisecond)
		c.Writer.WriteHeader(http.StatusCreated)
		_, _ = c.Writer.Write([]byte("LATE BODY"))
		close(handlerDone)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/late", nil)
	router.ServeHTTP(w, req)
	<-handlerDone

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200（超时响应）(body=%q)", w.Code, w.Body.String())
	}
	if strings.Contains(w.Body.String(), "LATE BODY") {
		t.Fatalf("超时后 handler 写入不应出现在响应中: %q", w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "传输超时") {
		t.Fatalf("响应应包含超时消息: %q", w.Body.String())
	}
}
