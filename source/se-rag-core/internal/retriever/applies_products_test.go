package retriever

// applies_products 过滤的单元测试：三态语义、逐源生效、与 doc_type 组合、
// 以及在候选阶段（top-n 截断之前）生效。

import (
	"context"
	"path/filepath"
	"testing"

	"se-rag-core/internal/chunker"
)

// appliesChunk 带 applies_products 的块。
func appliesChunk(id, text, file string, products []string, declared bool) chunker.Chunk {
	return chunker.Chunk{
		ChunkID: id, Text: text, SourceFile: file, LineStart: 1, LineEnd: 2,
		AppliesProducts: products, AppliesProductsDeclared: declared,
	}
}

// 三态：缺失保留、有交集保留、空列表与无交集丢弃。
func TestChunkFilterAppliesProducts(t *testing.T) {
	f := &ChunkFilter{Products: map[string]bool{"se9": true}}
	cases := []struct {
		name  string
		chunk chunker.Chunk
		want  bool
	}{
		{"字段缺失=不限产品", appliesChunk("a", "x", "a.md", nil, false), true},
		{"有交集", appliesChunk("b", "x", "b.md", []string{"se7", "se9"}, true), true},
		{"无交集", appliesChunk("c", "x", "c.md", []string{"se7", "se8"}, true), false},
		{"显式空列表", appliesChunk("d", "x", "d.md", []string{}, true), false},
	}
	for _, c := range cases {
		if got := f.Allow(c.chunk); got != c.want {
			t.Errorf("%s: Allow = %v, want %v", c.name, got, c.want)
		}
	}
}

// Products 为 nil 时不做产品过滤（用户直接点名 toolkit 的场景）。
func TestChunkFilterNoProductsPassesEverything(t *testing.T) {
	f := &ChunkFilter{}
	for _, c := range []chunker.Chunk{
		appliesChunk("a", "x", "a.md", nil, false),
		appliesChunk("b", "x", "b.md", []string{"se8"}, true),
		appliesChunk("c", "x", "c.md", []string{}, true),
	} {
		if !f.Allow(c) {
			t.Errorf("%s 不应被过滤（没有产品条件）", c.ChunkID)
		}
	}
	if f.Active() {
		t.Error("只有 Products 为 nil 时不应算作有过滤条件")
	}
}

// 产品过滤生效时 Active() 为真（预取深度才会放大），但 doc_type 标注不因此出现。
func TestChunkFilterProductsActiveButNoDocTypeTag(t *testing.T) {
	f := &ChunkFilter{Products: map[string]bool{"se9": true}}
	if !f.Active() {
		t.Error("产品过滤生效时 Active() 应为真（否则不会放大预取深度，过滤后可能一条不剩）")
	}
	if f.DocTypeActive() {
		t.Error("只有产品条件时 DocTypeActive() 应为假（结果不该被追加 /doc_type 标注）")
	}
	if tag := chunkDocTypeIfFiltering(f, appliesChunk("a", "x", "tools/a.md", nil, false)); tag != "" {
		t.Errorf("只有产品条件时不应标注 doc_type，得到 %q", tag)
	}
}

// 两个条件组合：都满足才保留。
func TestChunkFilterProductsCombinedWithDocType(t *testing.T) {
	f := &ChunkFilter{
		Allowed:   map[string]bool{"tools": true},
		DocTypeOf: func(string) string { return "tools" },
		Products:  map[string]bool{"se9": true},
	}
	// 类型对但产品不对
	if f.Allow(appliesChunk("a", "x", "tools/a.md", []string{"se8"}, true)) {
		t.Error("产品不适用时应丢弃")
	}
	// 产品对但类型不对
	f2 := &ChunkFilter{
		Allowed:   map[string]bool{"tools": true},
		DocTypeOf: func(string) string { return "faq" },
		Products:  map[string]bool{"se9": true},
	}
	if f2.Allow(appliesChunk("b", "x", "faq/b.md", []string{"se9"}, true)) {
		t.Error("类型不匹配时应丢弃")
	}
	// 两者都满足
	if !f.Allow(appliesChunk("c", "x", "tools/c.md", []string{"se9"}, true)) {
		t.Error("两个条件都满足时应保留")
	}
}

// WithProducts / ForPathPrefix 派生时两条件都要带过去。
func TestChunkFilterDerivationsKeepBothConditions(t *testing.T) {
	base := &ChunkFilter{
		Allowed:   map[string]bool{"tools": true},
		DocTypeOf: func(p string) string { return "tools" },
	}
	withProducts := base.WithProducts(map[string]bool{"se9": true})
	if withProducts.Products == nil || len(withProducts.Allowed) != 1 {
		t.Fatalf("WithProducts 后应同时保留两个条件：%+v", withProducts)
	}
	prefixed := withProducts.ForPathPrefix(func(p string) string { return "docs/toolkits/x/" + p })
	if prefixed.Products == nil || len(prefixed.Allowed) != 1 {
		t.Fatalf("ForPathPrefix 后应同时保留两个条件：%+v", prefixed)
	}
	if !prefixed.Allow(appliesChunk("a", "x", "tools/a.md", []string{"se9"}, true)) {
		t.Error("派生后仍应放行适用产品 + 类型匹配的块")
	}
	if prefixed.Allow(appliesChunk("b", "x", "tools/b.md", []string{"se8"}, true)) {
		t.Error("派生后仍应丢弃产品不适用的块")
	}
	// nil 上派生出的非 nil 产品条件
	if got := (*ChunkFilter)(nil).WithProducts(map[string]bool{"se9": true}); got == nil || got.Products == nil {
		t.Error("nil 过滤器上设置产品条件应得到有效的过滤器")
	}
}

// 逐源生效：只有带 Products 的源被过滤，其它源完整返回。
func TestMultiRetrieverProductFilterPerSource(t *testing.T) {
	product := writeSource(t, filepath.Join(t.TempDir(), "p"), sourceFixture{
		label:  "se9",
		chunks: []chunker.Chunk{chunk("p1", "工具资料 SE9", "faq.md")},
	})
	toolkit := writeSource(t, filepath.Join(t.TempDir(), "t"), sourceFixture{
		label: "sophon-tools",
		chunks: []chunker.Chunk{
			appliesChunk("t1", "工具资料 适用 se8", "tools/bmsec.md", []string{"se8"}, true),
			appliesChunk("t2", "工具资料 适用 se9", "tools/socbak.md", []string{"se9"}, true),
			appliesChunk("t3", "工具资料 不限产品", "tools/get-info.md", nil, false),
		},
	})
	// 只有 toolkit 源带产品过滤；产品源不受影响。
	toolkit.Products = map[string]bool{"se9": true}

	m := &MultiRetriever{Sources: []Source{product, toolkit}}
	out, err := m.Search(context.Background(), "工具资料", 10)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]bool{}
	for _, r := range out.Results {
		got[r.ChunkID] = true
	}
	for _, want := range []string{"p1", "t2", "t3"} {
		if !got[want] {
			t.Errorf("应保留 %s，得到 %v", want, keysOf(got))
		}
	}
	if got["t1"] {
		t.Errorf("适用 se8 的块必须丢弃，得到 %v", keysOf(got))
	}
}

// 过滤发生在候选阶段：被过滤的块分数最高时，结果仍能凑满 n 条。
func TestMultiRetrieverProductFilterBeforeTopN(t *testing.T) {
	// 10 个适用 se8 的块，查询词在它们里面反复出现（BM25 分数最高）；
	// 2 个适用 se9 的块，只提一次。
	var fast []chunker.Chunk
	for i, id := range []string{"f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10"} {
		fast = append(fast, appliesChunk(id, "yolo26 支持 模型 yolo26 支持 模型 yolo26 支持 模型",
			filepath.ToSlash(filepath.Join("tools", id+".md")), []string{"se8"}, true))
		_ = i
	}
	slow := []chunker.Chunk{
		appliesChunk("s1", "yolo26 支持 模型 的说明一", "tools/s1.md", []string{"se9"}, true),
		appliesChunk("s2", "yolo26 支持 模型 的说明二", "tools/s2.md", []string{"se9"}, true),
	}
	src := writeSource(t, filepath.Join(t.TempDir(), "t"), sourceFixture{
		label: "sophon-demo", chunks: append(fast, slow...),
	})
	src.Products = map[string]bool{"se9": true}

	m := &MultiRetriever{Sources: []Source{src}}
	out, err := m.Search(context.Background(), "yolo26 支持 模型", 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Results) != 2 {
		t.Fatalf("过滤发生在 top-n 之前：应仍能返回 2 条，得到 %d 条 %v", len(out.Results), idsOf(out.Results))
	}
	for _, r := range out.Results {
		if r.ChunkID != "s1" && r.ChunkID != "s2" {
			t.Errorf("只应返回适用 se9 的块，得到 %v", idsOf(out.Results))
		}
	}
}

func keysOf(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func idsOf(rs []Result) []string {
	out := make([]string, 0, len(rs))
	for _, r := range rs {
		out = append(out, r.ChunkID)
	}
	return out
}
