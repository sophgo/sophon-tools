package middleware

// sso_events_test.go 用真实 HTTP 服务 + 可取消的长连接验证 SSE 端点行为，
// 不只检查内存 map：
//   - 全局连接上限按"真实连接数"计（旧实现按 token 桶数，上限形同虚设）；
//   - 单 token 上限在真实连接上生效；
//   - 会话被顶掉后推送 SESSION_OFFLINE 并结束旧流（旧实现推完继续挂住，连接累积）；
//   - 同 token 重复 register 幂等，不误踢当前有效会话；
//   - 会话校验与订阅原子化：不会出现"校验通过但漏收离线通知"的窗口；
//   - 客户端取消/写失败后连接计数立即回收，容量可复用；
//   - register/logout 与握手交错并发无死锁、无 race（配合 -race 运行）。

import (
	"bufio"
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// --- 真实 SSE 客户端 ---------------------------------------------------------

type sseLine struct {
	line string
	err  error
}

// sseStream 是一条到 /api/sso/events 的真实长连接。
type sseStream struct {
	resp    *http.Response
	lines   chan sseLine
	cancel  context.CancelFunc
	closeMu sync.Once
}

// close 主动断开客户端（模拟关页面/网络中断）。
func (s *sseStream) close() {
	s.closeMu.Do(func() {
		s.cancel()
		if s.resp != nil && s.resp.Body != nil {
			_ = s.resp.Body.Close()
		}
	})
}

// waitEvent 等待指定事件名出现；超时即失败。
func (s *sseStream) waitEvent(t *testing.T, name string, timeout time.Duration) {
	t.Helper()
	deadline := time.After(timeout)
	want := "event: " + name
	for {
		select {
		case l, ok := <-s.lines:
			if !ok {
				t.Fatalf("等待事件 %s 时流已结束（未收到该事件）", name)
			}
			if l.err != nil {
				t.Fatalf("等待事件 %s 时读流失败: %v", name, l.err)
			}
			if strings.TrimSpace(l.line) == want {
				return
			}
		case <-deadline:
			t.Fatalf("%v 内未收到事件 %s（旧流未被通知/推送丢失）", timeout, name)
		}
	}
}

// expectNoEvent 断言在窗口内没有收到指定事件（用于幂等保护回归）。
func (s *sseStream) expectNoEvent(t *testing.T, name string, window time.Duration) {
	t.Helper()
	deadline := time.After(window)
	want := "event: " + name
	for {
		select {
		case l, ok := <-s.lines:
			if !ok {
				t.Fatalf("流意外结束（期望保持连接）；等待窗口内不应收到 %s", name)
			}
			if l.err != nil {
				t.Fatalf("读流失败: %v", l.err)
			}
			if strings.TrimSpace(l.line) == want {
				t.Fatalf("收到不应出现的 %s（幂等 register 把当前有效会话误踢）", name)
			}
		case <-deadline:
			return
		}
	}
}

// waitClosed 断言服务端结束了该流（客户端读到 EOF）。
func (s *sseStream) waitClosed(t *testing.T, timeout time.Duration) {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case l, ok := <-s.lines:
			if !ok || l.err == io.EOF {
				return
			}
			// 忽略离线事件之后的其它行，继续等 EOF
		case <-deadline:
			t.Fatalf("%v 内旧流未关闭（服务端未在 SESSION_OFFLINE 后释放连接）", timeout)
		}
	}
}

// newSSEEventsServer 起一个只挂 SSE 端点的真实 HTTP 服务（与生产路由同路径）。
// 关停前先断开本用例登记的所有客户端，避免失败路径上 httptest.Server.Close
// 等到超时（旧实现的失效连接永不结束）。
func newSSEEventsServer(t *testing.T) *httptest.Server {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/sso/events", SSOEvents)
	srv := httptest.NewServer(r)
	var mu sync.Mutex
	var opened []*sseStream
	register := func(s *sseStream) {
		mu.Lock()
		opened = append(opened, s)
		mu.Unlock()
	}
	t.Cleanup(func() {
		mu.Lock()
		for _, s := range opened {
			s.close()
		}
		mu.Unlock()
		// 服务端 handler 退出后才能 Close 返回：给一个有界窗口
		done := make(chan struct{})
		go func() { srv.Close(); close(done) }()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			srv.CloseClientConnections()
			<-done
		}
	})
	sseTrackedServers.Store(srv, register)
	return srv
}

// sseTrackedServers 记录测试服务 → 客户端登记函数，供 openSSE 自动登记。
var sseTrackedServers sync.Map // *httptest.Server -> func(*sseStream)

// openSSE 建立一条 SSE 长连接；返回连接与 HTTP 状态码。
func openSSE(t *testing.T, srv *httptest.Server, token string) (*sseStream, int) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/api/sso/events", nil)
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := srv.Client().Do(req)
	if err != nil {
		cancel()
		t.Fatalf("SSE 请求失败: %v", err)
	}
	s := &sseStream{resp: resp, lines: make(chan sseLine, 32), cancel: cancel}
	if reg, ok := sseTrackedServers.Load(srv); ok {
		reg.(func(*sseStream))(s)
	}
	if resp.StatusCode != http.StatusOK {
		// 拒绝路径没有事件流：读完即关，避免连接泄漏
		_, _ = io.Copy(io.Discard, resp.Body)
		s.close()
		return s, resp.StatusCode
	}
	go func() {
		defer close(s.lines)
		br := bufio.NewReader(resp.Body)
		for {
			line, err := br.ReadString('\n')
			if line != "" {
				s.lines <- sseLine{line: line}
			}
			if err != nil {
				s.lines <- sseLine{err: err}
				return
			}
		}
	}()
	return s, resp.StatusCode
}

// openSSEExpectOK 建立连接并断言 200。
func openSSEExpectOK(t *testing.T, srv *httptest.Server, token string) *sseStream {
	t.Helper()
	s, code := openSSE(t, srv, token)
	if code != http.StatusOK {
		t.Fatalf("SSE 建连状态=%d want 200", code)
	}
	return s
}

// waitConnCount 等待连接计数达到期望值（回收是异步的，给一个有界窗口）。
func waitConnCount(t *testing.T, want int, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for {
		if got := ssoConnCount(); got == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("SSE 连接计数=%d want %d（%v 内未收敛，疑似连接泄漏）", ssoConnCount(), want, timeout)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// --- 单 token 上限：按真实连接数 ---------------------------------------------

func TestSSOEventsPerTokenCapOnRealConnections(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)

	streams := make([]*sseStream, 0, sseMaxClientsPerToken)
	for i := 0; i < sseMaxClientsPerToken; i++ {
		streams = append(streams, openSSEExpectOK(t, srv, "token-a"))
	}
	waitConnCount(t, sseMaxClientsPerToken, 2*time.Second)

	// 第 9 条：超过单 token 上限 → 429（先清每 IP 频率窗口，隔离出单 token 上限）
	resetSSEConnTimes()
	if s, code := openSSE(t, srv, "token-a"); code != http.StatusTooManyRequests {
		if s != nil {
			s.close()
		}
		t.Fatalf("超过单 token 上限: 状态=%d want 429", code)
	}

	for _, s := range streams {
		s.close()
	}
	waitConnCount(t, 0, 2*time.Second)
}

// --- 全局上限：按真实连接数统计（旧实现数 token 桶数，上限永远不生效） --------

func TestSSOEventsGlobalCapCountsConnections(t *testing.T) {
	resetSSOState()
	// 平台同一时刻只有一个活跃会话（单点登录），因此真实连接数只能来自同一 token；
	// 要把 32 这条全局上限单独立起来，这里把它调小到 3（生产值 32 由
	// TestSSEDefaultThresholds 锁定）。若全局上限按 token 桶数统计（旧实现），
	// 桶数始终为 1，这条限制永远不会生效 —— 本用例正是断言它按真实连接数生效。
	oldGlobal := sseMaxClientsGlobal
	sseMaxClientsGlobal = 3
	t.Cleanup(func() { sseMaxClientsGlobal = oldGlobal })

	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)

	streams := make([]*sseStream, 0, sseMaxClientsGlobal)
	for i := 0; i < sseMaxClientsGlobal; i++ {
		resetSSEConnTimes() // 隔离"每 IP 每分钟 10 次"这条独立规则
		streams = append(streams, openSSEExpectOK(t, srv, "token-a"))
	}
	waitConnCount(t, sseMaxClientsGlobal, 3*time.Second)

	resetSSEConnTimes()
	s, code := openSSE(t, srv, "token-a")
	if code != http.StatusTooManyRequests {
		if s != nil {
			s.close()
		}
		t.Fatalf("真实连接数达到全局上限(%d)后仍放行: 状态=%d want 429（全局上限统计的不是真实连接数）",
			sseMaxClientsGlobal, code)
	}
	if got := ssoConnCount(); got != sseMaxClientsGlobal {
		t.Fatalf("被拒后连接计数=%d want %d", got, sseMaxClientsGlobal)
	}

	for _, st := range streams {
		st.close()
	}
	waitConnCount(t, 0, 3*time.Second)
}

// TestSSEDefaultThresholds 锁定生产阈值（单 token 8、全局 32、每 IP 每分钟 10）。
func TestSSEDefaultThresholds(t *testing.T) {
	if sseMaxClientsPerToken != 8 || sseMaxClientsGlobal != 32 || sseMaxConnsPerIPPerMin != 10 {
		t.Fatalf("SSE 阈值被改动: perToken=%d global=%d perIPPerMin=%d, want 8/32/10",
			sseMaxClientsPerToken, sseMaxClientsGlobal, sseMaxConnsPerIPPerMin)
	}
}

// --- 被顶号后旧流必须结束 ----------------------------------------------------

func TestSSOEventsOfflineEventClosesStream(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)
	s := openSSEExpectOK(t, srv, "token-a")
	defer s.close()
	waitConnCount(t, 1, 2*time.Second)

	// 新用户登录：旧会话应收到 SESSION_OFFLINE 并结束旧流
	SSORegister("bob", "token-b")
	s.waitEvent(t, "SESSION_OFFLINE", 2*time.Second)
	s.waitClosed(t, 3*time.Second)
	waitConnCount(t, 0, 2*time.Second)
}

// 同 token（同一会话）重复 register 属幂等：不得把当前有效会话的 SSE 连接踢掉，
// 否则前端每次刷新/重连都会自踢一次。
func TestSSOEventsReRegisterSameSessionIsIdempotent(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)
	s := openSSEExpectOK(t, srv, "token-a")
	defer s.close()
	waitConnCount(t, 1, 2*time.Second)

	// 前端重连/刷新会再次 register 同一 (username, token)
	SSORegister("alice", "token-a")
	s.expectNoEvent(t, "SESSION_OFFLINE", 400*time.Millisecond)

	// 会话仍是有效会话，连接保持可用
	if tok, ok := SSOActiveToken(); !ok || tok != "token-a" {
		t.Fatalf("幂等 register 后活跃会话异常: tok=%q ok=%v", tok, ok)
	}
	waitConnCount(t, 1, 2*time.Second)
}

// --- 会话校验与订阅原子：不会漏掉踢出通知 ------------------------------------

// 与 register 交错建连时，任何"握手成功（200）"的连接都必须能收到随后（或同时
// 发生）的会话切换通知；不允许出现"校验时是旧 token、订阅却在切换之后"的窗口。
func TestSSOEventsHandshakeRaceNeverMissesOffline(t *testing.T) {
	srv := newSSEEventsServer(t)
	const rounds = 60
	for i := 0; i < rounds; i++ {
		resetSSOState()
		SSORegister("alice", "token-a")

		start := make(chan struct{})
		var wg sync.WaitGroup
		var switched bool

		jitter := time.Duration(i%8) * 25 * time.Microsecond
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			time.Sleep(jitter)
			SSORegister("bob", "token-b")
		}()

		wg.Add(1)
		var s *sseStream
		var code int
		go func() {
			defer wg.Done()
			<-start
			s, code = openSSE(t, srv, "token-a") // t.Fatalf 不允许在子 goroutine：仅记录
		}()

		close(start)
		wg.Wait()
		switched = true

		if s == nil {
			continue
		}
		if !switched {
			t.Fatal("unreachable")
		}
		// 400 是"切换后握手被正确拒绝"，与 200 一起构成完备的两分支
		if code != http.StatusOK && code != http.StatusUnauthorized {
			t.Fatalf("握手状态=%d want 200 或 401", code)
		}
		if code == http.StatusOK {
			// 握手成功即已成为"活跃会话订阅者"，切换后必须收到离线通知
			s.waitEvent(t, "SESSION_OFFLINE", 3*time.Second)
			s.waitClosed(t, 3*time.Second)
		}
		s.close()
		waitConnCount(t, 0, 3*time.Second)
	}
}

// --- 客户端取消 / 写失败后连接计数回收 ---------------------------------------

// 客户端断开（取消）后容量必须立刻回收，不依赖下一次写失败。
func TestSSOEventsClientCancelReleasesSlot(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)

	a := openSSEExpectOK(t, srv, "token-a")
	resetSSEConnTimes()
	b := openSSEExpectOK(t, srv, "token-a")
	waitConnCount(t, 2, 2*time.Second)

	// 客户端取消后名额必须立刻回收（不依赖对端写失败才发现）
	a.close()
	b.close()
	waitConnCount(t, 0, 2*time.Second)

	// 容量已回收：同一会话可以重新建连
	for i := 0; i < 3; i++ {
		resetSSEConnTimes()
		c := openSSEExpectOK(t, srv, "token-a")
		c.close()
		waitConnCount(t, 0, 2*time.Second)
	}
}

// 服务端写失败（对端被 RST 断开）时必须结束该流并释放计数，不能挂着继续占名额。
func TestSSOEventsWriteFailureReleasesSlot(t *testing.T) {
	resetSSOState()
	SSORegister("alice", "token-a")
	srv := newSSEEventsServer(t)

	// 裸 TCP 建连后 RST 关闭：服务端后续写入必然失败
	conn, err := net.Dial("tcp", srv.Listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	req := "GET /api/sso/events HTTP/1.1\r\nHost: test\r\nAuthorization: Bearer token-a\r\n\r\n"
	if _, err := conn.Write([]byte(req)); err != nil {
		t.Fatal(err)
	}
	br := bufio.NewReader(conn)
	status, err := br.ReadString('\n')
	if err != nil || !strings.Contains(status, "200") {
		t.Fatalf("裸连接握手失败: status=%q err=%v", status, err)
	}
	waitConnCount(t, 1, 2*time.Second)

	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetLinger(0) // 关闭时发 RST 而非 FIN
	}
	_ = conn.Close()

	// 触发一次服务端写（会话切换推 SESSION_OFFLINE）：写失败必须退出并释放名额
	SSORegister("bob", "token-b")
	waitConnCount(t, 0, 3*time.Second)

	// 名额已释放：可以重新建连（用新会话 token）
	resetSSEConnTimes()
	s := openSSEExpectOK(t, srv, "token-b")
	s.close()
	waitConnCount(t, 0, 2*time.Second)
}

// --- 并发交错：register/logout 与建连/断开同时进行 ---------------------------

func TestSSOEventsConcurrentRegisterLogoutNoDeadlock(t *testing.T) {
	resetSSOState()
	srv := newSSEEventsServer(t)
	SSORegister("alice", "token-a")

	stop := make(chan struct{})
	var wg sync.WaitGroup

	// 会话抖动：register/logout 交替
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; ; i++ {
			select {
			case <-stop:
				return
			default:
			}
			SSORegister("alice", "token-a")
			SSORegister("bob", "token-b")
			SSOLogout("token-b")
			SSORegister("alice", "token-a")
			time.Sleep(time.Millisecond)
		}
	}()

	// 多个客户端反复建连/断开
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				tok, ok := SSOActiveToken()
				if !ok {
					tok = "token-a"
				}
				s, code := openSSE(t, srv, tok)
				if code == http.StatusOK {
					time.Sleep(5 * time.Millisecond)
				}
				if s != nil {
					s.close()
				}
			}
		}()
	}

	time.Sleep(700 * time.Millisecond)
	close(stop)

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(15 * time.Second):
		t.Fatal("并发 register/logout 与握手交错时疑似死锁（15s 未收敛）")
	}

	// 收尾：清会话后所有连接最终回收
	SSOLogout("token-a")
	tok, ok := SSOActiveToken()
	if ok {
		SSOLogout(tok)
	}
	waitConnCount(t, 0, 5*time.Second)
}
