package fusion

import (
	"testing"
)

func TestRRFCombinesTwoRanks(t *testing.T) {
	faiss := []Ranked{{"a", 0.9}, {"b", 0.8}, {"c", 0.7}}
	bm25 := []Ranked{{"b", 0.9}, {"c", 0.8}, {"d", 0.7}}
	got := RRF(faiss, bm25, 60)
	if len(got) == 0 || got[0].ChunkID != "b" {
		t.Fatalf("expected b first, got %+v", got)
	}
}

func TestRRFReturnsAllDistinct(t *testing.T) {
	faiss := []Ranked{{"a", 1}, {"b", 2}}
	bm25 := []Ranked{{"c", 3}}
	got := RRF(faiss, bm25, 60)
	if len(got) != 3 {
		t.Fatalf("expected 3 distinct, got %d", len(got))
	}
}

func TestRRFScoreMonotonic(t *testing.T) {
	// 单纯交集：b 在两边 rank0，得分应高于只在一边的 a
	faiss := []Ranked{{"b", 1}}
	bm25 := []Ranked{{"b", 1}, {"a", 0.1}}
	got := RRF(faiss, bm25, 60)
	if got[0].ChunkID != "b" {
		t.Fatalf("expected b first, got %+v", got)
	}
}
