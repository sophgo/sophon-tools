// Package oplock 提供设备"危险操作"全局互斥。
//
// reboot / shutdown / OTA 刷机 / 防火墙 rebuild 等设备级高危操作共享同一把锁：
// 一次只允许一个危险操作进行，冲突的直接返回明确错误而非排队混跑。
// 原因：并发触发（一边 OTA 刷机一边重启、重复 Rebuild 防火墙期间重启）可致设备变砖。
package oplock

import (
	"fmt"
	"sync"
	"time"
)

// BusyError 表示危险操作被另一个进行中的危险操作互斥。
type BusyError struct {
	Holder string    // 占用者描述，如 "reboot" / "ota:upgrade:SE7:pkg.tgz"
	Since  time.Time // 占用开始时间
}

func (e *BusyError) Error() string {
	return fmt.Sprintf("another dangerous operation in progress: %s (since %s)",
		e.Holder, e.Since.Format(time.RFC3339))
}

// OpLock 非阻塞互斥锁：获取失败不等待，立即返回错误。
type OpLock struct {
	mu     sync.Mutex
	holder string
	since  time.Time
}

// New 创建独立的 OpLock（测试用）。
func New() *OpLock { return &OpLock{} }

// global 全局共享锁：reboot/shutdown/OTA/防火墙 rebuild 等所有模块共用。
var global = New()

// Global 返回全局危险操作互斥锁。
func Global() *OpLock { return global }

// Acquire 尝试获取锁（非阻塞）。
// 成功时返回 release 函数（可安全多次调用）；若已有其他危险操作在进行，返回 *BusyError。
func (l *OpLock) Acquire(holder string) (func(), error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.holder != "" {
		return nil, &BusyError{Holder: l.holder, Since: l.since}
	}
	l.holder = holder
	l.since = time.Now()
	var once sync.Once
	return func() { once.Do(func() { l.release() }) }, nil
}

// release 释放锁（仅当持有者为当前调用者；幂等）。
func (l *OpLock) release() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.holder = ""
	l.since = time.Time{}
}

// Holder 返回当前占用者（"" 表示空闲）。仅用于诊断/测试。
func (l *OpLock) Holder() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.holder
}
