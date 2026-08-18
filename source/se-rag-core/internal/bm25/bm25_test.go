package bm25

import (
	"strings"
	"testing"
)

func TestTokenizeFiltersStopwords(t *testing.T) {
	got := Tokenize("SE7 的 系统 使用 BM1684X 芯片")
	joined := strings.Join(got, " ")
	for _, want := range []string{"se7", "bm1684x"} {
		if !strings.Contains(joined, want) {
			t.Errorf("want token %q in %v", want, got)
		}
	}
	if strings.Contains(joined, "的") {
		t.Errorf("stopword 的 not filtered: %v", got)
	}
	if !strings.Contains(joined, "系统") {
		t.Errorf("content token 系统 should be kept, got: %v", got)
	}
}

// 中文连续子串按 2-gram 滑窗切分："配置网络" → "配置" "置网" "网络"（精确 token 比对，非子串包含）。
func TestTokenizeChineseBigram(t *testing.T) {
	got := Tokenize("配置网络")
	m := mEN(got)
	for _, want := range []string{"配置", "网络", "置网"} {
		if !m[want] {
			t.Errorf("want 2-gram token %q in %v", want, got)
		}
	}
	if len(got) == 0 {
		t.Fatal("expected non-empty tokens")
	}
	// 英文/数字 token 保持原样，不被 bigram 切分
	gotEn := mEN(Tokenize("SE7 BM1684X 芯片"))
	for _, want := range []string{"se7", "bm1684x"} {
		if !gotEn[want] {
			t.Errorf("want alnum token %q in %v", want, got)
		}
	}
}

func mEN(toks []string) map[string]bool {
	m := map[string]bool{}
	for _, w := range toks {
		m[w] = true
	}
	return m
}

// 中文查询片段比文档更长（无法整体命中原样子串）也应命中：bigram 滑窗保证片段重叠。
func TestBM25ChineseSubstringMatch(t *testing.T) {
	docs := []string{"本篇介绍如何配置网络服务", "OTA 升级 用于 更新 系统 镜像"}
	idx := Build(docs, []string{"c0", "c1"})
	got := idx.Search("配置网络", 3)
	if len(got) == 0 {
		t.Fatal("expected results for substring query")
	}
	if got[0].ChunkID != "c0" {
		t.Errorf("top hit = %s want c0 (got: %+v)", got[0].ChunkID, got)
	}
}

func TestBM25Ordering(t *testing.T) {
	docs := []string{
		"BM1684X 支持 PCIE 主机模式",
		"SE7 使用 BM1684X 芯片 运行 推理 任务",
		"OTA 升级 用于 系统 镜像 更新 功能",
	}
	idx := Build(docs, []string{"c0", "c1", "c2"})
	got := idx.Search("BM1684X 芯片", 3)
	if len(got) == 0 {
		t.Fatal("expected results")
	}
	if got[0].ChunkID != "c1" {
		t.Errorf("top hit = %s want c1 (got: %+v)", got[0].ChunkID, got)
	}
}

func TestBM25RoundTrip(t *testing.T) {
	docs := []string{"SE7 TPU 内存", "BM1684X SDK 版本"}
	idx := Build(docs, []string{"c0", "c1"})
	data := idx.Serialize()
	loaded, err := Load(data)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if loaded.DocCount() != 2 {
		t.Errorf("DocCount = %d want 2", loaded.DocCount())
	}
	r := loaded.Search("TPU", 2)
	if len(r) == 0 || r[0].ChunkID != "c0" {
		t.Errorf("search after round-trip mismatch: %+v", r)
	}
}

func TestTFPrecomputedMatchesScanFallback(t *testing.T) {
	// 同一查询预统计与全量扫描回退（TF=nil，模拟旧格式索引）结果必须一致。
	docs := []string{
		"SE7 SE7 SE7 芯片",
		"BM1684X SDK 版本 SDK",
		"SE7 与 BM1684X 协同工作 SE7",
	}
	idx := Build(docs, []string{"c0", "c1", "c2"})
	pre := idx.Search("SE7 SDK", 5)
	if len(pre) == 0 {
		t.Fatal("no results with precomputed tf")
	}
	if idx.TF == nil {
		t.Fatal("Build should populate TF")
	}
	legacy := *idx
	legacy.TF = nil // 模拟旧索引（gob 无 TF 字段）
	back := legacy.Search("SE7 SDK", 5)
	if len(back) != len(pre) {
		t.Fatalf("fallback results %d != precomputed %d", len(back), len(pre))
	}
	for i := range pre {
		if pre[i].ChunkID != back[i].ChunkID || pre[i].Score != back[i].Score {
			t.Errorf("rank %d: precomputed %+v != fallback %+v", i, pre[i], back[i])
		}
	}
}
