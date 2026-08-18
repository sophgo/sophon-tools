package vector

import "testing"

func TestNormalizeUnitLength(t *testing.T) {
	v := Normalize([]float32{3, 4})
	n := v[0]*v[0] + v[1]*v[1]
	if n < 0.99 || n > 1.01 {
		t.Fatalf("unit norm = %v want ~1", n)
	}
}

func TestNormalizeZeroVectorCopy(t *testing.T) {
	// 零向量：返回同 len 的副本而非输入别名，修改返回值不得影响原切片
	z := []float32{0, 0}
	out := Normalize(z)
	if len(out) != 2 {
		t.Fatalf("len(out) = %d want 2", len(out))
	}
	out[0] = 1
	if z[0] != 0 {
		t.Fatal("Normalize returned alias of input on zero vector")
	}
}

func TestFlatIPFindMostSimilar(t *testing.T) {
	idx := &Index{Dim: 4}
	idx.Add(Normalize([]float32{1, 0, 0, 0}), "c0")
	idx.Add(Normalize([]float32{0, 1, 0, 0}), "c1")
	res := idx.Search(Normalize([]float32{0.9, 0.1, 0, 0}), 2)
	if len(res) != 2 || res[0].ChunkID != "c0" {
		t.Fatalf("expected c0 first, got %+v", res)
	}
}

func TestVectorRoundTrip(t *testing.T) {
	idx := &Index{Dim: 2}
	idx.Add([]float32{1, 0}, "c0")
	data := idx.Serialize()
	blk, err := Load(data)
	if err != nil {
		t.Fatal(err)
	}
	if blk.Search([]float32{1, 0}, 1)[0].ChunkID != "c0" {
		t.Error("round-trip search mismatch")
	}
}
