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

// 三路全部 weight=1 时必须与旧的两路 RRF 逐项相同（保证"无标识符时结果不变"）。
func TestRRFWeightedAllUnitEqualsRRF(t *testing.T) {
	faiss := []Ranked{{"a", 0.9}, {"b", 0.8}, {"c", 0.7}}
	bm25 := []Ranked{{"b", 0.9}, {"c", 0.8}, {"d", 0.7}}
	want := RRF(faiss, bm25, 60)
	got := RRFWeighted([]Path{
		{Ranked: faiss, Weight: 1},
		{Ranked: bm25, Weight: 1},
		{Ranked: nil, Weight: 1}, // 空的第三路（查询无标识符时就是这个形态）
	}, 60)
	if len(got) != len(want) {
		t.Fatalf("got %d results, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i].ChunkID != want[i].ChunkID || got[i].Score != want[i].Score {
			t.Errorf("item %d = %+v, want %+v", i, got[i], want[i])
		}
	}
}

// weight ≤ 0 按 1 处理（不改变旧行为）。
func TestRRFWeightedZeroWeightTreatedAsOne(t *testing.T) {
	a := []Ranked{{ChunkID: "x"}}
	got := RRFWeighted([]Path{{Ranked: a, Weight: 0}}, 60)
	want := RRF(a, nil, 60)
	if len(got) != 1 || got[0].Score != want[0].Score {
		t.Errorf("weight 0 should behave as 1: got %+v, want %+v", got, want)
	}
}

// 第三路权重 2：只被标题路排第 1 的块，要压过同时被两路排第 1 的块。
func TestRRFWeightedTitlePathWins(t *testing.T) {
	overview := "overview" // 向量 + BM25 都排第 1（内容相似度高）
	fieldTable := "field"  // 只有标题路命中，且排第 1
	vec := []Ranked{{overview, 0.9}}
	bm := []Ranked{{overview, 10.0}}
	title := []Ranked{{fieldTable, 0}}

	// 不加权（全部 1）：overview 拿两路得分，稳居第一
	plain := RRFWeighted([]Path{
		{Ranked: vec, Weight: 1},
		{Ranked: bm, Weight: 1},
		{Ranked: title, Weight: 1},
	}, 60)
	if plain[0].ChunkID != overview {
		t.Fatalf("with unit weights the doubly-matched chunk should lead, got %+v", plain)
	}

	// 标题路权重 2：field 翻到第一
	boosted := RRFWeighted([]Path{
		{Ranked: vec, Weight: 1},
		{Ranked: bm, Weight: 1},
		{Ranked: title, Weight: 2},
	}, 60)
	if boosted[0].ChunkID != fieldTable {
		t.Errorf("title path weight 2 should put %q first, got %+v", fieldTable, boosted)
	}
}

// 权重精确生效：score = weight/(k+rank+1)。
func TestRRFWeightedExactScores(t *testing.T) {
	got := RRFWeighted([]Path{
		{Ranked: []Ranked{{ChunkID: "a"}}, Weight: 2},
		{Ranked: []Ranked{{ChunkID: "a"}}, Weight: 1},
	}, 60)
	if len(got) != 1 {
		t.Fatalf("expected 1 result, got %+v", got)
	}
	want := 3.0 / 61.0 // 同一块在两路都是 rank 0
	if diff := got[0].Score - want; diff > 1e-12 || diff < -1e-12 {
		t.Errorf("score = %v, want %v", got[0].Score, want)
	}
}
