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
	for i, r := range raw {
		if strings.TrimSpace(r) == "" {
			continue
		}
		restored := restoreProtected(r, regions)
		startOff := strings.Index(clean, r)
		if startOff < 0 {
			startOff = 0
		}
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

func (c *MarkdownChunker) splitText(text string, depth int) []string {
	if estTokens(text) <= c.ChunkSize {
		if strings.TrimSpace(text) == "" {
			return nil
		}
		return []string{text}
	}
	if depth > 10 {
		return c.charSplit(text)
	}
	for _, sep := range separators {
		if !strings.Contains(text, sep) {
			continue
		}
		parts := strings.Split(text, sep)
		var out []string
		current := ""
		for i, p := range parts {
			seg := p
			if i > 0 {
				seg = sep + p
			}
			if estTokens(current+seg) <= c.ChunkSize {
				current += seg
			} else {
				if strings.TrimSpace(current) != "" {
					out = append(out, current)
				}
				if estTokens(seg) > c.ChunkSize {
					out = append(out, c.splitText(seg, depth+1)...)
				} else {
					current = seg
				}
			}
		}
		if strings.TrimSpace(current) != "" {
			out = append(out, current)
		}
		return out
	}
	return c.charSplit(text)
}

func (c *MarkdownChunker) charSplit(text string) []string {
	var out []string
	step := c.MaxChars - c.OverlapChars
	if step < 1 {
		step = c.MaxChars
	}
	for i := 0; i < len(text); i += step {
		end := i + c.MaxChars
		if end > len(text) {
			end = len(text)
		}
		piece := text[i:end]
		if strings.TrimSpace(piece) != "" {
			out = append(out, piece)
		}
	}
	return out
}

func (c *MarkdownChunker) charSplitChunks(text, sourceFile string, baseLine int) []Chunk {
	var out []Chunk
	for i := 0; i < len(text); i += c.MaxChunkChars {
		end := i + c.MaxChunkChars
		if end > len(text) {
			end = len(text)
		}
		piece := text[i:end]
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
