package titlematch

import (
	"testing"

	"se-rag-core/internal/chunker"
)

func chunk(id, text string) chunker.Chunk {
	return chunker.Chunk{ChunkID: id, Text: text}
}

// 排序规则：命中标识符个数降序 → 标题越短越靠前 → 原块序。
func TestRankOrdering(t *testing.T) {
	chunks := []chunker.Chunk{
		// 概览表：标题里没有标识符，不该命中本路（靠 BM25/向量去打分）
		chunk("overview", "【3 系统概述】\n### 3.13.5 寄存器概述\n| rtc_ctrl_status1 | 0x010 |\n"),
		// 标题短、精确命中
		chunk("exact", "【祖先】\n#### rtc_ctrl_status1（Offset 0x010）\n| 31:0 | x |\n"),
		// 标题长一些，同样命中
		chunk("longer", "【祖先】\n#### rtc_ctrl_status1 这个寄存器在某模块下的完整描述章节（Offset 0x010）\n字段表\n"),
		// 命中两个标识符 → 排最前
		chunk("two", "【祖先】\n#### rtc_ctrl_status1 与 wdt_stat 对比（Offset 0x010）\n"),
	}
	got := Rank(chunks, []string{"rtc_ctrl_status1", "wdt_stat"})
	want := []string{"two", "exact", "longer"}
	if len(got) != len(want) {
		t.Fatalf("Rank got %d hits (%+v), want %d", len(got), got, len(want))
	}
	for i := range want {
		if got[i].ChunkID != want[i] {
			t.Errorf("rank %d = %q, want %q (full: %+v)", i, got[i].ChunkID, want[i], got)
		}
	}
	// 命中个数与标题长度都要真实反映
	if got[0].Matched != 2 {
		t.Errorf("two should match 2 idents, got %d", got[0].Matched)
	}
	if got[1].Matched != 1 || got[2].Matched != 1 {
		t.Errorf("single-ident hits should report Matched=1, got %d and %d", got[1].Matched, got[2].Matched)
	}
	if got[1].TitleLen >= got[2].TitleLen {
		t.Errorf("shorter title should rank first: exact=%d longer=%d", got[1].TitleLen, got[2].TitleLen)
	}
}

// 没有标识符、或没有任何标题命中时返回空——调用方据此跳过第三路。
func TestRankNoHits(t *testing.T) {
	chunks := []chunker.Chunk{
		chunk("a", "### rtc_ctrl_status1\n"),
		chunk("b", "### 其他章节\n"),
	}
	if got := Rank(chunks, nil); len(got) != 0 {
		t.Errorf("no identifiers should yield no hits, got %+v", got)
	}
	if got := Rank(chunks, []string{"wdt_stat"}); len(got) != 0 {
		t.Errorf("unmatched identifier should yield no hits, got %+v", got)
	}
	if got := Rank(nil, []string{"rtc_ctrl_status1"}); len(got) != 0 {
		t.Errorf("no chunks should yield no hits, got %+v", got)
	}
}

// 只匹配标题，不匹配正文：概览表正文里满是寄存器名，但它不是以该名字命名的节。
func TestRankTitleOnlyNotBody(t *testing.T) {
	chunks := []chunker.Chunk{
		chunk("body-only", "【概述】\n### 寄存器概览\n| rtc_ctrl_status1 | 0x010 |\n| wdt_stat | 0x010 |\n"),
	}
	if got := Rank(chunks, []string{"rtc_ctrl_status1"}); len(got) != 0 {
		t.Errorf("body occurrences must not count as title match, got %+v", got)
	}
}

// 大小写不敏感：标题大写、查询小写（反之亦然）都算命中。
func TestRankCaseInsensitive(t *testing.T) {
	chunks := []chunker.Chunk{chunk("c", "【祖先】\n#### WDT_STAT（Offset 0x010）\n")}
	for _, q := range []string{"wdt_stat", "WDT_STAT", "Wdt_Stat"} {
		got := Rank(chunks, []string{q})
		if len(got) != 1 {
			t.Errorf("query %q should hit WDT_STAT title, got %+v", q, got)
		}
	}
}

// 上限 20 个候选，即使命中更多也截断。
func TestRankCapsAtMaxCandidates(t *testing.T) {
	var chunks []chunker.Chunk
	for i := 0; i < 50; i++ {
		chunks = append(chunks, chunk(string(rune('a'+i%26))+string(rune('0'+i/26)), "#### rtc_ctrl_status1\n"))
	}
	got := Rank(chunks, []string{"rtc_ctrl_status1"})
	if len(got) != MaxCandidates {
		t.Errorf("Rank returned %d hits, want %d", len(got), MaxCandidates)
	}
}

// 同一标题里重复出现同一标识符只算一个命中（匹配的是"命中了哪些标识符"，不是次数）。
func TestRankDedupesIdentifierCount(t *testing.T) {
	chunks := []chunker.Chunk{
		chunk("dup", "#### rtc_ctrl_status1\n#### rtc_ctrl_status1 又一节\n"),
		chunk("mixed", "#### rtc_ctrl_status1 与 wdt_stat\n"),
	}
	got := Rank(chunks, []string{"rtc_ctrl_status1", "wdt_stat"})
	if len(got) != 2 {
		t.Fatalf("expected 2 hits, got %+v", got)
	}
	// mixed 命中 2 个标识符，必须排第一（重复出现不等于命中更多标识符）
	if got[0].ChunkID != "mixed" {
		t.Errorf("chunk matching 2 distinct idents must rank first, got %+v", got)
	}
	if got[0].Matched != 2 || got[1].Matched != 1 {
		t.Errorf("Matched counts wrong: %+v", got)
	}
}

// Ranked 转换保持顺序，供 RRF 使用。
func TestRankedPreservesOrder(t *testing.T) {
	hits := []Hit{{ChunkID: "x"}, {ChunkID: "y"}, {ChunkID: "z"}}
	r := Ranked(hits)
	if len(r) != 3 {
		t.Fatalf("got %d ranked, want 3", len(r))
	}
	for i, want := range []string{"x", "y", "z"} {
		if r[i].ChunkID != want {
			t.Errorf("ranked[%d] = %q, want %q", i, r[i].ChunkID, want)
		}
	}
}
