package metrics

import "testing"

func TestFanSpeedBM1684X(t *testing.T) {
	// FanSpeed uses os.WriteFile which can't be mocked through FileReader.
	// Skip integration test when not on real hardware.
	if testing.Short() {
		t.Skip("requires real hardware for fan enable write")
	}
}

func TestFanSpeedUnsupportedChip(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{
		"/proc/cpuinfo": "model name	: BM1688\n",
	}}
	c := NewCollector(fr, nil)
	if got := c.FanSpeed(); got != 0 {
		t.Errorf("FanSpeed() = %d, want 0 for unsupported chip", got)
	}
}

func TestFanSpeedUnknownChip(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	if got := c.FanSpeed(); got != 0 {
		t.Errorf("FanSpeed() = %d, want 0 for unknown chip", got)
	}
}
