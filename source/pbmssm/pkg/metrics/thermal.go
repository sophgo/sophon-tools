package metrics

import (
	"strconv"
	"strings"
)

// 热区 / TPU sysfs 路径常量。
const (
	chipTempPath  = "/sys/class/thermal/thermal_zone0/temp" // 芯片温度（milli-celsius）
	boardTempPath = "/sys/class/thermal/thermal_zone1/temp" // 板温（milli-celsius）
	npuUsagePath  = "/sys/class/bm-tpu/bm-tpu0/device/npu_usage"
	tpuMemPath    = "/sys/kernel/debug/ion/bm_npu_heap_dump/total_mem"  // 需 root（bm1684/bm1684x）
	tpuMemPathV2  = "/sys/kernel/debug/ion/cvi_npu_heap_dump/total_mem" // 需 root（cv 家族：bm1688/cv186ah/cv84x6）
)

// ChipTemp 读取芯片温度（thermal_zone0），milli-celsius → 整数 ℃。
// 对齐 pget_info：CHIP_TEMP=$(cat thermal_zone0/temp); /1000。
// 失败返 0。
func (c *Collector) ChipTemp() int {
	return c.readTempC(chipTempPath)
}

// BoardTemp 读取板温（thermal_zone1），milli-celsius → 整数 ℃。
// 对齐 pget_info：BOARD_TEMP=$(cat thermal_zone1/temp); /1000。
// 失败返 0。
//
// CV84X2 不可抗说明（2026-08-26 真机核实，与 get_info v1.5.1 结论对齐）：
// 无独立板温传感器——thermal_zone0/1/2 全是 SoC 片内传感器（dts soc_thermal_0/1/2），
// 借读 zone1 会输出伪板温；EVB MCU 温度寄存器读回无意义值（压测冻结）。
// 故 cv84x6 板温恒返 0（get_info 同样输出 0），不再借读 zone1。
func (c *Collector) BoardTemp() int {
	if c.ChipType() == "cv84x6" {
		return 0
	}
	return c.readTempC(boardTempPath)
}

// readTempC 读 thermal_zone temp 文件，milli-celsius 转 ℃。
func (c *Collector) readTempC(path string) int {
	s := c.readStr(path)
	if s == "" {
		return 0
	}
	val, err := strconv.Atoi(s)
	if err != nil {
		return 0
	}
	return val / 1000
}

// TPUUsage 读取 TPU 利用率。
// 源：/sys/class/bm-tpu/bm-tpu0/device/npu_usage，内容形如 "usage:0 avusage:0"。
// 对齐 pget_info：取 "usage:" 后数字（百分比），丢弃 avusage。
// 失败返 0。
func (c *Collector) TPUUsage() int {
	s := c.readStr(npuUsagePath)
	if s == "" {
		return 0
	}
	// 按空白切分，找 "usage:" 前缀的 token
	for _, tok := range strings.Fields(s) {
		const prefix = "usage:"
		if strings.HasPrefix(tok, prefix) {
			n, err := strconv.Atoi(tok[len(prefix):])
			if err != nil {
				return 0
			}
			return n
		}
	}
	return 0
}

// TPUAverageUsage 读取 TPU 平均利用率（avusage 字段）。
// 源同 TPUUsage，取 "avusage:" 后数字（百分比）。
// 失败返 0。
func (c *Collector) TPUAverageUsage() int {
	s := c.readStr(npuUsagePath)
	if s == "" {
		return 0
	}
	for _, tok := range strings.Fields(s) {
		const prefix = "avusage:"
		if strings.HasPrefix(tok, prefix) {
			n, err := strconv.Atoi(tok[len(prefix):])
			if err != nil {
				return 0
			}
			return n
		}
	}
	return 0
}

// TpuMemUsage 读取 TPU 显存使用率（%）：used/total*100，四舍五入。
// 源 ion heap（bm_npu_heap_dump/cvi_npu_heap_dump）。total≤0 返 0。
// 供告警引擎 TpuScale 阈值比对。
func (c *Collector) TpuMemUsage() int {
	total, used := c.TpuMemory(c.ChipType())
	if total <= 0 {
		return 0
	}
	return int(float64(used)*100.0/float64(total) + 0.5)
}

// 源：/sys/kernel/debug/ion/bm_npu_heap_dump/total_mem 或 cvi_npu_heap_dump/total_mem（字节，需 root）。
// 对齐 pget_info：TPU_MEM(MiB) = total_mem/1024/1024。
// cv 家族（bm1688/cv186ah/cv84x6）走 cvi_ 前缀路径；bm1684/bm1684x 走 bm_ 前缀。
// 非 root 读不到 debugfs，降级返 0。
func (c *Collector) TPUMem() float64 {
	path := tpuMemPath
	if chipFamily(c.ChipType()) == "cv" {
		path = tpuMemPathV2
	}
	s := c.readStr(path)
	if s == "" {
		return 0
	}
	val, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return float64(val) / 1024.0 / 1024.0
}
