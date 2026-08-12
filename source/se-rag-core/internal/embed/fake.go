package embed

import "context"

// FakeEmbedder 离线/测试用：对任意文本返回固定的 dim 维向量，便于无网络全链路验证。
type FakeEmbedder struct {
	dim int
}

func NewFakeEmbedder(dim int) *FakeEmbedder {
	if dim <= 0 {
		dim = 2
	}
	return &FakeEmbedder{dim: dim}
}

func (f *FakeEmbedder) Name() string { return "fakeembed" }
func (f *FakeEmbedder) Dim() int     { return f.dim }
func (f *FakeEmbedder) Embed(_ context.Context, texts []string) ([][]float32, error) {
	out := make([][]float32, len(texts))
	for i, s := range texts {
		v := make([]float32, f.dim)
		// 用文本哈希生成确定性向量，保证相近文本近似
		h := fnvHash(s)
		for d := 0; d < f.dim; d++ {
			v[d] = float32((h>>uint(d*3%31))&0xFF) / 255.0
		}
		out[i] = v
	}
	return out, nil
}

// FakeReranker 离线/测试用：保持原有顺序。
type FakeReranker struct{}

func NewFakeReranker() *FakeReranker { return &FakeReranker{} }
func (f *FakeReranker) Name() string { return "fakererank" }
func (f *FakeReranker) Rerank(_ context.Context, _ string, docs []string, topN int) ([]int, error) {
	if topN > len(docs) {
		topN = len(docs)
	}
	idxs := make([]int, topN)
	for i := range idxs {
		idxs[i] = i
	}
	return idxs, nil
}

func fnvHash(s string) uint64 {
	var h uint64 = 1469598103934665603
	for i := 0; i < len(s); i++ {
		h ^= uint64(s[i])
		h *= 1099511628211
	}
	return h
}
