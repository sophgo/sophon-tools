package retriever

import (
	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/vector"
)

// ChunkFilter 检索期的块过滤（`-doc-type` 与 toolkit 的产品适用范围）。不改文档也不改索引：
// 同一份索引既能全量检索，也能只检索某几类文档 / 某几个产品适用的文档。
//
// 类型来源有两处，**文档自述优先**：
//  1. 块记录里的 doc_type（建索引时从 frontmatter 读，见 chunker.Chunk.DocType）；
//  2. 没有 frontmatter 时按源路径推断（见 registry.DocType）。
//
// 这样迁移期半新半旧的文档也能分类，而只认路径就永远无法区分
// "根目录的 overview" 与 "根目录的 image-catalog"。
//
// 过滤发生在融合（RRF）之前：每个索引先放大预取深度、按 doc_type 过滤、再排名融合。
// 若先按原深度取候选再过滤，被排除的块已经占掉名额，某些类型可能一条都不剩。
//
// 两个条件（doc_type、产品适用范围）互相独立、同时生效：都满足才保留。
type ChunkFilter struct {
	// Allowed 允许的 doc_type 集合。
	Allowed map[string]bool
	// DocTypeOf 把块记录里的源路径映射到 doc_type。源路径是"相对该索引 docs_dir"
	// 的路径；多索引场景用 ForPathPrefix 包一层，先还原成技能根相对路径再推断。
	DocTypeOf func(src string) string
	// Products 允许的产品集合（对应块 frontmatter 的 applies_products）。nil 表示
	// 不做产品过滤。多索引场景**逐源**设置：经产品带入的 toolkit 源才有值，
	// 用户直接指定 toolkit 时不过滤。
	Products map[string]bool
}

// ChunkDocType 单个块的实际 doc_type：块自述优先，缺失时按路径推断。
// 过滤器与结果标注都走这里，保证"过滤掉的"与"标注出来的"完全一致。
func (f *ChunkFilter) ChunkDocType(c chunker.Chunk) string {
	if c.DocType != "" {
		return c.DocType
	}
	return f.TypeOf(c.SourceFile)
}

// chunkDocTypeIfFiltering 单索引结果的类型标注：只有 doc_type 过滤生效时才返回 doc_type，
// 否则为空。产品适用范围过滤不影响标注——它不改变"这条结果是什么类型"。
func chunkDocTypeIfFiltering(f *ChunkFilter, c chunker.Chunk) string {
	if !f.DocTypeActive() {
		return ""
	}
	return f.ChunkDocType(c)
}

// Active 是否有实际的过滤条件（doc_type 或产品适用范围任一）。
func (f *ChunkFilter) Active() bool {
	return f != nil && (len(f.Allowed) > 0 || f.Products != nil)
}

// DocTypeActive 是否按 doc_type 过滤。结果标注只在它生效时追加类型段。
func (f *ChunkFilter) DocTypeActive() bool { return f != nil && len(f.Allowed) > 0 }

// Allow 该块是否放行。无过滤时一律放行；两个条件都满足才放行。
func (f *ChunkFilter) Allow(c chunker.Chunk) bool {
	if !f.Active() {
		return true
	}
	if len(f.Allowed) > 0 && !f.Allowed[f.ChunkDocType(c)] {
		return false
	}
	return f.productAllowed(c)
}

// productAllowed 块的 applies_products 是否与本次允许的产品集合相容。
//
//	字段缺失（AppliesProductsDeclared=false） → 保留：通用指南对所有产品有效
//	与允许集合有交集                        → 保留
//	其余（显式空列表、无交集）              → 丢弃
//
// 显式空列表与缺失必须区分：前者是"哪个产品都不适用"，后者是"不限产品"。
func (f *ChunkFilter) productAllowed(c chunker.Chunk) bool {
	if f.Products == nil {
		return true
	}
	if !c.AppliesProductsDeclared {
		return true
	}
	for _, p := range c.AppliesProducts {
		if f.Products[p] {
			return true
		}
	}
	return false
}

// TypeOf 该源路径的 doc_type（无过滤器时为空串，输出里就不带类型标注）。
func (f *ChunkFilter) TypeOf(src string) string {
	if f == nil || f.DocTypeOf == nil {
		return ""
	}
	return f.DocTypeOf(src)
}

// ForPathPrefix 派生一个新过滤器：先把源路径交给 prefix 还原成展示路径，再判断类型。
// prefix 为 nil 时原样返回自身。产品集合随派生一起带过去——它是源的属性，与路径无关。
func (f *ChunkFilter) ForPathPrefix(prefix func(string) string) *ChunkFilter {
	if f == nil || prefix == nil {
		return f
	}
	src := f.DocTypeOf
	return &ChunkFilter{
		Allowed: f.Allowed,
		DocTypeOf: func(p string) string {
			if src == nil {
				return ""
			}
			return src(prefix(p))
		},
		Products: f.Products,
	}
}

// WithProducts 派生一个只换产品集合的过滤器：products 为 nil 表示该源不做产品过滤。
//
// 这是"经产品带入的 toolkit 源按产品过滤、用户直接指定的 toolkit 不过滤"的落地点：
// 逐源设置，不改其它源、也不改 doc_type 条件。
func (f *ChunkFilter) WithProducts(products map[string]bool) *ChunkFilter {
	if f == nil {
		if products == nil {
			return nil
		}
		return &ChunkFilter{Products: products}
	}
	if products == nil && f.Products == nil {
		return f
	}
	return &ChunkFilter{
		Allowed:   f.Allowed,
		DocTypeOf: f.DocTypeOf,
		Products:  products,
	}
}

// filterCandidateK 带过滤时每个索引的预取深度上限。
//
// 过滤把一部分块排除在外，仍按原来的 top20 预取可能一条都不剩。索引规模在几百到
// 几千块量级（内存暴力检索），放大预取的成本可以忽略；上限 500 避免在超大索引上
// 无谓扫全表。
const filterCandidateK = 500

// candidateK 预取深度：无过滤时沿用默认值，有过滤时放大（不超过索引实际块数）。
func candidateK(base int, f *ChunkFilter, l *docstore.Loaded) int {
	if !f.Active() {
		return base
	}
	n := len(l.Chunks)
	if n == 0 || n > filterCandidateK {
		n = filterCandidateK
	}
	if n < base {
		n = base
	}
	return n
}

// searchVector 向量检索 + doc_type 过滤（过滤后截到 topK）。
func searchVector(l *docstore.Loaded, q []float32, topK int, f *ChunkFilter) []vector.Result {
	if !f.Active() {
		return l.Vector.Search(q, topK)
	}
	return filterVec(l.Vector.Search(q, candidateK(topK, f, l)), l, f, topK)
}

// searchBM25 BM25 检索 + doc_type 过滤（过滤后截到 topK）。
func searchBM25(l *docstore.Loaded, query string, topK int, f *ChunkFilter) []bm25.Result {
	if l.BM25 == nil {
		return nil
	}
	if !f.Active() {
		return l.BM25.Search(query, topK)
	}
	return filterBM(l.BM25.Search(query, candidateK(topK, f, l)), l, f, topK)
}

func filterVec(res []vector.Result, l *docstore.Loaded, f *ChunkFilter, topK int) []vector.Result {
	out := make([]vector.Result, 0, len(res))
	for _, r := range res {
		if len(out) >= topK {
			break
		}
		if c, ok := l.ChunkByID[r.ChunkID]; ok && f.Allow(c) {
			out = append(out, r)
		}
	}
	return out
}

func filterBM(res []bm25.Result, l *docstore.Loaded, f *ChunkFilter, topK int) []bm25.Result {
	out := make([]bm25.Result, 0, len(res))
	for _, r := range res {
		if len(out) >= topK {
			break
		}
		if c, ok := l.ChunkByID[r.ChunkID]; ok && f.Allow(c) {
			out = append(out, r)
		}
	}
	return out
}
