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
