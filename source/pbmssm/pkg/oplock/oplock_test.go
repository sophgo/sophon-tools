package oplock

import (
	"strings"
	"sync"
	"testing"
	"time"
)

// TestAcquireExclusive 独占性：同一把锁同一时刻仅一个持有者。
func TestAcquireExclusive(t *testing.T) {
	l := New()
	release, err := l.Acquire("reboot")
	if err != nil {
		t.Fatalf("first acquire: %v", err)
	}
	defer release()

	if _, err := l.Acquire("shutdown"); err == nil {
		t.Fatal("second acquire should fail while lock held")
	} else if be, ok := err.(*BusyError); !ok {
		t.Fatalf("expected *BusyError, got %T: %v", err, err)
	} else if be.Holder != "reboot" {
		t.Errorf("BusyError.Holder = %q, want %q", be.Holder, "reboot")
	} else if !strings.Contains(be.Error(), "another dangerous operation") {
		t.Errorf("error message should be explicit: %v", be.Error())
	}
}

// TestAcquireReleaseReacquire 释放后可再次获取（release 幂等）。
func TestAcquireReleaseReacquire(t *testing.T) {
	l := New()
	release, err := l.Acquire("reboot")
	if err != nil {
		t.Fatalf("acquire: %v", err)
	}
	release()
	release() // 幂等

	if _, err := l.Acquire("shutdown"); err != nil {
		t.Fatalf("re-acquire after release: %v", err)
	}
}

// TestConcurrentAcquireOnlyOneWins 并发争抢：N 个 goroutine 同时抢锁，恰好一个成功
// （赢家持有 50ms 再释放，保证其他 goroutine 确实处于"失败"而非"排队等待"）。
func TestConcurrentAcquireOnlyOneWins(t *testing.T) {
	l := New()
	const n = 20

	start := make(chan struct{})
	var wg sync.WaitGroup
	wins := make(chan struct{}, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			release, err := l.Acquire("op")
			if err != nil {
				return
			}
			wins <- struct{}{}
			time.Sleep(50 * time.Millisecond)
			release()
		}()
	}
	close(start)
	wg.Wait()
	close(wins)

	if got := len(wins); got != 1 {
		t.Errorf("exactly one goroutine should win, got %d", got)
	}
	if h := l.Holder(); h != "" {
		t.Errorf("lock should be free after all released, holder=%q", h)
	}
}

// TestConcurrentStrictlySerialized 串行性：任意时刻最多一个持有者（全程无并发生效）。
func TestConcurrentStrictlySerialized(t *testing.T) {
	l := New()
	var mu sync.Mutex
	active := 0
	maxActive := 0

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			// 获取失败则让出后重试（互斥锁语义不排队，由调用方决定重试）
			var release func()
			for {
				var err error
				release, err = l.Acquire("op")
				if err == nil {
					break
				}
				time.Sleep(time.Millisecond)
			}
			mu.Lock()
			active++
			if active > maxActive {
				maxActive = active
			}
			mu.Unlock()
			time.Sleep(5 * time.Millisecond)
			mu.Lock()
			active--
			mu.Unlock()
			release()
		}()
	}
	wg.Wait()
	if maxActive != 1 {
		t.Errorf("max concurrent holders = %d, want 1", maxActive)
	}
}
