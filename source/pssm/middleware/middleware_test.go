package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestRecoveryCatchesPanic(t *testing.T) {
	r := gin.New()
	r.Use(Recovery())
	r.GET("/boom", func(c *gin.Context) { panic("x") })
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/boom", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", w.Code)
	}
}

// TestRateLimitEnforcesBurst 真实验证令牌桶：burst=2 初始满桶，前 2 个请求消耗完，
// 第 3 个请求因无可用 token 被拒（503）。refillEvery=100ms 保证测试期间不补 token。
func TestRateLimitEnforcesBurst(t *testing.T) {
	r := gin.New()
	r.Use(RateLimit(2, 100*time.Millisecond))
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })

	for i := 1; i <= 3; i++ {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/ok", nil)
		r.ServeHTTP(w, req)
		switch i {
		case 1, 2:
			if w.Code != http.StatusOK {
				t.Fatalf("req #%d: expected 200, got %d", i, w.Code)
			}
		case 3:
			if w.Code != http.StatusServiceUnavailable {
				t.Fatalf("req #%d: expected 503 (bucket drained), got %d", i, w.Code)
			}
		}
	}
}

func TestAccessLogNoPanic(t *testing.T) {
	r := gin.New()
	r.Use(AccessLog())
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ok", nil)
	r.ServeHTTP(w, req) // 不 panic 即通过
}
