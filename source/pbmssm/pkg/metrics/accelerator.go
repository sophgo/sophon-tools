package metrics

import (
	"regexp"
	"strconv"
	"strings"
)

// proc 路径常量。
const (
	vpuInfoPath     = "/proc/vpuinfo"
	vpuInfoSophPath = "/proc/soph/vpuinfo"
	vppInfoPath     = "/proc/vppinfo"
	vppInfoSophPath = "/proc/soph/vppinfo"
	jpuInfoPath     = "/proc/jpuinfo"
	jpuInfoSophPath = "/proc/soph/jpuinfo"
)

var (
	vpuPercentRe  = regexp.MustCompile(`:(\d+)%`)
	vpuLinksRe    = regexp.MustCompile(`"link_num":(\d+),`)
	pipePercentRe = regexp.MustCompile(`(\d+)%\|`)
)

// VPUUsage 解析 /proc/[soph/]vpuinfo，返回 enc 使用率、dec 平均使用率、
// enc 链接数、dec 总链接数。不同芯片解析策略不同（对齐 Rust collect_vpu_usage）。
// 非 Sophon 芯片或不支持的芯片返 (0,0,0,0, false)。
func (c *Collector) VPUUsage() (enc, dec, encLinks, decLinks int64, ok bool) {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = vpuInfoPath
	case "bm1688", "cv186ah":
		path = vpuInfoSophPath
	default:
		return 0, 0, 0, 0, false
	}

	content := c.readStr(path)
	if content == "" {
		return 0, 0, 0, 0, false
	}
	// 去换行（对齐 Rust content_without_newlines）
	content = strings.ReplaceAll(content, "\n", "")

	percents := parseInts(vpuPercentRe.FindAllStringSubmatch(content, -1))
	links := parseInts(vpuLinksRe.FindAllStringSubmatch(content, -1))

	switch chip {
	case "bm1684":
		if len(percents) == 5 && len(links) == 5 {
			enc = percents[4]
			dec = (percents[0] + percents[1] + percents[2] + percents[3]) / 4
			encLinks = links[4]
			decLinks = links[0] + links[1] + links[2] + links[3]
			ok = true
		}
	case "bm1684x":
		if len(percents) == 3 && len(links) == 3 {
			enc = percents[2]
			dec = (percents[0] + percents[1]) / 2
			encLinks = links[2]
			decLinks = links[0] + links[1]
			ok = true
		}
	case "bm1688", "cv186ah":
		if len(percents) == 3 && len(links) == 3 {
			enc = percents[0]
			dec = (percents[1] + percents[2]) / 2
			encLinks = links[0]
			decLinks = links[1] + links[2]
			ok = true
		}
	}
	return
}

// VPPUsage 解析 /proc/[soph/]vppinfo，取所有 `(\d+)%|` 匹配值的平均。
func (c *Collector) VPPUsage() int64 {
	path := c.vppInfoPath()
	if path == "" {
		return 0
	}
	return c.parsePipePercent(path)
}

// JPUUsage 解析 /proc/[soph/]jpuinfo，取所有 `(\d+)%|` 匹配值的平均。
func (c *Collector) JPUUsage() int64 {
	path := c.jpuInfoPath()
	if path == "" {
		return 0
	}
	return c.parsePipePercent(path)
}

func (c *Collector) vppInfoPath() string {
	switch c.ChipType() {
	case "bm1684", "bm1684x":
		return vppInfoPath
	case "bm1688", "cv186ah":
		return vppInfoSophPath
	}
	return ""
}

func (c *Collector) jpuInfoPath() string {
	switch c.ChipType() {
	case "bm1684", "bm1684x":
		return jpuInfoPath
	case "bm1688", "cv186ah":
		return jpuInfoSophPath
	}
	return ""
}

func (c *Collector) parsePipePercent(path string) int64 {
	content := c.readStr(path)
	if content == "" {
		return 0
	}
	content = strings.ReplaceAll(content, "\n", "")
	percents := parseInts(pipePercentRe.FindAllStringSubmatch(content, -1))
	if len(percents) == 0 {
		return 0
	}
	var sum int64
	for _, p := range percents {
		sum += p
	}
	return sum / int64(len(percents))
}

// tpu/clk 路径
const (
	tpuClkPathBm1684 = "/sys/kernel/debug/clk/tpll_clock/clk_rate"
	tpuClkPathBm1688 = "/sys/kernel/debug/clk/clk_tpll/clk_rate"
	vpuClkPathBm1684 = "/sys/kernel/debug/clk/clk_gate_axi10/clk_rate"
	vpuClkPathBm1688 = "/sys/kernel/debug/clk/clk_cam0pll/clk_rate"
	cpuClkPathBm1684 = "/sys/kernel/debug/clk/clk_div_a53_1/clk_rate"
	cpuClkPathBm1688 = "/sys/kernel/debug/clk/clk_a53pll/clk_rate"
)

// TPUFrequencyClk 读取 TPU 时钟频率 (Hz → MHz)。
// 对齐 pget_info TPU_CLK。
func (c *Collector) TPUFrequencyClk() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = tpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = tpuClkPathBm1688
	default:
		return 0
	}
	return c.readClkRate(path)
}

// VPUFrequency 读取 VPU 时钟频率 (Hz → MHz)。
// 对齐 pget_info VPU_CLK。bm1688/cv186ah 需 /2。
func (c *Collector) VPUFrequency() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = vpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = vpuClkPathBm1688
	default:
		return 0
	}
	rate := c.readClkRate(path)
	if chip == "bm1688" || chip == "cv186ah" {
		rate /= 2
	}
	return rate
}

// CPUFrequencyClk 读取 CPU 时钟频率 (Hz → MHz)，sysfs 方式。
// 与 cpuFrequency 不同，此方法读 debugfs clk 而非 cpuinfo/scaling_cur_freq。
// 互补：scaling_cur_freq 反映实际频率，debugfs clk 反映基础时钟。
func (c *Collector) CPUFrequencyClk() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = cpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = cpuClkPathBm1688
	default:
		return 0
	}
	return c.readClkRate(path)
}

func (c *Collector) readClkRate(path string) int64 {
	s := c.readStr(path)
	if s == "" {
		return 0
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return v / 1000000 // Hz → MHz
}

// parseInts 从 regexp submatch 结果中提取 group 1 的整数值。
func parseInts(matches [][]string) []int64 {
	var out []int64
	for _, m := range matches {
		if len(m) >= 2 {
			if v, err := strconv.ParseInt(m[1], 10, 64); err == nil {
				out = append(out, v)
			}
		}
	}
	return out
}
