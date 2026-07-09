package metrics

import (
	"strconv"
	"strings"
)

// ion heap sumary 路径（按芯片类型）。
const (
	ionNpuHeapV1 = "/sys/kernel/debug/ion/bm_npu_heap_dump/summary"
	ionVppHeapV1 = "/sys/kernel/debug/ion/bm_vpp_heap_dump/summary"
	ionNpuHeapV2 = "/sys/kernel/debug/ion/cvi_npu_heap_dump/summary"
	ionVppHeapV2 = "/sys/kernel/debug/ion/cvi_vpp_heap_dump/summary"
)

// ChipType 读取 /proc/cpuinfo 的 model name，返回小写芯片型号。
// "bm1684x", "bm1684", "bm1688", "cv186ah"，失败返空串。
func (c *Collector) ChipType() string {
	content := c.readStr(cpuInfoPath)
	if content == "" {
		return ""
	}
	s := strings.ToLower(modelLine(content))
	switch {
	case strings.Contains(s, "bm1684x"):
		return "bm1684x"
	case strings.Contains(s, "bm1688"):
		return "bm1688"
	case strings.Contains(s, "bm1684"):
		return "bm1684"
	case strings.Contains(s, "cv186ah"):
		return "cv186ah"
	default:
		return ""
	}
}

// VppMemory 读取 VPP 堆内存（bytes）。对齐 Rust parse_memory_from_command：
//
//	BM1684/BM1684X → ionVppHeapV1 [1]行
//	BM1688/CV186AH → ionVppHeapV2 [1]行
//	不支持芯片 → 0,0
func (c *Collector) VppMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionVppHeapV1, "[1]")
	case "bm1688", "cv186ah":
		return c.parseIonHeapLine(ionVppHeapV2, "[1]")
	}
	return 0, 0
}

// VpuMemory 读取 VPU 堆内存（bytes）。仅 BM1684/BM1684X 支持。
func (c *Collector) VpuMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionVppHeapV1, "[1]")
	}
	return 0, 0
}

// TpuMemory 读取 TPU 堆内存（bytes）。
//
//	BM1684/BM1684X → ionNpuHeapV1 [0]行
//	BM1688/CV186AH → ionNpuHeapV2 [0]行
func (c *Collector) TpuMemory(chip string) (total, used int64) {
	switch chip {
	case "bm1684x", "bm1684":
		return c.parseIonHeapLine(ionNpuHeapV1, "[0]")
	case "bm1688", "cv186ah":
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
