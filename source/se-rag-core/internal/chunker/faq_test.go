package chunker

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestIsFAQFile(t *testing.T) {
	for name, want := range map[string]bool{
		"10-media-faq.md":         true,
		"se9/12-algorithm-faq.md": true,
		"11-BSP-FAQ.md":           true,
		"00-introduce.md":         false,
		"faq.md":                  false, // 约定后缀是 -faq.md
		"se9_sdk/sophon-sail.md":  false,
		"算能边缘产品BSP开发参考手册FAQ_clear.md": false,
	} {
		if got := IsFAQFile(name); got != want {
			t.Errorf("IsFAQFile(%q)=%v want %v", name, got, want)
		}
	}
}

func TestFAQSplitsPerQuestion(t *testing.T) {
	text := "---\ntitle: T\n---\n\n## 分类\n\n### 问题一\n\n答案一。\n\n### 问题二\n\n答案二。\n"
	chunks := NewDefaultChunker().ChunkFile(text, "x-faq.md")
	var got []string
	for _, c := range chunks {
		got = append(got, c.Text)
	}
	// 前言（frontmatter）一块；"## 分类" 无正文并入 "### 问题一"；问题二独立
	if len(chunks) != 3 {
		t.Fatalf("want 3 chunks, got %d: %q", len(chunks), got)
	}
	if !strings.HasPrefix(chunks[1].Text, "## 分类\n") || !strings.Contains(chunks[1].Text, "答案一") || strings.Contains(chunks[1].Text, "答案二") {
		t.Errorf("chunk1 should be 分类+问题一 only: %q", chunks[1].Text)
	}
	if !strings.HasPrefix(chunks[2].Text, "### 问题二") || strings.Contains(chunks[2].Text, "答案一") {
		t.Errorf("chunk2 should be 问题二 only: %q", chunks[2].Text)
	}
}

func TestFAQLineNumbers(t *testing.T) {
	text := "## A\n\n### Q1\n\nans1\n\n### Q2\n\nans2"
	chunks := NewDefaultChunker().ChunkFile(text, "x-faq.md")
	if len(chunks) != 2 {
		t.Fatalf("want 2, got %d", len(chunks))
	}
	lines := strings.Split(text, "\n")
	for _, c := range chunks {
		got := strings.Join(lines[c.LineStart-1:c.LineEnd], "\n")
		if got != c.Text {
			t.Errorf("line range %d-%d does not reproduce chunk text:\n got %q\nwant %q", c.LineStart, c.LineEnd, got, c.Text)
		}
	}
}

func TestFAQHashInCodeFenceIsNotHeading(t *testing.T) {
	text := "### Q\n\n答：\n\n```bash\n## 这是注释\n### 也是注释\necho hi\n```\n\n### Q2\n\nx"
	chunks := NewDefaultChunker().ChunkFile(text, "x-faq.md")
	if len(chunks) != 2 {
		t.Fatalf("want 2 chunks (code fence must not split), got %d", len(chunks))
	}
	if !strings.Contains(chunks[0].Text, "echo hi") || !strings.Contains(chunks[0].Text, "## 这是注释") {
		t.Errorf("code block should stay in the first chunk: %q", chunks[0].Text)
	}
}

func TestFAQChainedEmptyHeadingsMerge(t *testing.T) {
	text := "## 视频解码\n\n### 常见问题\n\n#### 问题\n\n答案"
	chunks := NewDefaultChunker().ChunkFile(text, "x-faq.md")
	if len(chunks) != 1 {
		t.Fatalf("heading-only sections should merge into the next one, got %d: %+v", len(chunks), chunks)
	}
	if !strings.Contains(chunks[0].Text, "## 视频解码") || !strings.Contains(chunks[0].Text, "答案") {
		t.Errorf("merged chunk should carry the category headings: %q", chunks[0].Text)
	}
}

func TestFAQOversizedSectionFallsBack(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("### 大问题\n\n")
	for i := 0; i < 120; i++ {
		sb.WriteString("这是一段很长的回答内容，用来撑大这个问答块，超过单块上限后应当退回通用切分。\n\n")
	}
	sb.WriteString("### 小问题\n\n小答案")
	text := sb.String()
	chunks := NewDefaultChunker().ChunkFile(text, "x-faq.md")
	if len(chunks) < 3 {
		t.Fatalf("oversized section should be split further, got %d chunks", len(chunks))
	}
	last := chunks[len(chunks)-1]
	if !strings.HasPrefix(last.Text, "### 小问题") {
		t.Errorf("last chunk should be 小问题: %q", last.Text)
	}
	// 行号按段落起点平移：最后一块的行号必须落在真实位置
	lines := strings.Split(text, "\n")
	if lines[last.LineStart-1] != "### 小问题" {
		t.Errorf("last.LineStart=%d points at %q", last.LineStart, lines[last.LineStart-1])
	}
	seen := map[string]bool{}
	for _, c := range chunks {
		if seen[c.ChunkID] {
			t.Errorf("duplicate ChunkID %s", c.ChunkID)
		}
		seen[c.ChunkID] = true
	}
}

// 非 FAQ 文件行为不变：不会按标题强制切块。
func TestNonFAQFileKeepsPlainChunking(t *testing.T) {
	text := "## A\n\n### Q1\n\nans1\n\n### Q2\n\nans2"
	if got := len(NewDefaultChunker().ChunkFile(text, "manual.md")); got != 1 {
		t.Errorf("non-FAQ small file should stay one chunk, got %d", got)
	}
}

func TestChunkDirectoryUsesFAQRule(t *testing.T) {
	dir := t.TempDir()
	body := "## A\n\n### Q1\n\nans1\n\n### Q2\n\nans2"
	os.WriteFile(filepath.Join(dir, "10-x-faq.md"), []byte(body), 0o644)
	os.WriteFile(filepath.Join(dir, "guide.md"), []byte(body), 0o644)
	m, err := NewDefaultChunker().ChunkDirectory(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(m["10-x-faq.md"]) != 2 || len(m["guide.md"]) != 1 {
		t.Errorf("faq=%d guide=%d, want 2 and 1", len(m["10-x-faq.md"]), len(m["guide.md"]))
	}
}
