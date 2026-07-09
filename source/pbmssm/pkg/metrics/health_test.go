package metrics

import "testing"

func TestHealthStatusHealthy(t *testing.T) {
	c := NewCollector(nil, nil)
	if !c.HealthStatus(50.0, 40.0) {
		t.Error("HealthStatus(50,40) = unhealthy, want healthy")
	}
}

func TestHealthStatusUnhealthyChip(t *testing.T) {
	c := NewCollector(nil, nil)
	if c.HealthStatus(90.0, 40.0) {
		t.Error("HealthStatus(90,40) = healthy, want unhealthy (chip over 85)")
	}
}

func TestHealthStatusUnhealthyBoard(t *testing.T) {
	c := NewCollector(nil, nil)
	if c.HealthStatus(50.0, 86.0) {
		t.Error("HealthStatus(50,86) = healthy, want unhealthy (board over 85)")
	}
}
