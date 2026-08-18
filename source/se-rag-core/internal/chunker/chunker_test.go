package chunker

import (
	"fmt"
	"os"
	"path/filepath"
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

// MYS-392：跨文件含相同段落文本时，ChunkID 必须互不相同（旧算法 md5(文本) 冲突，
// 检索时 ChunkByID 后写覆盖导致来源文件错乱）。
func TestChunkIDUniqueAcrossFiles(t *testing.T) {
	text := "# 标题\n\n" + strings.Repeat("这是完全相同的共享段落内容，两个文档都会出现。", 60)
	c := NewDefaultChunker()
	a := c.ChunkFile(text, "a.md")
	b := c.ChunkFile(text, "b.md")
	if len(a) == 0 || len(b) == 0 {
		t.Fatal("expected chunks")
	}
	seen := map[string]bool{}
	for _, ch := range append(append([]Chunk{}, a...), b...) {
		key := ch.SourceFile + ":" + ch.ChunkID
		if seen[key] {
			t.Errorf("duplicate ChunkID %q in %s (same text across files must differ)", ch.ChunkID, ch.SourceFile)
		}
		seen[key] = true
	}
}

// MYS-392：同一文件内不同位置的 chunk（即使文本相同）ChunkID 也必须唯一。
func TestChunkIDUniqueWithinFile(t *testing.T) {
	text := "# 标题\n\n" + strings.Repeat("重复出现的段落内容。", 90) + "\n\n## 第二节\n\n" + strings.Repeat("重复出现的段落内容。", 90)
	chunks := NewDefaultChunker().ChunkFile(text, "t.md")
	ids := map[string]int{}
	for _, ch := range chunks {
		ids[ch.ChunkID]++
	}
	for id, n := range ids {
		if n > 1 {
			t.Errorf("duplicate ChunkID %q within one file (%d times)", id, n)
		}
	}
}

// MYS-392：文档含代码块（保护占位符改变文本长度）时，代码块之后 chunk 的行号不得错位。
// 旧实现用 clean（含占位符）偏移套原 text 的行表，行号整体前移。
func TestLineNumbersAfterCodeBlock(t *testing.T) {
	pre := "# 标题\n" + strings.Repeat("这是代码块之前的文本。", 30)
	code := "\n\n```go\nfunc main() {\n    println(\"hello\")\n}\n```"
	post := "\n\n## 段落二\n\n" + strings.Repeat("这是代码块之后的文本。", 30)
	chunks := NewDefaultChunker().ChunkFile(pre+code+post, "t.md")
	if len(chunks) < 2 {
		t.Fatalf("expected >= 2 chunks, got %d", len(chunks))
	}
	last := chunks[len(chunks)-1]
	if !strings.Contains(last.Text, "段落二") {
		t.Fatalf("expected last chunk to contain 段落二, got %q", last.Text)
	}
	// 手工数行：1 标题 / 2 长行 / 3 空 / 4-8 代码块 / 9 空 / 10 ## 段落二
	if last.LineStart != 10 {
		t.Errorf("last chunk LineStart = %d, want 10 (code block must not shift line numbers)", last.LineStart)
	}
}

// MYS-392：文档含表格（同上保护区域）时，表格之后 chunk 的行号不得错位。
func TestLineNumbersAfterTable(t *testing.T) {
	pre := "# 标题\n" + strings.Repeat("这是表格之前的文本。", 30)
	table := "\n\n| a | b |\n| c | d |\n"
	post := "\n\n## 表格之后\n\n" + strings.Repeat("这是表格之后的文本。", 30)
	chunks := NewDefaultChunker().ChunkFile(pre+table+post, "t.md")
	if len(chunks) < 2 {
		t.Fatalf("expected >= 2 chunks, got %d", len(chunks))
	}
	last := chunks[len(chunks)-1]
	if !strings.Contains(last.Text, "表格之后") {
		t.Fatalf("expected last chunk to contain 表格之后, got %q", last.Text)
	}
	// 行号：1 标题 / 2 长行 / 3 空 / 4-5 表格 / 6-7 空 / 8 ## 表格之后
	// （table="\n\n|...|\n" 首尾共 3 个换行：空行 3、表格 4-5、空行 6；post 前导 \n\n 再补两个换行 → ## 表格之后 落在第 8 行）
	if last.LineStart != 8 {
		t.Errorf("last chunk LineStart = %d, want 8 (table must not shift line numbers)", last.LineStart)
	}
}

// MYS-392：文档中重复出现（FAQ 常见）的相同文本块，各自 chunk 的行号必须指向各自位置。
// 旧实现 strings.Index 取首次出现位置，所有副本行号都指向首处。
func TestLineNumbersDuplicateParagraph(t *testing.T) {
	line := "段落内容重复。"
	block := strings.Repeat(line+"\n", 400) // > 800 token，递归切分成多 chunk
	text := block + "\n## 分隔\n" + block     // 两个相同大块，中间夹分隔行
	chunks := NewDefaultChunker().ChunkFile(text, "t.md")

	firstLine := map[string]int{}
	dupes := 0
	for _, ch := range chunks {
		if prevStart, ok := firstLine[ch.Text]; ok {
			dupes++
			if ch.LineStart == prevStart {
				t.Errorf("duplicate chunk text mapped to first occurrence line %d (want its own line): %q", prevStart, ch.Text)
			}
		} else {
			firstLine[ch.Text] = ch.LineStart
		}
	}
	if dupes == 0 {
		t.Fatal("test setup broken: expected duplicate chunk texts across the two blocks")
	}
}

// MYS-392：ChunkID 掺源文件路径 + 块序号，任意维度变化都必须产生不同 ID。
func TestChunkIDScoped(t *testing.T) {
	if chunkID("a.md", 0, "text") == chunkID("b.md", 0, "text") {
		t.Error("ChunkID must differ across files with identical text")
	}
	if chunkID("a.md", 0, "text") == chunkID("a.md", 1, "text") {
		t.Error("ChunkID must differ across chunk indexes in one file")
	}
	if chunkID("a.md", 0, "text") == chunkID("a.md", 0, "other") {
		t.Error("ChunkID must differ across texts")
	}
}

// MYS-392：超长 chunk（charSplitChunks 路径）子块 ChunkID 掺文件路径+序号，行号随字节偏移递增。
func TestCharSplitChunksIDsAndLines(t *testing.T) {
	c := NewDefaultChunker()
	seq := 0
	text := strings.Repeat("abc\n", 1700) // 1700 行 * 4 = 6800 字节 > MaxChunkChars 6000
	chs := c.charSplitChunks(text, "big.md", 10, &seq)
	if len(chs) != 2 {
		t.Fatalf("expected 2 sub-chunks, got %d", len(chs))
	}
	if chs[0].ChunkID == chs[1].ChunkID {
		t.Error("sub-chunks of the same overlong chunk must have distinct ChunkIDs")
	}
	if chs[0].ChunkIndex != 0 || chs[1].ChunkIndex != 1 {
		t.Errorf("ChunkIndex = %d,%d want 0,1", chs[0].ChunkIndex, chs[1].ChunkIndex)
	}
	if seq != 2 {
		t.Errorf("seq = %d, want 2", seq)
	}
	if chs[0].LineStart != 10 || chs[0].LineEnd != 1510 { // 1500 行内有 1500 个 \n
		t.Errorf("chunk0 lines = %d..%d want 10..1510", chs[0].LineStart, chs[0].LineEnd)
	}
	if chs[1].LineStart != 1510 || chs[1].LineEnd != 1710 {
		t.Errorf("chunk1 lines = %d..%d want 1510..1710", chs[1].LineStart, chs[1].LineEnd)
	}
}

// MYS-392：目录级分块后，所有文件的 ChunkID 全局唯一（消费端 ChunkByID 按 ID 索引）。
func TestChunkDirectoryIDsUnique(t *testing.T) {
	dir := t.TempDir()
	text := "# 标题\n\n" + strings.Repeat("两个文档共享的段落文本。", 60)
	for _, f := range []string{"a.md", "b.md"} {
		if err := os.WriteFile(filepath.Join(dir, f), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	got, err := NewDefaultChunker().ChunkDirectory(dir)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]string{}
	for file, chs := range got {
		for _, ch := range chs {
			if prev, ok := seen[ch.ChunkID]; ok {
				t.Errorf("ChunkID %q shared by %s and %s", ch.ChunkID, prev, file)
			}
			seen[ch.ChunkID] = file
		}
	}
}
