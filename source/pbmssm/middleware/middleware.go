// Package middleware 提供 gin 中间件：Recovery / AccessLog / RateLimit。
package middleware

import (
	"net"
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
	// lastSeen 记录每个 IP 最近访问时间，用于清理过期条目，防止 map 无限增长。
	lastSeen map[string]time.Time
}

func newIPLimiterStore(burst int, refill time.Duration) *ipLimiterStore {
	s := &ipLimiterStore{
		limiters: make(map[string]*rate.Limiter),
		burst:    burst,
		refill:   refill,
		lastSeen: make(map[string]time.Time),
	}
	// 定期清理 10 分钟内未访问的 IP 限流器（防伪造 XFF 打爆内存）。
	go func() {
		ticker := time.NewTicker(5 * time.Minute)
		defer ticker.Stop()
		for range ticker.C {
			s.cleanup(time.Now().Add(-10 * time.Minute))
		}
	}()
	return s
}

func (s *ipLimiterStore) get(ip string) *rate.Limiter {
	s.mu.Lock()
	defer s.mu.Unlock()
	if l, ok := s.limiters[ip]; ok {
		s.lastSeen[ip] = time.Now()
		return l
	}
	l := rate.NewLimiter(rate.Every(s.refill), s.burst)
	s.limiters[ip] = l
	s.lastSeen[ip] = time.Now()
	return l
}

func (s *ipLimiterStore) cleanup(before time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for ip, seen := range s.lastSeen {
		if seen.Before(before) {
			delete(s.limiters, ip)
			delete(s.lastSeen, ip)
		}
	}
}

// realIP 返回客户端真实 IP（从 RemoteAddr 解析，忽略 X-Forwarded-For）。
// 防止攻击者伪造 XFF 头绕过每 IP 限流。
func realIP(c *gin.Context) string {
	host, _, err := net.SplitHostPort(c.Request.RemoteAddr)
	if err != nil {
		return c.Request.RemoteAddr
	}
	return host
}

// IPRateLimit 每 IP 独立令牌桶限流。burst 突发上限，refillEvery 每补 1 token 间隔。
// 超限返回 429。IP 取 RemoteAddr（忽略可伪造的 X-Forwarded-For）。
func IPRateLimit(burst int, refillEvery time.Duration) gin.HandlerFunc {
	store := newIPLimiterStore(burst, refillEvery)
	return func(c *gin.Context) {
		ip := realIP(c)
		if store.get(ip).Allow() {
			c.Next()
			return
		}
		c.JSON(http.StatusTooManyRequests, gin.H{"error": "too many requests", "code": "RATE_LIMITED"})
		c.Abort()
	}
}
