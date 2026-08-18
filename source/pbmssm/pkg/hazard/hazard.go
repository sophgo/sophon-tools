// Package hazard 提供两类高危操作护栏：
//   - 全局互斥锁：重启/关机/OTA/软件安装等危险操作共享一把锁，占用中其他高危
//     操作立即返回明确错误而非排队混跑（MYS-389）。
//   - 一次性确认码：高危操作提交前必须先取得随机确认码并在请求中回传，防误触。
package hazard

import (
	"crypto/rand"
	"fmt"
	"sync"
	"time"
)

// ---------------------------------------------------------------
// 全局互斥锁
// ---------------------------------------------------------------

// Lock 危险操作互斥锁（TryLock 语义：占用中返回错误，不阻塞排队）。
type Lock struct {
	mu     sync.Mutex
	holder string
}

// HazardOps 是全部高危操作共享的全局互斥锁。
// 占用者如 "reboot"、"ota-upgrade"、"software-install"，冲突时直接告知占用者。
var HazardOps = &Lock{}

// TryAcquire 尝试占用互斥锁；被占用时返回明确错误。
// holder 为空表示"不占用锁"（并发安全场景，如软件批量安装）：返回 no-op Guard，
// 其 Release 绝不触碰他人持有的锁。
func (l *Lock) TryAcquire(holder string) (*Guard, error) {
	if holder == "" {
		return &Guard{}, nil
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.holder != "" {
		return nil, fmt.Errorf("hazardous operation blocked: %s is already in progress", l.holder)
	}
	l.holder = holder
	return &Guard{l: l, holder: holder}, nil
}

// Release 释放互斥锁（幂等）。
func (l *Lock) Release() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.holder = ""
}

// Guard 是互斥锁占用句柄，配合 defer 使用：
//
//	guard, err := hazard.HazardOps.TryAcquire("reboot")
//	if err != nil { ... }
//	defer guard.Release()
type Guard struct {
	l      *Lock
	holder string
}

// Release 释放占用（幂等）。只释放自己持有的锁：若期间锁已被他人
// 重新获取（如 no-op Guard 与真实占用交错），不会误清他人的持有。
func (g *Guard) Release() {
	if g.l == nil {
		return
	}
	g.l.mu.Lock()
	if g.l.holder == g.holder {
		g.l.holder = ""
	}
	g.l.mu.Unlock()
}

// ---------------------------------------------------------------
// 二次确认码
// ---------------------------------------------------------------

const (
	confirmChars   = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
	confirmTTL     = 2 * time.Minute
	confirmCodeLen = 6
)

var (
	confirmMu     sync.Mutex
	confirmCode   string
	confirmExpire time.Time
)

// NewConfirmCode 生成新的一次性确认码（替换旧码），返回明文。
// 高危操作前调用：GET /api/v1/hazard/challenge。
func NewConfirmCode() string {
	buf := make([]byte, confirmCodeLen)
	if _, err := rand.Read(buf); err != nil {
		// crypto/rand 失败近乎不可能；退化为时间戳派生，仍能防误触。
		return fmt.Sprintf("%06d", time.Now().UnixNano()%1000000)
	}
	for i, b := range buf {
		buf[i] = confirmChars[int(b)%len(confirmChars)]
	}
	confirmMu.Lock()
	defer confirmMu.Unlock()
	confirmCode = string(buf)
	confirmExpire = time.Now().Add(confirmTTL)
	return confirmCode
}

// VerifyConfirmCode 校验确认码：TTL 窗口内（默认 2 分钟）可复用；
// 窗口过期后自动失效（防重放靠短窗口 + 每次高危动作前重新取码）。
func VerifyConfirmCode(code string) bool {
	confirmMu.Lock()
	defer confirmMu.Unlock()
	if confirmCode == "" || code == "" || code != confirmCode {
		return false
	}
	if time.Now().After(confirmExpire) {
		confirmCode = ""
		return false
	}
	return true
}
