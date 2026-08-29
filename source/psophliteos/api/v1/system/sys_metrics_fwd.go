package system

import (
	"crypto/subtle"
	"io"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"sophliteos/config"
	"sophliteos/database"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

// MetricsFwdApi 指标转发：sophliteos :8080/metrics 反代 bmssm 9779 /metrics。
// 目标是设备只暴露 8080 一个端口（bmssm 仅监听回环）；转发默认关闭，
// 开启后由静态 token 保护（Prometheus 侧配 authorization: credentials）。
type MetricsFwdApi struct{}

// ---- 抓取统计（内存，重启清零，页面标注"自服务启动"） ----

type fwdStats struct {
	mu         sync.Mutex
	OK         int64     // 成功转发次数
	Err401     int64     // token 缺失/错误
	Err502     int64     // bmssm 不可达
	LastScrape time.Time // 最近一次成功转发
	LastError  string    // 最近一次错误（含 401/502）
	StartedAt  time.Time // 统计起点（进程启动）
}

var fwdStat = fwdStats{StartedAt: time.Now()}

func (s *fwdStats) record(kind string, errMsg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch kind {
	case "ok":
		atomic.AddInt64(&s.OK, 1)
		s.LastScrape = time.Now()
		s.LastError = ""
	case "401":
		atomic.AddInt64(&s.Err401, 1)
		s.LastError = errMsg
	case "502":
		atomic.AddInt64(&s.Err502, 1)
		s.LastError = errMsg
	}
}

func (s *fwdStats) snapshot() (ok, e401, e502 int64, lastScrape time.Time, lastErr string, since time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.OK, s.Err401, s.Err502, s.LastScrape, s.LastError, s.StartedAt
}

// bmssmBase 从配置取 bmssm 地址（与 initialization/router 反代一致，缺省 127.0.0.1:9779）。
func bmssmBase() string {
	s := "127.0.0.1:9779"
	if v := config.Conf.GetViper(); v != nil {
		if s2 := v.GetString("bmssm.server"); s2 != "" {
			s = s2
		}
	}
	return "http://" + s
}

// fwdClient 抓取 bmssm 的专用 client（5s 超时：指标采集是轻量短请求）。
var fwdClient = &http.Client{Timeout: 5 * time.Second}

// Forward GET /metrics —— 公开端点（不走 SSO，供 Prometheus 抓取）。
// 关闭 → 404（不暴露功能存在性）；开启 → Bearer token 校验 → 透传 bmssm /metrics。
func (a *MetricsFwdApi) Forward(c *gin.Context) {
	cfg := database.LoadMetricsForward()
	if !cfg.Enabled {
		c.JSON(http.StatusNotFound, gin.H{"message": "404 page not found"})
		return
	}

	auth := c.GetHeader("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(auth, prefix) || subtle.ConstantTimeCompare(
		[]byte(strings.TrimPrefix(auth, prefix)), []byte(cfg.Token)) != 1 {
		fwdStat.record("401", "unauthorized: invalid or missing bearer token")
		c.Header("WWW-Authenticate", `Bearer realm="metrics"`)
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid or missing bearer token"})
		return
	}

	resp, err := fwdClient.Get(bmssmBase() + "/metrics")
	if err != nil {
		fwdStat.record("502", "bmssm unreachable: "+err.Error())
		c.String(http.StatusBadGateway, "metrics forward: bmssm unreachable")
		return
	}
	defer resp.Body.Close()

	fwdStat.record("ok", "")
	// 透传内容类型与响应体（Prometheus 文本协议，直接流式拷贝）
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		c.Header("Content-Type", ct)
	}
	c.Status(resp.StatusCode)
	io.Copy(c.Writer, resp.Body)
}

// Status GET /api/device/metrics-forward —— 开关状态、token、抓取统计、bmssm 可达性。
func (a *MetricsFwdApi) Status(c *gin.Context) {
	cfg, err := database.EnsureForwardToken()
	if err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "db error: "+err.Error()))
		return
	}
	ok, e401, e502, lastScrape, lastErr, since := fwdStat.snapshot()

	// 即时健康探测：bmssm /healthz
	reachable := false
	if r, err := fwdClient.Get(bmssmBase() + "/healthz"); err == nil {
		r.Body.Close()
		reachable = r.StatusCode == http.StatusOK
	}

	c.JSON(http.StatusOK, mvc.Success(gin.H{
		"enabled": cfg.Enabled,
		"token":   cfg.Token,
		"stats": gin.H{
			"scrapeOK":     ok,
			"scrapeErr401": e401,
			"scrapeErr502": e502,
			"lastScrapeAt": lastScrape,
			"lastError":    lastErr,
			"sinceStart":   since,
		},
		"bmssmReachable": reachable,
	}))
}

// SetEnabled PUT /api/device/metrics-forward —— 开/关。开启时自动补 token。
func (a *MetricsFwdApi) SetEnabled(c *gin.Context) {
	var req struct {
		Enabled *bool `json:"enabled" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil || req.Enabled == nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "invalid request body: enabled required"))
		return
	}
	cfg := database.LoadMetricsForward()
	cfg.Enabled = *req.Enabled
	if cfg.Enabled && cfg.Token == "" {
		tok, err := database.NewForwardToken()
		if err != nil {
			c.JSON(http.StatusOK, mvc.Fail(-1, "token generation failed: "+err.Error()))
			return
		}
		cfg.Token = tok
	}
	if err := database.SaveMetricsForward(cfg); err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "db error: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, mvc.Success(gin.H{"enabled": cfg.Enabled, "token": cfg.Token}))
}

// RotateToken POST /api/device/metrics-forward/token —— 轮换 token（旧 token 立即失效）。
func (a *MetricsFwdApi) RotateToken(c *gin.Context) {
	cfg := database.LoadMetricsForward()
	tok, err := database.NewForwardToken()
	if err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "token generation failed: "+err.Error()))
		return
	}
	cfg.Token = tok
	if err := database.SaveMetricsForward(cfg); err != nil {
		c.JSON(http.StatusOK, mvc.Fail(-1, "db error: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, mvc.Success(gin.H{"token": cfg.Token}))
}
