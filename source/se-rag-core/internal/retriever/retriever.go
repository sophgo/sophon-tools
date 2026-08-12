// Package retriever 混合检索器：向量(FAISS 暴力内积) + BM25 → RRF 融合 → Rerank。
// 在线路径 A 失败（无 key / 断网 / embedding 异常）时降级为纯 BM25 路径 B。
package retriever

import (
	"context"
	"fmt"
	"strings"
	"time"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/fusion"
	"se-rag-core/internal/vector"
)

const (
	vectorTopK = 20
	bm25TopK   = 20
	rrfK       = 60
	finalTopK  = 20
)

type Result struct {
	ChunkID    string
	Text       string
	SourceFile string
	LineStart  int
	LineEnd    int
	Score      float64
}

type SearchOutcome struct {
	Results        []Result
	Mode           string // "hybrid" | "bm25"
	FallbackReason string
	TotalMS        int64
}

type Retriever struct {
	Store    *docstore.Store
	Embedder embed.Embedder
	Reranker embed.Reranker
}

func (r *Retriever) Search(ctx context.Context, query string, product string, topM int) (*SearchOutcome, error) {
	t0 := time.Now()
	if topM <= 0 {
		topM = 8
	}
	loaded, err := r.Store.Open(product)
	if err != nil {
		return nil, fmt.Errorf("open index: %w", err)
	}
	out := &SearchOutcome{Mode: "hybrid"}

	// ---- 在线路径 A：embedding + 向量混合 ----
	if r.Embedder != nil {
		qvecs, err := r.Embedder.Embed(ctx, []string{query})
		if err == nil && len(qvecs) > 0 && qvecs[0] != nil {
			q := vector.Normalize(qvecs[0])
			// 维度校验（换供应商/模型维度不同会走这里）
			if len(q) != loaded.Vector.Dim && loaded.Vector.Dim != 0 {
				out.FallbackReason = fmt.Sprintf(
					"vector dim mismatch query=%d index=%d", len(q), loaded.Vector.Dim)
				return r.bm25Fallback(loaded, query, topM, out, t0)
			}
			out.Results = r.hybrid(ctx, loaded, query, q, topM)
			out.TotalMS = time.Since(t0).Milliseconds()
			return out, nil
		}
		out.FallbackReason = "embedding failed"
		if err != nil {
			out.FallbackReason = err.Error()
		}
	} else {
		out.FallbackReason = "embedder not configured"
	}

	// ---- 兜底路径 B：纯 BM25 ----
	return r.bm25Fallback(loaded, query, topM, out, t0)
}

func (r *Retriever) hybrid(ctx context.Context, loaded *docstore.Loaded, query string, q []float32, topM int) []Result {
	vecRes := loaded.Vector.Search(q, vectorTopK)
	bmRes := loaded.BM25.Search(query, bm25TopK)
	if bmRes == nil {
		bmRes = []bm25.Result{}
	}
	fused := fusion.RRF(toRankedVec(vecRes), toRankedBM25(bmRes), rrfK)

	// rerank（候选取 finalTopK）
	var order []string
	if r.Reranker != nil && len(fused) > 1 {
		ids := make([]string, 0, len(fused))
		docs := make([]string, 0, len(fused))
		for _, fr := range fused {
			if c, ok := loaded.ChunkByID[fr.ChunkID]; ok {
				ids = append(ids, fr.ChunkID)
				docs = append(docs, c.Text)
			}
		}
		if perm, err := r.Reranker.Rerank(ctx, query, docs, topM); err == nil {
			for _, p := range perm {
				if p >= 0 && p < len(ids) {
					order = append(order, ids[p])
				}
			}
		} else {
			// rerank 失败 → 退回 RRF 顺序
			for _, fr := range fused[:min(topM, len(fused))] {
				order = append(order, fr.ChunkID)
			}
		}
	} else {
		for _, fr := range fused[:min(topM, len(fused))] {
			order = append(order, fr.ChunkID)
		}
	}

	scoreFor := map[string]float64{}
	for _, fr := range fused {
		scoreFor[fr.ChunkID] = fr.Score
	}
	return buildResults(loaded, order, scoreFor)
}

func (r *Retriever) bm25Fallback(loaded *docstore.Loaded, query string, topM int, out *SearchOutcome, t0 time.Time) (*SearchOutcome, error) {
	out.Mode = "bm25"
	bmRes := loaded.BM25.Search(query, topM)
	scoreFor := map[string]float64{}
	order := make([]string, 0, len(bmRes))
	for _, b := range bmRes {
		order = append(order, b.ChunkID)
		scoreFor[b.ChunkID] = b.Score
	}
	out.Results = buildResults(loaded, order, scoreFor)
	out.TotalMS = time.Since(t0).Milliseconds()
	return out, nil
}

func buildResults(loaded *docstore.Loaded, order []string, scoreFor map[string]float64) []Result {
	seen := map[string]bool{}
	out := make([]Result, 0, len(order))
	for _, id := range order {
		if seen[id] {
			continue
		}
		seen[id] = true
		c, ok := loaded.ChunkByID[id]
		if !ok {
			continue
		}
		out = append(out, Result{
			ChunkID:    id,
			Text:       c.Text,
			SourceFile: c.SourceFile,
			LineStart:  c.LineStart,
			LineEnd:    c.LineEnd,
			Score:      scoreFor[id],
		})
	}
	return out
}

func toRankedVec(v []vector.Result) []fusion.Ranked {
	out := make([]fusion.Ranked, len(v))
	for i, x := range v {
		out[i] = fusion.Ranked{ChunkID: x.ChunkID, Score: x.Score}
	}
	return out
}

func toRankedBM25(b []bm25.Result) []fusion.Ranked {
	out := make([]fusion.Ranked, len(b))
	for i, x := range b {
		out[i] = fusion.Ranked{ChunkID: x.ChunkID, Score: x.Score}
	}
	return out
}

// DimMismatchError 维度不匹配错误（替换供应商/模型导致索引需重建）。
type DimMismatchError struct {
	IndexDim int
	QueryDim int
}

func (e *DimMismatchError) Error() string {
	return fmt.Sprintf("index rebuilt for %d-dim vectors, current query is %d-dim; run `se-rag build` to rebuild",
		e.IndexDim, e.QueryDim)
}

// CheckFingerprint 校验索引维度 vs 期望维度；不一致返回 DimMismatchError 提示重建。
func CheckFingerprint(indexDim, wantDim int) error {
	if indexDim != 0 && wantDim != 0 && indexDim != wantDim {
		return &DimMismatchError{IndexDim: indexDim, QueryDim: wantDim}
	}
	return nil
}

// FormatMarkdown 将检索结果格式化为 Markdown（对齐 Python query.py 输出格式）。
func FormatMarkdown(out *SearchOutcome) string {
	var sb strings.Builder
	for i, r := range out.Results {
		fmt.Fprintf(&sb, "### %d [%.3f] `%s:%d-%d`\n", i+1, r.Score, r.SourceFile, r.LineStart, r.LineEnd)
		text := r.Text
		rs := []rune(text)
		if len(rs) > 500 {
			text = string(rs[:500]) + "..."
		}
		sb.WriteString(strings.TrimSpace(text))
		sb.WriteString("\n\n")
	}
	sb.WriteString("---\n")
	fmt.Fprintf(&sb, "*%d results | mode=%s | total %dms*\n", len(out.Results), out.Mode, out.TotalMS)
	if out.FallbackReason != "" {
		fmt.Fprintf(&sb, "*fallback: %s*\n", out.FallbackReason)
	}
	return sb.String()
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
