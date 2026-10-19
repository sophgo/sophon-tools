package main

// SSE 事件广播。
//
// 设计取向：**单个全局广播器**，而不是每轮执行一个。
// 早先按 gen 分总线，导致「页面先连流、用户再点执行」时订阅者绑在旧总线上，
// 新一轮的 per-device 事件全部收不到，只能等 done 才刷新——过程一片空白。
// 换成一个总线后，订阅只发生一次，事件自带 gen 供前端判断归属。
//
// 慢订阅者不能拖死执行：publish 一律非阻塞，缓冲满了就断开该订阅者，
// 前端重连后重新拉 /api/state 即可（丢的只是中间进度帧）。

import (
	"encoding/json"
	"sync"
)

type eventBus struct {
	mu     sync.Mutex
	subs   map[int]chan eventDTO
	nextID int
	closed bool
	last   []eventDTO // 最近一条终态事件，供中途连上的页面补看
}

func newEventBus() *eventBus {
	return &eventBus{subs: map[int]chan eventDTO{}}
}

func (b *eventBus) subscribe() (<-chan eventDTO, func()) {
	b.mu.Lock()
	defer b.mu.Unlock()

	ch := make(chan eventDTO, 512)
	for _, ev := range b.last {
		select {
		case ch <- ev:
		default:
		}
	}

	id := b.nextID
	b.nextID++
	b.subs[id] = ch

	return ch, func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		if c, ok := b.subs[id]; ok {
			delete(b.subs, id)
			close(c)
		}
	}
}

func (b *eventBus) publish(ev eventDTO) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if ev.Kind == "done" {
		b.last = append(b.last, ev)
	}
	for id, ch := range b.subs {
		select {
		case ch <- ev:
		default:
			// 积压过多：断开它，好过无限占内存。前端会重连并重拉状态。
			delete(b.subs, id)
			close(ch)
		}
	}
}

// marshalSSE 把一个事件编码成 SSE 帧。
func marshalSSE(ev eventDTO) []byte {
	data, err := json.Marshal(ev)
	if err != nil {
		return nil
	}
	out := make([]byte, 0, len(data)+8)
	out = append(out, "data: "...)
	out = append(out, data...)
	out = append(out, '\n', '\n')
	return out
}
