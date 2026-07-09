package metrics

import "testing"

func TestVPUUsageBM1684X(t *testing.T) {
	// BM1684X: 3 entries, enc at index 2 (last). Rust: enc=percentages[2], dec=avg([0..2]).
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
		"/proc/vpuinfo": `{"dec_0": {"link_num":5, "usage":20%}
{"dec_1": {"link_num":7, "usage":10%}
{"enc": {"link_num":12, "usage":30%}`,
	}}
	c := NewCollector(fr, nil)
	enc, dec, encLinks, decLinks, ok := c.VPUUsage()
	if !ok {
		t.Fatal("VPUUsage() returned ok=false for bm1684x")
	}
	if enc != 30 || dec != 15 {
		t.Errorf("VPUUsage enc=%d dec=%d, want enc=30 dec=15", enc, dec)
	}
	if encLinks != 12 || decLinks != 12 {
		t.Errorf("VPUUsage links enc=%d dec=%d, want enc=12 dec=12", encLinks, decLinks)
	}
}

func TestVPUUsageBM1688(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo":          "model name	: BM1688\n",
		"/proc/soph/vpuinfo": `{"enc": {"link_num":3, "usage":40%}
{"dec_0": {"link_num":2, "usage":50%}
{"dec_1": {"link_num":4, "usage":60%}`,
	}}
	c := NewCollector(fr, nil)
	enc, dec, encLinks, decLinks, ok := c.VPUUsage()
	if !ok {
		t.Fatal("VPUUsage() returned ok=false for bm1688")
	}
	if enc != 40 || dec != 55 {
		t.Errorf("VPUUsage enc=%d dec=%d, want 40/55", enc, dec)
	}
	if encLinks != 3 || decLinks != 6 {
		t.Errorf("VPUUsage links enc=%d dec=%d, want 3/6", encLinks, decLinks)
	}
}

func TestVPUUsageMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
		// vpuinfo 缺失
	}}
	c := NewCollector(fr, nil)
	_, _, _, _, ok := c.VPUUsage()
	if ok {
		t.Error("VPUUsage() should return ok=false when vpuinfo is missing")
	}
}

func TestVPPUsage(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
		"/proc/vppinfo": "30%|########\n50%|##########\n70%|########",
	}}
	c := NewCollector(fr, nil)
	got := c.VPPUsage()
	if got != 50 {
		t.Errorf("VPPUsage() = %d, want 50 (avg of 30,50,70)", got)
	}
}

func TestVPPUsageMissing(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.VPPUsage(); got != 0 {
		t.Errorf("VPPUsage() = %d, want 0 when missing", got)
	}
}

func TestJPUUsage(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
		"/proc/jpuinfo": "25%|#####\n75%|###############",
	}}
	c := NewCollector(fr, nil)
	got := c.JPUUsage()
	if got != 50 {
		t.Errorf("JPUUsage() = %d, want 50 (avg of 25,75)", got)
	}
}
