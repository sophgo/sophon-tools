// Package confirm 提供高危操作二次确认码。
//
// 模式：客户端先 Prepare 拿到一次性随机确认码（短 TTL，绑定动作与调用者），
// 真正执行危险操作（reboot/shutdown/OTA 刷机/防火墙 rebuild 等）时携带该码，
// Verify 校验通过才放行 —— 防止误触/脚本误调用即执行。
package confirm

import (
	"crypto/rand"
	"errors"
	"fmt"
	"sync"
	"time"
)

// DefaultTTL 确认码默认有效期。
const DefaultTTL = 60 * time.Second

// codeDigits 确认码位数（6 位数字，便于回显/口述）。
const codeDigits = 6

// 校验错误。ErrMissing 表示未先 Prepare（动作+用户无匹配的码）。
var (
	ErrMissing = errors.New("no confirmation code issued for this action, request one via /ops/confirm first")
	ErrInvalid = errors.New("confirmation code mismatch")
	ErrExpired = errors.New("confirmation code expired, request a new one")
)

// codeEntry 一条已签发的确认码。
type codeEntry struct {
	code      string
	expiresAt time.Time
	attempts  int
}

// maxAttempts 单码最大校验尝试次数，防本地爆破。
const maxAttempts = 5

// Manager 确认码管理：并发安全，码一次性消费。
type Manager struct {
	mu      sync.Mutex
	pending map[string]codeEntry // key: action + "\x00" + username
}

// NewManager 新建 Manager。
func NewManager() *Manager {
	return &Manager{pending: make(map[string]codeEntry)}
}

// global 包级共享 Manager（所有高危操作端点共用）。
var global = NewManager()

// Global 返回全局确认码管理器。
func Global() *Manager { return global }

// key 组装动作+用户唯一键：确认码同时绑定动作与用户，
// 防止 A 取码 B 使用（即使都是 admin 也要求本人操作）。
func key(action, username string) string { return action + "\x00" + username }

// Prepare 为 action+username 签发一个一次性确认码，返回码与过期时间。
// 重复 Prepare 会作废旧码（新码生效）。
func (m *Manager) Prepare(action, username string, ttl time.Duration) (string, time.Time) {
	m.mu.Lock()
	defer m.mu.Unlock()

	code := randomCode()
	expiresAt := time.Now().Add(ttl)
	m.pending[key(action, username)] = codeEntry{code: code, expiresAt: expiresAt}
	return code, expiresAt
}

// Verify 校验 action+username 的确认码，通过后一次性消费。
// 返回 ErrMissing / ErrExpired / ErrInvalid。
func (m *Manager) Verify(action, username, code string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	k := key(action, username)
	entry, ok := m.pending[k]
	if !ok {
		return ErrMissing
	}
	if time.Now().After(entry.expiresAt) {
		delete(m.pending, k)
		return ErrExpired
	}
	if entry.code != code {
		entry.attempts++
		if entry.attempts >= maxAttempts {
			delete(m.pending, k) // 连续失败作废，需重新取码
		} else {
			m.pending[k] = entry
		}
		return ErrInvalid
	}
	delete(m.pending, k)
	return nil
}

// randomCode 生成 codeDigits 位十进制随机码（crypto/rand）。
func randomCode() string {
	// 用 32 字节随机数取模，避免逐位依赖少量熵；偏差可忽略。
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand 失败仅发生在内核熵池异常，回退时间戳（仅测试/降级场景）
		return fmt.Sprintf("%0*d", codeDigits, time.Now().UnixNano()%1000000)
	}
	// 取前 4 字节构成 uint32，映射到 [0, 10^digits) 后左补零。
	var n uint32
	for _, by := range b[:4] {
		n = n<<8 | uint32(by)
	}
	return fmt.Sprintf("%0*d", codeDigits, int(n%1_000_000))
}

// Reset 清空全部待确认码（测试辅助）。
func (m *Manager) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.pending = make(map[string]codeEntry)
}
