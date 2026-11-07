// Package titlematch 把"查询里的标识符"与"分块自身标题里的标识符"做精确匹配，
// 产出参与 RRF 的第三路排名（标识符—标题精确匹配提权）。
//
// 背景：BM25 与向量都按内容相似度打分，寄存器概览表里同类词多、得分天然更高，
// 于是查 `rtc_ctrl_status1` 时概览表排第一、真正的字段表排不进前三。标题命中是
// 更强的意图信号：用户写下一个标识符时，想看的就是以它命名的那一节。
//
// 设计约束：不改索引格式，全部在查询期从分块正文推导（见 chunker.SelfHeadings），
// 已有索引不需要重建。查询中没有标识符时本路为空，融合结果与旧版完全一致。
package titlematch

import (
	"sort"

	"se-rag-core/internal/chunker"
	"se-rag-core/internal/fusion"
	"se-rag-core/internal/ident"
)

// MaxCandidates 这一路最多产出的候选数。
//
// 即使命中的块完全不在向量 / BM25 的 top-K 里也要加入候选，所以本路必须自己扫
// 全索引的块；上限 20 保证"最多 20 个"的约定，同时避免某个泛化标识符把候选池撑爆。
const MaxCandidates = 20

// Weight 这一路在 RRF 中的权重（其余两路为 1）。
//
// 取 2 让精确命中稳居第一：某块只在本路第 1 名（得分 2/(60+0+1)≈0.0328）仍高于
// 一块同时被向量与 BM25 排第 1 名（2/(60+0+1)≈0.0328 与上式同值，但实际语料里
// 概览表通常在 BM25 第 1、向量前几名，合计约 0.032），因此权重 2 足以把字段表顶到
// 概览表之前；再高会把只沾边的块也一起抬起来。
const Weight = 2

// Hit 一个标题命中的块。
type Hit struct {
	ChunkID string
	// Matched 命中的标识符个数（去重）。
	Matched int
	// TitleLen 命中的标题里最短的那一条的字符数（越短越专指）。
	TitleLen int
}

// Rank 在给定的块集合里找出标题命中查询标识符的块，按设计规则排序并截断。
//
// 排序：命中标识符个数降序 → 标题越短越靠前 → 原顺序（调用方传入的顺序，通常是
// 索引里的块序，保证同分时结果稳定可复现）。
//
// 返回空表示查询里没有标识符，或没有任何块的标题命中——调用方据此跳过第三路，
// 保持与旧版完全一致的融合结果。
func Rank(chunks []chunker.Chunk, queryIdents []string) []Hit {
	if len(queryIdents) == 0 || len(chunks) == 0 {
		return nil
	}
	want := map[string]bool{}
	for _, q := range queryIdents {
		// 入参约定是已提取的标识符，但这里再归一化一次：传原文（"WDT_STAT"）或
		// 大小写不一致时也按同一套规则比较，省掉调用方一个易错点。对已归一化的
		// 输入是幂等的（Identifiers 只做小写化与去重）。
		for _, id := range ident.Identifiers(q) {
			want[id] = true
		}
	}
	if len(want) == 0 {
		return nil
	}

	hits := make([]Hit, 0, len(chunks))
	for _, c := range chunks {
		if h, ok := scoreChunk(c, want); ok {
			hits = append(hits, h)
		}
	}
	if len(hits) == 0 {
		return nil
	}
	sort.SliceStable(hits, func(i, j int) bool {
		if hits[i].Matched != hits[j].Matched {
			return hits[i].Matched > hits[j].Matched
		}
		return hits[i].TitleLen < hits[j].TitleLen
	})
	if len(hits) > MaxCandidates {
		hits = hits[:MaxCandidates]
	}
	return hits
}

// scoreChunk 计算单个块的标题命中情况。ok=false 表示该块没有任何标题命中。
func scoreChunk(c chunker.Chunk, want map[string]bool) (Hit, bool) {
	matched := map[string]bool{}
	shortest := 0
	for _, title := range chunker.SelfHeadings(c.Text) {
		n := 0
		for _, id := range ident.Identifiers(title) {
			if want[id] {
				matched[id] = true
				n++
			}
		}
		if n == 0 {
			continue
		}
		// 标题长度只在"这条标题确实命中"时参与比较：同一个块的多个标题里，
		// 取最短的那条作为专指程度，避免长标题把短标题的优势抹掉。
		if l := len([]rune(title)); shortest == 0 || l < shortest {
			shortest = l
		}
	}
	if len(matched) == 0 {
		return Hit{}, false
	}
	return Hit{ChunkID: c.ChunkID, Matched: len(matched), TitleLen: shortest}, true
}

// Ranked 把命中列表转成 RRF 的一路排名。
func Ranked(hits []Hit) []fusion.Ranked {
	out := make([]fusion.Ranked, len(hits))
	for i, h := range hits {
		out[i] = fusion.Ranked{ChunkID: h.ChunkID}
	}
	return out
}
