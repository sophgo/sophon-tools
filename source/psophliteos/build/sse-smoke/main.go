// sse-smoke 是 sophliteos SSO/SSE 的并发冒烟工具（MYS-2885）。
//
// 它把 middleware 中真实的 SSOEvents / SSORegister / SSOLogout 挂到一个独立进程内的
// 隔离测试服务上（只监听 127.0.0.1 回环，不读配置、不连 bmssm、不接触任何生产会话），
// 再由 driver 拉起多个**独立 OS 进程**并发高频执行 register + SSE 建连，用于验证：
//   - 真实连接计数与上限、以及被顶号后旧流是否立即关闭；
//   - 每 IP 建连频率限制；
//   - 结束后服务端连接零残留；
//   - 配合 -race 构建检查数据竞争（见 build/sse-smoke.sh）。
//
// 用法（一般由 build/sse-smoke.sh 驱动，不直接手调）：
//
//	sse-smoke -mode=server -addr=127.0.0.1:0 -ready-file=/tmp/addr
//	sse-smoke -mode=client -addr=127.0.0.1:PORT -client=1 -source-ip=127.0.0.2 -duration=35s
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

// serverStats 服务端统计（由 /stats 返回）。active/max 是**真实 HTTP 连接数**，
// 在 handler 包裹层统计（SSOEvents 会一直阻塞到该流结束），不依赖内部实现细节。
type serverStats struct {
	Requests          int64 `json:"requests"`          // 全部请求数
	SSEAttempts       int64 `json:"sseAttempts"`       // SSE 建连尝试数
	SSEAccepted       int64 `json:"sseAccepted"`       // 建连成功数（200）
	SSERejected       int64 `json:"sseRejected"`       // 被拒数（非 200）
	SSEUnauthorized   int64 `json:"sseUnauthorized"`   // 401（非活跃会话）
	SSERateLimited    int64 `json:"sseRateLimited"`    // 429
	ActiveConnections int64 `json:"activeConnections"` // 当前活跃 SSE 连接
	MaxConnections    int64 `json:"maxConnections"`    // 峰值活跃 SSE 连接
	Registers         int64 `json:"registers"`         // register 请求数
	Logouts           int64 `json:"logouts"`           // logout 请求数
	OfflineEventsSent int64 `json:"offlineEventsSent"` // 服务端写出的 SESSION_OFFLINE 事件数
}

var (
	statRequests    int64
	statSSEAttempts int64
	statSSEAccepted int64
	statSSERejected int64
	statSSEUnauth   int64
	statSSERate     int64
	statActive      int64
	statMax         int64
	statRegisters   int64
	statLogouts     int64
	statOfflineSent int64
)

// clientResult 单个客户端进程的结果。
type clientResult struct {
	Client        int      `json:"client"`
	SourceIP      string   `json:"sourceIp"`
	DurationMS    int64    `json:"durationMs"`
	Registers     int64    `json:"registers"`
	Logouts       int64    `json:"logouts"`
	SSEAttempts   int64    `json:"sseAttempts"`
	SSEOpened     int64    `json:"sseOpened"`
	SSERejected   int64    `json:"sseRejected"`
	OfflineEvents int64    `json:"offlineEvents"`
	ClosedBySrv   int64    `json:"closedByServer"`
	ClientAborts  int64    `json:"clientAborts"`
	UniqueTokens  int64    `json:"uniqueTokens"`
	Errors        []string `json:"errors,omitempty"`
}

func main() {
	mode := flag.String("mode", "server", "server | client")
	addr := flag.String("addr", "127.0.0.1:0", "监听地址（server）或目标地址（client）")
	readyFile := flag.String("ready-file", "", "server: 启动后把实际监听地址写入该文件")
	sourceIP := flag.String("source-ip", "", "client: 本地绑定源 IP（模拟不同来源，规避每 IP 频率限制）")
	clientID := flag.Int("client", 1, "client: 客户端编号")
	tabs := flag.Int("tabs", 8, "client: 每会话并发持有的 SSE 连接数（模拟多标签页）")
	connsPerMin := flag.Int("conns-per-min", 60, "client: 本进程每分钟建连尝试上限（客户端侧预算）")
	duration := flag.Duration("duration", 35*time.Second, "client: 持续运行时长")
	flag.Parse()

	switch *mode {
	case "server":
		runServer(*addr, *readyFile)
	case "client":
		runClient(*addr, *sourceIP, *clientID, *tabs, *connsPerMin, *duration)
	default:
		fmt.Fprintf(os.Stderr, "unknown -mode %q\n", *mode)
		os.Exit(2)
	}
}

// runServer 起隔离的 SSO/SSE 测试服务。
// 注意：register 直接调用 middleware.SSORegister（跳过 bmssm JWT 校验），因为这里
// 验证的是 SSE 连接/会话回收，不是鉴权；服务只在回环地址上面向本机冒烟客户端。
func runServer(addr, readyFile string) {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.POST("/api/sso/register", func(c *gin.Context) {
		atomic.AddInt64(&statRequests, 1)
		atomic.AddInt64(&statRegisters, 1)
		var req struct {
			Username string `json:"username"`
			Token    string `json:"token"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Username == "" || req.Token == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
			return
		}
		middleware.SSORegister(req.Username, req.Token)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	r.POST("/api/sso/logout", func(c *gin.Context) {
		atomic.AddInt64(&statRequests, 1)
		atomic.AddInt64(&statLogouts, 1)
		middleware.SSOLogout(middleware.SSORequestToken(c))
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	// SSE：包裹真实 handler，统计真实连接数/峰值/拒绝原因。
	r.GET("/api/sso/events", func(c *gin.Context) {
		atomic.AddInt64(&statRequests, 1)
		atomic.AddInt64(&statSSEAttempts, 1)
		atomic.AddInt64(&statActive, 1)
		for {
			cur := atomic.LoadInt64(&statActive)
			prev := atomic.LoadInt64(&statMax)
			if cur <= prev || atomic.CompareAndSwapInt64(&statMax, prev, cur) {
				break
			}
		}
		defer atomic.AddInt64(&statActive, -1)

		middleware.SSOEvents(c)

		switch c.Writer.Status() {
		case http.StatusOK:
			atomic.AddInt64(&statSSEAccepted, 1)
		case http.StatusUnauthorized:
			atomic.AddInt64(&statSSEUnauth, 1)
			atomic.AddInt64(&statSSERejected, 1)
		case http.StatusTooManyRequests:
			atomic.AddInt64(&statSSERate, 1)
			atomic.AddInt64(&statSSERejected, 1)
		default:
			atomic.AddInt64(&statSSERejected, 1)
		}
	})

	r.GET("/stats", func(c *gin.Context) {
		c.JSON(http.StatusOK, serverStats{
			Requests:          atomic.LoadInt64(&statRequests),
			SSEAttempts:       atomic.LoadInt64(&statSSEAttempts),
			SSEAccepted:       atomic.LoadInt64(&statSSEAccepted),
			SSERejected:       atomic.LoadInt64(&statSSERejected),
			SSEUnauthorized:   atomic.LoadInt64(&statSSEUnauth),
			SSERateLimited:    atomic.LoadInt64(&statSSERate),
			ActiveConnections: atomic.LoadInt64(&statActive),
			MaxConnections:    atomic.LoadInt64(&statMax),
			Registers:         atomic.LoadInt64(&statRegisters),
			Logouts:           atomic.LoadInt64(&statLogouts),
			OfflineEventsSent: middleware.SSEOfflineNotified(),
		})
	})

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "listen %s: %v\n", addr, err)
		os.Exit(1)
	}
	if readyFile != "" {
		if err := os.WriteFile(readyFile, []byte(ln.Addr().String()), 0o644); err != nil {
			fmt.Fprintf(os.Stderr, "write ready file: %v\n", err)
			os.Exit(1)
		}
	}
	fmt.Printf("LISTEN %s\n", ln.Addr().String())
	os.Stdout.Sync()

	srv := &http.Server{Handler: r, ReadHeaderTimeout: 30 * time.Second}
	if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
		fmt.Fprintf(os.Stderr, "serve: %v\n", err)
		os.Exit(1)
	}
}

// runClient 是一个独立客户端进程：循环"注册会话 → 并发建立多条 SSE 长连接（多标签页）
// → 持有若干秒 → 关闭"。多个客户端各自注册不同 token 互相顶号，因此可观测
// SESSION_OFFLINE 与服务端主动关闭旧流；每 5 轮以同 token 重注册，覆盖幂等保护路径。
//
// 建连节奏受"每 IP 每分钟 10 次"这条独立限流约束，故每个客户端使用一组源 IP
// （-source-ip 起向后顺延），并做客户端侧预算：每分钟最多 -conns-per-min 次建连尝试，
// 保证冒烟打到的是"连接计数/回收"逻辑，而不是被频率限制整体淹没。
func runClient(addr, sourceIP string, id, tabs int, connsPerMin int, duration time.Duration) {
	username := fmt.Sprintf("smoke-user-%d", id)
	ipPool := buildIPPool(sourceIP)
	// 每个源 IP 一个独立 Transport：连接不共享，便于统计与清理
	clients := make([]*http.Client, 0, len(ipPool))
	for _, ip := range ipPool {
		clients = append(clients, newLocalHTTPClient(ip))
	}
	if len(clients) == 0 {
		clients = append(clients, newLocalHTTPClient(nil))
	}

	res := clientResult{Client: id, SourceIP: sourceIP}
	deadline := time.Now().Add(duration)
	start := time.Now()
	var errMu sync.Mutex
	addErr := func(format string, args ...interface{}) {
		errMu.Lock()
		defer errMu.Unlock()
		if len(res.Errors) < 5 {
			res.Errors = append(res.Errors, fmt.Sprintf(format, args...))
		}
	}

	// 客户端侧建连预算（滑动一分钟）
	var connTimes []time.Time
	allowConn := func() bool {
		now := time.Now()
		cutoff := now.Add(-time.Minute)
		kept := connTimes[:0]
		for _, t := range connTimes {
			if t.After(cutoff) {
				kept = append(kept, t)
			}
		}
		connTimes = kept
		if len(connTimes) >= connsPerMin {
			return false
		}
		connTimes = append(connTimes, now)
		return true
	}

	var lastTok string
	lastTokConns := 0
	ipIdx := 0
	nextClient := func() *http.Client {
		c := clients[ipIdx%len(clients)]
		ipIdx++
		return c
	}

	for time.Now().Before(deadline) {
		// 1) 注册会话：多数轮次换新 token（模拟重新登录/多端登录互踢），
		//    每 5 轮复用上一 token 且沿用已有连接，覆盖"同 token 重注册幂等"路径。
		hc := nextClient()
		reuse := res.Registers%5 == 4 && lastTok != "" && lastTokConns > 0
		tok := fmt.Sprintf("tok-%d-%d", id, time.Now().UnixNano())
		if reuse {
			tok = lastTok
		} else {
			res.UniqueTokens++
			lastTokConns = 0
		}
		lastTok = tok

		body := fmt.Sprintf(`{"username":%q,"token":%q}`, username, tok)
		if req, err := http.NewRequest(http.MethodPost, "http://"+addr+"/api/sso/register", strings.NewReader(body)); err != nil {
			addErr("register req: %v", err)
		} else {
			req.Header.Set("Content-Type", "application/json")
			if resp, err := hc.Do(req); err != nil {
				addErr("register: %v", err)
			} else {
				io.Copy(io.Discard, resp.Body)
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					res.Registers++
				} else {
					addErr("register status %d", resp.StatusCode)
				}
			}
		}

		// 2) 并发建立多标签页连接，持有到本轮结束；期间其他客户端的登录会顶掉这些流
		holdUntil := time.Now().Add(1500 * time.Millisecond)
		if holdUntil.After(deadline) {
			holdUntil = deadline
		}
		var opened, rejected, offline, closed int64
		var wg sync.WaitGroup
		for t := 0; t < tabs; t++ {
			if !allowConn() {
				break
			}
			tc := nextClient() // 只在主 goroutine 里取，避免共享下标竞争
			wg.Add(1)
			go func(hc *http.Client) {
				defer wg.Done()
				o, off, ok, rej := streamOnce(hc, addr, tok, holdUntil)
				if ok {
					atomic.AddInt64(&opened, 1)
				}
				if rej {
					atomic.AddInt64(&rejected, 1)
				}
				if off {
					atomic.AddInt64(&offline, 1)
				}
				if o {
					atomic.AddInt64(&closed, 1)
				}
			}(tc)
		}
		wg.Wait()

		res.SSEAttempts += opened + rejected
		res.SSEOpened += opened
		res.SSERejected += rejected
		res.OfflineEvents += offline
		res.ClosedBySrv += closed
		if reuse {
			lastTokConns += int(opened)
		}

		// 3) 偶尔主动注销，覆盖 logout / 会话清空路径
		if res.Registers%3 == 0 {
			if req, err := http.NewRequest(http.MethodPost, "http://"+addr+"/api/sso/logout", nil); err == nil {
				req.Header.Set("Authorization", "Bearer "+tok)
				if resp, err := hc.Do(req); err == nil {
					io.Copy(io.Discard, resp.Body)
					resp.Body.Close()
					if resp.StatusCode == http.StatusOK {
						res.Logouts++
					}
				}
			}
		}

		time.Sleep(time.Duration(5+(id*7)%25) * time.Millisecond)
	}

	res.DurationMS = time.Since(start).Milliseconds()
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(res)
}

// buildIPPool 由 -source-ip 基址构造一组回环源地址（默认 127.0.0.2 起 8 个）。
// Linux 回环整段 127.0.0.0/8 均可用，仅本机生效，不影响宿主网络配置。
// driver 为各客户端分配互不重叠的基址，避免"每 IP 每分钟 10 次"被多进程共享后整体触顶。
func buildIPPool(base string) []net.IP {
	if base == "" {
		base = "127.0.0.2"
	}
	ip4 := net.ParseIP(base).To4()
	if ip4 == nil {
		fmt.Fprintf(os.Stderr, "invalid -source-ip %q\n", base)
		os.Exit(2)
	}
	out := make([]net.IP, 0, 8)
	first := int(ip4[3])
	for i := 0; i < 8; i++ {
		last := (first + i) % 250
		if last == 0 {
			last = 1
		}
		out = append(out, net.IPv4(ip4[0], ip4[1], ip4[2], byte(last)))
	}
	return out
}

// newLocalHTTPClient 构造绑定指定本地源 IP 的 HTTP 客户端。
func newLocalHTTPClient(ip net.IP) *http.Client {
	return &http.Client{
		Transport: &http.Transport{
			DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
				d := &net.Dialer{Timeout: 5 * time.Second}
				if ip != nil {
					d.LocalAddr = &net.TCPAddr{IP: ip}
				}
				return d.DialContext(ctx, network, address)
			},
			MaxIdleConns:        16,
			MaxIdleConnsPerHost: 16,
		},
	}
}

// streamOnce 建立一条 SSE 连接并读到结束；返回 (服务端主动关闭, 收到离线事件, 建连成功, 被拒)。
func streamOnce(httpClient *http.Client, addr, token string, deadline time.Time) (closedBySrv, offline, opened, rejected bool) {
	ctx, cancel := context.WithDeadline(context.Background(), deadline)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+addr+"/api/sso/events", nil)
	if err != nil {
		return
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := httpClient.Do(req)
	if err != nil {
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		io.Copy(io.Discard, resp.Body)
		return false, false, false, true
	}

	br := bufio.NewReader(resp.Body)
	for {
		line, err := br.ReadString('\n')
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "event: ") {
			if strings.TrimPrefix(trimmed, "event: ") == "SESSION_OFFLINE" {
				offline = true
			}
		}
		if err != nil {
			// ctx 到期（本客户端主动收工/本轮保持时间到）不算服务端关闭；
			// 只有收到 SESSION_OFFLINE 后被服务端结束的，或对端主动断开（EOF 且未到期）才算。
			closedBySrv = offline || (ctx.Err() == nil && !errors.Is(err, context.DeadlineExceeded))
			return closedBySrv, offline, true, false
		}
	}
}
