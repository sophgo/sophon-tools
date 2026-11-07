package chunker

import (
	"os"
	"path/filepath"
	"testing"
)

// _meta/ 与 assets/ 不进索引（MYS-2638 第 5 节）。
//
// 修复前的证据：se13 上查"规格 覆盖"，第 7、8 名都来自 coverage-report.md ——
// 一份描述"资料怎么转换来的"的报告被当成知识本身。
func TestChunkDirectorySkipsMetaAndAssets(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{
		"00-introduce.md":             "---\ndoc_type: overview\n---\n\n# 导航\n\n介绍。\n",
		"image-catalog.md":            "---\ndoc_type: image\n---\n\n# 图片目录\n\n图。\n",
		"spec/a-spec-v1.0.md":         "---\ndoc_type: spec\nversion: 1.0\n---\n\n# 规格\n\n参数。\n",
		"_meta/coverage-report.md":    "# 覆盖报告\n\n覆盖率 100%。\n",
		"_meta/source-manifest.json":  "{}",
		"_meta/image-catalog.json":    "[]",
		"assets/a-spec-v1.0/p001.jpg": "not-a-real-jpeg",
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
	for rel := range got {
		if filepath.ToSlash(rel) == "_meta/coverage-report.md" {
			t.Error("_meta/ 下的文档不得进入索引（coverage-report.md 会污染检索结果）")
		}
	}
	want := map[string]bool{
		"00-introduce.md": true, "image-catalog.md": true, "spec/a-spec-v1.0.md": true,
	}
	if len(got) != len(want) {
		t.Fatalf("chunked files = %v, want exactly %v", keys(got), want)
	}
	for rel := range want {
		if _, ok := got[rel]; !ok {
			t.Errorf("缺少块文件 %s（得到 %v）", rel, keys(got))
		}
	}
}

func keys(m map[string][]Chunk) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// 块要带上文档自述的 doc_type 与 version，供 -doc-type 过滤与结果标注。
func TestChunksCarryFrontmatterDocTypeAndVersion(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "a.md")
	body := "---\ntitle: x\ndoc_type: spec\nversion: 1.5\n---\n\n# 标题\n\n正文。\n"
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := NewDefaultChunker().ChunkDirectory(root)
	if err != nil {
		t.Fatalf("chunk dir: %v", err)
	}
	chs := got["a.md"]
	if len(chs) == 0 {
		t.Fatal("no chunks")
	}
	for i, c := range chs {
		if c.DocType != "spec" {
			t.Errorf("chunk %d DocType = %q, want spec", i, c.DocType)
		}
		if c.Version != "1.5" {
			t.Errorf("chunk %d Version = %q, want 1.5", i, c.Version)
		}
	}
}

// 没有 frontmatter 的文档不填 DocType（调用方按路径推断），也不填 Version。
func TestChunksWithoutFrontmatterHaveNoDocType(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "a.md"), []byte("# 标题\n\n正文。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := NewDefaultChunker().ChunkDirectory(root)
	if err != nil {
		t.Fatalf("chunk dir: %v", err)
	}
	for i, c := range got["a.md"] {
		if c.DocType != "" || c.Version != "" {
			t.Errorf("chunk %d = (%q,%q), want empty", i, c.DocType, c.Version)
		}
	}
}

// version: null 视为没有版本（输出里省略版本段）。
func TestFrontmatterVersionNullIsEmpty(t *testing.T) {
	cases := []struct{ in, want string }{
		{"---\nversion: null\n---\n", ""},
		{"---\nversion: 1.5\n---\n", "1.5"},
		{"---\nversion: \"1.5\"\n---\n", "1.5"},
		{"---\ntitle: x\n---\n", ""},
		{"# no frontmatter\n", ""},
	}
	for _, c := range cases {
		if got := FrontmatterVersion(c.in); got != c.want {
			t.Errorf("FrontmatterVersion(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}
