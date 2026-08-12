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
