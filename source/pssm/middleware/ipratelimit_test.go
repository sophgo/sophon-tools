package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestIPRateLimitEnforcesBurst(t *testing.T) {
	r := gin.New()
	// burst=2, refill=100ms：同 IP 前 2 个请求通过，第 3 个 429
	r.Use(IPRateLimit(2, 100*time.Millisecond))
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })

	for i := 1; i <= 3; i++ {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/ok", nil)
		req.RemoteAddr = "1.2.3.4:1234"
		r.ServeHTTP(w, req)
		switch i {
		case 1, 2:
			if w.Code != http.StatusOK {
				t.Fatalf("req #%d: expected 200, got %d", i, w.Code)
			}
		case 3:
			if w.Code != http.StatusTooManyRequests {
				t.Fatalf("req #%d: expected 429, got %d", i, w.Code)
			}
		}
	}
}

func TestIPRateLimitDifferentIPsIndependent(t *testing.T) {
	r := gin.New()
	r.Use(IPRateLimit(1, 100*time.Millisecond))
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })

	// IP A 消耗 token
	wA := httptest.NewRecorder()
	reqA := httptest.NewRequest(http.MethodGet, "/ok", nil)
	reqA.RemoteAddr = "10.0.0.1:1111"
	r.ServeHTTP(wA, reqA)
	if wA.Code != http.StatusOK {
		t.Fatalf("IP A first: expected 200, got %d", wA.Code)
	}

	// IP A 第二次应 429
	wA2 := httptest.NewRecorder()
	reqA2 := httptest.NewRequest(http.MethodGet, "/ok", nil)
	reqA2.RemoteAddr = "10.0.0.1:1111"
	r.ServeHTTP(wA2, reqA2)
	if wA2.Code != http.StatusTooManyRequests {
		t.Fatalf("IP A second: expected 429, got %d", wA2.Code)
	}

	// IP B 应独立通过
	wB := httptest.NewRecorder()
	reqB := httptest.NewRequest(http.MethodGet, "/ok", nil)
	reqB.RemoteAddr = "10.0.0.2:2222"
	r.ServeHTTP(wB, reqB)
	if wB.Code != http.StatusOK {
		t.Fatalf("IP B first: expected 200, got %d", wB.Code)
	}
}

func TestIPRateLimitConcurrent(t *testing.T) {
	r := gin.New()
	// burst=1, refill 很慢
	r.Use(IPRateLimit(1, 10*time.Second))
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })

	var wg sync.WaitGroup
	var okCount, limited int32
	var mu sync.Mutex

	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodGet, "/ok", nil)
			req.RemoteAddr = "1.2.3.4:1234"
			r.ServeHTTP(w, req)
			mu.Lock()
			if w.Code == http.StatusOK {
				okCount++
			} else if w.Code == http.StatusTooManyRequests {
				limited++
			}
			mu.Unlock()
		}()
	}
	wg.Wait()

	if okCount != 1 {
		t.Fatalf("expected exactly 1 OK (burst=1), got %d", okCount)
	}
	if limited != 9 {
		t.Fatalf("expected 9 limited, got %d", limited)
	}
}
