package chunker

import (
	"fmt"
	"math/rand"
	"strings"
	"testing"
)

// 用确定性随机文档核对：正文不丢、行号区间不越界、ChunkID 不重复。
// 生成器覆盖标题 / 目录 / 引用 / 代码围栏 / 表格 / 长小节等形态。
func TestHeadingRandomDocsLoseNoProse(t *testing.T) {
	rnd := rand.New(rand.NewSource(20261016))
	proseWords := []string{
		"设备", "接口", "内存", "分辨率", "编译", "固件", "网络", "配置", "参数", "说明",
		"本章主要介绍常用接口，主要内容如下：", "详细说明请阅读《开发参考手册》。",
	}
	for iter := 0; iter < 400; iter++ {
		text := genDoc(rnd, proseWords)
		lines := strings.Split(text, "\n")
		file := "doc.md"
		if iter%2 == 0 {
			file = "doc-faq.md"
		}
		cs := NewDefaultChunker().ChunkFile(text, file)
		all := ""
		for _, c := range cs {
			all += c.Text + "\n"
			if c.LineStart < 1 || c.LineEnd > len(lines) || c.LineStart > c.LineEnd {
				t.Fatalf("iter %d: bad range %d-%d (file %d lines)\n%s", iter, c.LineStart, c.LineEnd, len(lines), text)
			}
			body := c.Text
			if i := strings.Index(body, "】\n"); strings.HasPrefix(body, "【") && i >= 0 {
				body = body[i+len("】\n"):]
			}
			if !strings.HasSuffix(body, lines[c.LineEnd-1]) {
				t.Fatalf("iter %d: chunk %d does not end at line %d\nchunk=%q\nline=%q",
					iter, c.ChunkIndex, c.LineEnd, tail(body, 60), tail(lines[c.LineEnd-1], 60))
			}
		}
		seen := map[string]bool{}
		for _, c := range cs {
			if seen[c.ChunkID] {
				t.Fatalf("iter %d: duplicate ChunkID %s", iter, c.ChunkID)
			}
			seen[c.ChunkID] = true
		}
		// 正文行不丢：非空、非标题、非目录条目的行必须能在某个块里找到
		for i, l := range lines {
			s := strings.TrimSpace(l)
			if s == "" || headingRe.MatchString(l) || s == "---" || isTOCEntry(s) {
				continue
			}
			if !strings.Contains(all, s) {
				t.Fatalf("iter %d: prose line %d left the index: %q\n%s", iter, i+1, s, text)
			}
		}
	}
}

// genDoc 生成一篇确定性随机文档。prose 行都带句读或足够长，
// 以免与目录条目混淆（目录条目按定义很短且无句读）。
func genDoc(rnd *rand.Rand, prose []string) string {
	var sb strings.Builder
	n := 1 + rnd.Intn(4) // h1 数量
	for h := 0; h < n; h++ {
		fmt.Fprintf(&sb, "# 第%d章 主题%d\n\n", h+1, rnd.Intn(50))
		if rnd.Intn(3) == 0 { // 目录小节
			sb.WriteString("## 目录\n\n")
			switch rnd.Intn(4) {
			case 0: // 纯目录：应丢弃
				fmt.Fprintf(&sb, "- [小节%d](#小节%d)\n- [小节%d](#小节%d)\n\n", h, h, h+1, h+1)
			case 1: // 纯目录：编号短标题
				fmt.Fprintf(&sb, "%d.1 概述\n%d.2 安装\n\n", h+1, h+1)
			case 2: // 带导语的"目录"小节：必须保留
				sb.WriteString(prose[rnd.Intn(len(prose))] + "\n\n")
				fmt.Fprintf(&sb, "- [小节%d](#小节%d)\n\n", h, h)
			case 3: // 带引用块与代码块的"目录"小节：必须保留
				sb.WriteString("> 前置条件与空间要求见下。\n\n```bash\nsudo df -h /\n```\n\n")
			}
		}
		for s := 0; s < 1+rnd.Intn(4); s++ {
			fmt.Fprintf(&sb, "## 小节%d.%d\n\n", h+1, s+1)
			switch rnd.Intn(6) {
			case 0:
				fmt.Fprintf(&sb, "| 名称 | 说明 |\n|---|---|\n| p%d | %s |\n\n", s, prose[rnd.Intn(len(prose))])
			case 1:
				fmt.Fprintf(&sb, "```c\nint f%d(void);\n## 不是标题\n```\n\n", s)
			case 2:
				fmt.Fprintf(&sb, "> %s\n\n", prose[rnd.Intn(len(prose))])
			case 3:
				for i := 0; i < 60; i++ { // 撑到超长，触发二切
					fmt.Fprintf(&sb, "%s第 %d 段补充说明。\n\n", prose[rnd.Intn(len(prose))], i)
				}
			case 4:
				fmt.Fprintf(&sb, "### 小节%d.%d.1\n\n", h+1, s+1) // 仅标题小节 + 更深的下一级
				fmt.Fprintf(&sb, "#### 小节%d.%d.1.1\n\n%s\n\n", h+1, s+1, prose[rnd.Intn(len(prose))])
			default:
				fmt.Fprintf(&sb, "%s\n\n", prose[rnd.Intn(len(prose))])
			}
		}
	}
	return sb.String()
}

func tail(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return "…" + string(r[len(r)-n:])
}
