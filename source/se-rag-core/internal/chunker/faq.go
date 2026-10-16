package chunker

import (
	"path/filepath"
	"regexp"
	"strings"
)

// StrategyVersion 分块策略版本。分块规则变化会改变索引内容，此时递增；
// 它被写入索引 meta，doctor / query 据此提示旧索引需要重建。
//
//	v0（meta 中为空）：所有文件统一按 800 token 递归切分
//	faq-heading-v1   ：FAQ 文档（*-faq.md）按 ##/###/#### 标题切块，每个问答独立成块
const StrategyVersion = "faq-heading-v1"

// faqMaxChars 单个问答块的字符上限；超过则退回通用递归切分（保留代码块 / 表格保护）。
const faqMaxChars = 2400

// IsFAQFile 判断是否按 FAQ 规则分块：文件名以 -faq.md 结尾（不区分大小写），
// 例如 10-media-faq.md、11-bsp-faq.md、12-algorithm-faq.md。
func IsFAQFile(sourceFile string) bool {
	return strings.HasSuffix(strings.ToLower(filepath.Base(sourceFile)), "-faq.md")
}

var (
	faqHeadingRe = regexp.MustCompile(`^(#{2,4})\s+\S`)
	faqFenceRe   = regexp.MustCompile("^\\s*(```|~~~)")
)

// chunkFAQ 按标题（h2–h4，代码围栏内的 # 不算）把文档切成问答块：
//   - 首个标题之前的内容（frontmatter、导语）自成一块；
//   - 只有标题、没有正文的段落（如 "## 视频解码" 后紧跟 "### 常见问题"）并入下一段，不单独成块；
//   - 段落超过 faqMaxChars 时，对该段走通用切分，行号按段落起点平移。
func (c *MarkdownChunker) chunkFAQ(text, sourceFile string) []Chunk {
	lines := strings.Split(text, "\n")

	// 1) 找段落边界（0 起的行下标）
	starts := []int{0}
	fence := false
	for i, l := range lines {
		if faqFenceRe.MatchString(l) {
			fence = !fence
			continue
		}
		if !fence && i > 0 && faqHeadingRe.MatchString(l) {
			starts = append(starts, i)
		}
	}
	starts = append(starts, len(lines))

	// 2) 合并只有标题的段落到下一段
	type sec struct{ from, to int }
	var secs []sec
	pendingFrom := -1
	for k := 0; k+1 < len(starts); k++ {
		from, to := starts[k], starts[k+1]
		if pendingFrom >= 0 {
			from = pendingFrom
			pendingFrom = -1
		}
		if headingOnly(lines[from:to]) && k+2 < len(starts) {
			pendingFrom = from
			continue
		}
		secs = append(secs, sec{from, to})
	}

	// 3) 生成块
	var out []Chunk
	seq := 0
	emit := func(txt string, ls, le int) {
		out = append(out, Chunk{
			ChunkID:    chunkID(sourceFile, seq, txt),
			Text:       txt,
			SourceFile: sourceFile,
			LineStart:  ls,
			LineEnd:    le,
			ChunkIndex: seq,
		})
		seq++
	}
	for _, s := range secs {
		txt := strings.Join(lines[s.from:s.to], "\n")
		if strings.TrimSpace(txt) == "" {
			continue
		}
		if len([]rune(txt)) <= faqMaxChars {
			emit(txt, s.from+1, s.to)
			continue
		}
		for _, sub := range c.chunkPlain(txt, sourceFile) {
			emit(sub.Text, sub.LineStart+s.from, sub.LineEnd+s.from)
		}
	}
	return out
}

// headingOnly 段落是否只有标题行和空行（没有正文）。
func headingOnly(sec []string) bool {
	n := 0
	for _, l := range sec {
		if strings.TrimSpace(l) == "" {
			continue
		}
		if !faqHeadingRe.MatchString(l) {
			return false
		}
		n++
	}
	return n > 0
}
