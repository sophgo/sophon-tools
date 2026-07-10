package compat

import (
	"os"
	"testing"

	"bmssm/config"
	"bmssm/global"
	"bmssm/pkg/metrics"
)

// fakeMetrics 测试用 MetricProvider，返回夹具预置值。
type fakeMetrics struct {
	os         string
	rt         string
	sdk        string
	cpu        metrics.CPU
	mem        metrics.Memory
	disks      []metrics.Disk
	nets       []metrics.NetCard
	chipT      int
	boardT     int
	tpuU       int
	tpuMem     float64
	memLayout  metrics.MemoryLayout
	diskLayout metrics.DiskLayout
}

func (f *fakeMetrics) OSVersion() string           { return f.os }
func (f *fakeMetrics) Runtime() string             { return f.rt }
func (f *fakeMetrics) SdkVersion() string          { return f.sdk }
func (f *fakeMetrics) CPUInfo() metrics.CPU        { return f.cpu }
func (f *fakeMetrics) Memory() metrics.Memory      { return f.mem }
func (f *fakeMetrics) Disks() []metrics.Disk       { return f.disks }
func (f *fakeMetrics) NetCards() []metrics.NetCard { return f.nets }
func (f *fakeMetrics) ChipTemp() int               { return f.chipT }
func (f *fakeMetrics) BoardTemp() int              { return f.boardT }
func (f *fakeMetrics) TPUUsage() int               { return f.tpuU }
func (f *fakeMetrics) TPUMem() float64             { return f.tpuMem }
func (f *fakeMetrics) MemoryLayout() metrics.MemoryLayout {
	return f.memLayout
}
func (f *fakeMetrics) DiskLayout() metrics.DiskLayout {
	return f.diskLayout
}

// defaultFakeMetrics 返回真机夹具值（SE7 / BM1684X）。
func defaultFakeMetrics() *fakeMetrics {
	return &fakeMetrics{
		os:     "Ubuntu 20.04 LTS",
		rt:     "91:45:41",
		sdk:    "23.09 LTS",
		cpu:    metrics.CPU{Frequency: 2300, Cores: 8, UtilizationRate: 1.25, Type: "bm1684x", Arch: "aarch64"},
		mem:    metrics.Memory{Total: 6277, Free: 3586, Available: 5781},
		disks:  []metrics.Disk{{DiskName: "/dev/mmcblk0p7", Total: 93750, Free: 83984, MountOn: "/data"}},
		nets:   []metrics.NetCard{{Name: "eth0", IP: "192.168.1.100", Mask: "255.255.255.0", Mac: "00:11:22:33:44:55", Bandwidth: 1000, NetTx: 123456, NetRx: 654321}},
		chipT:  39,
		boardT: 42,
		tpuU:   0,
		tpuMem: 3950,
		memLayout: metrics.MemoryLayout{
			ChipType: "bm1684x",
			System:   metrics.MemRegion{TotalMB: 6277, UsedMB: 2691, UsagePct: 42.875824},
			TPU:      metrics.MemRegion{TotalMB: 2414, UsedMB: 0, UsagePct: 0},
			VPU:      metrics.MemRegion{TotalMB: 2943, UsedMB: 0, UsagePct: 0},
			VPP:      metrics.MemRegion{TotalMB: 3072, UsedMB: 0, UsagePct: 0},
		},
		diskLayout: metrics.DiskLayout{
			EmmcOverall: metrics.MemRegion{TotalMB: 27866, UsedMB: 5297, UsagePct: 19.0},
			Partitions: []metrics.DiskPart{
				{Device: "/dev/mmcblk0p1", MountOn: "/boot", MemRegion: metrics.MemRegion{TotalMB: 128, UsedMB: 20, UsagePct: 15.6}},
				{Device: "/dev/mmcblk0p2", MountOn: "/recovery", MemRegion: metrics.MemRegion{TotalMB: 104, UsedMB: 20, UsagePct: 19.7}},
				{Device: "/dev/mmcblk0p5", MountOn: "/media/root-rw", MemRegion: metrics.MemRegion{TotalMB: 8481, UsedMB: 1427, UsagePct: 16.8}},
				{Device: "/dev/mmcblk0p6", MountOn: "/data", MemRegion: metrics.MemRegion{TotalMB: 16355, UsedMB: 1165, UsagePct: 7.1}},
			},
		},
	}
}

// withGlobals 设置并返回 global 设备字段（测试后由调用方 defer 恢复）。
func setDeviceGlobals(t *testing.T) func() {
	origChipSn := global.ChipSn
	origDeviceSnEx := global.DeviceSnEx
	origDeviceTypeEx := global.DeviceTypeEx
	origDeviceType := global.DeviceType
	origModuleType := global.ModuleType
	global.ChipSn = "EC712AC0C24120073"
	global.DeviceSnEx = "HQATEVBAIAIAI0001"
	global.DeviceTypeEx = "SE7 V1"
	global.DeviceType = "soc"
	global.ModuleType = "BM1684X"
	return func() {
		global.ChipSn = origChipSn
		global.DeviceSnEx = origDeviceSnEx
		global.DeviceTypeEx = origDeviceTypeEx
		global.DeviceType = origDeviceType
		global.ModuleType = origModuleType
	}
}

// ---------------------------------------------------------------
// BuildCtrlBasic System 字段来自 metrics
// ---------------------------------------------------------------

func TestBuildCtrlBasicSystemFields(t *testing.T) {
	_ = os.Setenv("BMSSM_CONF", t.TempDir())
	config.LoadConfig()
	restore := setDeviceGlobals(t)
	defer restore()

	svc := NewCompatServiceWith(defaultFakeMetrics())
	basic, err := svc.BuildCtrlBasic()
	if err != nil {
		t.Fatalf("BuildCtrlBasic failed: %v", err)
	}

	if basic.System.OperatingSystem != "Ubuntu 20.04 LTS" {
		t.Errorf("System.OperatingSystem = %q, want Ubuntu 20.04 LTS", basic.System.OperatingSystem)
	}
	if basic.System.Runtime != "91:45:41" {
		t.Errorf("System.Runtime = %q, want 91:45:41 (H:MM:SS)", basic.System.Runtime)
	}
	if basic.System.SdkVersion != "23.09 LTS" {
		t.Errorf("System.SdkVersion = %q, want 23.09 LTS", basic.System.SdkVersion)
	}
	if basic.System.BmssmVersion == "" {
		t.Error("System.BmssmVersion should be non-empty (global.Version)")
	}
	if basic.System.BuildTime == "" {
		t.Error("System.BuildTime should be non-empty (ldflags injected)")
	}
	// DeviceType/DeviceTypeEx 仍来自 global
	if basic.System.DeviceType != "soc" {
		t.Errorf("System.DeviceType = %q, want soc", basic.System.DeviceType)
	}
	if basic.System.DeviceTypeEx != "SE7 V1" {
		t.Errorf("System.DeviceTypeEx = %q, want SE7 V1", basic.System.DeviceTypeEx)
	}
}

// ---------------------------------------------------------------
// BuildCtrlResource 用 metrics 真值填充
// ---------------------------------------------------------------

func TestBuildCtrlResourceMetrics(t *testing.T) {
	restore := setDeviceGlobals(t)
	defer restore()

	svc := NewCompatServiceWith(defaultFakeMetrics())
	res := svc.BuildCtrlResource()
	if len(res) != 1 {
		t.Fatalf("BuildCtrlResource len = %d, want 1", len(res))
	}
	r := res[0]

	// 顶层
	if r.DeviceSn != "HQATEVBAIAIAI0001" {
		t.Errorf("DeviceSn = %q, want HQATEVBAIAIAI0001", r.DeviceSn)
	}
	if r.DeviceModel != "SE7 V1" {
		t.Errorf("DeviceModel = %q, want SE7 V1", r.DeviceModel)
	}
	// DeviceType 展示用截取后的型号主体（"SE7 V1" → "SE7"），完整型号在 DeviceModel。
	if r.DeviceType != "SE7" {
		t.Errorf("DeviceType = %q, want SE7", r.DeviceType)
	}
	if r.CollectDateTime == "" {
		t.Error("CollectDateTime should be non-empty")
	}

	// CPU
	cpu := r.CentralProcessingUnit.Cpu
	if cpu.Frequency != 2300 {
		t.Errorf("CPU.Frequency = %d, want 2300", cpu.Frequency)
	}
	if cpu.Cores != 8 {
		t.Errorf("CPU.Cores = %v, want 8", cpu.Cores)
	}
	if cpu.UtilizationRate != 1.25 {
		t.Errorf("CPU.UtilizationRate = %v, want 1.25", cpu.UtilizationRate)
	}
	if cpu.Type != "bm1684x" {
		t.Errorf("CPU.Type = %q, want bm1684x", cpu.Type)
	}
	if cpu.Arch != "aarch64" {
		t.Errorf("CPU.Arch = %q, want aarch64", cpu.Arch)
	}

	// Memory
	mem := r.CentralProcessingUnit.Memory
	if mem.Total != 6277 {
		t.Errorf("Memory.Total = %v, want 6277", mem.Total)
	}
	if mem.Free != 3586 {
		t.Errorf("Memory.Free = %v, want 3586", mem.Free)
	}
	if mem.Available != 5781 {
		t.Errorf("Memory.Available = %v, want 5781", mem.Available)
	}

	// Disk
	if len(r.CentralProcessingUnit.Disk) != 1 {
		t.Fatalf("Disk len = %d, want 1", len(r.CentralProcessingUnit.Disk))
	}
	d := r.CentralProcessingUnit.Disk[0]
	if d.DiskName != "/dev/mmcblk0p7" {
		t.Errorf("Disk.DiskName = %q, want /dev/mmcblk0p7", d.DiskName)
	}
	if d.Total != 93750 {
		t.Errorf("Disk.Total = %v, want 93750", d.Total)
	}
	if d.MountOn != "/data" {
		t.Errorf("Disk.MountOn = %q, want /data", d.MountOn)
	}

	// NetCard
	if len(r.CentralProcessingUnit.NetCard) != 1 {
		t.Fatalf("NetCard len = %d, want 1", len(r.CentralProcessingUnit.NetCard))
	}
	nc := r.CentralProcessingUnit.NetCard[0]
	if nc.IP != "192.168.1.100" {
		t.Errorf("NetCard.IP = %q, want 192.168.1.100", nc.IP)
	}
	if nc.NetCardName != "eth0" {
		t.Errorf("NetCard.NetCardName = %q, want eth0", nc.NetCardName)
	}
	if nc.Bandwidth != 1000 {
		t.Errorf("NetCard.Bandwidth = %d, want 1000", nc.Bandwidth)
	}

	// Board[0]
	if len(r.CoreComputingUnit.Board) != 1 {
		t.Fatalf("Board len = %d, want 1", len(r.CoreComputingUnit.Board))
	}
	b := r.CoreComputingUnit.Board[0]
	if b.BoardSn != "EC712AC0C24120073" {
		t.Errorf("Board.BoardSn = %q, want EC712AC0C24120073 (global.ChipSn)", b.BoardSn)
	}
	if b.SdkVersion != "23.09 LTS" {
		t.Errorf("Board.SdkVersion = %q, want 23.09 LTS", b.SdkVersion)
	}
	if b.Temperature != 42 {
		t.Errorf("Board.Temperature = %d, want 42 (board temp)", b.Temperature)
	}

	// Chip[0]
	if len(b.Chip) != 1 {
		t.Fatalf("Chip len = %d, want 1", len(b.Chip))
	}
	ch := b.Chip[0]
	if ch.Temperature != 39 {
		t.Errorf("Chip.Temperature = %d, want 39 (chip temp)", ch.Temperature)
	}
	if ch.UtilizationRate != 0 {
		t.Errorf("Chip.UtilizationRate = %d, want 0 (TPU usage)", ch.UtilizationRate)
	}
	if ch.ChipSn != "EC712AC0C24120073" {
		t.Errorf("Chip.ChipSn = %q, want EC712AC0C24120073", ch.ChipSn)
	}
	if ch.Memory.Total != 3950 {
		t.Errorf("Chip.Memory.Total = %v, want 3950 (TPU mem MB)", ch.Memory.Total)
	}

	// Chip capacity from metrics.ChipCapacity("BM1684X") → 32 TOPS, chipType 2
	if ch.CalculationCapacity != 32 {
		t.Errorf("Chip.CalculationCapacity = %v, want 32 (BM1684X INT8 TOPS)", ch.CalculationCapacity)
	}
	if ch.ChipType != 2 {
		t.Errorf("Chip.ChipType = %d, want 2 (BM1684X)", ch.ChipType)
	}
	if ch.CalculationCapacityInt8 != 32 {
		t.Errorf("Chip.CalculationCapacityInt8 = %v, want 32", ch.CalculationCapacityInt8)
	}
	if ch.CalculationCapacityFp16 != 8 { // 32/4
		t.Errorf("Chip.CalculationCapacityFp16 = %v, want 8", ch.CalculationCapacityFp16)
	}
	if ch.CalculationCapacityFp32 != 4 { // 32/8
		t.Errorf("Chip.CalculationCapacityFp32 = %v, want 4", ch.CalculationCapacityFp32)
	}
}
