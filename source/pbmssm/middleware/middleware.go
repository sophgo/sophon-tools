// Package middleware 提供 gin 中间件：Recovery / AccessLog / RateLimit。
package middleware

import (
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"bmssm/logger"
)

// Recovery 捕获 panic，返回 500 并记录日志。
func Recovery() gin.HandlerFunc {
	return gin.CustomRecoveryWithWriter(nil, func(c *gin.Context, rec any) {
		logger.Error("panic recovered: %v", rec)
		c.AbortWithStatus(http.StatusInternalServerError)
	})
}

// AccessLog 记录每个请求的方法/路径/状态/耗时。
func AccessLog() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		logger.Info("%s %s %d %v", c.Request.Method, c.Request.URL.Path, c.Writer.Status(), time.Since(start))
	}
}

// RateLimit 令牌桶限流：burst 突发上限，refillEvery 每补 1 token 的时间间隔。
func RateLimit(burst int, refillEvery time.Duration) gin.HandlerFunc {
	limiter := rate.NewLimiter(rate.Every(refillEvery), burst)
	return func(c *gin.Context) {
		if limiter.Allow() {
			c.Next()
			return
		}
		c.JSON(http.StatusServiceUnavailable, "Request too frequently, please try it later")
		c.Abort()
	}
}

// ipLimiterStore 每 IP 独立令牌桶存储。
type ipLimiterStore struct {
	mu       sync.Mutex
	limiters map[string]*rate.Limiter
	burst    int
	refill   time.Duration
}

func newIPLimiterStore(burst int, refill time.Duration) *ipLimiterStore {
	return &ipLimiterStore{
		limiters: make(map[string]*rate.Limiter),
		burst:    burst,
		refill:   refill,
	}
}

func (s *ipLimiterStore) get(ip string) *rate.Limiter {
	s.mu.Lock()
	defer s.mu.Unlock()
	if l, ok := s.limiters[ip]; ok {
		return l
	}
	l := rate.NewLimiter(rate.Every(s.refill), s.burst)
	s.limiters[ip] = l
	return l
}

// IPRateLimit 每 IP 独立令牌桶限流。burst 突发上限，refillEvery 每补 1 token 间隔。
// 超限返回 429。
func IPRateLimit(burst int, refillEvery time.Duration) gin.HandlerFunc {
	store := newIPLimiterStore(burst, refillEvery)
	return func(c *gin.Context) {
		ip := c.ClientIP()
		if store.get(ip).Allow() {
			c.Next()
			return
		}
		c.JSON(http.StatusTooManyRequests, gin.H{"error": "too many requests", "code": "RATE_LIMITED"})
		c.Abort()
	}
}
