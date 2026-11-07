// Package fusion 实现 Reciprocal Rank Fusion（RRF）。
package fusion

import "sort"

type Ranked struct {
	ChunkID string
	Score   float64
}

type RRFResult struct {
	ChunkID string
	Score   float64
}

// RRF：对多路排名取并集，得分 = sum(1/(k+rank+1))，rank 从 0 起（最相关）。
// 默认 k=60（对齐 Python retriever.py）。
func RRF(faissResults, bm25Results []Ranked, k int) []RRFResult {
	if k < 1 {
		k = 60
	}
	m := map[string]float64{}
	for rank, r := range faissResults {
		m[r.ChunkID] += 1 / float64(k+rank+1)
	}
	for rank, r := range bm25Results {
		m[r.ChunkID] += 1 / float64(k+rank+1)
	}
	out := make([]RRFResult, 0, len(m))
	for id, sc := range m {
		out = append(out, RRFResult{id, sc})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].ChunkID < out[j].ChunkID
	})
	return out
}

// Path 一路排名及其在 RRF 中的权重。
type Path struct {
	Ranked []Ranked
	// Weight 该路每一名次得分的倍数；≤0 视为 1（不改变两路融合的旧行为）。
	Weight float64
}

// RRFWeighted 加权 RRF：得分 = sum(weight_p / (k+rank_p+1))。
//
// 权重让"标识符—标题精确匹配"这一路（weight=2）压过向量与 BM25 两路（weight=1）：
// 精确命中标题的块即使只在一路出现且名次靠后，也能排到只被内容相似度命中的块前面。
// 排序规则与 RRF 一致（分数降序、同分按 ChunkID 升序），因此全部 weight=1 时
// 与 RRF 结果逐字节相同。
func RRFWeighted(paths []Path, k int) []RRFResult {
	if k < 1 {
		k = 60
	}
	m := map[string]float64{}
	for _, p := range paths {
		w := p.Weight
		if w <= 0 {
			w = 1
		}
		for rank, r := range p.Ranked {
			m[r.ChunkID] += w / float64(k+rank+1)
		}
	}
	out := make([]RRFResult, 0, len(m))
	for id, sc := range m {
		out = append(out, RRFResult{id, sc})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].ChunkID < out[j].ChunkID
	})
	return out
}
