package embed

import "context"

// EmbeddingLimiter 限流器：内置 key 时启用（并发≤2、单次≤3段落）。
type EmbeddingLimiter struct {
	sem      chan struct{}
	maxBatch int
}

func NewEmbeddingLimiter(maxConcurrent int) *EmbeddingLimiter {
	return &EmbeddingLimiter{sem: make(chan struct{}, maxConcurrent), maxBatch: 3}
}

// Do 把 n 个文本按 ≤maxBatch 一份拆成多批，串行提交（每批内一次调用）。
func (l *EmbeddingLimiter) Do(ctx context.Context, n int, fn func() error) error {
	batches := (n + l.maxBatch - 1) / l.maxBatch
	for b := 0; b < batches; b++ {
		select {
		case l.sem <- struct{}{}:
		case <-ctx.Done():
			return ctx.Err()
		}
		if err := fn(); err != nil {
			<-l.sem
			return err
		}
		<-l.sem
	}
	return nil
}
