package main

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// captureStderr 捕获函数执行期间的 stderr（dispatch 把错误写到 os.Stderr）。
func captureStderr(t *testing.T, f func()) string {
	t.Helper()
	old := os.Stderr
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stderr = w
	done := make(chan string, 1)
	go func() {
		buf, _ := io.ReadAll(r)
		done <- string(buf)
	}()
	f()
	w.Close()
	os.Stderr = old
	return <-done
}

// `-doc-type` 的路径模式端到端验证：没有注册表时类型按块源路径推断。
//
// 夹具目录结构（相对 --docs-dir）：
//
//	f-aq/faq.md            faq（无 frontmatter，走路径推断）
//	manual/guide.md        manual（frontmatter doc_type=manual, version=1.0.3）
//	tools/flash.md         tools
//	sdk/tpu-mlir.md        sdk
//	datasheet/spec.md      datasheet
//	_meta/coverage.md      other（元数据，不进索引）
//	00-introduce.md        overview（根目录文件）
//
// 所有文档都含同一个关键词 "sophon-sail"，这样过滤前后的差异只可能来自 doc_type。
func docTypeFixture(t *testing.T) (docsDir, indexDir string) {
	t.Helper()
	root := t.TempDir()
	docsDir = filepath.Join(root, "docs")
	files := map[string]string{
		"faq/faq.md":        "# FAQ\n\n## sophon-sail 装不上\n\nsophon-sail 装不上时先确认 pip 源。\n",
		"manual/guide.md":   "---\ntitle: 手册\ndoc_type: manual\nversion: 1.0.3\n---\n\n# 产品使用手册\n\n## sophon-sail 版本\n\n手册里写 sophon-sail 版本要与 SDK 对齐。\n",
		"tools/flash.md":    "# 工具\n\n## sophon-sail 随箱包\n\n随箱工具盘里有 sophon-sail 的离线 wheel。\n",
		"sdk/tpu-mlir.md":   "# SDK\n\n## sophon-sail 安装\n\nsophon-sail 通过 pip install sophon-sail 安装。\n",
		"datasheet/spec.md": "# 数据手册\n\n## sophon-sail 支持\n\n数据手册提到 sophon-sail 所需的驱动版本。\n",
		"_meta/coverage.md": "# 覆盖报告\n\nsophon-sail 覆盖 100%。\n",
		"00-introduce.md":   "---\ndoc_type: overview\n---\n\n# 导航\n\n本目录收录 sophon-sail 相关资料。\n",
	}
	for rel, body := range files {
		p := filepath.Join(docsDir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	indexDir = filepath.Join(root, "idx")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", indexDir}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	return docsDir, indexDir
}

// 不带 -doc-type 时结果不标注类型，输出与旧版逐字节一致。
func TestDocTypeAbsentKeepsOutputUnchanged(t *testing.T) {
	_, idx := docTypeFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if strings.Contains(out, "/manual]") || strings.Contains(out, "/sdk]") || strings.Contains(out, "/faq]") {
		t.Errorf("output must not carry any doc type tag without -doc-type:\n%s", out)
	}
}

// -doc-type 单值：只留该类型的块，并在结果行标注类型。
func TestDocTypeFilterSingleType(t *testing.T) {
	_, idx := docTypeFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "datasheet", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[datasheet]") {
		t.Errorf("results should be tagged with the doc type:\n%s", out)
	}
	if !strings.Contains(out, "`datasheet/spec.md:") {
		t.Errorf("datasheet block should be returned:\n%s", out)
	}
	if strings.Contains(out, "`sdk/") {
		t.Errorf("sdk blocks must be filtered out:\n%s", out)
	}
}

// -doc-type 支持逗号分隔多值。
func TestDocTypeFilterMultipleTypes(t *testing.T) {
	_, idx := docTypeFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "sdk,datasheet", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	for _, want := range []string{"[sdk]", "[datasheet]"} {
		if !strings.Contains(out, want) {
			t.Errorf("multi-type filter should keep %s:\n%s", want, out)
		}
	}
}

// 文档写了 frontmatter doc_type 时以文档自述为准，优先于路径推断。
func TestDocTypeFrontmatterWins(t *testing.T) {
	docsDir := t.TempDir()
	// 路径是 looks-like-sdk/，但 frontmatter 说是 manual：必须按 manual 分类。
	p := filepath.Join(docsDir, "looks-like-sdk", "doc.md")
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	body := "---\ntitle: x\ndoc_type: manual\nversion: 2.0\n---\n\n# 手册\n\n## sophon-sail\n\n正文。\n"
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	idx := filepath.Join(t.TempDir(), "idx")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})

	// 按路径推断的类型（sdk）不应命中
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "sdk", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "0 results") {
		t.Errorf("frontmatter doc_type=manual should not match -doc-type sdk:\n%s", out)
	}
	// 自述类型应命中。单索引走单索引检索路径，标注只有类型段（版本段只在多索引
	// 合并的结果里出现，见 retriever.MultiRetriever.makeResult）。
	out = captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "manual", "sophon-sail"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[manual]") {
		t.Errorf("frontmatter doc_type should drive the tag:\n%s", out)
	}
}

// 过滤后没有任何块时正常返回 0 结果，不报错。
func TestDocTypeFilterYieldsEmptyResult(t *testing.T) {
	_, idx := docTypeFixture(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "module", "sophon-sail"}); rc != 0 {
			t.Fatalf("filtering everything out should not fail, rc=%d", rc)
		}
	})
	if !strings.Contains(out, "0 results") {
		t.Errorf("expected zero results:\n%s", out)
	}
}

// 非法 doc_type 报错并列出合法取值。
func TestDocTypeUnknownValueErrors(t *testing.T) {
	_, idx := docTypeFixture(t)
	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() {
			rc = dispatch([]string{"query", "-offline", "-index-dir", idx, "-doc-type", "nonsense", "sophon-sail"})
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

// 多索引 + -doc-type：每个索引分别过滤后再合并。
func TestDocTypeFilterAcrossIndexes(t *testing.T) {
	root := t.TempDir()
	var idxs []string
	for i, sub := range []string{"sdk", "manual"} {
		docsDir := filepath.Join(root, "docs"+itoa(i))
		p := filepath.Join(docsDir, sub, "doc.md")
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		body := "# 文档\n\n## sophon-sail\n\n" + sub + " 相关内容。\n"
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		idx := filepath.Join(root, "idx"+itoa(i))
		captureStdout(t, func() {
			if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
				t.Fatalf("build rc=%d", rc)
			}
		})
		idxs = append(idxs, idx)
	}

	args := []string{"query", "-offline", "-doc-type", "sdk"}
	for _, idx := range idxs {
		args = append(args, "-index-dir", idx)
	}
	out := captureStdout(t, func() {
		if rc := dispatch(append(args, "sophon-sail")); rc != 0 {
			t.Fatalf("multi query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[sdk]") {
		t.Errorf("merged result should carry the doc type tag:\n%s", out)
	}
	if strings.Contains(out, "[manual]") {
		t.Errorf("manual blocks must be filtered out:\n%s", out)
	}
}

// docTypeFromPath 的映射规则。
func TestDocTypeFromPath(t *testing.T) {
	cases := []struct{ path, want string }{
		{"datasheet/spec.md", docTypeDatasheet},
		{"sdk/tpu-mlir.md", docTypeSDK},
		{"manual/guide.md", docTypeManual},
		{"faq/x.md", docTypeFAQ},
		{"tools/flash.md", docTypeTools},
		{"spec/brochure.md", docTypeSpec},
		{"module/power.md", docTypeModule},
		{"00-introduce.md", docTypeOverview},
		{"image-catalog.md", docTypeOverview}, // 根目录文件一律 overview
		{"_meta/coverage-report.md", docTypeOther},
		{"assets/a/x.md", docTypeOther},
		{"nested/deep/x.md", docTypeOther}, // 不认识的第一层目录
		{"overview/x.md", docTypeOther},    // overview 只由根目录文件产生
		{`windows\style\spec.md`, docTypeOther},
	}
	for _, c := range cases {
		if got := docTypeFromPath(c.path); got != c.want {
			t.Errorf("docTypeFromPath(%q) = %q, want %q", c.path, got, c.want)
		}
	}
}
