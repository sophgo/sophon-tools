package metrics

import (
	"strconv"
	"strings"

	"bmssm/pkg/system"
)

// ion heap sumary 路径（按芯片类型）。
const (
	ionNpuHeapV1 = "/sys/kernel/debug/ion/bm_npu_heap_dump/summary"
	ionVppHeapV1 = "/sys/kernel/debug/ion/bm_vpp_heap_dump/summary"
	ionVpuHeapV1 = "/sys/kernel/debug/ion/bm_vpu_heap_dump/summary"
	ionNpuHeapV2 = "/sys/kernel/debug/ion/cvi_npu_heap_dump/summary"
	ionVppHeapV2 = "/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary"
)

// ChipType 读取 /proc/cpuinfo，返回小写芯片型号。
// "bm1684x", "bm1684", "bm1688", "cv186ah", "cv84x6"，失败返空串。
// 经 system.DetectCpuModel 两级识别：CPU part 0xd05 优先于 model name
// （CV84X2 上 model name 可能误报 bm1688/cv186ah），dts compatible 兜底。
func (c *Collector) ChipType() string {
	s := c.cpuModel()
	switch {
	case strings.Contains(s, "bm1684x"):
		return "bm1684x"
	case strings.Contains(s, "bm1688"):
		return "bm1688"
	case strings.Contains(s, "bm1684"):
		return "bm1684"
	case strings.Contains(s, "cv186ah"):
		return "cv186ah"
	case strings.Contains(s, "cv84x6"):
		return "cv84x6"
	default:
		return ""
	}
}

// cpuModel 返回规范化芯片型号（小写，经 CPU part/dts 两级识别）。
func (c *Collector) cpuModel() string {
	content := c.readStr(cpuInfoPath)
	if content == "" {
		return ""
	}
	return system.DetectCpuModel(content, system.DeviceTreeRoot)
}

// chipFamily 归一化芯片家族：bm1684（含 bm1684x）/ cv（bm1688、cv186ah、cv84x6）。
// 用于选择"是否走 bm1688 路径"（SN、ion heap、vpuinfo、SDK 版本等）。
// 时钟路径不能按家族共享（CV84X2 时钟名与 bm1688 不同），需按芯片特判。
func chipFamily(chip string) string {
	switch chip {
	case "bm1684", "bm1684x":
		return "bm1684"
	case "bm1688", "cv186ah", "cv84x6":
		return "cv"
	}
	return ""
}

// VppMemory 读取 VPP 堆内存（bytes）。对齐 Rust parse_memory_from_command：
//
//	BM1684/BM1684X → ionVppHeapV1 [1]行
//	BM1688/CV186AH/CV84X2 → ionVppHeapV2 [1]行
//	不支持芯片 → 0,0
func (c *Collector) VppMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionVppHeapV1, "[1]")
	case "bm1688", "cv186ah", "cv84x6":
		return c.parseIonHeapLine(ionVppHeapV2, "[1]")
	}
	return 0, 0
}

// VpuMemory 读取 VPU 堆内存（bytes）。仅 BM1684/BM1684X 支持（BM1688/CV186AH/CV84X2 无 vpu heap）。
// 读 bm_vpu_heap_dump/summary 的 [2] 行（曾误读 vpp heap，已修正）。
func (c *Collector) VpuMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionVpuHeapV1, "[2]")
	}
	return 0, 0
}

// TpuMemory 读取 TPU 堆内存（bytes）。
//
//	BM1684/BM1684X → ionNpuHeapV1 [0]行
//	BM1688/CV186AH/CV84X2 → ionNpuHeapV2 [0]行
func (c *Collector) TpuMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionNpuHeapV1, "[0]")
	case "bm1688", "cv186ah", "cv84x6":
		return c.parseIonHeapLine(ionNpuHeapV2, "[0]")
	}
	return 0, 0
}

// parseIonHeapLine 读取 ion heap summary 文件，找以 prefix（如 "[0]"）开头的行，
// 解析 total 与 used 字节数。对齐 Rust parse_memory_from_command（原版用 awk 取 $4/$6）。
//
// 真机 summary 行形如（BM1684X 实测）：
//
//	"[0] npu heap size:2531262464 bytes, used:0 bytes\tusage rate:0%, ..."
//
// total 字段名为 `size:`（V2 cvi_ 堆可能为 `total:`），故两者皆识别；used 字段恒为 `used:`。
// 字段以空白分隔，`size:VALUE` 与 `used:VALUE` 均为独立 token，可直接剥前缀解析。
func (c *Collector) parseIonHeapLine(path, prefix string) (total, used int64) {
	content := c.readStr(path)
	if content == "" {
		return 0, 0
	}
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		fields := strings.Fields(line)
		for _, f := range fields {
			switch {
			case strings.HasPrefix(f, "size:"), strings.HasPrefix(f, "total:"):
				if v, err := strconv.ParseInt(f[strings.IndexByte(f, ':')+1:], 10, 64); err == nil {
					total = v
				}
			case strings.HasPrefix(f, "used:"):
				if v, err := strconv.ParseInt(f[len("used:"):], 10, 64); err == nil {
					used = v
				}
			}
		}
		return total, used
	}
	return 0, 0
}
