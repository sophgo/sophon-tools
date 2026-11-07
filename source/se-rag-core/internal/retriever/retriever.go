// Package retriever 混合检索器：向量(内存暴力内积) + BM25 → RRF 融合 → Rerank。
// 在线路径 A 失败（无 key / 断网 / embedding 异常）时降级为纯 BM25 路径 B。
package retriever

import (
	"context"
	"fmt"
	"strings"
	"time"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/fusion"
	"se-rag-core/internal/ident"
	"se-rag-core/internal/titlematch"
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
	// Entity 结果所属实体 id（注册表模式，多索引合并时标注）；路径模式为空。
	// 为空时输出与旧版逐字节一致。
	Entity string
	// DocType 该块的文档类型（只在使用 -doc-type 时填写）。为空时输出不带类型标注，
	// 因此"单实体单索引且不带 -doc-type"的逐字节约定不受影响。
	DocType string
	// Version 文档版本（frontmatter 的 version，没有时为 null）。仅在多索引/带 -doc-type
	// 的输出里作为标注的版本段出现；为空时省略版本段。
	Version string
}

type SearchOutcome struct {
	Results        []Result
	Mode           string // "hybrid" | "bm25"
	FallbackReason string
	Gateway        string // 实际服务本次检索的网关地址（空 = 未联网/未成功）
	TotalMS        int64
}

// gatewayNamer 由 embedder/reranker 实现，暴露最近一次实际命中的网关。
// 用可选接口而非改动 Embedder 契约：sophnet 等供应商不经网关，无需实现。
type gatewayNamer interface {
	Gateway() string
}

type Retriever struct {
	Store    *docstore.Store
	Embedder embed.Embedder
	Reranker embed.Reranker
	// Filter 检索期块过滤（`-doc-type`）；nil 表示不过滤，行为与旧版一致。
	Filter *ChunkFilter
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

	// 纯 BM25 索引（build -offline 产出）没有向量可比：即使用户配了 embedder，
	// 也不构造查询向量、不 rerank——否则会把查询文本发出去，违背离线索引的约定。
	if loaded.Meta.BM25Only() {
		out.FallbackReason = "index is bm25-only (built with build -offline)"
		return r.bm25Fallback(loaded, query, topM, out, t0)
	}

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
			out.Gateway = embedderGateway(r.Embedder)
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
	vecRes := searchVector(loaded, q, vectorTopK, r.Filter)
	// 防御：BM25 缺失（不应发生，Open 已校验）时退化为纯向量融合
	bmRes := searchBM25(loaded, query, bm25TopK, r.Filter)
	fused := fusion.RRFWeighted([]fusion.Path{
		{Ranked: toRankedVec(vecRes), Weight: 1},
		{Ranked: toRankedBM25(bmRes), Weight: 1},
		titlePath(loaded, query, r.Filter),
	}, rrfK)

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
	// rerank 结果也要按 topM 截断：reranker 收到 topN 但契约上仍可能返回更多下标，
	// 不截断会让 -top-n 在有 rerank 的路径上同样失效。
	if len(order) > topM {
		order = order[:topM]
	}

	scoreFor := map[string]float64{}
	for _, fr := range fused {
		scoreFor[fr.ChunkID] = fr.Score
	}
	return buildResults(loaded, order, scoreFor, r.Filter)
}

func (r *Retriever) bm25Fallback(loaded *docstore.Loaded, query string, topM int, out *SearchOutcome, t0 time.Time) (*SearchOutcome, error) {
	out.Mode = "bm25"
	if loaded.BM25 == nil {
		// 防御：BM25 缺失（不应发生，Open 已校验）时返回显式错误而非 panic
		return nil, fmt.Errorf("%w: bm25 index unavailable", docstore.ErrIncomplete)
	}
	// 无标识符（或没有块的标题命中）时走原路径：结果与旧版逐字节一致。
	hits := titleHits(loaded, query, r.Filter)
	if len(hits) == 0 {
		bmRes := searchBM25(loaded, query, topM, r.Filter)
		scoreFor := map[string]float64{}
		order := make([]string, 0, len(bmRes))
		for _, b := range bmRes {
			order = append(order, b.ChunkID)
			scoreFor[b.ChunkID] = b.Score
		}
		out.Results = buildResults(loaded, order, scoreFor, r.Filter)
		out.TotalMS = time.Since(t0).Milliseconds()
		return out, nil
	}

	// 有标识符命中：BM25 与"标题精确匹配"两路做加权 RRF（离线模式没有向量路）。
	// 预取深度要够宽，否则 BM25 名次靠前的块已占满名额，标题命中块拿不到名次。
	bmRes := searchBM25(loaded, query, topM+len(hits), r.Filter)
	fused := fusion.RRFWeighted([]fusion.Path{
		{Ranked: toRankedBM25(bmRes), Weight: 1},
		{Ranked: titlematch.Ranked(hits), Weight: titlematch.Weight},
	}, rrfK)
	// 融合结果是两路排名的并集，条数可能远多于 topM（两路各 topM+len(hits) 条），
	// 必须按 topM 截断——否则 -top-n 在有标题命中的查询里会被忽略。
	if len(fused) > topM {
		fused = fused[:topM]
	}
	scoreFor := map[string]float64{}
	order := make([]string, 0, len(fused))
	for _, fr := range fused {
		order = append(order, fr.ChunkID)
		scoreFor[fr.ChunkID] = fr.Score
	}
	out.Results = buildResults(loaded, order, scoreFor, r.Filter)
	out.TotalMS = time.Since(t0).Milliseconds()
	return out, nil
}

// titlePath 第三路排名：查询里的标识符与分块自身标题的精确匹配。
// 没有标识符或没有标题命中时返回一路空排名（权重 1、零个名次），
// RRFWeighted 对空路不产生任何影响，因此旧查询的结果与旧版逐字节一致。
func titlePath(loaded *docstore.Loaded, query string, f *ChunkFilter) fusion.Path {
	hits := titleHits(loaded, query, f)
	if len(hits) == 0 {
		return fusion.Path{Weight: 1}
	}
	return fusion.Path{Ranked: titlematch.Ranked(hits), Weight: titlematch.Weight}
}

// titleHits 标题命中查询标识符的块（已按设计排序、截断到上限）。
// 带 doc_type 过滤时命中块同样必须通过过滤，否则 `-doc-type sdk` 会漏出 datasheet 块。
func titleHits(loaded *docstore.Loaded, query string, f *ChunkFilter) []titlematch.Hit {
	ids := ident.Identifiers(query)
	if len(ids) == 0 {
		return nil
	}
	chunks := loaded.Chunks
	if f.Active() {
		chunks = make([]chunker.Chunk, 0, len(loaded.Chunks))
		for _, c := range loaded.Chunks {
			if f.Allow(c) {
				chunks = append(chunks, c)
			}
		}
	}
	return titlematch.Rank(chunks, ids)
}

func buildResults(loaded *docstore.Loaded, order []string, scoreFor map[string]float64, f *ChunkFilter) []Result {
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
			// 单索引只在 -doc-type 生效时标注类型：不带过滤时输出必须与旧版逐字节一致，
			// 即使文档 frontmatter 自述了 doc_type（多索引结果另有 [实体/doc_type 版本] 标注规则）。
			DocType: chunkDocTypeIfFiltering(f, c),
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

// FingerprintMismatchError 索引指纹与当前配置不一致（供应商/模型/维度任一差异）→ 需重建。
type FingerprintMismatchError struct {
	IndexFp string
	WantFp  string
}

func (e *FingerprintMismatchError) Error() string {
	return fmt.Sprintf("index built for %s, current config is %s; run `se-rag build` to rebuild",
		e.IndexFp, e.WantFp)
}

// CheckFingerprint 校验索引完整指纹（provider.model@dim）vs 期望指纹；
// 任一为空（历史索引缺指纹字段/配置缺失）视为无法验证 → 提示重建，安全优先。
func CheckFingerprint(indexFp, wantFp string) error {
	if indexFp == "" || wantFp == "" {
		return &FingerprintMismatchError{IndexFp: indexFp, WantFp: wantFp}
	}
	if indexFp != wantFp {
		return &FingerprintMismatchError{IndexFp: indexFp, WantFp: wantFp}
	}
	return nil
}

// shortGateway 把网关 base URL 压成 host，便于输出阅读。
func shortGateway(u string) string {
	if i := strings.Index(u, "://"); i >= 0 {
		u = u[i+3:]
	}
	if i := strings.IndexAny(u, "/"); i >= 0 {
		u = u[:i]
	}
	return u
}

// FormatMarkdown 将检索结果格式化为 Markdown（对齐 Python query.py 输出格式）。
// 结果带实体标注（注册表模式）时在行尾追加 `[实体id]`；带 doc_type（用了 -doc-type）时
// 再追加 `/doc_type`（如 `[bm1688/datasheet]`）；文档有版本时再追加空格与版本
// （如 `[se9/spec v1.5]`）。全为空时输出与旧版逐字节一致。
func FormatMarkdown(out *SearchOutcome) string {
	var sb strings.Builder
	for i, r := range out.Results {
		fmt.Fprintf(&sb, "### %d [%.3f] `%s:%d-%d`", i+1, r.Score, r.SourceFile, r.LineStart, r.LineEnd)
		if tag := ResultTag(r.Entity, r.DocType, r.Version); tag != "" {
			fmt.Fprintf(&sb, " [%s]", tag)
		}
		sb.WriteString("\n")
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
	if out.Gateway != "" {
		fmt.Fprintf(&sb, "*gateway: %s*\n", shortGateway(out.Gateway))
	}
	if out.FallbackReason != "" {
		fmt.Fprintf(&sb, "*fallback: %s*\n", out.FallbackReason)
	}
	return sb.String()
}

// ResultTag 结果标注：`实体/doc_type 版本`，例如 `se9/spec v1.5`、`bm1684x/faq`。
//
// 三段都可缺：只有实体时不带斜杠；没有 doc_type 时不带类型段；版本为 null
// （frontmatter 写 null，或文档是 FAQ / 工具 README 这类无版本资料）时省略版本段。
// 全空返回空串——路径模式（无实体、无 doc_type）因此与旧版逐字节一致。
func ResultTag(entity, docType, version string) string {
	tag := entity
	if docType != "" {
		if tag != "" {
			tag += "/" + docType
		} else {
			tag = docType
		}
	}
	if version != "" {
		if tag != "" {
			tag += " " + version
		} else {
			tag = version
		}
	}
	return tag
}

// embedderGateway 取 embedder 最近一次命中的网关（未实现则空串）。
func embedderGateway(e embed.Embedder) string {
	if g, ok := e.(gatewayNamer); ok {
		return g.Gateway()
	}
	return ""
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
