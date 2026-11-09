package main

// 1.9.0：查询产品时默认带入该产品关联的 toolkit，并按文档 frontmatter 的
// applies_products 只保留适用该产品的工具/例程文档。
//
// 夹具（productToolkitFixture）：
//
//	docs/products/se9/**            SE9 自己的 FAQ / 手册
//	docs/toolkits/sophon-tools/tools/bmsec.md      applies_products: [se8]
//	docs/toolkits/sophon-tools/tools/socbak.md     applies_products: [se7, se9]
//	docs/toolkits/sophon-tools/tools/get-info.md   字段缺失（不限产品）
//	docs/toolkits/sophon-tools/tools/spacc.md      applies_products: []（哪个产品都不适用）
//	docs/toolkits/sophon-demo/demo/yolo26.md       applies_products: [se7, se8, se9, se13]
//
// 所有 toolkit 文档都含同一个关键词 "工具资料"，过滤前后的差异只可能来自 applies_products。

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"
)

const productToolkitRegistry = `{
  "schema_version": 3,
  "entities": [
    {"id":"se9","type":"product","name":"SE9","status":"ready","aliases":["SE9"],
     "modules":[],"toolkits":["sophon-tools","sophon-demo"],
     "docs_dir":"docs/products/se9","index_dir":"indexes/product-se9"},
    {"id":"se13","type":"product","name":"SE13","status":"ready","aliases":["SE13"],
     "modules":[],"toolkits":["sophon-tools","sophon-demo"],
     "docs_dir":"docs/products/se13","index_dir":"indexes/product-se13"},
    {"id":"bm1688","type":"chip","name":"BM1688","status":"ready","aliases":["BM1688"],
     "docs_dir":"docs/chips/bm1688","index_dir":"indexes/chip-bm1688"},
    {"id":"sophon-tools","type":"toolkit","name":"随箱工具","status":"ready",
     "aliases":["sophon-tools"],"docs_dir":"docs/toolkits/sophon-tools",
     "index_dir":"indexes/toolkit-sophon-tools"},
    {"id":"sophon-demo","type":"toolkit","name":"例程库","status":"ready",
     "aliases":["sophon-demo"],"docs_dir":"docs/toolkits/sophon-demo",
     "index_dir":"indexes/toolkit-sophon-demo"}
  ]
}`

// productToolkitFiles 夹具的文档内容（相对技能根）。
func productToolkitFiles() map[string]string {
	fm := func(products string) string {
		return "---\ntitle: 工具资料\nentity: toolkit\ndoc_type: tools\n" + products + "---\n\n"
	}
	return map[string]string{
		"registry.json": productToolkitRegistry,
		// 产品自己的文档：与 toolkit 文档竞争同一个关键词，验证的是"哪些源参与"而非"排序"。
		"docs/products/se9/faq/faq.md":      "# SE9 FAQ\n\n## 工具资料 从哪来\n\nSE9 的工具资料在随箱盘里。\n",
		"docs/products/se13/faq/faq.md":     "# SE13 FAQ\n\n## 工具资料 从哪来\n\nSE13 的工具资料在随箱盘里。\n",
		"docs/chips/bm1688/sdk/tpu-mlir.md": "# BM1688 SDK\n\n## 工具资料 编译\n\ntpu-mlir 编译模型。\n",
		// 适用 se8：查 SE9 必须看不到。
		"docs/toolkits/sophon-tools/tools/bmsec.md": fm("applies_products: [se8]\n") +
			"# bmsec\n\n## 批量 ssh\n\n工具资料：bmsec 批量 ssh 到多台设备。\n",
		// 适用 se7/se9：查 SE9 必须看到。
		"docs/toolkits/sophon-tools/tools/socbak.md": fm("applies_products: [se7, se9]\n") +
			"# socbak\n\n## 打包\n\n工具资料：socbak 把系统打包成刷机包。\n",
		// 字段缺失：不限产品，查任何产品都必须看到。
		"docs/toolkits/sophon-tools/tools/get-info.md": fm("") +
			"# get-info\n\n## 概览\n\n工具资料：get-info 打印板卡信息。\n",
		// 显式空列表：哪个产品都不适用，查产品时必须丢弃；但直接查 toolkit 时仍可见。
		"docs/toolkits/sophon-tools/tools/spacc.md": fm("applies_products: []\n") +
			"# spacc\n\n##  efuse\n\n工具资料：spacc 读写 efuse。\n",
		"docs/toolkits/sophon-demo/demo/yolo26.md": fm("applies_products:\n  - se7\n  - se8\n  - se9\n  - se13\n") +
			"# YOLO26 例程\n\n## 部署\n\n工具资料：yolo26 例程在 BM1688 上跑检测。\n",
		"docs/toolkits/sophon-demo/demo/arcface.md": fm("applies_products: [se8]\n") +
			"# ArcFace 例程\n\n## 部署\n\n工具资料：arcface 人脸识别例程。\n",
	}
}

// productToolkitFixture 落夹具并建全部索引，返回技能根。
func productToolkitFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for rel, body := range productToolkitFiles() {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", filepath.Join(root, "registry.json"), "-all", "-offline"}); rc != 0 {
			t.Fatalf("build -all -offline rc=%d", rc)
		}
	})
	return root
}

// queryFixture 跑一次注册表模式查询，返回 (stdout, stderr)。
func queryFixture(t *testing.T, root string, args ...string) (stdout, stderr string) {
	t.Helper()
	base := append([]string{"query", "-registry", filepath.Join(root, "registry.json"), "-offline"}, args...)
	stderr = captureStderr(t, func() {
		stdout = captureStdout(t, func() {
			if rc := dispatch(base); rc != 0 {
				t.Fatalf("query %v rc=%d, stderr=%s", args, rc, stderr)
			}
		})
	})
	return stdout, stderr
}

// 默认带入：只查 se9 也会检索 sophon-tools / sophon-demo，且只保留适用 se9 的文档。
func TestQueryProductIncludesToolkitsByDefault(t *testing.T) {
	root := productToolkitFixture(t)
	out, errOut := queryFixture(t, root, "-entity", "se9", "-top-n", "20", "工具资料")

	// 适用的两份文档必须命中（bmsec 适用 se8、arcface 适用 se8、spacc 空列表都不行）
	for _, want := range []string{
		"docs/toolkits/sophon-tools/tools/socbak.md",
		"docs/toolkits/sophon-demo/demo/yolo26.md",
		"docs/toolkits/sophon-tools/tools/get-info.md", // 字段缺失 = 不限产品
	} {
		if !strings.Contains(out, want) {
			t.Errorf("默认带入 toolkit 后应命中 %s：\n%s", want, out)
		}
	}
	for _, unwanted := range []string{
		"docs/toolkits/sophon-tools/tools/bmsec.md", // applies_products: [se8]
		"docs/toolkits/sophon-demo/demo/arcface.md", // applies_products: [se8]
		"docs/toolkits/sophon-tools/tools/spacc.md", // applies_products: []
	} {
		if strings.Contains(out, unwanted) {
			t.Errorf("不适用 se9 的文档不得出现：%s\n%s", unwanted, out)
		}
	}
	// stderr 说明带入了哪些 toolkit、按哪个产品过滤、怎么关掉
	for _, want := range []string{"note: toolkits included:", "sophon-tools", "sophon-demo",
		"applies_products ∋ se9", "-no-toolkits"} {
		if !strings.Contains(errOut, want) {
			t.Errorf("stderr 提示应包含 %q：\n%s", want, errOut)
		}
	}
}

// -no-toolkits：关掉默认带入，检索范围回到 1.8.1（只有 se9 自己的文档）。
func TestQueryProductNoToolkitsFlag(t *testing.T) {
	root := productToolkitFixture(t)
	out, errOut := queryFixture(t, root, "-entity", "se9", "-no-toolkits", "-top-n", "20", "工具资料")

	if strings.Contains(out, "docs/toolkits/") || strings.Contains(out, "tools/") {
		t.Errorf("-no-toolkits 时不得检索 toolkit 索引：\n%s", out)
	}
	// 单目标（只剩 se9 一个索引）走路径模式输出：路径相对 docs_dir。
	if !strings.Contains(out, "`faq/faq.md:") {
		t.Errorf("产品自己的文档仍应命中：\n%s", out)
	}
	if strings.Contains(errOut, "toolkits included") {
		t.Errorf("-no-toolkits 时不应再提示 toolkits included：\n%s", errOut)
	}
}

// 直接点名 toolkit 时不过滤：同一份索引，整体看时四项都在（含空列表文档）。
// 单目标走路径模式输出，路径相对 docs_dir（`tools/xxx.md`）。
func TestQueryDirectToolkitIsNotFiltered(t *testing.T) {
	root := productToolkitFixture(t)
	out, errOut := queryFixture(t, root, "-entity", "sophon-tools", "-top-n", "20", "工具资料")

	for _, want := range []string{
		"`tools/bmsec.md:",
		"`tools/socbak.md:",
		"`tools/get-info.md:",
		"`tools/spacc.md:",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("直接查 toolkit 时不得过滤，应命中 %s：\n%s", want, out)
		}
	}
	if strings.Contains(errOut, "toolkits included") {
		t.Errorf("用户直接点名 toolkit 时不应提示默认带入：\n%s", errOut)
	}
}

// 同一个 toolkit 既被直接指定、又被产品带入：按直接指定处理（不过滤）。
func TestQueryDirectToolkitWinsOverProductLink(t *testing.T) {
	root := productToolkitFixture(t)
	out, _ := queryFixture(t, root, "-entity", "se9,sophon-tools", "-top-n", "20", "工具资料")

	// bmsec 只适用 se8：产品带入时会过滤掉，直接指定必须保留。
	if !strings.Contains(out, "tools/bmsec.md") {
		t.Errorf("toolkit 同时被直接指定时应视为直接目标（不过滤）：\n%s", out)
	}
	if !strings.Contains(out, "tools/spacc.md") {
		t.Errorf("同上：显式空列表的文档在直接指定时也应可见：\n%s", out)
	}
}

// 只有显式写的 product 触发默认带入：芯片、模组、sdk 与 -all 都不触发。
func TestQueryToolkitsOnlyForExplicitProducts(t *testing.T) {
	root := productToolkitFixture(t)

	// 芯片：不带入 toolkit，输出里没有 toolkit 文档，也没有提示
	out, errOut := queryFixture(t, root, "-entity", "bm1688", "-top-n", "20", "工具资料")
	if strings.Contains(out, "docs/toolkits/") || strings.Contains(out, "`tools/") {
		t.Errorf("查芯片不应带入 toolkit：\n%s", out)
	}
	if strings.Contains(errOut, "toolkits included") {
		t.Errorf("查芯片不应提示 toolkits：\n%s", errOut)
	}
	// 单目标走路径模式：路径相对 docs_dir。
	if !strings.Contains(out, "`sdk/tpu-mlir.md:") {
		t.Errorf("芯片自己的文档应命中：\n%s", out)
	}

	// -all：toolkit 本来就是直接目标，不因产品过滤被砍掉一半
	allOut, allErr := queryFixture(t, root, "-all", "-top-n", "30", "工具资料")
	if !strings.Contains(allOut, "docs/toolkits/sophon-tools/tools/bmsec.md") {
		t.Errorf("-all 把全部实体当直接目标，toolkit 不得按产品过滤：\n%s", allOut)
	}
	if strings.Contains(allErr, "toolkits included") {
		t.Errorf("-all 不应提示默认带入：\n%s", allErr)
	}
}

// 产品与 toolkit 同时被指定、且 toolkit 是经产品带入的另一个源：只有那个源被过滤。
func TestQueryProductFilterDoesNotLeakToOtherSources(t *testing.T) {
	root := productToolkitFixture(t)
	// se13 与 se9 的产品文档都不带 applies_products，各自必须完整返回；
	// 两个产品的 toolkit 交集（都是同一批）按"任一产品适用"保留，即 se7/se9/se13 的文档留下。
	out, _ := queryFixture(t, root, "-entity", "se9,se13", "-top-n", "30", "工具资料")

	// 多产品查询里 -top-n 30 足够覆盖全部块，路径是技能根相对
	for _, want := range []string{
		"docs/products/se9/faq/faq.md",
		"docs/products/se13/faq/faq.md",
		"docs/toolkits/sophon-tools/tools/socbak.md",   // [se7, se9] 与 se9 有交集
		"docs/toolkits/sophon-demo/demo/yolo26.md",     // 含 se9 / se13
		"docs/toolkits/sophon-tools/tools/get-info.md", // 缺失 = 不限产品
	} {
		if !strings.Contains(out, want) {
			t.Errorf("多产品查询应命中 %s：\n%s", want, out)
		}
	}
	for _, unwanted := range []string{"tools/bmsec.md", "demo/arcface.md", "tools/spacc.md"} {
		if strings.Contains(out, unwanted) {
			t.Errorf("多产品查询也不得命中 %s：\n%s", unwanted, out)
		}
	}
}

// 过滤必须发生在 top-n 截断之前：过滤掉的块分数最高时，结果仍要凑满 n 条。
func TestQueryProductFilterHappensBeforeTopN(t *testing.T) {
	root := t.TempDir()
	// bmsec（适用 se8）用高权重关键词充满文档；socbak 只提一次同样的词。
	// 若先按 top-n 取候选再过滤，前 n 条会被 bmsec 占满、过滤后一条不剩。
	docs := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"se9","type":"product","name":"SE9","status":"ready","aliases":["SE9"],
     "modules":[],"toolkits":["sophon-tools"],
     "docs_dir":"docs/products/se9","index_dir":"indexes/product-se9"},
    {"id":"sophon-tools","type":"toolkit","name":"随箱工具","status":"ready",
     "aliases":["sophon-tools"],"docs_dir":"docs/toolkits/sophon-tools",
     "index_dir":"indexes/toolkit-sophon-tools"}
  ]
}`,
		"docs/products/se9/faq/faq.md": "# SE9 FAQ\n\n## 排障\n\n与检索词无关的内容。\n",
		// 30 个适用 se8 的段落，全部高强度命中 "bmsec 批量 ssh"
		"docs/toolkits/sophon-tools/tools/bmsec.md": "---\ndoc_type: tools\napplies_products: [se8]\n---\n\n" +
			strings.Repeat("# bmsec\n\nbmsec 批量 ssh 批量 ssh 批量 ssh\n\n", 20),
		// 3 个适用 se9 的段落，描述相同话题但只有一次关键词
		"docs/toolkits/sophon-tools/tools/socbak.md": "---\ndoc_type: tools\napplies_products: [se9]\n---\n\n" +
			"# socbak\n\nbmsec 批量 ssh 之外，socbak 负责打包。\n",
	}
	for rel, body := range docs {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", filepath.Join(root, "registry.json"), "-all", "-offline"}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})

	out, _ := queryFixture(t, root, "-entity", "se9", "-top-n", "3", "-doc-type", "tools", "bmsec 批量 ssh")
	if strings.Contains(out, "tools/bmsec.md") {
		t.Errorf("适用 se8 的文档不得出现：\n%s", out)
	}
	if !strings.Contains(out, "tools/socbak.md") {
		t.Errorf("过滤发生在 top-n 之前：适用 se9 的文档即使分数低也必须返回：\n%s", out)
	}
	if n := hitCount(out); n == 0 {
		t.Errorf("结果不应为空：\n%s", out)
	}
}

// hitCount 结果行数（`### N [score]` 的条数）。
func hitCount(out string) int {
	n := 0
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(line, "### ") {
			n++
		}
	}
	return n
}

// 与 -doc-type 组合：两个条件都满足才保留。
func TestQueryProductFilterCombinesWithDocType(t *testing.T) {
	root := productToolkitFixture(t)
	out, _ := queryFixture(t, root, "-entity", "se9", "-top-n", "30", "-doc-type", "tools", "工具资料")

	for _, want := range []string{
		"docs/toolkits/sophon-tools/tools/socbak.md",
		"docs/toolkits/sophon-demo/demo/yolo26.md",
		"docs/toolkits/sophon-tools/tools/get-info.md",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("tools 类且适用 se9 的文档应命中 %s：\n%s", want, out)
		}
	}
	if strings.Contains(out, "docs/products/se9/faq/faq.md") {
		t.Errorf("-doc-type tools 不得返回 faq 文档：\n%s", out)
	}
	if strings.Contains(out, "tools/bmsec.md") || strings.Contains(out, "tools/spacc.md") {
		t.Errorf("产品过滤仍要生效：\n%s", out)
	}
	// 两个条件同时生效时，标注带 doc_type（与只有 -doc-type 时一致）
	if !strings.Contains(out, "[sophon-demo/tools]") {
		t.Errorf("结果应标注 [实体/doc_type]：\n%s", out)
	}
}

// 输出标注格式不变：多目标时仍是 `[实体/doc_type 版本]` 加技能根相对路径。
func TestQueryProductToolkitOutputFormat(t *testing.T) {
	root := productToolkitFixture(t)
	out, _ := queryFixture(t, root, "-entity", "se9", "-top-n", "30", "工具资料")
	for _, tag := range []string{"[se9]", "[sophon-tools/tools]", "[sophon-demo/tools]"} {
		if !strings.Contains(out, tag) {
			t.Errorf("结果应标注 %s：\n%s", tag, out)
		}
	}
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("离线查询应报告 mode=bm25：\n%s", out)
	}
}

// 不含 product 的检索（只查芯片）输出与 1.8.1 逐字节一致：
// 单目标走路径模式输出——路径相对 docs_dir、不带任何标注。
// （逐字节的严格对照在 TestRegistryQuerySingleEntityMatchesPathMode 与 golden 里，
// 这里只守住"没有 product 时不触发任何新行为"这条线。）
func TestQueryWithoutProductKeepsPathModeOutput(t *testing.T) {
	root := productToolkitFixture(t)
	out, errOut := queryFixture(t, root, "-entity", "bm1688", "工具资料")
	if errOut != "" {
		t.Errorf("查芯片不应有任何 stderr 提示：\n%s", errOut)
	}
	if !strings.Contains(out, "`sdk/tpu-mlir.md:") {
		t.Errorf("单目标应保持路径模式输出（路径相对 docs_dir）：\n%s", out)
	}
	// 单目标、无 doc-type：不带任何标注（与路径模式格式一致）
	if strings.Contains(out, "[bm1688") || strings.Contains(out, "[sdk]") {
		t.Errorf("单实体不带 -doc-type 时不得标注：\n%s", out)
	}
}

// 注册表里有 toolkits 但索引没建：报错并给出 build 命令（不静默只查产品自己的索引）。
func TestQueryProductMissingToolkitIndexFails(t *testing.T) {
	root := productToolkitFixture(t)
	// 删掉 sophon-demo 的索引
	if err := os.RemoveAll(filepath.Join(root, "indexes", "toolkit-sophon-demo")); err != nil {
		t.Fatal(err)
	}
	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() {
			rc = dispatch([]string{"query", "-registry", filepath.Join(root, "registry.json"),
				"-entity", "se9", "-offline", "工具资料"})
		})
	})
	if rc == 0 {
		t.Fatal("默认带入的 toolkit 缺索引时应报错")
	}
	if !strings.Contains(stderr, "se-rag build -entity sophon-demo") {
		t.Errorf("错误应给出缺失索引的 build 命令：\n%s", stderr)
	}
}

// -no-toolkits 在路径模式下报错（注册表专属参数，不静默忽略）。
func TestNoToolkitsRejectedInPathMode(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# A\n\n## I2C\n\nI2C0 复用 GPIO3。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	idx := filepath.Join(dir, "idx")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() {
			rc = dispatch([]string{"query", "-index-dir", idx, "-offline", "-no-toolkits", "I2C"})
		})
	})
	if rc == 0 {
		t.Fatal("路径模式传 -no-toolkits 应报错")
	}
	if !strings.Contains(stderr, "-no-toolkits only works in registry mode") {
		t.Errorf("错误应说明该参数只在注册表模式有效：\n%s", stderr)
	}
}

// doctor 对 toolkit 多一行：索引里带 applies_products 的块数。
func TestDoctorReportsAppliesProductsForToolkit(t *testing.T) {
	root := productToolkitFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"doctor", "-registry", filepath.Join(root, "registry.json"),
			"-entity", "sophon-tools"}); rc != 0 {
			t.Fatalf("doctor rc=%d", rc)
		}
	})
	if !strings.Contains(out, "applies_products:") {
		t.Fatalf("toolkit 的 doctor 输出应报告 applies_products 块数：\n%s", out)
	}
	// 夹具里 sophon-tools 共 4 个块：bmsec / socbak / spacc 声明了，get-info 没有。
	if !strings.Contains(out, "applies_products: 3/4 chunks declared") {
		t.Errorf("块数应为 3/4：\n%s", out)
	}
	// 非 toolkit 不该有这一行
	chipOut := captureStdout(t, func() {
		if rc := dispatch([]string{"doctor", "-registry", filepath.Join(root, "registry.json"),
			"-entity", "bm1688"}); rc != 0 {
			t.Fatalf("doctor rc=%d", rc)
		}
	})
	if strings.Contains(chipOut, "applies_products:") {
		t.Errorf("非 toolkit 不该报告 applies_products：\n%s", chipOut)
	}
}

// 含 product 的注册表里，查非 product 实体仍与路径模式逐字节一致（1.8.1 不变式）。
func TestQueryNonProductEntityMatchesPathMode(t *testing.T) {
	root := productToolkitFixture(t)
	reg, err := loadRegistry(filepath.Join(root, "registry.json"))
	if err != nil {
		t.Fatal(err)
	}
	chip, _ := reg.ByID("bm1688")

	entityOut, entityErr := queryFixture(t, root, "-entity", "bm1688", "工具资料")
	pathOut := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-index-dir", reg.IndexPath(chip), "-offline", "工具资料"}); rc != 0 {
			t.Fatalf("path query rc=%d", rc)
		}
	})
	if entityErr != "" {
		t.Errorf("查非 product 实体不应有 stderr 提示：\n%s", entityErr)
	}
	if entityOut != pathOut {
		t.Errorf("非 product 实体的输出必须与路径模式逐字节一致：\nentity:\n%s\npath:\n%s", entityOut, pathOut)
	}
}

// -with-related 带进来的 toolkit 同样按产品过滤；-no-toolkits 不管这一路。
func TestQueryWithRelatedToolkitStillFiltered(t *testing.T) {
	root := productToolkitFixture(t)

	// 不带 -no-toolkits：toolkit 经 -with-related 带入，提示里不提 -no-toolkits（它管不着）
	out, errOut := queryFixture(t, root, "-entity", "se9", "-with-related", "-no-toolkits", "-top-n", "30", "工具资料")
	if !strings.Contains(out, "docs/toolkits/sophon-demo/demo/yolo26.md") {
		t.Errorf("-with-related 仍应带入 toolkit（-no-toolkits 只关默认带入）：\n%s", out)
	}
	if strings.Contains(out, "tools/bmsec.md") {
		t.Errorf("-with-related 带入的 toolkit 仍要按产品过滤：\n%s", out)
	}
	if !strings.Contains(errOut, "toolkits included") {
		t.Errorf("应提示 toolkit 被带入：\n%s", errOut)
	}
	if strings.Contains(errOut, "-no-toolkits to disable") {
		t.Errorf("-with-related 带入时不该提 -no-toolkits：\n%s", errOut)
	}
}

// 产品引用了 placeholder toolkit：跳过并提示，不因此让查询失败。
func TestQueryPlaceholderToolkitIsSkipped(t *testing.T) {
	root := t.TempDir()
	docs := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"se9","type":"product","name":"SE9","status":"ready","aliases":["SE9"],
     "modules":[],"toolkits":["sophon-tools","sophon-demo"],
     "docs_dir":"docs/products/se9","index_dir":"indexes/product-se9"},
    {"id":"sophon-tools","type":"toolkit","name":"随箱工具","status":"ready",
     "aliases":["sophon-tools"],"docs_dir":"docs/toolkits/sophon-tools",
     "index_dir":"indexes/toolkit-sophon-tools"},
    {"id":"sophon-demo","type":"toolkit","name":"例程库","status":"placeholder",
     "aliases":["sophon-demo"],"docs_dir":null,"index_dir":null}
  ]
}`,
		"docs/products/se9/faq/faq.md":               "# SE9 FAQ\n\n## 工具资料\n\nSE9 的工具资料在随箱盘里。\n",
		"docs/toolkits/sophon-tools/tools/socbak.md": "---\ndoc_type: tools\napplies_products: [se9]\n---\n\n# socbak\n\n## 打包\n\n工具资料：socbak 打包。\n",
	}
	for rel, body := range docs {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", filepath.Join(root, "registry.json"), "-all", "-offline"}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	out, errOut := queryFixture(t, root, "-entity", "se9", "-top-n", "10", "工具资料")
	if !strings.Contains(out, "tools/socbak.md") {
		t.Errorf("ready 的 toolkit 仍应检索：\n%s", out)
	}
	if !strings.Contains(errOut, "skipped placeholder: sophon-demo") {
		t.Errorf("placeholder toolkit 应被跳过并提示：\n%s", errOut)
	}
}

// 提示行按 UTF-8 对齐（含 `∋` 等非 ASCII 字符），避免长度计算截断字符。
func TestToolkitsNoteIsValidUTF8(t *testing.T) {
	note := toolkitsNote([]string{"sophon-tools", "sophon-demo"}, []string{"se9"}, true)
	if !utf8.ValidString(note) {
		t.Fatalf("提示行不是合法 UTF-8：%q", note)
	}
	if !strings.Contains(note, "-no-toolkits to disable") {
		t.Errorf("默认带入的提示应说明怎么关闭：%q", note)
	}
	noDisable := toolkitsNote([]string{"sophon-tools"}, []string{"se9"}, false)
	if strings.Contains(noDisable, "-no-toolkits") {
		t.Errorf("-with-related 带入时不该提 -no-toolkits：%q", noDisable)
	}
}
