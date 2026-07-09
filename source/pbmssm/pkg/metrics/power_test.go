package metrics

import "testing"

func TestPowerUsageUnsupportedChip(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: BM1688\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.PowerUsage(); got != 0 {
		t.Errorf("PowerUsage() = %f, want 0 for unsupported chip", got)
	}
}

func TestPowerUsageBm1684X(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"which":  {out: "/usr/sbin/i2cget"},
		"i2cget": {out: "0x0f"},
	}}
	c := NewCollector(fr, cmd)
	got := c.PowerUsage()
	// hi=0x0f=15, lo=0x0f=15, (15*256+15)/1000 = 3.855
	want := float64(15*256+15) / 1000.0
	if got != want {
		t.Errorf("PowerUsage() = %f, want %f", got, want)
	}
}

func TestPowerUsageNoI2cget(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: bm1684x\n",
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"which": {err: errSome},
	}}
	c := NewCollector(fr, cmd)
	if got := c.PowerUsage(); got != 0 {
		t.Errorf("PowerUsage() = %f, want 0 when i2cget missing", got)
	}
}
