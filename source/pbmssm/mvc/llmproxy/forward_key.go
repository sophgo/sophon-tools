package llmproxy

import (
	"sync"
)

// ForwardKeyListener 转发 key 轮换监听者（MYS-387）：
// ResetForwardKey 轮换成功后回调，携带新 key，供各持有方热同步：
//   - agentproxy Hub（WS 子协议认证）换用新 key，旧 key 立即失效；
//   - agentproxy reasonix 进程重启以加载新 DEEPSEEK_API_KEY（转发鉴权凭据）。
//
// llmproxy 只声明回调，不反向引入 agentproxy（避免包循环）；
// agentproxy 在 Start 时通过 RegisterForwardKeyListener 注册实现
// （与 RegisterContextWindowApplier 同一模式）。
type ForwardKeyListener func(newKey string)

var (
	fkMu        sync.RWMutex
	fkListeners []ForwardKeyListener
)

// RegisterForwardKeyListener 追加一个转发 key 轮换监听者（幂等追加）。
func RegisterForwardKeyListener(fn ForwardKeyListener) {
	if fn == nil {
		return
	}
	fkMu.Lock()
	defer fkMu.Unlock()
	fkListeners = append(fkListeners, fn)
}

// notifyForwardKeyRotated 轮换成功后通知全部监听者。
func notifyForwardKeyRotated(key string) {
	fkMu.RLock()
	fns := make([]ForwardKeyListener, len(fkListeners))
	copy(fns, fkListeners)
	fkMu.RUnlock()
	for _, fn := range fns {
		fn(key)
	}
}
