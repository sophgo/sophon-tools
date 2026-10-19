package main

// 进度上报节流。
//
// 为什么需要：copyWithProgress 每 256KiB 回调一次。100 台并行传 1GB 时会产生
// 约 41 万次回调；GUI 侧每个事件都要跨线程投递并刷新两张表，主线程会被打爆，
// 表现是"执行期间界面卡死、中止按钮点不动"。
//
// 这里在**事件产生处**（而不是 UI 里）节流，CLI 与 GUI 同时受益：
// 进度前进不足 1% 且距上次上报不足 200ms 时不发事件；
// 进度到达 100% 时强制发一次，保证终点不会被吞掉。

import (
	"sync"
	"time"
)

type progressThrottle struct {
	mu       sync.Mutex
	lastPct  float64
	lastTime time.Time
	started  bool
}

// allow 报告这次进度是否值得上报。
func (t *progressThrottle) allow(p float64) bool {
	t.mu.Lock()
	defer t.mu.Unlock()

	now := time.Now()
	if !t.started {
		t.started = true
		t.lastPct = p
		t.lastTime = now
		return true
	}
	// 到达终点必须发，否则界面会一直停在 99%。
	if p >= 1 {
		t.lastPct = p
		t.lastTime = now
		return true
	}
	if p-t.lastPct < progressMinDelta && now.Sub(t.lastTime) < progressMinPeriod {
		return false
	}
	t.lastPct = p
	t.lastTime = now
	return true
}
