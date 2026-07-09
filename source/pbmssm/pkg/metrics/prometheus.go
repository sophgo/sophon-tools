// Package metrics 提供 Prometheus 指标注册与更新。
package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
)

const namespace = "sophon"

var defaultLabels = []string{"device_id", "model", "serial", "chip_type", "board_type"}

// DeviceLabels Prometheus 标签值（对齐 Rust exporter 的 5 元组标签）。
type DeviceLabels struct {
	DeviceID  string
	Model     string
	Serial    string
	ChipType  string
	BoardType string
}

// labelsForDevice 将 DeviceLabels 转换为 Prometheus label values 切片。
func labelsForDevice(d DeviceLabels) []string {
	return []string{d.DeviceID, d.Model, d.Serial, d.ChipType, d.BoardType}
}

// MetricsRegistry 持有全部 24 个 Prometheus gauge（对齐 Rust exporter 指标集）。
type MetricsRegistry struct {
	NumDevices prometheus.Gauge

	SystemMemoryTotal *prometheus.GaugeVec
	SystemMemoryUsed  *prometheus.GaugeVec
	SystemMemoryFree  *prometheus.GaugeVec
	VppMemoryTotal    *prometheus.GaugeVec
	VppMemoryUsed     *prometheus.GaugeVec
	VpuMemoryTotal    *prometheus.GaugeVec
	VpuMemoryUsed     *prometheus.GaugeVec
	TpuMemoryTotal    *prometheus.GaugeVec
	TpuMemoryUsed     *prometheus.GaugeVec
	DeviceMemoryTotal *prometheus.GaugeVec
	DeviceMemoryUsed  *prometheus.GaugeVec

	CPUUsage    *prometheus.GaugeVec
	TPUUsage    *prometheus.GaugeVec
	TPUAvgUsage *prometheus.GaugeVec
	VPUEncUsage *prometheus.GaugeVec
	VPUDecUsage *prometheus.GaugeVec
	VPUEncLinks *prometheus.GaugeVec
	VPUDecLinks *prometheus.GaugeVec
	VPPUsage    *prometheus.GaugeVec
	JPUUsage    *prometheus.GaugeVec

	ChipTemp     *prometheus.GaugeVec
	BoardTemp    *prometheus.GaugeVec
	FanSpeed     *prometheus.GaugeVec
	PowerUsage   *prometheus.GaugeVec
	HealthStatus *prometheus.GaugeVec

	ChipInfo *prometheus.GaugeVec
}

// NewMetricsRegistry 创建并注册所有 Prometheus 指标。
func NewMetricsRegistry() *MetricsRegistry {
	r := &MetricsRegistry{
		NumDevices: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: namespace, Name: "num_devices",
			Help: "Number of TPU devices",
		}),

		SystemMemoryTotal: newGaugeVec("system_memory_total_bytes", "Total system memory in bytes"),
		SystemMemoryUsed:  newGaugeVec("system_memory_used_bytes", "Used system memory in bytes"),
		SystemMemoryFree:  newGaugeVec("system_memory_free_bytes", "Free system memory in bytes"),
		VppMemoryTotal:    newGaugeVec("vpp_memory_total_bytes", "Total VPP memory in bytes"),
		VppMemoryUsed:     newGaugeVec("vpp_memory_used_bytes", "Used VPP memory in bytes"),
		VpuMemoryTotal:    newGaugeVec("vpu_memory_total_bytes", "Total VPU memory in bytes"),
		VpuMemoryUsed:     newGaugeVec("vpu_memory_used_bytes", "Used VPU memory in bytes"),
		TpuMemoryTotal:    newGaugeVec("tpu_memory_total_bytes", "Total TPU memory in bytes"),
		TpuMemoryUsed:     newGaugeVec("tpu_memory_used_bytes", "Used TPU memory in bytes"),
		DeviceMemoryTotal: newGaugeVec("device_memory_total_bytes", "Total device memory in bytes"),
		DeviceMemoryUsed:  newGaugeVec("device_memory_used_bytes", "Used device memory in bytes"),

		CPUUsage:    newGaugeVec("cpu_usage_percent", "Current CPU usage percentage"),
		TPUUsage:    newGaugeVec("tpu_usage_percent", "Current TPU usage percentage"),
		TPUAvgUsage: newGaugeVec("tpu_average_usage_percent", "Average TPU usage percentage"),
		VPUEncUsage: newGaugeVec("vpu_enc_usage_percent", "Current VPU encoder usage percentage"),
		VPUDecUsage: newGaugeVec("vpu_dec_usage_percent", "Current VPU decoder usage percentage"),
		VPUEncLinks: newGaugeVec("vpu_enc_links_percent", "Current VPU encoder links"),
		VPUDecLinks: newGaugeVec("vpu_dec_links_percent", "Current VPU decoder links"),
		VPPUsage:    newGaugeVec("vpp_usage_percent", "Current VPP usage percentage"),
		JPUUsage:    newGaugeVec("jpu_usage_percent", "Current JPU usage percentage"),

		ChipTemp:     newGaugeVec("chip_temperature_celsius", "Chip temperature in Celsius"),
		BoardTemp:    newGaugeVec("board_temperature_celsius", "Board temperature in Celsius"),
		FanSpeed:     newGaugeVec("fan_speed_rpm", "Fan speed in RPM"),
		PowerUsage:   newGaugeVec("power_usage_watts", "Power usage in watts"),
		HealthStatus: newGaugeVec("health_status", "Device health status (1=healthy, 0=unhealthy)"),

		ChipInfo: newGaugeVec("chip_info", "Chip information"),
	}

	// Register NumDevices (no labels)
	prometheus.MustRegister(r.NumDevices)

	// Register all labeled gauges
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
		prometheus.MustRegister(g)
	}
	return r
}

func newGaugeVec(name, help string) *prometheus.GaugeVec {
	return prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: namespace, Name: name, Help: help,
		},
		defaultLabels,
	)
}

// Update 将一次采集的 HardwareMetrics 写入所有 gauge。
func (r *MetricsRegistry) Update(hw *HardwareMetrics, dev DeviceLabels) {
	ls := labelsForDevice(dev)

	set := func(g *prometheus.GaugeVec, v float64) {
		g.WithLabelValues(ls...).Set(v)
	}
	setInt := func(g *prometheus.GaugeVec, v int64) { set(g, float64(v)) }

	// 系统内存
	setInt(r.SystemMemoryTotal, hw.SystemMemoryTotal)
	setInt(r.SystemMemoryUsed, hw.SystemMemoryUsed)
	setInt(r.SystemMemoryFree, hw.SystemMemoryFree)

	// 设备内存
	setInt(r.VppMemoryTotal, hw.VppMemoryTotal)
	setInt(r.VppMemoryUsed, hw.VppMemoryUsed)
	setInt(r.VpuMemoryTotal, hw.VpuMemoryTotal)
	setInt(r.VpuMemoryUsed, hw.VpuMemoryUsed)
	setInt(r.TpuMemoryTotal, hw.TpuMemoryTotal)
	setInt(r.TpuMemoryUsed, hw.TpuMemoryUsed)
	setInt(r.DeviceMemoryTotal, hw.DeviceMemoryTotal)
	setInt(r.DeviceMemoryUsed, hw.DeviceMemoryUsed)

	// 性能
	setInt(r.CPUUsage, hw.CPUUsage)
	setInt(r.TPUUsage, hw.TPUUsage)
	setInt(r.TPUAvgUsage, hw.TPUAvgUsage)
	setInt(r.VPUEncUsage, hw.VPUEncUsage)
	setInt(r.VPUDecUsage, hw.VPUDecUsage)
	setInt(r.VPUEncLinks, hw.VPUEncLinks)
	setInt(r.VPUDecLinks, hw.VPUDecLinks)
	setInt(r.VPPUsage, hw.VPPUsage)
	setInt(r.JPUUsage, hw.JPUUsage)

	// 温度和风扇
	set(r.ChipTemp, hw.ChipTemp)
	set(r.BoardTemp, hw.BoardTemp)
	setInt(r.FanSpeed, hw.FanSpeed)

	// 功耗
	set(r.PowerUsage, hw.PowerUsage)

	// 健康状态
	set(r.HealthStatus, float64(hw.HealthStatus))

	// 芯片信息（值为 1 表示设备存在）
	set(r.ChipInfo, 1.0)
}

// SetDeviceCount 设置设备数量。
func (r *MetricsRegistry) SetDeviceCount(n int64) {
	r.NumDevices.Set(float64(n))
}

// Reset 清空所有指标。
func (r *MetricsRegistry) Reset() {
	r.NumDevices.Set(0)
	for _, g := range []*prometheus.GaugeVec{
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
		g.Reset()
	}
}

// HardwareMetrics 单次采集的全部硬件指标（所有字段非零值时有效）。
// 各字段含义对齐 Rust exporter 的 HardwareMetrics。
type HardwareMetrics struct {
	// 系统内存（bytes）
	SystemMemoryTotal int64
	SystemMemoryUsed  int64
	SystemMemoryFree  int64

	// 设备内存（bytes）
	VppMemoryTotal    int64
	VppMemoryUsed     int64
	VpuMemoryTotal    int64
	VpuMemoryUsed     int64
	TpuMemoryTotal    int64
	TpuMemoryUsed     int64
	DeviceMemoryTotal int64
	DeviceMemoryUsed  int64

	// 使用率（百分比，0-100）
	CPUUsage    int64
	TPUUsage    int64
	TPUAvgUsage int64
	VPUEncUsage int64
	VPUDecUsage int64
	VPUEncLinks int64
	VPUDecLinks int64
	VPPUsage    int64
	JPUUsage    int64

	// 温度（摄氏度）
	ChipTemp  float64
	BoardTemp float64

	// 风扇（RPM）
	FanSpeed int64

	// 功耗（W）
	PowerUsage float64

	// 健康状态（1=健康，0=不健康）
	HealthStatus int64

	// ---- 存档扩展字段（来自 pget_info）----

	// Per-CPU
	PerCPU []PerCPUDelta // 每核使用率 (archive only, Prometheus 用 label 维度)

	// 频率 (MHz)
	CPUFreqMHz int64
	TPUFreqMHz int64
	VPUFreqMHz int64

	// 内存
	SystemMemUsagePct float64 // (0-100)

	// 网络/磁盘吞吐 (来自 Deltas)
	NetThroughput  []NetIfaceDelta
	DiskThroughput []DiskIfaceDelta

	// 多路功耗
	VTPUPower   float64 // W
	VTPUVoltage float64 // mV
	VDDCPower   float64 // W
	VDDCVoltage float64 // mV
	V12Power    float64 // mW

	// 风扇频率
	FanFreqHz float64

	// 启动时间
	BootTimeSec float64

	// MMC 寿命
	MMCLifeTime float64
	MMCPreEOL   float64
}

// CollectAll 执行一次完整采集，返回 HardwareMetrics。
// 每个子采集独立降级（失败返零值），不阻断整体。
func (c *Collector) CollectAll() *HardwareMetrics {
	hw := &HardwareMetrics{}

	mem := c.Memory()
	hw.SystemMemoryTotal = int64(mem.Total * 1024 * 1024)
	hw.SystemMemoryUsed = int64((mem.Total - mem.Free) * 1024 * 1024)
	hw.SystemMemoryFree = int64(mem.Free * 1024 * 1024)

	cpu := c.CPUInfo()
	hw.CPUUsage = int64(cpu.UtilizationRate)

	hw.TPUUsage = int64(c.TPUUsage())
	hw.TPUAvgUsage = int64(c.TPUAverageUsage())

	chip := c.ChipType()
	vppTotal, vppUsed := c.VppMemory(chip)
	hw.VppMemoryTotal = vppTotal
	hw.VppMemoryUsed = vppUsed
	vpuTotal, vpuUsed := c.VpuMemory(chip)
	hw.VpuMemoryTotal = vpuTotal
	hw.VpuMemoryUsed = vpuUsed
	tpuTotal, tpuUsed := c.TpuMemory(chip)
	hw.TpuMemoryTotal = tpuTotal
	hw.TpuMemoryUsed = tpuUsed
	hw.DeviceMemoryTotal = vppTotal + vpuTotal + tpuTotal
	hw.DeviceMemoryUsed = vppUsed + vpuUsed + tpuUsed

	enc, dec, encLinks, decLinks, ok := c.VPUUsage()
	if ok {
		hw.VPUEncUsage = enc
		hw.VPUDecUsage = dec
		hw.VPUEncLinks = encLinks
		hw.VPUDecLinks = decLinks
	}
	hw.VPPUsage = c.VPPUsage()
	hw.JPUUsage = c.JPUUsage()

	hw.ChipTemp = float64(c.ChipTemp())
	hw.BoardTemp = float64(c.BoardTemp())
	hw.FanSpeed = c.FanSpeed()
	hw.PowerUsage = c.PowerUsage()
	if c.HealthStatus(hw.ChipTemp, hw.BoardTemp) {
		hw.HealthStatus = 1
	}

	// ---- 新增采集 ----

	// 频率
	hw.CPUFreqMHz = c.CPUFrequencyClk()
	hw.TPUFreqMHz = c.TPUFrequencyClk()
	hw.VPUFreqMHz = c.VPUFrequency()

	// 内存使用率
	hw.SystemMemUsagePct = c.MemoryUsagePercent()

	// 统一 delta 窗口 (CPU per-core + Net + Disk)
	ds := c.sampleDeltas()
	hw.CPUUsage = int64(ds.CPUUsage) // 用 delta 窗口的 CPU 覆盖之前的 100ms 窗口
	hw.PerCPU = ds.PerCPU
	hw.NetThroughput = ds.NetThroughput
	hw.DiskThroughput = ds.DiskThroughput

	// 多路功耗
	hw.VTPUPower, hw.VTPUVoltage, hw.VDDCPower, hw.VDDCVoltage, hw.V12Power = c.PowerMultiRail()

	// 风扇频率
	hw.FanFreqHz = c.FanFrequency()

	// 启动时间
	hw.BootTimeSec = c.BootTime()

	// MMC 寿命
	hw.MMCLifeTime, hw.MMCPreEOL = c.MMCLifetime()

	return hw
}

// ToArchRecord 将 HardwareMetrics 转换为存档用的定长 ArchRecord (v3)。
// v3: 删除 TPU 平均使用率、12V 功耗、eMMC 寿命/预寿命；内存以使用率(%)存档。
func (hw *HardwareMetrics) ToArchRecord() *ArchRecord {
	memUsagePct := func(total, used int64) float32 {
		if total <= 0 {
			return 0
		}
		return float32(float64(used) / float64(total) * 100.0)
	}
	return &ArchRecord{
		CPUUsage:          float32(hw.CPUUsage),
		TPUUsage:          float32(hw.TPUUsage),
		VPUEncUsage:       float32(hw.VPUEncUsage),
		VPUDecUsage:       float32(hw.VPUDecUsage),
		VPUEncLinks:       float32(hw.VPUEncLinks),
		VPUDecLinks:       float32(hw.VPUDecLinks),
		VPPUsage:          float32(hw.VPPUsage),
		JPUUsage:          float32(hw.JPUUsage),
		SystemMemUsagePct: float32(hw.SystemMemUsagePct),
		VppMemoryUsagePct: memUsagePct(hw.VppMemoryTotal, hw.VppMemoryUsed),
		VpuMemoryUsagePct: memUsagePct(hw.VpuMemoryTotal, hw.VpuMemoryUsed),
		TpuMemoryUsagePct: memUsagePct(hw.TpuMemoryTotal, hw.TpuMemoryUsed),
		ChipTemp:          float32(hw.ChipTemp),
		BoardTemp:         float32(hw.BoardTemp),
		FanSpeedRPM:       float32(hw.FanSpeed),
		PowerUsage:        float32(hw.PowerUsage),
		BootTime:          float32(hw.BootTimeSec),
	}
}
