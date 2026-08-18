package chunker

import (
	"crypto/md5"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Chunk 单个文本块（对齐 Python chunker.Chunk）
type Chunk struct {
	ChunkID    string
	Text       string
	SourceFile string
	LineStart  int
	LineEnd    int
	ChunkIndex int
}

// MarkdownChunker 对齐 Python 分块策略：
// 800 token / 80 overlap / 保护```代码块```与|表格| / 硬上限 6000 字符。
type MarkdownChunker struct {
	ChunkSize     int
	Overlap       int
	MaxChars      int
	OverlapChars  int
	MaxChunkChars int
}

func NewDefaultChunker() *MarkdownChunker {
	return &MarkdownChunker{
		ChunkSize:     800,
		Overlap:       80,
		MaxChars:      1200, // 800 token * 1.5 chars-per-token
		OverlapChars:  120,  // 80 token * 1.5
		MaxChunkChars: 6000,
	}
}

// 分隔符优先级（从高到低）
var separators = []string{"\n## ", "\n### ", "\n#### ", "\n\n", "\n", "。", ". ", " "}

func (c *MarkdownChunker) ChunkFile(text, sourceFile string) []Chunk {
	clean, regions := extractProtected(text)
	linePos := buildLinePositions(text)
	raw := c.splitText(clean, 0)

	var out []Chunk
	pos := 0 // 上一片段 core 的结束偏移（各片段的 core 连续拼接即 clean，故按序累加定位）
	for i, r := range raw {
		text := r.overlap + r.core
		startOff := pos
		pos += len(r.core)
		if strings.TrimSpace(text) == "" {
			continue
		}
		restored := restoreProtected(text, regions)
		if len([]rune(restored)) > c.MaxChunkChars {
			out = append(out, c.charSplitChunks(restored, sourceFile, offsetToLine(linePos, startOff))...)
			continue
		}
		out = append(out, Chunk{
			ChunkID:    md5Hex(restored),
			Text:       restored,
			SourceFile: sourceFile,
			LineStart:  offsetToLine(linePos, startOff),
			LineEnd:    offsetToLine(linePos, startOff) + countNewlines(restored),
			ChunkIndex: i,
		})
	}

	// 统一 LineEnd 修正（保证 ≥ LineStart）
	for id := range out {
		if out[id].LineEnd < out[id].LineStart {
			out[id].LineEnd = out[id].LineStart
		}
	}
	return out
}

// ChunkDirectory 递归收集 *.md，跳过 SEARCH_INDEX.md
func (c *MarkdownChunker) ChunkDirectory(docsDir string) (map[string][]Chunk, error) {
	result := map[string][]Chunk{}
	err := filepath.Walk(docsDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || filepath.Ext(path) != ".md" || filepath.Base(path) == "SEARCH_INDEX.md" {
			return nil
		}
		text, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(docsDir, path)
		chs := c.ChunkFile(string(text), filepath.ToSlash(rel))
		if len(chs) > 0 {
			result[rel] = chs
		}
		return nil
	})
	return result, err
}

// ---- 内部辅助 ----

func md5Hex(s string) string {
	return fmt.Sprintf("%x", md5.Sum([]byte(s)))[:16]
}

func countNewlines(s string) int {
	n := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			n++
		}
	}
	return n
}

func buildLinePositions(text string) []int {
	pos := []int{0}
	for i := 0; i < len(text); i++ {
		if text[i] == '\n' {
			pos = append(pos, i+1)
		}
	}
	return pos
}

// offsetToLine 将字符偏移映射到 1-based 行号（二分）
func offsetToLine(pos []int, offset int) int {
	if offset <= 0 {
		return 1
	}
	lo, hi := 0, len(pos)-1
	for lo < hi {
		mid := (lo + hi + 1) / 2
		if pos[mid] <= offset {
			lo = mid
		} else {
			hi = mid - 1
		}
	}
	return lo + 1
}

// splitPiece 一次分块结果：core 为核心正文，overlap 为拼在 core 之前的
// 前导重叠（上一片段 core 的尾部文本；首段为空）。同一文本各片段的 core
// 按序连续拼接即原文，因此可据此精确定位行号。
type splitPiece struct {
	core    string
	overlap string
}

// overlapCharLen overlap 的字符数：OverlapChars 显式设置时用其值，
// 否则按约 1.5 字符/token 由 Overlap 换算（与 MaxChars=800*1.5 同一启发式）。
func (c *MarkdownChunker) overlapCharLen() int {
	if c.OverlapChars > 0 {
		return c.OverlapChars
	}
	return c.Overlap * 3 / 2
}

func (c *MarkdownChunker) splitText(text string, depth int) []splitPiece {
	if estTokens(text) <= c.ChunkSize {
		if strings.TrimSpace(text) == "" {
			return nil
		}
		return []splitPiece{{core: text}}
	}
	if depth > 10 {
		return c.charSplit(text)
	}
	for _, sep := range separators {
		if !strings.Contains(text, sep) {
			continue
		}
		parts := strings.Split(text, sep)
		var out []splitPiece
		current := ""
		overlap := "" // 待拼接到下一块的前导重叠（当前段 core 的尾部）
		for i, p := range parts {
			seg := p
			if i > 0 {
				seg = sep + p
			}
			if estTokens(overlap+current+seg) <= c.ChunkSize {
				current += seg
			} else {
				if strings.TrimSpace(overlap+current) != "" {
					out = append(out, splitPiece{core: current, overlap: overlap})
				}
				if estTokens(seg) > c.ChunkSize {
					out = append(out, c.splitText(seg, depth+1)...)
					overlap = ""
					current = ""
				} else {
					overlap = overlapTail(current, c.overlapCharLen())
					current = seg // 触发溢出的 seg 成为下一段核心的开头
				}
			}
		}
		if strings.TrimSpace(overlap+current) != "" {
			out = append(out, splitPiece{core: current, overlap: overlap})
		}
		return out
	}
	return c.charSplit(text)
}

// overlapTail 取 s 尾部最多 n 个 rune 作为相邻块重叠；若切点落在保护占位符
// __PROTECTED_N__ 中间，则回溯到占位符起点，保证占位符完整进入重叠文本。
func overlapTail(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	cut := len(r) - n
	const mkLen = len("__PROTECTED_")
	for i := cut - 1; i >= 0; i-- {
		if hasMarkerAt(r, i) {
			// 最近的占位符起点距切点 ≤ 占位符全长（含 _N__ 后缀）时，认为切点落在占位符内
			if cut-i <= mkLen+4 {
				cut = i
			}
			break
		}
	}
	return string(r[cut:])
}

// hasMarkerAt 判断 r[i:] 是否以保护占位符前缀"__PROTECTED_"开头。
func hasMarkerAt(r []rune, i int) bool {
	const mk = "__PROTECTED_"
	if i+len(mk) > len(r) {
		return false
	}
	for j := 0; j < len(mk); j++ {
		if r[i+j] != rune(mk[j]) {
			return false
		}
	}
	return true
}

func (c *MarkdownChunker) charSplit(text string) []splitPiece {
	var out []splitPiece
	r := []rune(text)
	step := c.MaxChars - c.overlapCharLen()
	if step < 1 {
		step = c.MaxChars
	}
	for i := 0; i < len(r); i += step {
		end := i + c.MaxChars
		if end > len(r) {
			end = len(r)
		}
		piece := string(r[i:end])
		if strings.TrimSpace(piece) != "" {
			out = append(out, splitPiece{core: piece})
		}
	}
	return out
}

// charSplitChunks 超长 chunk 的字符级二切（runes 步进，保持 UTF-8 完整）。
func (c *MarkdownChunker) charSplitChunks(text, sourceFile string, baseLine int) []Chunk {
	var out []Chunk
	r := []rune(text)
	for i := 0; i < len(r); i += c.MaxChunkChars {
		end := i + c.MaxChunkChars
		if end > len(r) {
			end = len(r)
		}
		piece := string(r[i:end])
		if strings.TrimSpace(piece) != "" {
			out = append(out, Chunk{
				ChunkID:    md5Hex(piece),
				Text:       piece,
				SourceFile: sourceFile,
				LineStart:  baseLine + countNewlines(text[:i]),
				LineEnd:    baseLine + countNewlines(text[:end]),
				ChunkIndex: len(out),
			})
		}
	}
	return out
}

func estTokens(s string) int {
	cn, other := 0, 0
	for _, r := range s {
		if r >= 0x4e00 && r <= 0x9fff {
			cn++
		} else {
			other++
		}
	}
	return cn*3/2 + other/4
}

// ---- 保护区域（代码块/表格）----

type seg struct {
	s, e int
	kind string
}

type region struct {
	start, end int
	content    string
	kind       string
}

func extractProtected(text string) (string, []region) {
	var segs []seg
	segs = scanCodeBlock(text, segs)
	segs = scanTables(text, segs)
	sort.SliceStable(segs, func(i, j int) bool { return segs[i].s < segs[j].s })

	clamp := func(lo, hi, n int) (int, int) {
		if lo < 0 {
			lo = 0
		}
		if lo > n {
			lo = n
		}
		if hi < lo {
			hi = lo
		}
		if hi > n {
			hi = n
		}
		return lo, hi
	}

	var regions []region
	var sb strings.Builder
	last := 0
	for i, s := range segs {
		lo, hi := clamp(s.s, s.e, len(text))
		// 仅保留非空、且不重叠在已处理区域之后的片段（防御越界于 len(text)）。
		if hi > lo && lo >= last {
			sb.WriteString(text[last:lo])
			sb.WriteString(fmt.Sprintf("__PROTECTED_%d__", i))
			regions = append(regions, region{lo, hi, text[lo:hi], s.kind})
			last = hi
		}
	}
	sb.WriteString(text[last:])
	return sb.String(), regions
}

func scanCodeBlock(text string, in []seg) []seg {
	out := in
	i := 0
	for i < len(text) {
		idx := indexOfFrom(text, "```", i)
		if idx < 0 {
			break
		}
		end := indexOfFrom(text, "```", idx+3)
		if end < 0 {
			break
		}
		e := end + 3
		out = append(out, seg{idx, e, "code"})
		i = e
	}
	return out
}

func scanTables(text string, in []seg) []seg {
	out := in
	lines := strings.Split(text, "\n")
	n := len(text)
	off := 0
	i := 0
	for i < len(lines) {
		line := lines[i]
		if tableRow(line) {
			st := off
			j := i
			for j < len(lines) && tableRow(lines[j]) {
				// +1 对应换行符；最后一行无换行时 off 不应超过 len(text)
				off += len(lines[j]) + 1
				if off > n {
					off = n
				}
				j++
			}
			out = append(out, seg{st, off, "table"})
			i = j
			continue
		}
		off += len(line) + 1
		if off > n {
			off = n
		}
		i++
	}
	return out
}

func tableRow(s string) bool {
	ts := strings.TrimSpace(s)
	return strings.HasPrefix(ts, "|") && strings.HasSuffix(ts, "|") && strings.Contains(ts, "|")
}

func restoreProtected(text string, regions []region) string {
	out := text
	for i, r := range regions {
		out = strings.Replace(out, fmt.Sprintf("__PROTECTED_%d__", i), r.content, 1)
	}
	return out
}

func indexOfFrom(s, sub string, from int) int {
	if from < 0 {
		from = 0
	}
	if from >= len(s) {
		return -1
	}
	idx := strings.Index(s[from:], sub)
	if idx < 0 {
		return -1
	}
	return from + idx
}
