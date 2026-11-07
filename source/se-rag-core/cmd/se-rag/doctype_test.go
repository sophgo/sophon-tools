package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"se-rag-core/internal/registry"
)

// docTypeFixture 建一个带多类文档的夹具注册表，用于 -doc-type 端到端验证：
//
//	docs/products/se9/faq/faq.md                faq（无 frontmatter，走路径推断）
//	docs/products/se9/manual/guide.md           manual（frontmatter doc_type/version）
//	docs/products/se9/tools/flash.md            tools
//	docs/chips/bm1688/sdk/tpu-mlir.md           sdk
//	docs/chips/bm1688/datasheet/spec.md         datasheet
//	docs/modules/sm7/power.md                   module
//
// 所有文档都刻意包含同一个关键词 "sophon-sail"，这样过滤前后的差异只可能来自 doc_type。
func docTypeFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	files := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"se9","type":"product","name":"SE9","status":"ready","aliases":["SE9"],
     "modules":["sm7"],"docs_dir":"docs/products/se9","index_dir":"indexes/product-se9"},
    {"id":"sm7","type":"module","name":"SM7","status":"ready","aliases":["SM7"],
     "chips":["bm1688"],"docs_dir":"docs/modules/sm7","index_dir":"indexes/module-sm7"},
    {"id":"bm1688","type":"chip","name":"BM1688","status":"ready","aliases":["BM1688"],
     "docs_dir":"docs/chips/bm1688","index_dir":"indexes/chip-bm1688"}
  ]
}`,
		"docs/products/se9/faq/faq.md": "# SE9 FAQ\n\n## sophon-sail 装不上\n\nsophon-sail 装不上时先确认 pip 源。\n",
		// manual 带 frontmatter：验证"文档自述的 doc_type 与 version 优先于路径推断"。
		"docs/products/se9/manual/guide.md":   "---\ntitle: SE9 手册\nentity: se9\ndoc_type: manual\nversion: 1.0.3\nsource: save_docs 预置包\n---\n\n# 微服务器 SE7 32-BP1 产品使用手册 v1.0.3\n\n## sophon-sail 版本\n\n手册里写 sophon-sail 版本要与 SDK 对齐。\n",
		"docs/products/se9/tools/flash.md":    "# SE9 工具\n\n## sophon-sail 随箱包\n\n随箱工具盘里有 sophon-sail 的离线 wheel。\n",
		"docs/chips/bm1688/sdk/tpu-mlir.md":   "# BM1688 SDK\n\n## sophon-sail 安装\n\nsophon-sail 通过 pip install sophon-sail 安装。\n",
		"docs/chips/bm1688/datasheet/spec.md": "# BM1688 数据手册\n\n## sophon-sail 支持\n\n数据手册提到 sophon-sail 所需的驱动版本。\n",
		"docs/modules/sm7/power.md":           "# SM7 模组\n\n## sophon-sail 适配\n\nSM7 模组适配 sophon-sail 的固件。\n",
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

// buildDocTypeFixture 建全部 ready 实体的离线索引。
func buildDocTypeFixture(t *testing.T, root string) {
	t.Helper()
	regPath := filepath.Join(root, "registry.json")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", regPath, "-all", "-offline"}); rc != 0 {
			t.Fatalf("build -all -offline rc=%d", rc)
		}
	})
}

// 不带 -doc-type 时结果不标注 doc_type（单实体单索引的逐字节约定靠这个保证）。
func TestDocTypeAbsentKeepsOutputUnchanged(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	// 单实体单索引走的是路径模式的同一套输出：既没有实体标注，也没有 doc_type 标注。
	if strings.Contains(out, "[bm1688") || strings.Contains(out, "[sdk]") {
		t.Errorf("output must not carry any tag without -doc-type:\n%s", out)
	}
}

// -doc-type 过滤：只留指定类型的块，并在结果行追加 /doc_type。
func TestDocTypeFilterSingleType(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688", "-doc-type", "datasheet", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[bm1688/datasheet]") {
		t.Errorf("results should be tagged with the doc type:\n%s", out)
	}
	if !strings.Contains(out, "`docs/chips/bm1688/datasheet/spec.md:") {
		t.Errorf("datasheet block should be returned:\n%s", out)
	}
	if strings.Contains(out, "`docs/chips/bm1688/sdk/") {
		t.Errorf("sdk blocks must be filtered out:\n%s", out)
	}
}

// -doc-type 支持逗号分隔多值。
func TestDocTypeFilterMultipleTypes(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688", "-doc-type", "sdk,datasheet", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	for _, want := range []string{"[bm1688/sdk]", "[bm1688/datasheet]"} {
		if !strings.Contains(out, want) {
			t.Errorf("multi-type filter should keep %s:\n%s", want, out)
		}
	}
}

// 跨实体（-with-related）时每类文档各自标注，过滤对每个索引分别生效。
func TestDocTypeFilterAcrossEntities(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	// se9 → sm7（ready module）→ bm1688
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "se9", "-with-related", "-doc-type", "sdk,module", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	for _, want := range []string{"[bm1688/sdk]", "[sm7/module]"} {
		if !strings.Contains(out, want) {
			t.Errorf("filtered merged query should include %s:\n%s", want, out)
		}
	}
	for _, unwanted := range []string{"/faq]", "/manual]", "/tools]", "/datasheet]"} {
		if strings.Contains(out, unwanted) {
			t.Errorf("filtered merged query must not include %s:\n%s", unwanted, out)
		}
	}
}

// 过滤后没有任何块时：正常返回 0 结果，不报错。
func TestDocTypeFilterYieldsEmptyResult(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	// 产品目录里没有 datasheet 类文档
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "se9", "-doc-type", "datasheet", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("filtering everything out should not fail, rc=%d", rc)
		}
	})
	if !strings.Contains(out, "0 results") {
		t.Errorf("expected zero results:\n%s", out)
	}
}

// 非法 doc_type 报错并列出合法取值。
func TestDocTypeUnknownValueErrors(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() {
			rc = dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688", "-doc-type", "nonsense", "-offline", "sophon-sail"})
		})
	})
	if rc == 0 {
		t.Fatal("unknown doc type should fail")
	}
	for _, want := range []string{"unknown doc type", "nonsense", "datasheet"} {
		if !strings.Contains(stderr, want) {
			t.Errorf("error should mention %q, got:\n%s", want, stderr)
		}
	}
}

// 路径模式也支持 -doc-type：类型按块源路径相对 --docs-dir 的第一层子目录名推断。
// （注册表模式下推断依据是技能根相对路径，两者规则不同，各自由自己的测试覆盖。）
func TestDocTypeWorksInPathMode(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)

	// chip-bm1688 的 docs_dir 是 docs/chips/bm1688，块路径形如 sdk/tpu-mlir.md、
	// datasheet/spec.md —— 第一层子目录名正好就是 doc_type。
	args := func(docType string) []string {
		return []string{"query", "-index-dir", filepath.Join(root, "indexes", "chip-bm1688"),
			"-doc-type", docType, "-offline", "sophon-sail"}
	}
	out := captureStdout(t, func() {
		if rc := dispatch(args("datasheet")); rc != 0 {
			t.Fatalf("path mode -doc-type rc=%d", rc)
		}
	})
	if !strings.Contains(out, "`datasheet/spec.md:") {
		t.Errorf("path mode should keep the datasheet block:\n%s", out)
	}
	if strings.Contains(out, "`sdk/") {
		t.Errorf("path mode -doc-type datasheet must filter out sdk blocks:\n%s", out)
	}

	// 非法取值仍然报错（两种模式共用同一套校验与取值表）
	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() { rc = dispatch(args("nonsense")) })
	})
	if rc == 0 {
		t.Fatal("unknown doc type in path mode should fail")
	}
	if !strings.Contains(stderr, "unknown doc type") {
		t.Errorf("error should name the unknown doc type, got:\n%s", stderr)
	}
}

// 文档类型按路径推断的端到端确认：每类文档都能被自己的 doc_type 单独选中。
func TestDocTypeCoversEveryLayout(t *testing.T) {
	root := docTypeFixture(t)
	buildDocTypeFixture(t, root)
	regPath := filepath.Join(root, "registry.json")

	cases := []struct {
		entity string
		typ    string
		path   string
		tag    string // 期望的结果标注；空表示 `[实体/doc_type]` 且不带版本
	}{
		{"se9", registry.DocTypeFAQ, "docs/products/se9/faq/faq.md", ""},
		{"se9", registry.DocTypeManual, "docs/products/se9/manual/guide.md", "[se9/manual 1.0.3]"},
		{"se9", registry.DocTypeTools, "docs/products/se9/tools/flash.md", ""},
		{"bm1688", registry.DocTypeSDK, "docs/chips/bm1688/sdk/tpu-mlir.md", ""},
		{"bm1688", registry.DocTypeDatasheet, "docs/chips/bm1688/datasheet/spec.md", ""},
		{"sm7", registry.DocTypeModule, "docs/modules/sm7/power.md", ""},
	}
	for _, c := range cases {
		want := c.tag
		if want == "" {
			want = "[" + c.entity + "/" + c.typ + "]"
		}
		out := captureStdout(t, func() {
			if rc := dispatch([]string{"query", "-registry", regPath, "-entity", c.entity,
				"-doc-type", c.typ, "-offline", "sophon-sail"}); rc != 0 {
				t.Fatalf("%s/%s: query rc=%d", c.entity, c.typ, rc)
			}
		})
		if !strings.Contains(out, "`"+c.path+":") {
			t.Errorf("%s with -doc-type %s should return %s:\n%s", c.entity, c.typ, c.path, out)
		}
		if !strings.Contains(out, want) {
			t.Errorf("%s/%s: result line should carry the tag %s:\n%s", c.entity, c.typ, want, out)
		}
	}
}
