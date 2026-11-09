package chunker

// applies_products：toolkit 文档的产品适用范围（1.9.0）。
//
// 三态必须可区分，这是同一份索引能被"按产品过滤"的前提：
//
//	字段缺失      → 不限产品（AppliesProductsDeclared=false）
//	非空列表      → 只对这些产品有效
//	空列表 `[]`   → 哪个产品都不适用

import (
	"bytes"
	"encoding/gob"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// 块列表：`applies_products:` 换行后逐项 `- se7`。
func TestFrontmatterAppliesProductsBlockList(t *testing.T) {
	content := "---\ntitle: yolo26\nentity: sophon-demo\ndoc_type: tools\napplies_products:\n  - se7\n  - se9\n---\n\n# yolo26\n\n例程。\n"
	got, declared := FrontmatterAppliesProducts(content)
	if !declared {
		t.Fatal("块列表应判为已声明")
	}
	if want := []string{"se7", "se9"}; !reflect.DeepEqual(got, want) {
		t.Errorf("applies_products = %v, want %v", got, want)
	}
}

// 行内 flow 列表也接受（脚本生成的 frontmatter 两种写法都出现过），取值统一小写。
func TestFrontmatterAppliesProductsInlineList(t *testing.T) {
	cases := map[string][]string{
		"---\napplies_products: [se7, se8, se9]\n---\n":        {"se7", "se8", "se9"},
		"---\napplies_products: [SE7,SE9]\n---\n":              {"se7", "se9"},
		`---` + "\n" + `applies_products: ["se9"]` + "\n---\n": {"se9"},
	}
	for content, want := range cases {
		got, declared := FrontmatterAppliesProducts(content)
		if !declared {
			t.Errorf("%q: 应判为已声明", content)
			continue
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%q: applies_products = %v, want %v", content, got, want)
		}
	}
}

// 空列表 `[]` 与字段缺失语义相反，必须能分辨。
func TestFrontmatterAppliesProductsEmptyVsMissing(t *testing.T) {
	empty, declared := FrontmatterAppliesProducts("---\ndoc_type: tools\napplies_products: []\n---\n\n# x\n")
	if !declared {
		t.Fatal("`applies_products: []` 必须判为已声明（空列表 ≠ 缺失）")
	}
	if len(empty) != 0 {
		t.Errorf("空列表应解析为 0 项，得到 %v", empty)
	}
	if empty == nil {
		// nil 会让 gob 往返后与"缺失"混淆；显式空切片是这一态的表示。
		t.Error("空列表应返回非 nil 的空切片")
	}

	for _, content := range []string{
		"---\ndoc_type: tools\n---\n\n# 没有该字段\n",
		"---\napplies_products: null\n---\n\n# null\n",
		"---\napplies_products: ~\n---\n\n# tilde\n",
		"# 完全没有 frontmatter\n",
	} {
		got, declared := FrontmatterAppliesProducts(content)
		if declared {
			t.Errorf("%q: 字段缺失/null 应判为未声明，得到 %v", content, got)
		}
		if len(got) != 0 {
			t.Errorf("%q: 未声明时不应有取值，得到 %v", content, got)
		}
	}
}

// 块列表在遇到下一个 frontmatter 键时停止，不会把后面的键当成列表项。
func TestFrontmatterAppliesProductsStopsAtNextKey(t *testing.T) {
	content := "---\napplies_products:\n  - se9\nversion: null\nsource: 手写\n---\n\n# x\n"
	got, declared := FrontmatterAppliesProducts(content)
	if !declared || !reflect.DeepEqual(got, []string{"se9"}) {
		t.Errorf("applies_products = %v (declared=%v), want [se9] true", got, declared)
	}
}

// 分块时把 applies_products 填进每个块（文档级属性，同文件的块共享）。
func TestChunkDirectoryAppliesProducts(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{
		"demo/yolo26.md": "---\ndoc_type: tools\napplies_products:\n  - se7\n  - se9\n---\n\n# YOLO26 例程\n\n## 部署\n\nBM1688 上跑 yolo26。\n",
		"tools/bmsec.md": "---\ndoc_type: tools\napplies_products: [se8]\n---\n\n# bmsec\n\n## 批量 ssh\n\n批量执行。\n",
		"guide.md":       "# 通用指南\n\n## 概览\n\n没有 frontmatter，不限产品。\n",
	}
	for rel, body := range files {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	got, err := NewDefaultChunker().ChunkDirectory(root)
	if err != nil {
		t.Fatalf("chunk dir: %v", err)
	}
	want := map[string]struct {
		products []string
		declared bool
	}{
		"demo/yolo26.md": {[]string{"se7", "se9"}, true},
		"tools/bmsec.md": {[]string{"se8"}, true},
		"guide.md":       {nil, false},
	}
	for rel, w := range want {
		chs := got[rel]
		if len(chs) == 0 {
			t.Errorf("%s: 没有块", rel)
			continue
		}
		for i, c := range chs {
			if c.AppliesProductsDeclared != w.declared {
				t.Errorf("%s 块 %d: declared = %v, want %v", rel, i, c.AppliesProductsDeclared, w.declared)
			}
			if !reflect.DeepEqual(c.AppliesProducts, w.products) {
				t.Errorf("%s 块 %d: applies_products = %v, want %v", rel, i, c.AppliesProducts, w.products)
			}
		}
	}
}

// 持久化往返：三态经 gob 编码解码后仍然可区分（回归点：空列表若编码成 nil，
// 解码后就会退化成"字段缺失"，把"哪个产品都不适用"变成"不限产品"）。
func TestAppliesProductsGobRoundTrip(t *testing.T) {
	in := []Chunk{
		{ChunkID: "a", Text: "缺字段", SourceFile: "a.md"},
		{ChunkID: "b", Text: "空列表", SourceFile: "b.md", AppliesProducts: []string{}, AppliesProductsDeclared: true},
		{ChunkID: "c", Text: "非空", SourceFile: "c.md", AppliesProducts: []string{"se7", "se9"}, AppliesProductsDeclared: true},
	}
	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(in); err != nil {
		t.Fatalf("encode: %v", err)
	}
	var out []Chunk
	if err := gob.NewDecoder(&buf).Decode(&out); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(out) != len(in) {
		t.Fatalf("round trip: %d chunks, want %d", len(out), len(in))
	}
	if out[0].AppliesProductsDeclared {
		t.Error("缺失字段往返后仍应是不限产品")
	}
	if !out[1].AppliesProductsDeclared || len(out[1].AppliesProducts) != 0 {
		t.Errorf("空列表往返后应仍是「已声明、0 项」，得到 %v (declared=%v)",
			out[1].AppliesProducts, out[1].AppliesProductsDeclared)
	}
	if !out[2].AppliesProductsDeclared || !reflect.DeepEqual(out[2].AppliesProducts, []string{"se7", "se9"}) {
		t.Errorf("非空列表往返后 = %v (declared=%v)", out[2].AppliesProducts, out[2].AppliesProductsDeclared)
	}
}
