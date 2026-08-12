package embed

import "context"

// EmbeddingLimiter 内置 key 限流器：并发 ≤ maxConcurrent、单次 ≤ perCall 段落。
type EmbeddingLimiter struct {
	sem chan struct{}
}

func NewEmbeddingLimiter(maxConcurrent int) *EmbeddingLimiter {
	return &EmbeddingLimiter{sem: make(chan struct{}, maxConcurrent)}
}

// perCall 单次 embedding 最多段落数（内置 key 平台约束，需求限定单次≤2）。
const perCall = 2

// Embed 把 texts 拆成 ≤3 一段的子批，逐批调用 embedBatch（每批一次 HTTP 调用，真正
// 以 ≤3 段落为载荷），整体并发受 sem 限制。返回按传入顺序排列的向量。
func (l *EmbeddingLimiter) Embed(ctx context.Context, texts []string, embedBatch func([]string) ([][]float32, error)) ([][]float32, error) {
	out := make([][]float32, len(texts))
	for start := 0; start < len(texts); start += perCall {
		end := start + perCall
		if end > len(texts) {
			end = len(texts)
		}
		batch := texts[start:end]
		select {
		case l.sem <- struct{}{}:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
		ev, err := embedBatch(batch)
		<-l.sem
		if err != nil {
			return nil, err
		}
		copy(out[start:end], ev)
	}
	return out, nil
}
