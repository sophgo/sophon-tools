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
	tpuMemPath    = "/sys/kernel/debug/ion/bm_npu_heap_dump/total_mem" // 需 root
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
func (c *Collector) BoardTemp() int {
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

// 源：/sys/kernel/debug/ion/bm_npu_heap_dump/total_mem（字节，需 root）。
// 对齐 pget_info：TPU_MEM(MiB) = total_mem/1024/1024。
// 非 root 读不到 debugfs，降级返 0。
func (c *Collector) TPUMem() float64 {
	s := c.readStr(tpuMemPath)
	if s == "" {
		return 0
	}
	val, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return float64(val) / 1024.0 / 1024.0
}
