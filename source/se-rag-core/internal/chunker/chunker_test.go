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

func TestChunkOverlapInMainPath(t *testing.T) {
	// 主路径（分隔符切分）相邻块应共享约 Overlap 字符的重叠文本（README: 800/80）。
	filler := "这是包含很多中文内容的一个段落，用于测试分块逻辑。"
	text := "# 标题\n\n" + strings.Repeat(filler+"\n\n", 60)
	c := NewDefaultChunker()
	chunks := c.ChunkFile(text, "t.md")
	if len(chunks) < 2 {
		t.Fatalf("expected >=2 chunks, got %d", len(chunks))
	}
	// 每对相邻块：后一块应包含前一块的尾部片段（overlap>0），且整体大小不超限
	for i := 1; i < len(chunks); i++ {
		tail := chunks[i-1].Text
		if len([]rune(tail)) > c.OverlapChars {
			tail = string([]rune(tail)[len([]rune(tail))-c.OverlapChars:])
		}
		if !strings.HasPrefix(chunks[i].Text, tail) {
			t.Errorf("chunk %d should overlap with chunk %d tail, got prefix %q... vs tail %q...",
				i, i-1, truncated(chunks[i].Text, 30), truncated(tail, 30))
		}
	}
	// 关键：重叠文本不应破坏保护占位符还原完整性
	for _, ch := range chunks {
		if strings.Contains(ch.Text, "__PROTECTED_") {
			t.Errorf("chunk leaked protected placeholder: %.60q", ch.Text)
		}
	}
}

func TestChunkOverlapAcrossCodeBlock(t *testing.T) {
	// 重叠边界落在保护占位符附近时，代码块/表格仍应完整还原、不残留占位符碎片。
	filler := "长段中文文本用于撑大块长度，确保溢出切分多次。"
	code := "```go\nfunc main() {\n    fmt.Println(\"hi\")\n}\n```"
	text := strings.Repeat(filler+"\n\n", 30) + code + "\n\n" + strings.Repeat(filler+"\n\n", 30)
	chunks := NewDefaultChunker().ChunkFile(text, "t.md")
	if len(chunks) < 2 {
		t.Fatalf("expected >=2 chunks, got %d", len(chunks))
	}
	joined := ""
	for _, ch := range chunks {
		joined += ch.Text
		if strings.Contains(ch.Text, "__PROTECTED_") {
			t.Errorf("chunk leaked protected placeholder: %.60q", ch.Text)
		}
	}
	if !strings.Contains(joined, "func main()") {
		t.Error("code block content lost across chunks")
	}
}

func TestSplitPieceCoresConcatenateToSource(t *testing.T) {
	// 不变量：各片段 core 按序拼接必须还原 clean 原文（依赖它做精确行号定位），
	// 且重叠文本只作为前缀追加、不得修改核心内容。
	c := NewDefaultChunker()
	texts := []string{
		"# 标题\n\n" + strings.Repeat("这是包含很多中文内容的一个段落，用于测试分块逻辑。\n\n", 60),
		"前文\n\n```go\nfunc main() { println(\"hi\") }\n```\n\n" + strings.Repeat("无分隔长段中文文本，用于触发字符级兜底切分。"+"\n\n", 50),
		"| a | b |\n| c | d |\n\n" + strings.Repeat("表格后面的正文段落，注意保护表格标记的完整性。"+"\n\n", 40),
	}
	for n, text := range texts {
		clean, _ := extractProtected(text)
		pieces := c.splitText(clean, 0)
		joined := ""
		for _, p := range pieces {
			joined += p.core
		}
		if joined != clean {
			t.Errorf("case %d: cores do not concatenate to source (joined %d runes, source %d runes)",
				n, len([]rune(joined)), len([]rune(clean)))
		}
	}
}

func truncated(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}
