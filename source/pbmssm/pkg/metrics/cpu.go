package metrics

import (
	"runtime"
	"strconv"
	"strings"
	"time"
)

const (
	cpuInfoPath   = "/proc/cpuinfo"
	cpuFreqPath   = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
	cpuFreqMaxPath = "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"
	statPath      = "/proc/stat"
	cpuSampleGap  = 100 * time.Millisecond // CPU 利用率双采样间隔
)

// CPUInfo 采集 CPU 指标：核数/频率/使用率/型号/架构。
// 核数：/proc/cpuinfo "processor" 行计数。
// 频率：scaling_cur_freq（kHz→MHz），缺失时 fallback cpuinfo_max_freq。
// 使用率：/proc/stat 双采样 (total-idle)/total*100，对齐 pget_info。
// 型号：/proc/cpuinfo "model name" 行。
// 架构：runtime.GOARCH 映射（arm64→aarch64，amd64→x86_64）。
// 各字段失败独立降级。
func (c *Collector) CPUInfo() CPU {
	cpu := CPU{
		Arch: mapArch(runtime.GOARCH),
	}
	content := c.readStr(cpuInfoPath)
	if content != "" {
		cpu.Cores = countCores(content)
		// 经 CPU part 0xd05 修正的型号（CV84X2 上 model name 可能误报 bm1688）
		cpu.Type = c.cpuModel()
	}
	cpu.Frequency = c.cpuFrequency()
	cpu.UtilizationRate = c.cpuUtilization()
	return cpu
}

// countCores 统计 /proc/cpuinfo 中 "processor" 行数。
func countCores(content string) float64 {
	n := 0
	for _, line := range strings.Split(content, "\n") {
		if strings.HasPrefix(line, "processor") {
			n++
		}
	}
	return float64(n)
}

// modelLine 取 /proc/cpuinfo "model name" 行的值。
func modelLine(content string) string {
	for _, line := range strings.Split(content, "\n") {
		const prefix = "model name"
		if strings.HasPrefix(line, prefix) {
			// "model name\t: bm1684x" —— 取 ':' 之后
			idx := strings.Index(line, ":")
			if idx >= 0 {
				return strings.TrimSpace(line[idx+1:])
			}
		}
	}
	return ""
}

// cpuFrequency 读 scaling_cur_freq（kHz），fallback cpuinfo_max_freq，
// 再 fallback debugfs clk（CPUFrequencyClk，按芯片选 clk_* 路径）。
// CV84X2 无 cpufreq 驱动（/sys/.../cpufreq 不存在），此前恒返 0；
// debugfs clk_ap_ca55 与 get_info CPU_CLK 同源（对齐 get_info v1.5.1）。
func (c *Collector) cpuFrequency() int {
	s := c.readStr(cpuFreqPath)
	if s == "" {
		s = c.readStr(cpuFreqMaxPath)
	}
	if s != "" {
		if v, err := strconv.Atoi(s); err == nil {
			return v / 1000 // kHz → MHz
		}
	}
	return int(c.CPUFrequencyClk()) // Hz → MHz（accelerator.go）
}

// cpuUtilization /proc/stat 双采样：首行 "cpu " 的 user,nice,sys,idle,iowait,irq,softirq
// usage = (total_delta - idle_delta) / total_delta * 100
// 失败/单次读取返 0。
func (c *Collector) cpuUtilization() float64 {
	t0 := c.readStr(statPath)
	if t0 == "" {
		return 0
	}
	if c.sleep != nil {
		c.sleep.Sleep(cpuSampleGap)
	} else {
		time.Sleep(cpuSampleGap)
	}
	t1 := c.readStr(statPath)
	if t1 == "" {
		return 0
	}
	tot0, idle0 := parseStatTotal(t0)
	tot1, idle1 := parseStatTotal(t1)
	dt := tot1 - tot0
	if dt <= 0 {
		return 0
	}
	di := idle1 - idle0
	return float64(dt-di) / float64(dt) * 100.0
}

// parseStatTotal 解析 /proc/stat 首行 "cpu  n n n n n n n n n n"，
// total = user+nice+sys+idle+iowait+irq+softirq（前 7 个数值，不含 steal/guest），
// idle = 第 4 个数值。对齐 pget_info a[2..8]。
func parseStatTotal(line string) (total, idle int64) {
	fields := strings.Fields(line)
	if len(fields) < 5 || fields[0] != "cpu" {
		return 0, 0
	}
	// fields[1..] 为 user,nice,sys,idle,iowait,irq,softirq,steal,guest,...
	// total 取前 7 项（user..softirq），idle = fields[4]
	for i := 1; i <= 7 && i < len(fields); i++ {
		n, err := strconv.ParseInt(fields[i], 10, 64)
		if err != nil {
			continue
		}
		total += n
		if i == 4 { // idle
			idle = n
		}
	}
	return total, idle
}

// CPUFrequency 读取 CPU 频率 (MHz)，公开方法。
// 内部复用 cpuFrequency。
func (c *Collector) CPUFrequency() int {
	return c.cpuFrequency()
}

// PerCPUUsage 返回 delta 窗口内的 per-core 使用率。
// 调用方负责在调用 sampleDeltas 后使用其结果。
func (c *Collector) PerCPUUsage() []PerCPUDelta {
	ds := c.sampleDeltas()
	return ds.PerCPU
}

// mapArch 将 runtime.GOARCH 映射为与 lscpu/uname 一致的架构名。
func mapArch(goarch string) string {
	switch goarch {
	case "arm64":
		return "aarch64"
	case "amd64":
		return "x86_64"
	case "386":
		return "i386"
	default:
		return goarch
	}
}
