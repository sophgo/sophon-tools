package main

// 标识符—标题精确匹配提权（v7.1）的端到端测试。
//
// 覆盖：标题命中块排到第一、没有标识符时结果与旧版一致、多索引场景、
// -doc-type 过滤不泄露、在线路径 rerank 后的第一名。

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
	"se-rag-core/internal/ident"
	"se-rag-core/internal/retriever"
)

// boostDoc 写一篇仿 datasheet：一张"寄存器概览表"（正文里满是寄存器名、得分天然高）
// 与若干寄存器字段表（标题就是寄存器名）。返回 docs 目录。
func boostDoc(t *testing.T, dir string) string {
	t.Helper()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(filepath.Join(docsDir, "datasheet"), 0o755); err != nil {
		t.Fatal(err)
	}
	// 概览表：一行一个寄存器名，BM25 会因此给出极高的内容相似度
	overview := strings.Join([]string{
		"---", "title: BM1688 数据手册", "entity: bm1688", "doc_type: datasheet",
		"version: 1.0.1", "source: 测试夹具", "---", "",
		"# BM1688 数据手册", "",
		"## 3.13 8051 子系统",
		"",
		"### 3.13.5 寄存器概述",
		"",
		"| Name | Offset | Description |",
		"| --- | --- | --- |",
		"| rtc_ctrl0 | 0x008 | rtc_ctrl_status1 所在模块的控制寄存器 |",
		"| rtc_ctrl_status0 | 0x00c | rtc_ctrl_status1 的前一个状态寄存器 |",
		"| rtc_ctrl_status1 | 0x010 | rtc_ctrl_status1 |",
		"| rtc_ctrl_status2gpio | 0x014 | rtc_ctrl_status1 之后的状态寄存器 |",
		"",
		"### 3.13.6 寄存器描述",
		"",
		"#### rtc_ctrl0（Offset 0x008）",
		"",
		"| Bits | Name | Access | Description | Reset |",
		"| --- | --- | --- | --- | --- |",
		"| 0 | req_shdn | W1P | 关机请求 |  |",
		"",
		"#### rtc_ctrl_status1（Offset 0x010）",
		"",
		"| Bits | Name | Access | Description | Reset |",
		"| --- | --- | --- | --- | --- |",
		"| 31:0 | rtc_sec_value_o | RO | RTC 秒计数器值 |  |",
		"",
		"#### rtc_ctrl_status2gpio（Offset 0x014）",
		"",
		"| Bits | Name | Access | Description | Reset |",
		"| --- | --- | --- | --- | --- |",
		"| 7:0 | status2gpio_en | R/W | GPIO 状态输出使能 | 0x0 |",
		"",
	}, "\n")
	if err := os.WriteFile(filepath.Join(docsDir, "datasheet", "spec.md"), []byte(overview), 0o644); err != nil {
		t.Fatal(err)
	}
	// 无关文档：确保候选池里不只有目标块
	noise := "# BM1688 SDK\n\n## tpu-mlir 编译模型\n\n先用 model_transform.py 转 MLIR，再生成 bmodel。\n"
	if err := os.WriteFile(filepath.Join(docsDir, "sdk.md"), []byte(noise), 0o644); err != nil {
		t.Fatal(err)
	}
	return docsDir
}

// buildBoostIndex 用 -offline 建 boostDoc 的索引，返回索引目录。
func buildBoostIndex(t *testing.T, dir string) string {
	t.Helper()
	rc := runCtx{
		docsDir:  boostDoc(t, dir),
		indexDir: filepath.Join(dir, "idx"),
		product:  metaProductLabel,
		offline:  true,
		embedF:   failEmbedderFactory(t, "build -offline"),
		rerankF:  failRerankerFactory(t, "build -offline"),
	}
	captureStdout(t, func() {
		if err := runBuild(rc); err != nil {
			t.Fatalf("build -offline: %v", err)
		}
	})
	return rc.indexDir
}

// firstResultLine 取输出里第一条 `### 1 [...]` 行，便于断言第一名。
func firstResultLine(out string) string {
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "### 1 ") {
			return l
		}
	}
	return ""
}

// 核心行为：查询里的标识符命中某块的标题时，该块排第一，
// 即使概览表在 BM25 里得分更高。
func TestIdentifierTitleMatchRanksFirst(t *testing.T) {
	dir := t.TempDir()
	idx := buildBoostIndex(t, dir)

	out := captureStdout(t, func() {
		if err := runQuery(runCtx{
			indexDir: idx, product: metaProductLabel,
			query: "rtc_ctrl_status1", topN: 5, offline: true,
		}); err != nil {
			t.Fatalf("query: %v", err)
		}
	})
	first := firstResultLine(out)
	if first == "" {
		t.Fatalf("no results\n%s", out)
	}
	// 第一名的块必须包含字段表小节，而不是概览表
	body := out[strings.Index(out, first):]
	if !strings.Contains(body, "#### rtc_ctrl_status1（Offset 0x010）") {
		t.Errorf("first result should be the register field table, got:\n%s", out)
	}
	if strings.Contains(body[:min(len(body), 600)], "### 3.13.5 寄存器概述") {
		t.Errorf("first result is the overview table, expected the field table:\n%s", out)
	}
}

// 没有标识符的查询：排序完全由 BM25 决定（第三路为空），与直接取 BM25 top-N 一致。
func TestNoIdentifierKeepsOrdering(t *testing.T) {
	dir := t.TempDir()
	idx := buildBoostIndex(t, dir)

	loaded, err := (&docstore.Store{IndexDir: idx}).Open(metaProductLabel)
	if err != nil {
		t.Fatalf("open index: %v", err)
	}

	// 这些查询都没有合格标识符（无下划线 / 纯数字 / 中文 / 去下划线太短），
	// 因此第三路为空，结果必须与纯 BM25 排名逐项相同。
	queries := []string{"I2C 怎么接", "1080p 分辨率", "寄存器 概述", "rtc 与短词 a_b 都不算标识符"}
	for _, q := range queries {
		if ids := ident.Identifiers(q); len(ids) != 0 {
			t.Fatalf("test query %q unexpectedly contains identifiers %v", q, ids)
		}
		out := captureStdout(t, func() {
			if err := runQuery(runCtx{
				indexDir: idx, product: metaProductLabel,
				query: q, topN: 5, offline: true,
			}); err != nil {
				t.Fatalf("query %q: %v", q, err)
			}
		})
		want := loaded.BM25.Search(q, 5)
		if len(want) == 0 {
			if firstResultLine(out) != "" {
				t.Errorf("query %q: bm25 has no hits but output has results:\n%s", q, out)
			}
			continue
		}
		got := resultLines(out)
		if len(got) != len(want) {
			t.Errorf("query %q: got %d results, bm25 has %d\n%s", q, len(got), len(want), out)
			continue
		}
		for i, w := range want {
			c, ok := loaded.ChunkByID[w.ChunkID]
			if !ok {
				t.Fatalf("bm25 returned unknown chunk %q", w.ChunkID)
			}
			// 结果行形如 `### 1 [0.016] `spect.md:3-20``，用文件+行号确认是同一个块
			expect := "`" + c.SourceFile + ":" + itoa(c.LineStart) + "-" + itoa(c.LineEnd) + "`"
			if !strings.Contains(got[i], expect) {
				t.Errorf("query %q rank %d: got %q, want block %s\n%s", q, i+1, got[i], expect, out)
			}
		}
	}
}

// resultLines 取输出里所有 `### N [...]` 结果行。
func resultLines(out string) []string {
	var lines []string
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "### ") && !strings.HasPrefix(l, "### 3.") && !strings.HasPrefix(l, "### 6.") {
			lines = append(lines, l)
		}
	}
	return lines
}

func itoa(n int) string { return strconv.Itoa(n) }

// -doc-type 过滤时，标题命中块也必须通过过滤：允许 datasheet 时寄存器表可被提权到第一，
// 只允许 sdk 时同一块必须消失。
func TestTitleMatchRespectsDocTypeFilter(t *testing.T) {
	dir := t.TempDir()
	idx := buildBoostIndex(t, dir)
	store := &docstore.Store{IndexDir: idx}

	// 夹具的 spec.md 在 frontmatter 里自述 doc_type: datasheet，
	// sdk.md 没有 frontmatter，由 DocTypeOf 按路径判为 sdk。
	typeOf := func(src string) string {
		if strings.HasSuffix(src, "sdk.md") {
			return "sdk"
		}
		return "datasheet"
	}

	// 只要 datasheet：寄存器字段表应当是第一名
	dsOnly := &retriever.Retriever{Store: store, Filter: &retriever.ChunkFilter{
		Allowed: map[string]bool{"datasheet": true}, DocTypeOf: typeOf,
	}}
	out, err := dsOnly.Search(context.Background(), "rtc_ctrl_status1", metaProductLabel, 5)
	if err != nil {
		t.Fatalf("search datasheet: %v", err)
	}
	if len(out.Results) == 0 {
		t.Fatal("expected datasheet results")
	}
	if !strings.Contains(out.Results[0].Text, "#### rtc_ctrl_status1（Offset 0x010）") {
		t.Errorf("first datasheet result should be the register field table, got %s:%d",
			out.Results[0].SourceFile, out.Results[0].LineStart)
	}

	// 只要 sdk：标题命中的 datasheet 块必须被过滤掉，不能因为提权而漏出来
	sdkOnly := &retriever.Retriever{Store: store, Filter: &retriever.ChunkFilter{
		Allowed: map[string]bool{"sdk": true}, DocTypeOf: typeOf,
	}}
	out, err = sdkOnly.Search(context.Background(), "rtc_ctrl_status1", metaProductLabel, 5)
	if err != nil {
		t.Fatalf("search sdk: %v", err)
	}
	for _, res := range out.Results {
		if strings.Contains(res.Text, "#### rtc_ctrl_status1") {
			t.Errorf("doc-type filter must exclude the title-matched datasheet block, got %s:%d",
				res.SourceFile, res.LineStart)
		}
	}
}

// 多索引：每个索引内部各自做三路融合，再按现有方式合并；标题命中块必须能进入候选，
// 即使它完全不在该索引的 BM25 top-20 里。
func TestMultiIndexTitleMatchEntersCandidates(t *testing.T) {
	dir := t.TempDir()
	// 索引 A：目标寄存器在标题里，但正文几乎没有查询词
	docsA := filepath.Join(dir, "docsA")
	if err := os.MkdirAll(filepath.Join(docsA, "ds"), 0o755); err != nil {
		t.Fatal(err)
	}
	a := "# A 手册\n\n## 寄存器\n\n### rtc_ctrl_status1（Offset 0x010）\n\n| Bits | Name |\n| --- | --- |\n| 31:0 | rtc_sec_value_o |\n"
	if err := os.WriteFile(filepath.Join(docsA, "ds", "a.md"), []byte(a), 0o644); err != nil {
		t.Fatal(err)
	}
	// 索引 B：正文里满是要查的词，标题都不是它
	docsB := filepath.Join(dir, "docsB")
	if err := os.MkdirAll(docsB, 0o755); err != nil {
		t.Fatal(err)
	}
	b := "# B 手册\n\n## 概述\n\nrtc_ctrl_status1 rtc_ctrl_status1 rtc_ctrl_status1 反复出现。\n"
	if err := os.WriteFile(filepath.Join(docsB, "b.md"), []byte(b), 0o644); err != nil {
		t.Fatal(err)
	}

	idxA, idxB := filepath.Join(dir, "idxA"), filepath.Join(dir, "idxB")
	for _, c := range []struct{ docs, idx string }{{docsA, idxA}, {docsB, idxB}} {
		captureStdout(t, func() {
			if rc := dispatch([]string{"build", "-offline", "--docs-dir", c.docs, "-index-dir", c.idx}); rc != 0 {
				t.Fatalf("build %s rc=%d", c.docs, rc)
			}
		})
	}

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idxA, "-index-dir", idxB, "rtc_ctrl_status1"}); rc != 0 {
			t.Fatalf("multi query rc=%d", rc)
		}
	})
	first := firstResultLine(out)
	if !strings.Contains(first, "a.md") {
		t.Errorf("title-matched chunk from index A should rank first across indexes, got %q\n%s", first, out)
	}
}

// 在线路径：rerank 之后标题命中块仍排第一（fake embedder/reranker 保持顺序）。
func TestTitleMatchSurvivesRerank(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "")
	dir := t.TempDir()
	idx := filepath.Join(dir, "idx")
	captureStdout(t, func() {
		if err := runBuild(runCtx{
			docsDir: boostDoc(t, dir), indexDir: idx, product: metaProductLabel,
			useBuiltin: true,
			embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
			rerankF:    func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
		}); err != nil {
			t.Fatalf("build: %v", err)
		}
	})
	out := captureStdout(t, func() {
		if err := runQuery(runCtx{
			indexDir: idx, product: metaProductLabel, query: "rtc_ctrl_status1", topN: 5,
			useBuiltin: true,
			embedF:     func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
			rerankF:    func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
		}); err != nil {
			t.Fatalf("query: %v", err)
		}
	})
	if !strings.Contains(out, "mode=hybrid") {
		t.Fatalf("expected hybrid mode\n%s", out)
	}
	first := firstResultLine(out)
	body := out[strings.Index(out, first):]
	if !strings.Contains(body, "#### rtc_ctrl_status1（Offset 0x010）") {
		t.Errorf("first result should be the field table after rerank:\n%s", out)
	}
	if !regexp.MustCompile(`^### 1 `).MatchString(first) {
		t.Errorf("unexpected first result line: %q", first)
	}
}

// 标题命中但 BM25 里完全没有的块（纯靠标题进候选）也要出现，且得分为正。
func TestTitleMatchChunkOutsideBM25TopK(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 目标块正文只有字段名，不含查询词本身；另有大量含查询词的块把它挤出 BM25 top-3
	target := "# T\n\n## 描述\n\n### rtc_ctrl_status1（Offset 0x010）\n\n| Bits | Name |\n| --- | --- |\n| 31:0 | rtc_sec_value_o |\n"
	if err := os.WriteFile(filepath.Join(docsDir, "target.md"), []byte(target), 0o644); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 10; i++ {
		body := "# N" + string(rune('a'+i)) + "\n\n## 概述\n\nrtc_ctrl_status1 rtc_ctrl_status1 rtc_ctrl_status1 多次出现。\n"
		if err := os.WriteFile(filepath.Join(docsDir, "noise"+string(rune('a'+i))+".md"), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	idx := filepath.Join(dir, "idx")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-offline", "-index-dir", idx, "-top-n", "3", "rtc_ctrl_status1"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "target.md") {
		t.Errorf("title-matched chunk outside bm25 top-k must still be a candidate:\n%s", out)
	}
	first := firstResultLine(out)
	if !strings.Contains(first, "target.md") {
		t.Errorf("title-matched chunk should rank first, got %q\n%s", first, out)
	}
}

// -top-n 必须被遵守（MYS-2661）：有标题命中时，融合结果是两路排名的并集，
// 条数远多于 top-n。修复前这里会返回 8 条。
func TestTopNIsRespectedWithTitleMatch(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 目标块：标题就是标识符（会进第三路）
	target := "# T\n\n## 描述\n\n### rtc_ctrl_status1（Offset 0x010）\n\n| Bits | Name |\n| --- | --- |\n"
	if err := os.WriteFile(filepath.Join(docsDir, "target.md"), []byte(target), 0o644); err != nil {
		t.Fatal(err)
	}
	// 12 个正文满是查询词的块：保证 BM25 预取深度里有多余的名次，融合后条数超 top-n
	for i := 0; i < 12; i++ {
		body := "# N" + itoa(i) + "\n\n## 概述\n\nrtc_ctrl_status1 rtc_ctrl_status1 多次出现。\n"
		if err := os.WriteFile(filepath.Join(docsDir, "noise"+itoa(i)+".md"), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	idx := filepath.Join(dir, "idx")
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	for _, topN := range []int{1, 2, 3} {
		out := captureStdout(t, func() {
			if rc := dispatch([]string{"query", "-offline", "-index-dir", idx,
				"-top-n", itoa(topN), "rtc_ctrl_status1"}); rc != 0 {
				t.Fatalf("query rc=%d", rc)
			}
		})
		// 用输出尾部的 `*N results | …*` 计数：块正文里的 `###` 小节标题也会被
		// 行前缀匹配到，按 `### ` 行数会多算。
		if got := resultCount(out); got != topN {
			t.Errorf("-top-n %d 返回 %d 条，应当恰好 %d 条：\n%s", topN, got, topN, out)
		}
	}
}

// resultCount 从查询输出的尾部摘要行 `*N results | mode=…*` 取结果条数。
func resultCount(out string) int {
	re := regexp.MustCompile(`\*(\d+) results`)
	m := re.FindStringSubmatch(out)
	if m == nil {
		return -1
	}
	n, _ := strconv.Atoi(m[1])
	return n
}

// 多索引的离线路径同样遵守 -top-n（rrfMerge 已按 topM 截断，这里钉住它）。
func TestTopNIsRespectedAcrossIndexes(t *testing.T) {
	dir := t.TempDir()
	var idxs []string
	for n := 0; n < 2; n++ {
		docsDir := filepath.Join(dir, "docs"+itoa(n))
		if err := os.MkdirAll(docsDir, 0o755); err != nil {
			t.Fatal(err)
		}
		for i := 0; i < 6; i++ {
			body := "# D" + itoa(n) + "-" + itoa(i) + "\n\n## 概述\n\nWDT_STAT 寄存器 说明。\n"
			if err := os.WriteFile(filepath.Join(docsDir, "d"+itoa(i)+".md"), []byte(body), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		idx := filepath.Join(dir, "idx"+itoa(n))
		captureStdout(t, func() {
			if rc := dispatch([]string{"build", "-offline", "--docs-dir", docsDir, "-index-dir", idx}); rc != 0 {
				t.Fatalf("build rc=%d", rc)
			}
		})
		idxs = append(idxs, idx)
	}
	args := []string{"query", "-offline", "-top-n", "2"}
	for _, idx := range idxs {
		args = append(args, "-index-dir", idx)
	}
	out := captureStdout(t, func() {
		if rc := dispatch(append(args, "WDT_STAT 寄存器")); rc != 0 {
			t.Fatalf("multi query rc=%d", rc)
		}
	})
	if got := resultCount(out); got != 2 {
		t.Errorf("多索引 -top-n 2 返回 %d 条，应当恰好 2 条：\n%s", got, out)
	}
}
