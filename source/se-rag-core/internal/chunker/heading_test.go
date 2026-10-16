package chunker

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// 问答文档（*-faq.md）：每个小节独立成块
func chunkH(text string) []Chunk { return NewDefaultChunker().ChunkFile(text, "x-faq.md") }

// 手册文档：相邻小节打包
func chunkM(text string) []Chunk { return NewDefaultChunker().ChunkFile(text, "manual.md") }

func TestHeadingSplitsPerSectionWithBreadcrumb(t *testing.T) {
	text := "---\ntitle: T\n---\n\n# bmcv_foo\n\n简介\n\n## 参数说明\n\n参数 a\n\n## 返回值\n\n成功\n"
	cs := chunkH(text)
	// bmcv_foo 简介 / 参数说明 / 返回值（只有 frontmatter 的前言不单独成块）
	if len(cs) != 3 {
		t.Fatalf("want 3 chunks, got %d: %+v", len(cs), cs)
	}
	if !strings.HasPrefix(cs[1].Text, "【bmcv_foo】\n## 参数说明") || strings.Contains(cs[1].Text, "成功") {
		t.Errorf("param chunk should carry breadcrumb and only its own section: %q", cs[1].Text)
	}
	if strings.HasPrefix(cs[0].Text, "【") {
		t.Errorf("top-level section has no breadcrumb: %q", cs[0].Text)
	}
}

func TestHeadingBreadcrumbDepth(t *testing.T) {
	text := "# A\n\na\n\n## B\n\nb\n\n### C\n\nc\n\n## D\n\nd\n"
	cs := chunkH(text)
	var c, d string
	for _, x := range cs {
		if strings.Contains(x.Text, "### C") {
			c = x.Text
		}
		if strings.Contains(x.Text, "## D") {
			d = x.Text
		}
	}
	if !strings.HasPrefix(c, "【A › B】\n") {
		t.Errorf("C breadcrumb: %q", c)
	}
	if !strings.HasPrefix(d, "【A】\n") { // D 与 B 同级，祖先只有 A
		t.Errorf("D breadcrumb: %q", d)
	}
}

func TestHeadingLineNumbersReproduceBody(t *testing.T) {
	text := "## A\n\n### Q1\n\nans1\n\n### Q2\n\nans2"
	lines := strings.Split(text, "\n")
	for _, c := range chunkH(text) {
		body := c.Text
		if i := strings.Index(body, "】\n"); strings.HasPrefix(body, "【") && i >= 0 {
			body = body[i+len("】\n"):]
		}
		if got := strings.Join(lines[c.LineStart-1:c.LineEnd], "\n"); got != body {
			t.Errorf("lines %d-%d != body:\n got %q\nwant %q", c.LineStart, c.LineEnd, got, body)
		}
	}
}

func TestHeadingHashInCodeFenceIsNotHeading(t *testing.T) {
	text := "### Q\n\n答：\n\n```bash\n## 注释\n# 也是注释\necho hi\n```\n\n### Q2\n\nx"
	cs := chunkH(text)
	if len(cs) != 2 || !strings.Contains(cs[0].Text, "echo hi") || !strings.Contains(cs[0].Text, "## 注释") {
		t.Fatalf("fence content must stay in the first chunk: %+v", cs)
	}
}

func TestHeadingOnlySectionsFoldIntoBreadcrumb(t *testing.T) {
	cs := chunkH("## 视频解码\n\n### 常见问题\n\n#### 问题\n\n答案")
	if len(cs) != 1 || !strings.HasPrefix(cs[0].Text, "【视频解码 › 常见问题】\n#### 问题") || !strings.Contains(cs[0].Text, "答案") {
		t.Fatalf("heading-only sections should not be chunks; their titles live in the breadcrumb: %+v", cs)
	}
}

func TestHeadingNoHeadingsStillChunked(t *testing.T) {
	var sb strings.Builder
	for i := 0; i < 200; i++ {
		fmt.Fprintf(&sb, "第 %d 段文字，用来撑大文档内容长度。\n\n", i)
	}
	cs := chunkH(sb.String())
	if len(cs) < 3 {
		t.Fatalf("headingless long doc should be split, got %d", len(cs))
	}
	for _, c := range cs {
		if n := len([]rune(c.Text)); n > pieceHardChars+200 {
			t.Errorf("chunk too large: %d", n)
		}
	}
}

func TestHeadingLongSectionSplitsAtBlankLinesAndRepeatsHeading(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("# 手册\n\n## 大节\n\n")
	for i := 0; i < 80; i++ {
		fmt.Fprintf(&sb, "这是第 %d 段较长的说明文字，包含一些细节内容，用于把这个小节撑到超过上限。\n\n", i)
	}
	sb.WriteString("## 小节\n\n尾巴")
	text := sb.String()
	cs := chunkH(text)
	lines := strings.Split(text, "\n")
	var big []Chunk
	for _, c := range cs {
		if strings.HasPrefix(c.Text, "【手册】\n## 大节") {
			big = append(big, c)
		}
	}
	if len(big) < 2 {
		t.Fatalf("long section should split into several chunks carrying the heading, got %d", len(big))
	}
	for _, c := range big {
		if n := len([]rune(c.Text)); n > pieceHardChars+100 {
			t.Errorf("piece too large: %d", n)
		}
	}
	last := cs[len(cs)-1]
	if !strings.HasPrefix(last.Text, "【手册】\n## 小节") || lines[last.LineStart-1] != "## 小节" {
		t.Errorf("last chunk wrong: %q (line %d → %q)", last.Text, last.LineStart, lines[last.LineStart-1])
	}
	// 切开的块之间行区间应首尾相接，不丢行
	prev := 0
	for _, c := range cs {
		if prev != 0 && c.LineStart != prev+1 {
			t.Errorf("gap between chunks: prev end %d, next start %d", prev, c.LineStart)
		}
		prev = c.LineEnd
	}
	if prev != len(lines) {
		t.Errorf("last chunk ends at %d, file has %d lines", prev, len(lines))
	}
}

func TestHeadingSplitInsideTableRepeatsHeader(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("## 参数表\n\n| 名称 | 说明 |\n|---|---|\n")
	for i := 0; i < 120; i++ {
		fmt.Fprintf(&sb, "| p%d | 这是第 %d 个参数的说明说明说明说明 |\n", i, i)
	}
	cs := chunkH(sb.String())
	if len(cs) < 2 {
		t.Fatalf("want split, got %d", len(cs))
	}
	for i, c := range cs[1:] {
		if !strings.Contains(c.Text, "| 名称 | 说明 |\n|---|---|") {
			t.Errorf("continuation %d should repeat table header: %q", i+1, c.Text[:60])
		}
	}
}

func TestHeadingUnclosedFenceDoesNotLoseText(t *testing.T) {
	text := "## A\n\n```c\nint x;\n\n## B\n\nlast words"
	cs := chunkH(text)
	joined := ""
	for _, c := range cs {
		joined += c.Text
	}
	if !strings.Contains(joined, "last words") {
		t.Errorf("text after an unclosed fence must still be indexed: %+v", cs)
	}
}

func TestChunkIDsUniqueInHeadingMode(t *testing.T) {
	cs := chunkH("## A\n\nsame\n\n## A\n\nsame\n")
	seen := map[string]bool{}
	for _, c := range cs {
		if seen[c.ChunkID] {
			t.Errorf("duplicate ChunkID %s", c.ChunkID)
		}
		seen[c.ChunkID] = true
	}
}

func TestChunkDirectoryHeadingMode(t *testing.T) {
	dir := t.TempDir()
	body := []byte("## A\n\nx\n\n## B\n\ny")
	os.WriteFile(filepath.Join(dir, "a-faq.md"), body, 0o644)
	os.WriteFile(filepath.Join(dir, "guide.md"), body, 0o644)
	m, err := NewDefaultChunker().ChunkDirectory(dir)
	if err != nil || len(m["a-faq.md"]) != 2 || len(m["guide.md"]) != 1 {
		t.Fatalf("err=%v faq=%d guide=%d, want 2 and 1", err, len(m["a-faq.md"]), len(m["guide.md"]))
	}
}

func TestIsFAQFile(t *testing.T) {
	for name, want := range map[string]bool{
		"10-media-faq.md": true, "se9/12-algorithm-faq.md": true, "11-BSP-FAQ.md": true,
		"00-introduce.md": false, "faq.md": false, "sophon-sail_clear.md": false,
	} {
		if got := IsFAQFile(name); got != want {
			t.Errorf("IsFAQFile(%q)=%v want %v", name, got, want)
		}
	}
}

func TestManualPacksSmallSectionsUnderSameH1(t *testing.T) {
	pad := strings.Repeat("这里是一段说明文字。", 30)
	text := "# bmcv_foo\n\n简介\n" + pad + "\n\n## 接口形式\n\nint foo();\n\n## 参数说明\n\n参数 a\n\n## 返回值\n\n成功\n\n# bmcv_bar\n\n另一个接口\n" + pad + "\n\n## 接口形式\n\nint bar();\n"
	cs := chunkM(text)
	if len(cs) != 2 {
		t.Fatalf("want 2 chunks (one per h1 block), got %d: %+v", len(cs), cs)
	}
	if !strings.Contains(cs[0].Text, "参数 a") || !strings.Contains(cs[0].Text, "成功") || strings.Contains(cs[0].Text, "另一个接口") {
		t.Errorf("first chunk should pack bmcv_foo only: %q", cs[0].Text)
	}
	if !strings.Contains(cs[1].Text, "int bar()") {
		t.Errorf("second chunk should be bmcv_bar: %q", cs[1].Text)
	}
}

func TestManualDoesNotPackBeyondMax(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("# 手册\n\n")
	for i := 0; i < 6; i++ {
		fmt.Fprintf(&sb, "## 节%d\n\n%s\n\n", i, strings.Repeat("文字内容", 100))
	}
	cs := chunkM(sb.String())
	if len(cs) < 2 {
		t.Fatalf("sections beyond packMaxChars must start a new chunk, got %d", len(cs))
	}
	for _, c := range cs {
		if n := len([]rune(c.Text)); n > packMaxChars+200 {
			t.Errorf("packed chunk too large: %d", n)
		}
	}
}

func TestManualTinyChunkCrossesH1(t *testing.T) {
	cs := chunkM("# A\n\n一句话\n\n# B\n\n正文正文\n")
	if len(cs) != 1 {
		t.Fatalf("a tiny chunk should absorb the next h1 section, got %d", len(cs))
	}
}

func TestTOCSectionIsDropped(t *testing.T) {
	cs := chunkM("# 手册\n\n简介\n\n## 目录\n\n1 安全\n2 简介\n3 规格\n\n## 1 安全\n\n正文\n")
	for _, c := range cs {
		if strings.Contains(c.Text, "3 规格") {
			t.Errorf("table of contents must not be indexed: %q", c.Text)
		}
	}
	if !strings.Contains(cs[len(cs)-1].Text, "正文") {
		t.Errorf("sections after the TOC must survive: %+v", cs)
	}
	for _, title := range []string{"目录", "目 录", "Contents", "Table of Contents"} {
		if !isTOCTitle(title) {
			t.Errorf("%q should be a TOC title", title)
		}
	}
	if isTOCTitle("目录结构说明") {
		t.Error("only exact TOC titles are dropped")
	}
}
