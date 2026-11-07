package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// 结果头行形如 "### 1 [0.016] `manual/guide.md:1-9`"，带类型标注时末尾多一个 " [manual]"。
var resultHeader = regexp.MustCompile("(?m)^### \\d+ \\[[0-9.]+\\] `[^`]+`(.*)$")

// frontmatterDocsIndex 建一个单索引：文档 frontmatter 自述了 doc_type 与 version。
func frontmatterDocsIndex(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	docs := filepath.Join(root, "docs")
	if err := os.MkdirAll(filepath.Join(docs, "manual"), 0o755); err != nil {
		t.Fatal(err)
	}
	body := "---\ntitle: 安装手册\ndoc_type: manual\nversion: v1.2\n---\n\n# 安装手册 v1.2\n\n## 网络配置\n\n" +
		"设备默认 IP 为 192.168.150.1，用 bm_set_ip 修改网络配置。\n"
	if err := os.WriteFile(filepath.Join(docs, "manual", "guide.md"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	idx := filepath.Join(root, "index")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docs, "-index-dir", idx}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	return idx
}

// #229 review P1：单索引、不带 -doc-type 时，即使文档 frontmatter 写了 doc_type，结果也不得带类型标注
// （README 承诺此时输出与旧版逐字节一致）；带 -doc-type 时才标注。
func TestSingleIndexFrontmatterDocsStayUntaggedWithoutDocType(t *testing.T) {
	idx := frontmatterDocsIndex(t)

	plain := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-index-dir", idx, "-offline", "网络配置"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	heads := resultHeader.FindAllStringSubmatch(plain, -1)
	if len(heads) == 0 {
		t.Fatalf("expected at least one result:\n%s", plain)
	}
	for _, h := range heads {
		if strings.TrimSpace(h[1]) != "" {
			t.Errorf("without -doc-type a single-index result must carry no tag, got %q:\n%s", h[1], plain)
		}
	}

	filtered := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-index-dir", idx, "-doc-type", "manual", "-offline", "网络配置"}); rc != 0 {
			t.Fatalf("query -doc-type rc=%d", rc)
		}
	})
	if !strings.Contains(filtered, "[manual]") {
		t.Errorf("with -doc-type the result should be tagged [manual]:\n%s", filtered)
	}
}

// #229 review P2：注册表专属参数在路径模式下显式报错，而不是被静默忽略。
func TestPathModeRejectsRegistryOnlyFlags(t *testing.T) {
	idx := frontmatterDocsIndex(t)
	for _, extra := range [][]string{{"-with-related"}, {"-sdk-version", "latest"}} {
		args := append([]string{"query", "-index-dir", idx, "-offline"}, extra...)
		args = append(args, "网络配置")
		var rc int
		stderr := captureStderr(t, func() {
			captureStdout(t, func() { rc = dispatch(args) })
		})
		if rc == 0 {
			t.Errorf("%v in path mode should fail", extra)
		}
		if !strings.Contains(stderr, "registry mode") {
			t.Errorf("%v error should point to registry mode, got:\n%s", extra, stderr)
		}
	}
}
