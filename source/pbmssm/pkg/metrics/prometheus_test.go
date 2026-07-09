package metrics

import (
	"testing"

	"github.com/prometheus/client_golang/prometheus"
	promdto "github.com/prometheus/client_model/go"
)

func TestNewMetricsRegistry(t *testing.T) {
	r := NewMetricsRegistry()
	t.Cleanup(func() {
		prometheus.Unregister(r.NumDevices)
		for _, g := range []prometheus.Collector{
			r.SystemMemoryTotal, r.SystemMemoryUsed, r.SystemMemoryFree,
			r.VppMemoryTotal, r.VppMemoryUsed,
			r.VpuMemoryTotal, r.VpuMemoryUsed,
			r.TpuMemoryTotal, r.TpuMemoryUsed,
			r.DeviceMemoryTotal, r.DeviceMemoryUsed,
			r.CPUUsage, r.TPUUsage, r.TPUAvgUsage,
			r.VPUEncUsage, r.VPUDecUsage, r.VPUEncLinks, r.VPUDecLinks,
			r.VPPUsage, r.JPUUsage,
			r.ChipTemp, r.BoardTemp, r.FanSpeed, r.PowerUsage,
			r.HealthStatus, r.ChipInfo,
		} {
			prometheus.Unregister(g)
		}
	})
	if r == nil {
		t.Fatal("NewMetricsRegistry returned nil")
	}
	if r.NumDevices == nil {
		t.Error("NumDevices not created")
	}
	if r.SystemMemoryTotal == nil {
		t.Error("SystemMemoryTotal not created")
	}
	if r.ChipInfo == nil {
		t.Error("ChipInfo not created")
	}
}

func TestMetricsRegistryUpdateAndReset(t *testing.T) {
	r := NewMetricsRegistry()
	t.Cleanup(func() {
		prometheus.Unregister(r.NumDevices)
		for _, g := range []prometheus.Collector{
			r.SystemMemoryTotal, r.SystemMemoryUsed, r.SystemMemoryFree,
			r.VppMemoryTotal, r.VppMemoryUsed,
			r.VpuMemoryTotal, r.VpuMemoryUsed,
			r.TpuMemoryTotal, r.TpuMemoryUsed,
			r.DeviceMemoryTotal, r.DeviceMemoryUsed,
			r.CPUUsage, r.TPUUsage, r.TPUAvgUsage,
			r.VPUEncUsage, r.VPUDecUsage, r.VPUEncLinks, r.VPUDecLinks,
			r.VPPUsage, r.JPUUsage,
			r.ChipTemp, r.BoardTemp, r.FanSpeed, r.PowerUsage,
			r.HealthStatus, r.ChipInfo,
		} {
			prometheus.Unregister(g)
		}
	})
	dev := DeviceLabels{
		DeviceID: "0", Model: "SE5", Serial: "SN123",
		ChipType: "BM1684", BoardType: "0x10",
	}
	hw := &HardwareMetrics{
		SystemMemoryTotal: 8 * 1024 * 1024 * 1024,
		SystemMemoryUsed:  4 * 1024 * 1024 * 1024,
		SystemMemoryFree:  4 * 1024 * 1024 * 1024,
		CPUUsage:          42,
		TPUUsage:          75,
		TPUAvgUsage:       70,
		ChipTemp:          55.5,
		BoardTemp:         48.2,
		FanSpeed:          3000,
		PowerUsage:        12.5,
		HealthStatus:      1,
		DeviceMemoryTotal: 16 * 1024 * 1024 * 1024,
		DeviceMemoryUsed:  4 * 1024 * 1024 * 1024,
	}
	r.Update(hw, dev)
	r.SetDeviceCount(1)

	// Gather metrics and verify one gauge has expected value
	mfs, err := prometheus.DefaultGatherer.Gather()
	if err != nil {
		t.Fatalf("gather failed: %v", err)
	}
	find := func(families []*promdto.MetricFamily, name string) *promdto.MetricFamily {
		for _, mf := range families {
			if mf.GetName() == name {
				return mf
			}
		}
		return nil
	}
	mf := find(mfs, "sophon_cpu_usage_percent")
	if mf == nil {
		t.Fatal("sophon_cpu_usage_percent not found in gathered metrics")
	}
	if len(mf.Metric) == 0 {
		t.Fatal("no metrics in sophon_cpu_usage_percent")
	}
	labels := mf.Metric[0].GetLabel()
	if len(labels) != 5 {
		t.Errorf("expected 5 labels, got %d", len(labels))
	}

	r.Reset()
	mfs2, _ := prometheus.DefaultGatherer.Gather()
	mf2 := find(mfs2, "sophon_cpu_usage_percent")
	if mf2 != nil && len(mf2.Metric) > 0 {
		t.Errorf("after reset, expected gone but found %d data-points", len(mf2.Metric))
	}
	_ = mfs2
}

func TestLabelsForDevice(t *testing.T) {
	d := DeviceLabels{DeviceID: "0", Model: "SE7", Serial: "ABC", ChipType: "BM1684X", BoardType: "3"}
	got := labelsForDevice(d)
	if len(got) != 5 || got[0] != "0" || got[3] != "BM1684X" {
		t.Errorf("labelsForDevice = %v, want [0 SE7 ABC BM1684X 3]", got)
	}
}
