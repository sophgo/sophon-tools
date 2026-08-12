package chunker

import (
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
