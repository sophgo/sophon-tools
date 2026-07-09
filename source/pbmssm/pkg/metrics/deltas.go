// deltas.go — 统一双采样窗口（效仿 pget_info: 500ms 窗口同时读 cpu/net/disk delta）。
package metrics

import (
	"os"
	"strconv"
	"strings"
)

const deltaInterval = 500 // milliseconds — align with noopSleeper mock in tests

// DeltaSample 一次双采样窗口中采集的 diff 值。
type DeltaSample struct {
	// CPU：aggregate usage (0-100)，per-core usage/breakdown
	CPUUsage     float64
	PerCPU       []PerCPUDelta // 每个核的分项

	// 网络：每网卡 RX/TX KiB/s
	NetThroughput []NetIfaceDelta

	// 磁盘：每盘 read/write KiB/s
	DiskThroughput []DiskIfaceDelta
}

// PerCPUDelta 单个 CPU 核的 usage + breakdown (user/kernel/io/irq)。
type PerCPUDelta struct {
	Usage  float64 // 0-100
	User   float64
	Kernel float64
	IO     float64
	IRQ    float64
}

// NetIfaceDelta 单个网卡吞吐。
type NetIfaceDelta struct {
	Name    string
	RXKibps float64
	TXKibps float64
}

// DiskIfaceDelta 单个块设备吞吐。
type DiskIfaceDelta struct {
	Name       string
	ReadKibps  float64
	WriteKibps float64
}

// sampleDeltas 执行一次统一双采样（效仿 pget_info get_cpu_all）。
// 读 t0 → sleep 500ms → 读 t1 → 计算 delta。
// 失败独立降级：单个子系统失败不影响其他。
func (c *Collector) sampleDeltas() DeltaSample {
	var ds DeltaSample

	// t0 raw data
	cpu0 := c.readStr(statPath)
	net0 := c.readStr("/proc/net/dev")
	disk0 := c.readStr("/proc/diskstats")

	if c.sleep != nil {
		c.sleep.Sleep(deltaInterval * 1e6) // nanoseconds from milliseconds
	}

	// t1 raw data
	cpu1 := c.readStr(statPath)
	net1 := c.readStr("/proc/net/dev")
	disk1 := c.readStr("/proc/diskstats")

	// CPU delta
	if cpu0 != "" && cpu1 != "" {
		ds.CPUUsage, ds.PerCPU = calcCPUFullDelta(cpu0, cpu1)
	}
	// Net delta
	if net0 != "" && net1 != "" {
		ds.NetThroughput = calcNetDelta(net0, net1)
	}
	// Disk delta
	if disk0 != "" && disk1 != "" {
		ds.DiskThroughput = calcDiskDelta(disk0, disk1)
	}
	return ds
}

// calcCPUFullDelta 解析 /proc/stat 双采样，返回 aggregate usage + per-core breakdown。
func calcCPUFullDelta(t0Str, t1Str string) (float64, []PerCPUDelta) {
	cpuLines0 := parseStatLines(t0Str)
	cpuLines1 := parseStatLines(t1Str)
	if len(cpuLines0) == 0 || len(cpuLines1) == 0 {
		return 0, nil
	}

	var totalUsage float64
	var perCPU []PerCPUDelta

	for cpuKey, s0 := range cpuLines0 {
		s1, ok := cpuLines1[cpuKey]
		if !ok {
			continue
		}
		dt := (s1.total - s0.total)
		di := (s1.idle - s0.idle)
		if dt <= 0 {
			continue
		}
		usage := float64(dt-di) / float64(dt) * 100.0
		user := float64((s1.user + s1.nice) - (s0.user + s0.nice)) / float64(dt) * 100.0
		kernel := float64(s1.system - s0.system) / float64(dt) * 100.0
		ioWait := float64(s1.iowait - s0.iowait) / float64(dt) * 100.0
		irq := float64((s1.irq + s1.softirq) - (s0.irq + s0.softirq)) / float64(dt) * 100.0

		if cpuKey == "cpu" {
			totalUsage = usage
		} else {
			perCPU = append(perCPU, PerCPUDelta{
				Usage: usage, User: user, Kernel: kernel, IO: ioWait, IRQ: irq,
			})
		}
	}
	return totalUsage, perCPU
}

type statFields struct {
	user, nice, system, idle, iowait, irq, softirq, total int64
}

// parseStatLines 解析 /proc/stat 所有 "cpu*" 行。
func parseStatLines(content string) map[string]statFields {
	out := make(map[string]statFields)
	for _, line := range strings.Split(content, "\n") {
		if !strings.HasPrefix(line, "cpu") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 5 {
			continue
		}
		key := fields[0]
		nums := parseInt64Fields(fields[1:], 7)
		if len(nums) < 7 {
			continue
		}
		total := nums[0] + nums[1] + nums[2] + nums[3] + nums[4] + nums[5] + nums[6]
		out[key] = statFields{
			user: nums[0], nice: nums[1], system: nums[2], idle: nums[3],
			iowait: nums[4], irq: nums[5], softirq: nums[6], total: total,
		}
	}
	return out
}

func parseInt64Fields(fields []string, n int) []int64 {
	out := make([]int64, 0, n)
	for i := 0; i < n && i < len(fields); i++ {
		v, err := strconv.ParseInt(fields[i], 10, 64)
		if err != nil {
			continue
		}
		out = append(out, v)
	}
	return out
}

// calcNetDelta 解析 /proc/net/dev 双采样，计算每网卡 RX/TX KiB/s。
// 对齐 pget_info: 只处理有 /sys/class/net/<name>/device 的物理网卡。
func calcNetDelta(t0Str, t1Str string) []NetIfaceDelta {
	net0 := parseNetDev(t0Str)
	net1 := parseNetDev(t1Str)

	var out []NetIfaceDelta
	for name, r0 := range net0 {
		r1, ok := net1[name]
		if !ok {
			continue
		}
		// 跳过 loopback 和 virtual
		if name == "lo" {
			continue
		}
		// 检查是否有物理设备
		devicePath := "/sys/class/net/" + name + "/device"
		if _, err := os.Stat(devicePath); os.IsNotExist(err) {
			continue
		}
		rxKibps := float64(r1.rx-r0.rx) / 1024.0 / (float64(deltaInterval) / 1000.0)
		txKibps := float64(r1.tx-r0.tx) / 1024.0 / (float64(deltaInterval) / 1000.0)
		out = append(out, NetIfaceDelta{Name: name, RXKibps: rxKibps, TXKibps: txKibps})
	}
	return out
}

type netDevCounters struct{ rx, tx int64 }

func parseNetDev(content string) map[string]netDevCounters {
	out := make(map[string]netDevCounters)
	for _, line := range strings.Split(content, "\n") {
		idx := strings.Index(line, ":")
		if idx < 0 {
			continue
		}
		name := strings.TrimSpace(line[:idx])
		fields := strings.Fields(line[idx+1:])
		if len(fields) < 10 {
			continue
		}
		rx, _ := strconv.ParseInt(fields[0], 10, 64)
		tx, _ := strconv.ParseInt(fields[8], 10, 64)
		out[name] = netDevCounters{rx: rx, tx: tx}
	}
	return out
}

// calcDiskDelta 解析 /proc/diskstats 双采样，计算每块物理盘 read/write KiB/s。
func calcDiskDelta(t0Str, t1Str string) []DiskIfaceDelta {
	d0 := parseDiskstats(t0Str)
	d1 := parseDiskstats(t1Str)

	// 获取物理磁盘列表
	phyDisks := getPhysicalBlockDevices()

	var out []DiskIfaceDelta
	for _, devName := range phyDisks {
		r0, ok0 := d0[devName]
		r1, ok1 := d1[devName]
		if !ok0 || !ok1 {
			continue
		}
		readKibps := float64(r1.readSectors-r0.readSectors) * 512 / 1024.0 / (float64(deltaInterval) / 1000.0)
		writeKibps := float64(r1.writeSectors-r0.writeSectors) * 512 / 1024.0 / (float64(deltaInterval) / 1000.0)
		out = append(out, DiskIfaceDelta{Name: devName, ReadKibps: readKibps, WriteKibps: writeKibps})
	}
	return out
}

type diskCounters struct{ readSectors, writeSectors int64 }

func parseDiskstats(content string) map[string]diskCounters {
	out := make(map[string]diskCounters)
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 14 {
			continue
		}
		name := fields[2]
		readSec, _ := strconv.ParseInt(fields[5], 10, 64)  // sectors read
		writeSec, _ := strconv.ParseInt(fields[9], 10, 64) // sectors written
		out[name] = diskCounters{readSectors: readSec, writeSectors: writeSec}
	}
	return out
}

// getPhysicalBlockDevices 返回物理块设备名列表（调用 lsblk，或扫描 /sys/block）。
// lsblk -dn -o NAME,TYPE | awk '$2=="disk"' 实现。
func getPhysicalBlockDevices() []string {
	entries, err := os.ReadDir("/sys/block")
	if err != nil {
		return nil
	}
	var disks []string
	for _, e := range entries {
		name := e.Name()
		// 排除 loop、ram、dm-*
		if strings.HasPrefix(name, "loop") || strings.HasPrefix(name, "ram") ||
			strings.HasPrefix(name, "dm-") {
			continue
		}
		// 排除 mmcblk*boot* 分区
		if strings.Contains(name, "boot") {
			continue
		}
		disks = append(disks, name)
	}
	return disks
}
