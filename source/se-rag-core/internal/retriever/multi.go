package retriever

import (
	"context"
	"fmt"
	"sort"
	"time"

	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/fusion"
	"se-rag-core/internal/vector"
)

// 多索引合并参数（对齐设计 D3）：
//   - 每个索引各自做现有 hybrid（向量 top20 + BM25 top20 → RRF），取 RRF 前 multiPerIndex 条，
//     此阶段**不 rerank**；
//   - 按各索引排名轮转截取，候选总数上限 multiCandidates，然后统一 rerank 一次，取 top-n；
//   - 离线 / 全部索引 bm25-only / rerank 失败：按各索引内排名做 RRF(k=60) 合并。
const (
	multiPerIndex   = 20
	multiCandidates = 40
)

// Source 一个待检索的索引。
type Source struct {
	// Label 结果标注用的实体 id；路径模式下为空（不标注，路径保持原样）。
	Label   string
	Store   *docstore.Store
	Product string
	// PathPrefix 把块记录的 SourceFile 改写成展示路径（实体模式下是相对技能根目录的
	// 路径，如 docs/products/se9/xxx.md）；为 nil 时原样输出。
	PathPrefix func(src string) string
}

func (s Source) name() string {
	if s.Label != "" {
		return s.Label
	}
	return s.Store.IndexDir
}

// MultiRetriever 跨多个索引检索并合并结果。
//
// 单索引（len(Sources)==1 且不需要跨索引合并语义）不走这里：CLI 直接调 Retriever，
// 保证与旧版本逐字节一致。
type MultiRetriever struct {
	Sources  []Source
	Embedder embed.Embedder
	Reranker embed.Reranker
}

// Search 跨索引检索。任一目标索引缺失或损坏都直接报错，不静默退化为"只查有的那几个"。
func (m *MultiRetriever) Search(ctx context.Context, query string, topM int) (*SearchOutcome, error) {
	t0 := time.Now()
	if topM <= 0 {
		topM = 8
	}
	if len(m.Sources) == 0 {
		return nil, fmt.Errorf("no index to search")
	}

	loaded := make([]*docstore.Loaded, len(m.Sources))
	for i, s := range m.Sources {
		l, err := s.Store.Open(s.Product)
		if err != nil {
			return nil, fmt.Errorf("open index for %s at %s: %w", s.name(), s.Store.IndexDir, err)
		}
		loaded[i] = l
	}

	out := &SearchOutcome{Mode: "hybrid"}
	// usedVectors 记录本次是否真的算过向量检索：决定最终输出的 mode 标签。
	// 只有 rerank 失败时仍然算 hybrid（结果是向量 + BM25 的 RRF 融合，只是没精排）；
	// 没算过向量（离线 / bm25-only / embedding 失败 / 维度不匹配）才是 bm25。
	usedVectors := false

	// ---- 在线路径：各索引 hybrid 取候选 → 轮转合并 → 统一 rerank 一次 ----
	if m.Embedder != nil && !allBM25Only(loaded) {
		qvecs, err := m.Embedder.Embed(ctx, []string{query})
		if err == nil && len(qvecs) > 0 && qvecs[0] != nil {
			q := vector.Normalize(qvecs[0])
			if cands, ok := m.hybridCandidates(loaded, query, q, out); ok {
				usedVectors = true
				if res, ok := m.rerankOnce(ctx, query, cands, topM); ok {
					out.Gateway = embedderGateway(m.Embedder)
					out.Results = res
					out.TotalMS = time.Since(t0).Milliseconds()
					return out, nil
				}
				// rerank 失败：按设计改用各索引内排名的 RRF 合并。
				out.FallbackReason = "rerank failed; merged by RRF over per-index rankings"
			}
			// 维度不匹配：hybridCandidates 已写好 fallback 说明，落到下面的 RRF 合并。
		} else {
			out.FallbackReason = "embedding failed"
			if err != nil {
				out.FallbackReason = err.Error()
			}
		}
	} else if allBM25Only(loaded) {
		out.FallbackReason = "all indexes are bm25-only (built with build -offline)"
	} else {
		out.FallbackReason = "embedder not configured"
	}

	// ---- 离线 / bm25-only / 维度不匹配 / rerank 失败：按各索引内排名做 RRF 合并 ----
	if !usedVectors {
		out.Mode = "bm25"
	}
	out.Results = m.rrfMerge(loaded, query, topM)
	out.TotalMS = time.Since(t0).Milliseconds()
	return out, nil
}

// candidate 一个合并候选：来自哪个源 + 块本身 + 在该源内的 RRF 排名。
type candidate struct {
	src   int
	chunk chunker.Chunk
	rank  int     // 在所属源候选列表里的序号（0 起）
	score float64 // 该源内的 RRF 得分（仅用于输出与同分排序）
}

// hybridCandidates 每个索引各做一次现有 hybrid，只在源内截取 RRF 前 multiPerIndex 条（不
// rerank），然后按排名轮转截取到 multiCandidates 条。返回 false 表示某个在线索引的
// 向量维度与查询不符，无法走 hybrid（out.FallbackReason 已写明原因）。
func (m *MultiRetriever) hybridCandidates(loaded []*docstore.Loaded, query string, q []float32, out *SearchOutcome) ([]candidate, bool) {
	perSource := make([][]candidate, len(loaded))
	for i, l := range loaded {
		if l.Meta.BM25Only() {
			// 离线索引没有向量：该源按纯 BM25 排名参与轮转（不构造查询向量）。
			perSource[i] = bm25Candidates(i, l, query, multiPerIndex)
			continue
		}
		dim := 0
		if l.Vector != nil {
			dim = l.Vector.Dim
		}
		if dim != 0 && len(q) != dim {
			out.FallbackReason = fmt.Sprintf("vector dim mismatch at %s: query=%d index=%d", m.Sources[i].name(), len(q), dim)
			return nil, false
		}
		var bmRes []fusion.Ranked
		if l.BM25 != nil { // 防御：BM25 缺失（不应发生，Open 已校验）时退化为纯向量融合
			bmRes = toRankedBM25(l.BM25.Search(query, bm25TopK))
		}
		fused := fusion.RRF(toRankedVec(l.Vector.Search(q, vectorTopK)), bmRes, rrfK)
		if len(fused) > multiPerIndex {
			fused = fused[:multiPerIndex]
		}
		cands := make([]candidate, 0, len(fused))
		for rank, fr := range fused {
			c, ok := l.ChunkByID[fr.ChunkID]
			if !ok {
				continue
			}
			cands = append(cands, candidate{src: i, chunk: c, rank: rank, score: fr.Score})
		}
		perSource[i] = cands
	}
	return roundRobin(perSource, multiCandidates), true
}

// rrfMerge 合并多索引的纯 BM25 排名：按各索引内的名次累加 1/(k+rank+1)（k=60），
// 同一块出现在多个索引时得分累加。离线索引与在线索引一视同仁——不构造查询向量，
// 因此离线路径不会把查询文本发出去。
func (m *MultiRetriever) rrfMerge(loaded []*docstore.Loaded, query string, topM int) []Result {
	score := map[string]float64{}
	srcOf := map[string]int{}
	var order []string // 首次出现顺序，作同分的稳定次序
	for i, l := range loaded {
		for rank, r := range bm25Ranked(l, query, bm25TopK) {
			if _, seen := score[r.ChunkID]; !seen {
				order = append(order, r.ChunkID)
				srcOf[r.ChunkID] = i
			}
			score[r.ChunkID] += 1 / float64(rrfK+rank+1)
		}
	}
	sort.SliceStable(order, func(a, b int) bool {
		if score[order[a]] != score[order[b]] {
			return score[order[a]] > score[order[b]]
		}
		return order[a] < order[b]
	})
	if len(order) > topM {
		order = order[:topM]
	}
	res := make([]Result, 0, len(order))
	for _, id := range order {
		i := srcOf[id]
		c, ok := loaded[i].ChunkByID[id]
		if !ok {
			continue
		}
		res = append(res, m.makeResult(i, c, score[id]))
	}
	return res
}

// rerankOnce 对合并后的候选统一 rerank 一次，取前 topM。
// 返回 ok=false 表示 rerank 失败——调用方据此改用 RRF 合并（设计约定，
// 而不是悄悄退回候选原顺序，那样会把未精排的结果当成精排结果输出）。
func (m *MultiRetriever) rerankOnce(ctx context.Context, query string, cands []candidate, topM int) ([]Result, bool) {
	if len(cands) == 0 {
		return nil, true
	}
	docs := make([]string, len(cands))
	for i, c := range cands {
		docs[i] = c.chunk.Text
	}
	perm, ok := rerankPerm(ctx, m.Reranker, query, docs, topM)
	if !ok {
		return nil, false
	}
	res := make([]Result, 0, len(perm))
	for _, p := range perm {
		if p < 0 || p >= len(cands) {
			continue
		}
		c := cands[p]
		res = append(res, m.makeResult(c.src, c.chunk, c.score))
	}
	return res, true
}

// rerankPerm rerank 后的下标顺序。ok=false 表示 reranker 缺失或调用失败；
// 候选不足 2 条时无需精排，按原顺序返回（ok=true）。
func rerankPerm(ctx context.Context, rr embed.Reranker, query string, docs []string, topN int) (perm []int, ok bool) {
	if topN > len(docs) {
		topN = len(docs)
	}
	if rr != nil && len(docs) > 1 {
		got, err := rr.Rerank(ctx, query, docs, topN)
		if err != nil {
			return nil, false
		}
		return got, true
	}
	perm = make([]int, topN)
	for i := range perm {
		perm[i] = i
	}
	return perm, true
}

func (m *MultiRetriever) makeResult(src int, c chunker.Chunk, score float64) Result {
	path := c.SourceFile
	if m.Sources[src].PathPrefix != nil {
		path = m.Sources[src].PathPrefix(c.SourceFile)
	}
	return Result{
		ChunkID:    c.ChunkID,
		Text:       c.Text,
		SourceFile: path,
		LineStart:  c.LineStart,
		LineEnd:    c.LineEnd,
		Score:      score,
		Entity:     m.Sources[src].Label,
	}
}

// roundRobin 按各源排名轮转截取（各源第 1 名 → 各源第 2 名 → …），总数不超过 limit。
// 轮转而非直接拼接，避免某个索引前几名把候选名额全占掉。
func roundRobin(perSource [][]candidate, limit int) []candidate {
	out := make([]candidate, 0, limit)
	for depth := 0; len(out) < limit; depth++ {
		progressed := false
		for _, src := range perSource {
			if depth >= len(src) {
				continue
			}
			progressed = true
			out = append(out, src[depth])
			if len(out) >= limit {
				return out
			}
		}
		if !progressed {
			return out
		}
	}
	return out
}

// bm25Candidates 单个索引的纯 BM25 候选（离线源参与轮转时用）。
func bm25Candidates(src int, l *docstore.Loaded, query string, limit int) []candidate {
	if l.BM25 == nil {
		return nil
	}
	res := l.BM25.Search(query, limit)
	out := make([]candidate, 0, len(res))
	for rank, r := range res {
		if rank >= limit {
			break
		}
		c, ok := l.ChunkByID[r.ChunkID]
		if !ok {
			continue
		}
		out = append(out, candidate{src: src, chunk: c, rank: rank, score: r.Score})
	}
	return out
}

// bm25Ranked 单个索引的 BM25 排名（BM25 缺失时为空，防御损坏索引）。
func bm25Ranked(l *docstore.Loaded, query string, topK int) []fusion.Ranked {
	if l.BM25 == nil {
		return nil
	}
	return toRankedBM25(l.BM25.Search(query, topK))
}

func allBM25Only(loaded []*docstore.Loaded) bool {
	for _, l := range loaded {
		if !l.Meta.BM25Only() {
			return false
		}
	}
	return true
}
