package vector

import (
	"bytes"
	"encoding/gob"
	"math"
	"sort"
)

// Normalize 返回 v 的 L2 归一化副本（零向量原样返回）
func Normalize(v []float32) []float32 {
	var norm float64
	for _, x := range v {
		norm += float64(x) * float64(x)
	}
	norm = math.Sqrt(norm)
	if norm == 0 {
		return v
	}
	out := make([]float32, len(v))
	for i, x := range v {
		out[i] = float32(float64(x) / norm)
	}
	return out
}

type Result struct {
	ChunkID  string
	VecIndex int
	Score    float64
}

// Index 暴力内积索引（对齐 FAISS IndexFlatIP）。
// 向量需已 L2 归一化，内积即余弦相似度。
type Index struct {
	Dim      int
	Vecs     [][]float32
	ChunkIDs []string
}

func (idx *Index) Add(vec []float32, chunkID string) {
	if idx.Dim == 0 {
		idx.Dim = len(vec)
	}
	idx.Vecs = append(idx.Vecs, vec)
	idx.ChunkIDs = append(idx.ChunkIDs, chunkID)
}

func (idx *Index) Search(vec []float32, topK int) []Result {
	type p struct {
		id string
		i  int
		sc float64
	}
	var items []p
	for i, v := range idx.Vecs {
		var dot float64
		max := len(v)
		if len(vec) < max {
			max = len(vec)
		}
		for j := 0; j < max; j++ {
			dot += float64(v[j]) * float64(vec[j])
		}
		items = append(items, p{idx.ChunkIDs[i], i, dot})
	}
	sort.Slice(items, func(a, b int) bool {
		if items[a].sc != items[b].sc {
			return items[a].sc > items[b].sc
		}
		return items[a].i < items[b].i
	})
	if topK > 0 && len(items) > topK {
		items = items[:topK]
	}
	out := make([]Result, len(items))
	for k, it := range items {
		out[k] = Result{it.id, it.i, it.sc}
	}
	return out
}

func (idx *Index) Serialize() []byte {
	var buf bytes.Buffer
	_ = gob.NewEncoder(&buf).Encode(idx)
	return buf.Bytes()
}

func Load(data []byte) (*Index, error) {
	var idx Index
	if err := gob.NewDecoder(bytes.NewReader(data)).Decode(&idx); err != nil {
		return nil, err
	}
	return &idx, nil
}
