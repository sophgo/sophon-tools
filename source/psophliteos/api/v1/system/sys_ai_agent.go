package system

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"sophliteos/logger"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
	"github.com/patrickmn/go-cache"
)

// AiAgentApi AI Agent 功能：picoclaw web 端口探测与转发、本地模型样例。
// LLM/VLM API 配置由 bmssm 的 /api/v1/llm-proxy/config 管理（sophliteos 不再刷新 picoclaw）。
//
// MYS-379 安全加固：路由已叠加 SSO（见 router/system/sys_ai_agent.go）。本层：
//   - 探测目标身份校验：部署锚定（设备已安装 sophpicoclaw）+ 候选端口白名单 + HTTP 探针；
//   - 探测结果缓存（ok 30s / miss 5s）：消除每请求 4 次探测的资源消耗、
//     探测与代理间的 TOCTOU 竞态，以及端口扫描式反馈；
//   - 代理路径/方法白名单：只放行 picoclaw Web 控制台常规路径，禁止任意路径透传；
//   - 失败仅回显通用提示，不透露探测细节。
type AiAgentApi struct{}

const defaultPicoclawPort = 18800 // picoclaw web 默认端口（sophpicoclaw-launcher）

// picoclawCandidates 允许探测与代理的目标端口白名单（出厂部署口径）：
// 18800 sophpicoclaw-launcher Web 控制台；18790 sophpicoclaw gateway；
// 8081/18801 历史手工部署遗留端口。代理目标只允许来自本列表。
// 包级变量便于测试注入。
var picoclawCandidates = []int{defaultPicoclawPort, 18790, 8081, 18801}

// 探测结果缓存：命中端口后 okTTL 内复用；未命中负缓存 missTTL（防探测风暴与
// 端口扫描反馈面）。TTL 为变量便于测试缩短。
var (
	probeOKTTL  = 30 * time.Second
	probeMissTTL = 5 * time.Second
	probeCache   = cache.New(30*time.Second, time.Minute)
)

// probeMu 串行化真实探测，避免并发请求同时触发多个探测。
var probeMu sync.Mutex

// picoclawInstalled 部署锚定：设备是否已安装 sophpicoclaw（仅检查配置目录存在）。
// 口径与 pbmssm devproxyKeyPath 一致：SOPHON_PICOCLAW_HOME → /opt/sophon/picoclaw
// （出厂路径）→ 当前部署用户 ~/.picoclaw（手工部署）。包级变量便于测试注入。
var picoclawInstalled = func() bool {
	dirs := []string{}
	if home := os.Getenv("SOPHON_PICOCLAW_HOME"); home != "" {
		dirs = append(dirs, filepath.Join(home, ".picoclaw"))
	}
	dirs = append(dirs,
		"/opt/sophon/picoclaw/.picoclaw",
		filepath.Join(os.Getenv("HOME"), ".picoclaw"),
	)
	for _, d := range dirs {
		if st, err := os.Stat(d); err == nil && st.IsDir() {
			return true
		}
	}
	return false
}

// picoclawWebUp 探测 127.0.0.1:port 上是否为 picoclaw web（GET / 返回 2xx/3xx）。
// 不跟随重定向：picoclaw Web 控制台 GET / 即 302（README 验证口径），
// 避免探测被 Location 带到本机其他服务。包级变量便于测试注入。
var picoclawWebUp = func(port int) bool {
	client := &http.Client{
		Timeout:       3 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	url := fmt.Sprintf("http://127.0.0.1:%d/", port)
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	// 仅消费少量响应体，防大响应占用
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	return resp.StatusCode >= 200 && resp.StatusCode < 400
}

// detectPicoclawPort 返回确认可用的 picoclaw web 端口；up=false 表示未确认可用
// （此时返回默认端口以兼容旧行为，调用方应结合 up 判定）。
// 先查缓存（ok 30s / miss 5s），未命中才加锁探测；同一缓存结果被 port 端点与
// proxy 共享，消除「探测目标与代理目标不一致」的 TOCTOU。
func detectPicoclawPort() (port int, up bool) {
	if v, ok := probeCache.Get("port"); ok {
		return probeCached(v), v.(int) >= 0
	}
	probeMu.Lock()
	defer probeMu.Unlock()
	// 双重检查：锁内其他请求可能已完成探测
	if v, ok := probeCache.Get("port"); ok {
		return probeCached(v), v.(int) >= 0
	}
	if !picoclawInstalled() {
		probeCache.Set("port", -1, probeMissTTL) // 无安装锚定：负缓存，不探测
		return defaultPicoclawPort, false
	}
	for _, p := range picoclawCandidates {
		if picoclawWebUp(p) {
			probeCache.Set("port", p, probeOKTTL)
			return p, true
		}
	}
	probeCache.Set("port", -1, probeMissTTL)
	return defaultPicoclawPort, false
}

// probeCached 把缓存值还原为对外端口：负缓存（-1，未确认可用）统一回退默认端口，
// 保持 port 字段始终是合法端口值，仅 up 区分确认状态。
func probeCached(v interface{}) int {
	if p := v.(int); p >= 0 {
		return p
	}
	return defaultPicoclawPort
}

// resetPicoclawProbeCache 清空探测缓存（测试用）。
func resetPicoclawProbeCache() {
	probeCache.Flush()
}

// Port GET 返回探测到的 picoclaw web 端口；up 标识服务是否确认可用。
// 探测失败仅回传 up=false，不回显任何端口探测细节。
func (a *AiAgentApi) Port(c *gin.Context) {
	port, up := detectPicoclawPort()
	c.JSON(http.StatusOK, mvc.Success(gin.H{"port": port, "up": up}))
}

// picoclawProxyPathAllowed 代理路径白名单：只放行 picoclaw Web 控制台常规路径
// （入口页/静态资源/控制台 API/聊天 WebSocket），禁止任意路径透传。
// 对路径穿越（..、反斜杠、编码穿越）一律拒绝。
func picoclawProxyPathAllowed(p string) bool {
	if p == "" || strings.Contains(p, "..") || strings.Contains(p, "\\") {
		return false
	}
	clean := p
	if i := strings.IndexByte(clean, '?'); i >= 0 {
		clean = clean[:i]
	}
	switch {
	case clean == "/" || clean == "/index.html" || clean == "/favicon.ico" || clean == "/robots.txt":
		return true
	case strings.HasPrefix(clean, "/api/"):
		return true
	case clean == "/ws" || strings.HasPrefix(clean, "/ws/"):
		return true
	}
	if i := strings.LastIndexByte(clean, '.'); i > 0 {
		switch strings.ToLower(clean[i:]) {
		case ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
			".woff", ".woff2", ".webp", ".map", ".txt":
			return true
		}
	}
	return false
}

// picoclawProxyMethodAllowed 代理方法白名单：禁 CONNECT/TRACE 等隧道/反射原语。
func picoclawProxyMethodAllowed(m string) bool {
	switch m {
	case http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut,
		http.MethodDelete, http.MethodPatch, http.MethodOptions:
		return true
	}
	return false
}

// Proxy 反向代理 picoclaw web（保留路径与查询串；供 iframe 同源访问使用）。
// 仅代理「已确认的 AI 助手服务」：安装锚定 + 候选端口白名单 + HTTP 探针
// （探测结果缓存复用，无 TOCTOU）；路径/方法经白名单校验；
// 任何失败只回显通用提示，不泄露探测与目标细节。
func (a *AiAgentApi) Proxy(c *gin.Context) {
	port, up := detectPicoclawPort()
	if !up {
		c.JSON(http.StatusBadGateway, mvc.Fail(-1, "AI 助手服务未就绪"))
		return
	}
	// 路径取自通配参数（gin proxy/*any），归一化斜杠后走白名单；
	// 不能直接用 URL.Path——其含 /api/device/ai-agent/proxy 前缀。
	targetPath := c.Param("any")
	if !strings.HasPrefix(targetPath, "/") {
		targetPath = "/" + targetPath
	}
	if !picoclawProxyMethodAllowed(c.Request.Method) || !picoclawProxyPathAllowed(targetPath) {
		c.JSON(http.StatusForbidden, mvc.Fail(-1, "forbidden"))
		return
	}
	target, err := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", port))
	if err != nil {
		c.JSON(http.StatusBadGateway, mvc.Fail(-1, "AI 助手服务未就绪"))
		return
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
		logger.Error("picoclaw 代理错误 %s %s: %v", r.Method, r.URL.Path, e)
		w.WriteHeader(http.StatusBadGateway) // 只给状态码，不回显内部错误
	}
	proxy.ServeHTTP(c.Writer, c.Request)
}