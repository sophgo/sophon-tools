package chunker

import (
	"fmt"
	"strings"
	"testing"
)

func contains(s, sub string) bool { return strings.Contains(s, sub) }

func TestChunkRespectsCodeBlock(t *testing.T) {
	text := "# 标题\n\n## 段落\n\n```go\nfunc main() {\n    println(\"hello\")\n}\n```\n\n## 结尾\n\n这是结尾一段。"
	chunks := NewDefaultChunker().ChunkFile(text, "test.md")
	if len(chunks) == 0 {
		t.Fatal("expected chunks")
	}
	found := false
	for _, c := range chunks {
		if contains(c.Text, "func main()") && contains(c.Text, "println") {
			found = true
			break
		}
	}
	if !found {
		t.Error("code block should be preserved inside single chunk when small")
	}
}

func TestChunkLineNumbers(t *testing.T) {
	text := "line1\nline2\nline3\nline4\nline5"
	chunks := NewDefaultChunker().ChunkFile(text, "test.md")
	if len(chunks) != 1 {
		t.Fatalf("expected 1 chunk, got %d", len(chunks))
	}
	if chunks[0].LineStart != 1 || chunks[0].LineEnd != 5 {
		t.Errorf("line range = %d..%d want 1..5", chunks[0].LineStart, chunks[0].LineEnd)
	}
}

func TestChunksSizedBelowMax(t *testing.T) {
	long := strings.Repeat("这是包含很多中文内容的一个段落，用于测试分块是否会把文本切得过大。", 200)
	chunks := NewDefaultChunker().ChunkFile("# 标题\n\n"+long, "t.md")
	if len(chunks) == 0 {
		t.Fatal("expected chunks")
	}
	for _, c := range chunks {
		if len([]rune(c.Text)) > 6000 {
			t.Errorf("chunk too large: %d runes > 6000", len([]rune(c.Text)))
		}
	}
}

func TestExtractProtectedNoTrailingNewlineTable(t *testing.T) {
	// 回归：以表格结尾且文件末尾无换行时，旧 scanTables 的 off 会溢出到 len(text)+1，
	// extractProtected 对 text[s.s:s.e] / text[last:s.s] 切片越界 panic。
	text := "前文\n\n| a | b |\n| c | d |\n\n最后的表格：\n| x | y |\n| p | q |"
	txt, regions := extractProtected(text)
	if txt == "" {
		t.Fatalf("unexpected empty result")
	}
	// 每张表格都应作为保护区域被还原，且原文内容不被破坏
	for i, r := range regions {
		if !strings.Contains(txt, fmt.Sprintf("__PROTECTED_%d__", i)) {
			t.Fatalf("missing protected placeholder %d", i)
		}
		_ = r
	}
}
