package bm25

import (
	"bytes"
	"encoding/gob"
	"math"
	"sort"
)

// BM25Okapi 经典参数（对齐 rank_bm25.BM25Okapi 默认 k1=1.5, b=0.75）
const (
	k1 = 1.5
	b  = 0.75
)

type Result struct {
	ChunkID string
	Score   float64
}

// Index 倒排索引，导出字段以便 gob 序列化
type Index struct {
	CorpusTokens [][]string
	DocLen       []int
	AvgDocLen    float64
	DF           map[string]int   // term -> doc frequency
	Postings     map[string][]int // term -> [docIndex,...]
	// TF 查询期 term 频次预统计：term -> 与 Postings 平行的 doc 内频次。
	// build 时随倒排一并生成，免去查询时对每个命中 doc 全量扫描统计 tf。
	// 旧格式索引无此字段（gob 解码为 nil），Search 回退全量扫描，向后兼容。
	TF       map[string][]int
	Size     int
	ChunkIDs []string
}

func Build(docs []string, chunkIDs []string) *Index {
	idx := &Index{
		DF:       map[string]int{},
		Postings: map[string][]int{},
		TF:       map[string][]int{},
	}
	n := len(docs)
	corpus := make([][]string, 0, n)
	var sum int
	for _, d := range docs {
		toks := Tokenize(d)
		corpus = append(corpus, toks)
		sum += len(toks)
		dfSeen := map[string]struct{}{}
		for _, t := range toks {
			if _, ok := dfSeen[t]; !ok {
				dfSeen[t] = struct{}{}
				idx.DF[t]++
				idx.Postings[t] = append(idx.Postings[t], len(corpus)-1)
				idx.TF[t] = append(idx.TF[t], 1)
				continue
			}
			// 同一 doc 内重复 term：tf +1（Postings 该条对应本 doc，TF 与其平行）
			idx.TF[t][len(idx.TF[t])-1]++
		}
	}
	idx.CorpusTokens = corpus
	idx.DocLen = make([]int, n)
	for i, toks := range corpus {
		idx.DocLen[i] = len(toks)
	}
	if n > 0 {
		idx.AvgDocLen = float64(sum) / float64(n)
	}
	idx.Size = n
	if len(chunkIDs) == n {
		idx.ChunkIDs = chunkIDs
	} else {
		idx.ChunkIDs = make([]string, n)
		for i := range idx.ChunkIDs {
			idx.ChunkIDs[i] = itoa(i)
		}
	}
	return idx
}

func (i *Index) DocCount() int { return i.Size }

func (i *Index) Serialize() []byte {
	var buf bytes.Buffer
	_ = gob.NewEncoder(&buf).Encode(i)
	return buf.Bytes()
}

func Load(data []byte) (*Index, error) {
	var idx Index
	if err := gob.NewDecoder(bytes.NewReader(data)).Decode(&idx); err != nil {
		return nil, err
	}
	return &idx, nil
}

func (i *Index) Search(query string, topK int) []Result {
	q := Tokenize(query)
	// 统计每个 doc 的 term 频次
	scores := make([]float64, i.Size)
	for _, term := range q {
		df, ok := i.DF[term]
		if !ok {
			continue
		}
		idf := math.Log(1 + (float64(i.Size)-float64(df)+0.5)/(float64(df)+0.5))
		// tf 优先取预统计（与 Postings 平行）；旧格式索引无 TF 时回退全量扫描
		var tfs []int
		if i.TF != nil {
			tfs = i.TF[term]
		}
		for pi, d := range i.Postings[term] {
			tf := 0.0
			if tfs != nil {
				tf = float64(tfs[pi])
			} else {
				for _, t := range i.CorpusTokens[d] {
					if t == term {
						tf++
					}
				}
			}
			dl := i.DocLen[d]
			denom := tf + k1*(1-b+b*float64(dl)/i.AvgDocLen)
			scores[d] += idf * tf * (k1 + 1) / denom
		}
	}

	type pair struct {
		id string
		sc float64
		di int
	}
	var res []pair
	for ai, sc := range scores {
		if sc > 0 {
			res = append(res, pair{i.ChunkIDs[ai], sc, ai})
		}
	}
	sort.Slice(res, func(a, b int) bool {
		if res[a].sc != res[b].sc {
			return res[a].sc > res[b].sc
		}
		return res[a].di < res[b].di
	})
	if topK > 0 && len(res) > topK {
		res = res[:topK]
	}
	out := make([]Result, len(res))
	for id, p := range res {
		out[id] = Result{ChunkID: p.id, Score: p.sc}
	}
	return out
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
