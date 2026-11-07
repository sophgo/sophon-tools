package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"se-rag-core/internal/registry"
	"se-rag-core/internal/retriever"
)

// layoutFixture 建一个统一骨架的夹具：_meta/ 与 assets/ 存在但不得进索引，
// 根目录两个文件的 doc_type 靠 frontmatter 区分。
func layoutFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	files := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"se13","type":"product","name":"SE13","status":"ready","aliases":["SE13"],
     "modules":[],"docs_dir":"docs/products/se13","index_dir":"indexes/product-se13"},
    {"id":"sophon-tools","type":"toolkit","name":"随箱工具","status":"ready",
     "aliases":["sophon-tools","socbak"],
     "docs_dir":"docs/toolkits/sophon-tools","index_dir":"indexes/toolkit-sophon-tools"}
  ]
}`,
		"docs/products/se13/00-introduce.md":              "---\ntitle: SE13 导航\nentity: se13\ndoc_type: overview\nversion: null\nsource: save_docs 预置包\n---\n\n# SE13 技术资料导航\n\n本目录收录 SE13 的彩页与手册。\n",
		"docs/products/se13/spec/se13-brochure-v1.1.2.md": "---\ntitle: SE13 彩页\nentity: se13\ndoc_type: spec\nversion: 1.1.2\nsource: save_docs 预置包\n---\n\n# 边缘大模型微服务器 SE13 产品彩页 v1.1.2\n\n## 产品规格\n\n规格参数一览，覆盖主控、内存与接口。\n",
		// 覆盖报告刻意写成"规格 覆盖"最相关的内容：修复前它会挤进前几名。
		"docs/products/se13/_meta/coverage-report.md": "# SE13 技术资料覆盖报告\n\n规格 覆盖：彩页逐页覆盖，规格 覆盖 100%，覆盖 校验通过。\n",
		"docs/toolkits/sophon-tools/00-introduce.md":  "---\ntitle: 随箱工具导航\nentity: sophon-tools\ndoc_type: overview\nversion: null\nsource: sophon-tools README（预置）\n---\n\n# 随箱工具资料导航\n\n随箱工具同时覆盖 BM1684X 与 BM1688。\n",
		"docs/toolkits/sophon-tools/tools/socbak.md":  "---\ntitle: socbak工具\nentity: sophon-tools\ndoc_type: tools\nversion: null\nsource: sophon-tools README（预置）\n---\n\n# socbak工具\n\n## 打包做包功能\n\nsocbak 可以把当前系统做成刷机包，备份到外置存储。\n",
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
	return root
}

func buildLayoutFixture(t *testing.T, root string) {
	t.Helper()
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", filepath.Join(root, "registry.json"),
			"-all", "-offline"}); rc != 0 {
			t.Fatalf("build -all -offline rc=%d", rc)
		}
	})
}

// _meta/ 下的覆盖报告不得进索引：查询"规格 覆盖"的结果里不能出现 coverage-report。
func TestMetaDocsNeverAppearInResults(t *testing.T) {
	root := layoutFixture(t)
	buildLayoutFixture(t, root)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", filepath.Join(root, "registry.json"),
			"-entity", "se13", "-offline", "规格 覆盖"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if strings.Contains(out, "coverage-report") {
		t.Errorf("_meta/coverage-report.md 不得进索引：\n%s", out)
	}
	// 单实体单索引走路径模式，块路径相对 docs_dir（不带 docs/products/se13/ 前缀）。
	if !strings.Contains(out, "`spec/se13-brochure-v1.1.2.md:") {
		t.Errorf("应命中规格文档：\n%s", out)
	}
}

// 根目录两个文件靠 frontmatter 区分 doc_type：-doc-type overview / image 各自只命中自己。
func TestRootFilesUseFrontmatterDocType(t *testing.T) {
	root := layoutFixture(t)
	buildLayoutFixture(t, root)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", filepath.Join(root, "registry.json"),
			"-entity", "se13", "-doc-type", "overview", "-offline", "资料导航"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[se13/overview]") {
		t.Errorf("overview 应按 frontmatter 标注：\n%s", out)
	}
	if strings.Contains(out, "spec/se13-brochure") {
		t.Errorf("-doc-type overview 不得命中 spec 文档：\n%s", out)
	}
}

// resolve 能命中 toolkit；它的别名（工具名）也参与匹配。
func TestResolveToolkit(t *testing.T) {
	root := layoutFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", filepath.Join(root, "registry.json"),
			"socbak 怎么备份"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	if !strings.Contains(out, "sophon-tools") || !strings.Contains(out, "toolkit") {
		t.Errorf("resolve 应命中 sophon-tools（toolkit）：\n%s", out)
	}
}

// 产品 --with-related 时把 toolkit 一并纳入检索目标。
func TestQueryWithRelatedIncludesToolkit(t *testing.T) {
	root := layoutFixture(t)
	buildLayoutFixture(t, root)
	// 给 se13 补上 toolkits 关联（夹具默认没有），验证展开路径。
	regPath := filepath.Join(root, "registry.json")
	body := `{
  "schema_version": 3,
  "entities": [
    {"id":"se13","type":"product","name":"SE13","status":"ready","aliases":["SE13"],
     "modules":[],"toolkits":["sophon-tools"],
     "docs_dir":"docs/products/se13","index_dir":"indexes/product-se13"},
    {"id":"sophon-tools","type":"toolkit","name":"随箱工具","status":"ready",
     "aliases":["sophon-tools","socbak"],
     "docs_dir":"docs/toolkits/sophon-tools","index_dir":"indexes/toolkit-sophon-tools"}
  ]
}`
	if err := os.WriteFile(regPath, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "se13",
			"-with-related", "-offline", "socbak 备份"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[sophon-tools/tools]") {
		t.Errorf("-with-related 应展开到 toolkits 并标注 [sophon-tools/tools]：\n%s", out)
	}
}

// 版本标注：[实体/doc_type 版本]；frontmatter 的 version 为 null 时省略版本段。
func TestResultTagFormat(t *testing.T) {
	cases := []struct{ entity, docType, version, want string }{
		{"se9", "spec", "1.5", "se9/spec 1.5"},
		{"bm1684x", "faq", "", "bm1684x/faq"},
		{"se9", "", "1.5", "se9 1.5"},
		{"se9", "spec", "", "se9/spec"},
		{"", "tools", "", "tools"},
		{"", "", "", ""},
	}
	for _, c := range cases {
		if got := retriever.ResultTag(c.entity, c.docType, c.version); got != c.want {
			t.Errorf("resultTag(%q,%q,%q) = %q, want %q",
				c.entity, c.docType, c.version, got, c.want)
		}
	}
}

// 单实体单索引 + 不带 -doc-type 时输出保持原样（无任何标注）。
func TestSingleIndexOutputStaysUntagged(t *testing.T) {
	root := layoutFixture(t)
	buildLayoutFixture(t, root)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", filepath.Join(root, "registry.json"),
			"-entity", "se13", "-offline", "规格"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if strings.Contains(out, "[se13") {
		t.Errorf("单索引不带 -doc-type 时不得标注：\n%s", out)
	}
}

var _ = registry.DocTypeSpec
