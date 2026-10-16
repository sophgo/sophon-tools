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
//	heading-v2       ：所有 Markdown 按 #~#### 标题切块（每个问答 / 每个小节独立成块），
//	                   块首带祖先标题路径，超长小节在行边界处二切
const StrategyVersion = "heading-v2"

const (
	// sectionMaxChars 单个小节的字符上限；超过则在行边界处切成多块。
	sectionMaxChars = 2400
	// pieceSoftChars 二切时优先在空行处断开的最小累计长度；pieceHardChars 超过则强制在行边界断开。
	pieceSoftChars = 1200
	pieceHardChars = 2400
)

var (
	headingRe = regexp.MustCompile(`^(#{1,4})\s+(\S.*?)\s*$`)
	fenceRe   = regexp.MustCompile("^\\s*(```|~~~)")
	sepRowRe  = regexp.MustCompile(`^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$`)
)

type hsection struct {
	from, to int      // 0 起的行下标 [from,to)
	level    int      // 本节标题层级（1–4）；无标题的前言为 0
	crumbs   []string // 祖先标题（不含自身）
	headLine string   // 本段第一行标题原文（无标题的前言为空）
	title    string   // 本节标题文字
}

// chunkByHeadings 把文档按标题（h1–h4，围栏内的 # 不算）切成小节，每个小节一块：
//   - 首个标题之前的内容（frontmatter、导语）自成一块；
//   - 只有标题没有正文的小节、只有 frontmatter 的前言、"目录"小节不单独成块（标题已在后代小节的祖先路径里）；
//   - 块文本以 "【祖先1 › 祖先2】" 开头（有祖先时），让只含 "参数说明" 这类通用标题的块也带着所属主题；
//   - 超长小节在行边界处二切：优先空行，其次强制；续块重复小节标题，表格续块重复表头；
//   - 行号（LineStart/LineEnd）始终是原文行号，不含上述前缀。
func (c *MarkdownChunker) chunkByHeadings(text, sourceFile string) []Chunk {
	lines := strings.Split(text, "\n")
	secs := splitSections(lines)
	if !IsFAQFile(sourceFile) {
		secs = packSections(lines, secs)
	}

	var out []Chunk
	seq := 0
	emit := func(body string, crumbs []string, ls, le int) {
		if strings.TrimSpace(body) == "" {
			return
		}
		txt := body
		if len(crumbs) > 0 {
			txt = "【" + strings.Join(crumbs, " › ") + "】\n" + body
		}
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
		body := strings.Join(lines[s.from:s.to], "\n")
		if len([]rune(body)) <= sectionMaxChars {
			emit(body, s.crumbs, s.from+1, s.to)
			continue
		}
		for i, p := range splitLong(lines, s) {
			b := p.text
			if i > 0 && s.headLine != "" {
				b = s.headLine + "\n" + b
			}
			emit(b, s.crumbs, p.from+1, p.to)
		}
	}
	return out
}

// IsFAQFile 判断是否是问答类文档：文件名以 -faq.md 结尾（不区分大小写），如 10-media-faq.md。
// 问答文档的每个小节（一个问答）无论多短都独立成块；其他文档（手册 / README）的相邻小节会被打包。
func IsFAQFile(sourceFile string) bool {
	return strings.HasSuffix(strings.ToLower(filepath.Base(sourceFile)), "-faq.md")
}

const (
	// packMaxChars 手册类文档里相邻小节打包后的字符上限。
	packMaxChars = 1800
	// packTinyChars 当前打包块小于该值时，允许越过 h1 边界继续并入下一节（避免出现只有标题的碎块）。
	packTinyChars = 200
)

// packSections 把手册类文档里相邻的小节打包成接近 packMaxChars 的块：
// API 手册每个接口下有"接口形式 / 参数说明 / 返回值 …"一串很短的小节，单独成块只有几十个字，
// 既没有检索价值又会让索引膨胀数倍。打包不越过 h1 边界（不同章节 / 不同接口不混在一块），
// 除非当前块还很小。
func packSections(lines []string, secs []hsection) []hsection {
	size := func(a, b int) int { return len([]rune(strings.Join(lines[a:b], "\n"))) }
	var out []hsection
	for _, s := range secs {
		if n := len(out); n > 0 {
			p := &out[n-1]
			total := size(p.from, s.to)
			crossH1 := s.level <= 1
			// 两节之间有被丢弃的内容（目录 / 仅标题的小节）时不打包，避免把丢弃的文字带回来
			if s.from == p.to && total <= packMaxChars && (!crossH1 || size(p.from, p.to) < packTinyChars) {
				p.to = s.to
				continue
			}
		}
		out = append(out, s)
	}
	return out
}

// splitSections 找出标题边界、计算祖先路径，并丢弃只有标题的小节。
func splitSections(lines []string) []hsection {
	type head struct {
		idx   int
		level int
		title string
	}
	var heads []head
	fence := false
	for i, l := range lines {
		if fenceRe.MatchString(l) {
			fence = !fence
			continue
		}
		if fence {
			continue
		}
		if m := headingRe.FindStringSubmatch(l); m != nil {
			heads = append(heads, head{i, len(m[1]), m[2]})
		}
	}

	// 每个小节的祖先路径：栈里保留层级严格小于当前的标题
	var raw []hsection
	var stack []head
	if len(heads) == 0 || heads[0].idx > 0 {
		end := len(lines)
		if len(heads) > 0 {
			end = heads[0].idx
		}
		raw = append(raw, hsection{from: 0, to: end})
	}
	for k, h := range heads {
		for len(stack) > 0 && stack[len(stack)-1].level >= h.level {
			stack = stack[:len(stack)-1]
		}
		var crumbs []string
		for _, a := range stack {
			crumbs = append(crumbs, a.title)
		}
		end := len(lines)
		if k+1 < len(heads) {
			end = heads[k+1].idx
		}
		raw = append(raw, hsection{from: h.idx, to: end, level: h.level, crumbs: crumbs, headLine: lines[h.idx], title: h.title})
		stack = append(stack, h)
	}

	// 只有标题没有正文、且下一个标题更深（即本标题会出现在后代的祖先路径里）的小节才丢弃；
	// 下一个标题是同级或更浅时（如 "### 6.3 硬盘挂载" 紧跟 "## 说明"、FAQ 里同级的下一个问题），
	// 标题不会被任何祖先路径带走，必须保留成块，否则该章节名会从索引里彻底消失。
	var secs []hsection
	for k, sec := range raw {
		if sec.headLine == "" && frontmatterOnly(lines[sec.from:sec.to]) {
			continue // 只有 frontmatter 的前言不单独成块
		}
		if isTOCTitle(sec.title) {
			continue // 自动生成的目录会列出全部标题，几乎命中任何查询
		}
		if headingOnly(lines[sec.from:sec.to]) && k+1 < len(raw) && raw[k+1].level > sec.level {
			continue
		}
		secs = append(secs, sec)
	}
	return secs
}

// headingOnly 小节是否只有标题行和空行（没有正文）。
func headingOnly(sec []string) bool {
	n := 0
	for _, l := range sec {
		if strings.TrimSpace(l) == "" {
			continue
		}
		if !headingRe.MatchString(l) {
			return false
		}
		n++
	}
	return n > 0
}

type piece struct {
	from, to int // 0 起的行下标 [from,to)
	text     string
}

// splitLong 把超长小节切成若干块：累计 ≥ pieceSoftChars 后遇到围栏外的空行断开；
// 累计 > pieceHardChars 时强制在当前行边界断开。表格被切开时，续块前补上表头两行。
func splitLong(lines []string, s hsection) []piece {
	head := tableHeads(lines, s)
	var out []piece
	fence := false
	cur := s.from
	size := 0
	flush := func(end int) {
		if end <= cur {
			return
		}
		body := strings.Join(lines[cur:end], "\n")
		if h := head[cur-s.from]; h != "" {
			body = h + "\n" + body
		}
		out = append(out, piece{cur, end, body})
		cur = end
		size = 0
	}
	for i := s.from; i < s.to; i++ {
		l := lines[i]
		if fenceRe.MatchString(l) {
			fence = !fence
		}
		n := len([]rune(l)) + 1
		if size+n > pieceHardChars && i > cur {
			flush(i)
		}
		size += n
		if !fence && strings.TrimSpace(l) == "" && size >= pieceSoftChars && i+1 < s.to {
			flush(i + 1)
		}
	}
	flush(s.to)
	return out
}

// tableHeads 返回小节内每一行"如果在此处被切开，续块需要补的表头"：
// 行位于围栏外某个表格的第 3 行及之后（表头 + 分隔行之后的数据行）时，取该表格的表头两行，否则为空。
func tableHeads(lines []string, s hsection) []string {
	out := make([]string, s.to-s.from)
	fence := false
	hdr := ""
	rowInTable := 0
	for i := s.from; i < s.to; i++ {
		l := lines[i]
		if fenceRe.MatchString(l) {
			fence = !fence
			hdr, rowInTable = "", 0
			continue
		}
		if fence || !isTableRow(l) {
			hdr, rowInTable = "", 0
			continue
		}
		rowInTable++
		if rowInTable == 1 {
			hdr = ""
			if i+1 < s.to && sepRowRe.MatchString(lines[i+1]) {
				hdr = l + "\n" + lines[i+1]
			}
			continue
		}
		if rowInTable >= 3 {
			out[i-s.from] = hdr
		}
	}
	return out
}

func isTableRow(l string) bool {
	t := strings.TrimSpace(l)
	return strings.HasPrefix(t, "|") && strings.Count(t, "|") >= 2
}

// frontmatterOnly 小节是否只有 YAML frontmatter（--- ... ---）和空行。
func frontmatterOnly(sec []string) bool {
	in, seen := false, 0
	for _, l := range sec {
		t := strings.TrimSpace(l)
		if t == "---" {
			seen++
			in = !in
			continue
		}
		if t != "" && !in {
			return false
		}
	}
	return seen == 2
}

// isTOCTitle 标题是否是"目录"一类（目录 / 目 录 / Contents / Table of Contents）。
func isTOCTitle(title string) bool {
	t := strings.ToLower(strings.ReplaceAll(strings.TrimSpace(title), " ", ""))
	return t == "目录" || t == "contents" || t == "tableofcontents"
}
