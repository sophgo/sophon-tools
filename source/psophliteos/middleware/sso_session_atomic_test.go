package middleware

// sso_session_atomic_test.go 覆盖"会话变更 + 终止通知"的原子性与代次绑定语义
// （MYS-2885 首次验收 review 项 1）。
//
// 核心不变量：**终止通知只发给"被本次变更替换掉的那一代会话"的订阅**，
// 不能按 token 桶无差别清理。否则「A 活跃 → B 登录 → A 用同一 token 重新登录并订阅
// → B 那次延迟通知到达」会把当前有效的 A 连接误踢（reviewer 用 overlay 在
// unlock→notify 之间插桩复现：TestReviewDelayedNotifyKicksReactivatedSession）。
//
// 这里不靠插桩制造窗口，而是直接验证可观测结果：
//   1. 同 token 跨会话代次重新登录后，旧代次的订阅被终止、新代次的订阅必须存活；
//   2. logout → 同 token 重登 → 新订阅不受旧代次通知影响；
//   3. 代次单调递增，且"过期判定"严格按 < 当前代次；
//   4. 并发 A/B 交替登录/登出后，最终存活的订阅集合与代次语义一致（-race 下跑）。

import (
	"net/http"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// subscribeDirect 直接在进程内订阅（不起 HTTP 服务），便于精确构造代次时序。
// 返回的 ssoClient 与 SSOEvents 内部使用的是同一套登记路径（sseRegisterClient）。
func subscribeDirect(t *testing.T, token string) *ssoClient {
	t.Helper()
	cl, status := sseRegisterClient(token, "10.255.255.1")
	if status != http.StatusOK {
		t.Fatalf("subscribe(%s) status=%d want 200", token, status)
	}
	return cl
}

// drainEvents 取出通道里已缓冲的全部事件（非阻塞）。
func drainEvents(cl *ssoClient) []string {
	var out []string
	for {
		select {
		case ev, ok := <-cl.ch:
			if !ok {
				return out
			}
			out = append(out, ev)
		default:
			return out
		}
	}
}

// assertNoEvent 断言通道里没有事件（连接仍存活、未被误踢）。
func assertNoEvent(t *testing.T, cl *ssoClient, what string) {
	t.Helper()
	if evs := drainEvents(cl); len(evs) != 0 {
		t.Fatalf("%s 收到不应出现的事件 %v（被过期通知误踢）", what, evs)
	}
}

// assertGotOffline 断言收到终止事件。
func assertGotOffline(t *testing.T, cl *ssoClient, what string) {
	t.Helper()
	evs := drainEvents(cl)
	for _, ev := range evs {
		if ev == sseEventSessionOffline {
			return
		}
	}
	t.Fatalf("%s 未收到 %s，实际事件=%v", what, sseEventSessionOffline, evs)
}

// TestSessionChangeTerminatesOnlyReplacedGeneration 复现 reviewer 的时序：
// A 活跃 → B 登录（A 的代次被替换）→ A 用同一 token 重新登录并订阅 → 新订阅必须存活。
//
// 旧实现把"通知"放在 ssoMu 之外按 token 桶发送，B 登录的延迟通知会命中 A 的新连接；
// 新实现按代次判定：A 的新连接代次 ≥ 当前代次，不属于被替换会话，必须保留。
func TestSessionChangeTerminatesOnlyReplacedGeneration(t *testing.T) {
	resetSSOState()

	// A 登录并订阅（代次 g1）
	SSORegister("alice", "review-token-A")
	oldA := subscribeDirect(t, "review-token-A")

	// B 登录：A 的代次被替换，oldA 必须立刻收到终止事件
	SSORegister("bob", "review-token-B")
	assertGotOffline(t, oldA, "被顶掉的 A 旧订阅")

	// A 用同一 token 重新登录并重新订阅（新代次）
	SSORegister("alice", "review-token-A")
	newA := subscribeDirect(t, "review-token-A")

	// 关键断言：新订阅不得收到任何过期通知
	assertNoEvent(t, newA, "重新激活的 A 新订阅")

	// 再登一次 B：这次 newA 才应该被踢
	SSORegister("bob", "review-token-B")
	assertGotOffline(t, newA, "被新登录顶掉的 A 新订阅")

	sseUnregisterClient("review-token-A", newA)
	sseUnregisterClient("review-token-A", oldA)
	waitConnCount(t, 0, 2*time.Second)
}

// TestLogoutThenReloginSameTokenKeepsNewSubscription 覆盖 logout → 同 token 重登。
// logout 会推进代次并终止旧订阅；重登后的新订阅不能被旧的 logout 通知波及。
func TestLogoutThenReloginSameTokenKeepsNewSubscription(t *testing.T) {
	resetSSOState()
	const tok = "same-token"

	SSORegister("alice", tok)
	before := subscribeDirect(t, tok)

	// logout：旧订阅必须收到终止事件
	SSOLogout(tok)
	assertGotOffline(t, before, "logout 前的订阅")

	// 同 token 重新登录并订阅
	SSORegister("alice", tok)
	after := subscribeDirect(t, tok)

	// 新订阅不得继承任何过期通知
	assertNoEvent(t, after, "logout 后同 token 重登的新订阅")
	if got, ok := SSOActiveToken(); !ok || got != tok {
		t.Fatalf("重登后活跃会话异常: tok=%q ok=%v", got, ok)
	}

	// 幂等：同 (user, token) 再注册不得踢掉自己
	SSORegister("alice", tok)
	assertNoEvent(t, after, "同会话幂等重注册后的订阅")

	sseUnregisterClient(tok, after)
	sseUnregisterClient(tok, before)
	waitConnCount(t, 0, 2*time.Second)
}

// TestSessionGenerationMonotonic 验证代次单调递增，且幂等注册不推进代次
// （否则每次前端重连都会把同会话的其它标签页踢掉）。
func TestSessionGenerationMonotonic(t *testing.T) {
	resetSSOState()

	SSORegister("alice", "tok-1")
	cl := subscribeDirect(t, "tok-1")
	gen1 := cl.gen

	// 幂等注册：代次不变
	SSORegister("alice", "tok-1")
	ssoMu.RLock()
	afterIdempotent := ssoGen
	ssoMu.RUnlock()
	if afterIdempotent != gen1 {
		t.Fatalf("幂等注册不应推进会话代次: before=%d after=%d", gen1, afterIdempotent)
	}

	// 换 token：代次推进
	SSORegister("alice", "tok-2")
	ssoMu.RLock()
	afterSwitch := ssoGen
	ssoMu.RUnlock()
	if afterSwitch <= gen1 {
		t.Fatalf("换 token 应推进会话代次: before=%d after=%d", gen1, afterSwitch)
	}

	// 新订阅拿到新代次
	cl2 := subscribeDirect(t, "tok-2")
	if cl2.gen != afterSwitch {
		t.Fatalf("新订阅代次=%d want %d", cl2.gen, afterSwitch)
	}

	sseUnregisterClient("tok-1", cl)
	sseUnregisterClient("tok-2", cl2)
	waitConnCount(t, 0, 2*time.Second)
}

// TestConcurrentSessionChurnKeepsConsistency 并发 A/B 交替登录、logout、订阅/退订，
// 结束后必须零残留，且始终不存在"当前活跃会话的订阅收到终止事件"的状态。
// -race 下运行验证锁序正确、无数据竞争。
func TestConcurrentSessionChurnKeepsConsistency(t *testing.T) {
	resetSSOState()
	const tokA, tokB = "churn-A", "churn-B"

	stop := make(chan struct{})
	var wg sync.WaitGroup

	// 会话抖动：A/B 交替登录，穿插 logout
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; ; i++ {
			select {
			case <-stop:
				return
			default:
			}
			switch i % 4 {
			case 0:
				SSORegister("alice", tokA)
			case 1:
				SSORegister("bob", tokB)
			case 2:
				SSOLogout(tokB)
			case 3:
				SSORegister("alice", tokA)
			}
			time.Sleep(time.Millisecond)
		}
	}()

	// 订阅抖动：反复订阅/退订，模拟多标签页
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
					time.Sleep(time.Millisecond)
					continue
				}
				cl, status := sseRegisterClient(tok, "10.255.255.2")
				if status == http.StatusOK {
					time.Sleep(2 * time.Millisecond)
					// 退订必须是幂等的：可能已被会话变更摘除
					sseUnregisterClient(tok, cl)
				}
			}
		}()
	}

	time.Sleep(500 * time.Millisecond)
	close(stop)
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(15 * time.Second):
		t.Fatal("并发会话抖动疑似死锁（15s 未收敛）")
	}

	// 收尾：清空会话后所有连接必须回收
	if tok, ok := SSOActiveToken(); ok {
		SSOLogout(tok)
	}
	waitConnCount(t, 0, 5*time.Second)
}

// TestStaleNotificationDoesNotReachNewSubscriptionUnderChurn 高频重复 reviewer 的
// 三步时序（A 活跃 → B 登录 → A 同 token 重登并订阅），断言每次新订阅都不收到通知。
// 这是在真实并发下对同一不变量的压力验证。
func TestStaleNotificationDoesNotReachNewSubscriptionUnderChurn(t *testing.T) {
	resetSSOState()
	const rounds = 200

	for i := 0; i < rounds; i++ {
		// 每轮清空"每 IP 每分钟 10 次新建"窗口：该限流与本次断言的不变量无关，
		// 且同一测试进程都来自同一个回环 IP。
		resetSSEConnTimes()
		SSORegister("alice", "loop-token-A")
		old := subscribeDirect(t, "loop-token-A")

		SSORegister("bob", "loop-token-B")
		assertGotOffline(t, old, "被顶掉的旧订阅")

		SSORegister("alice", "loop-token-A")
		fresh := subscribeDirect(t, "loop-token-A")
		assertNoEvent(t, fresh, "重新激活后同 token 的新订阅")

		sseUnregisterClient("loop-token-A", fresh)
		sseUnregisterClient("loop-token-A", old)
	}
	waitConnCount(t, 0, 5*time.Second)
}

// TestPublishAndNotifyAreAtomic 用测试注入点精确复现 reviewer 的时序：
// 「B 已发布新会话（ssoMu 在旧实现里已释放），A 恰好在此刻用同一 token 重新登录并订阅」。
//
// 注入点位于"新会话已发布、终止通知未发出"这一刻。正确实现此刻仍持 ssoMu 写锁，
// 因此另一个 goroutine 的 SSORegister(A)/sseRegisterClient(A) 必须阻塞，直到本次变更
// （含终止通知）全部完成 —— 于是订阅到的连接代次必然属于新会话，绝不会收到过期通知。
//
// 旧实现把 ssoNotify 放在 ssoMu 之外：注入点处锁已释放，A 的重登与新订阅能立刻插入，
// 随后那次按 token 桶发出的通知就把当前有效的 A 连接踢掉（reviewer 的失败现象）。
func TestPublishAndNotifyAreAtomic(t *testing.T) {
	resetSSOState()
	const tokA = "review-token-A"

	SSORegister("alice", tokA)
	oldA := subscribeDirect(t, tokA)

	published := make(chan struct{})
	proceed := make(chan struct{})
	// 只在第一次（B 的那次变更）停住；后续调用（A 的重登）必须立刻返回，
	// 否则测的就是"hook 自己被 once 互斥"，而不是被测代码的原子性。
	var paused atomic.Bool
	ssoAfterPublish = func(uint64) {
		if paused.CompareAndSwap(false, true) {
			close(published)
			<-proceed
		}
	}
	t.Cleanup(func() { ssoAfterPublish = nil })

	bDone := make(chan struct{})
	go func() {
		defer close(bDone)
		SSORegister("bob", "review-token-B")
	}()

	<-published // B 已发布、通知未发；旧实现在此已释放 ssoMu

	// 此刻尝试用同一 token 重新激活 A 并订阅：正确实现会阻塞到 B 的变更整体完成。
	reactivated := make(chan *ssoClient, 1)
	go func() {
		SSORegister("alice", tokA)
		resetSSEConnTimes()
		cl, status := sseRegisterClient(tokA, "10.255.255.9")
		if status == http.StatusOK {
			reactivated <- cl
			return
		}
		reactivated <- nil
	}()

	// 给重登 goroutine 一点时间尝试插入：正确实现下它必须还阻塞着。
	select {
	case cl := <-reactivated:
		close(proceed)
		<-bDone
		if cl != nil {
			assertNoEvent(t, cl, "窗口期内重新激活的 A 订阅")
			sseUnregisterClient(tokA, cl)
		}
		sseUnregisterClient(tokA, oldA)
		t.Fatalf("注入点处仍可插入并发会话变更/订阅：发布与终止通知未原子化")
	case <-time.After(150 * time.Millisecond):
		// 预期路径：被 ssoMu 写锁挡住
	}

	close(proceed)
	<-bDone

	// B 的变更完成后，重登的 A 变成新活跃会话，其订阅不应收到过期通知。
	var newA *ssoClient
	select {
	case newA = <-reactivated:
	case <-time.After(5 * time.Second):
		t.Fatal("重登 goroutine 未完成")
	}
	if newA == nil {
		t.Fatal("重登后订阅失败")
	}
	assertNoEvent(t, newA, "B 变更完成后的 A 新订阅")

	// 旧订阅必须已被终止
	assertGotOffline(t, oldA, "被替换的 A 旧订阅")

	sseUnregisterClient(tokA, newA)
	sseUnregisterClient(tokA, oldA)
	waitConnCount(t, 0, 3*time.Second)
}
