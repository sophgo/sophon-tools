package main

// 多索引（注册表模式）下的标识符—标题提权。

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// 多索引场景：每个索引内部各自完成三路融合后再合并。
// 标题命中块即使在所属索引的 BM25 里名次靠后，也必须进入合并候选并排在前面。
func TestRegistryMultiIndexTitleBoost(t *testing.T) {
	root := t.TempDir()
	// 两个实体：编译器相关章节放在 cv84x6 的标题里，bm1688 的正文反复出现该词。
	files := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"bm1688","type":"chip","name":"BM1688","status":"ready","aliases":["BM1688"],
     "modules":[],"docs_dir":"docs/chips/bm1688","index_dir":"indexes/chip-bm1688"},
    {"id":"cv84x6","type":"chip","name":"CV84X6","status":"ready","aliases":["CV84X6"],
     "modules":[],"docs_dir":"docs/chips/cv84x6","index_dir":"indexes/chip-cv84x6"}
  ]
}`,
		// bm1688：正文里堆满 build_kernel，但标题都不是它（靠内容相似度拿高分）
		"docs/chips/bm1688/sdk/notes.md": "# BM1688 SDK\n\n## 编译说明\n\nbuild_kernel build_kernel build_kernel 反复出现，本章并不叫这个名字。\n",
		// cv84x6：标题就是 build_kernel，正文很短
		"docs/chips/cv84x6/sdk/guide.md": "# CV84X6 指南\n\n## 6. 各模块编译方法\n\n### 6.2 build_kernel（Kernel / boot.itb）\n\n编译内核并 pack_boot。\n",
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
	regPath := filepath.Join(root, "registry.json")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", regPath, "-all", "-offline"}); rc != 0 {
			t.Fatalf("build -all -offline rc=%d", rc)
		}
	})

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688,cv84x6",
			"-offline", "build_kernel 报错"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	first := firstResultLine(out)
	if !strings.Contains(first, "[cv84x6]") || !strings.Contains(first, "guide.md") {
		t.Errorf("title-matched chunk from cv84x6 should rank first across indexes, got %q\n%s", first, out)
	}
	// 两条索引都被检索到（合并而非只取一个）
	if !strings.Contains(out, "[cv84x6]") || !strings.Contains(out, "[bm1688]") {
		t.Errorf("multi-index query should tag results from both entities:\n%s", out)
	}
}

// 多索引 + 无标识符：不产生提权，结果与不带第三路的旧行为一致（只断言不崩、有结果）。
func TestRegistryMultiIndexNoIdentifierStable(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{
		"registry.json": `{
  "schema_version": 3,
  "entities": [
    {"id":"bm1688","type":"chip","name":"BM1688","status":"ready","aliases":["BM1688"],
     "modules":[],"docs_dir":"docs/chips/bm1688","index_dir":"indexes/chip-bm1688"},
    {"id":"cv84x6","type":"chip","name":"CV84X6","status":"ready","aliases":["CV84X6"],
     "modules":[],"docs_dir":"docs/chips/cv84x6","index_dir":"indexes/chip-cv84x6"}
  ]
}`,
		"docs/chips/bm1688/sdk/notes.md": "# BM1688 SDK\n\n## tpu-mlir 编译模型\n\n先用 model_transform.py 转 MLIR。\n",
		"docs/chips/cv84x6/sdk/guide.md": "# CV84X6 指南\n\n## 编译环境\n\n宿主机需要 cmake 与 gcc。\n",
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
	regPath := filepath.Join(root, "registry.json")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", regPath, "-all", "-offline"}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "bm1688,cv84x6",
			"-offline", "编译"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if firstResultLine(out) == "" {
		t.Errorf("expected results for an identifier-free query:\n%s", out)
	}
}
