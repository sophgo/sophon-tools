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
	case "bm1688", "cv186ah", "cv84x6":
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
	case "bm1688", "cv186ah", "cv84x6":
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
	case "bm1688", "cv186ah", "cv84x6":
		return vppInfoSophPath
	}
	return ""
}

func (c *Collector) jpuInfoPath() string {
	switch c.ChipType() {
	case "bm1684", "bm1684x":
		return jpuInfoPath
	case "bm1688", "cv186ah", "cv84x6":
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
	tpuClkPathCv84x6 = "/sys/kernel/debug/clk/clk_tpu_ip/clk_rate"
	vpuClkPathBm1684 = "/sys/kernel/debug/clk/clk_gate_axi10/clk_rate"
	vpuClkPathBm1688 = "/sys/kernel/debug/clk/clk_cam0pll/clk_rate"
	vpuClkPathCv84x6 = "/sys/kernel/debug/clk/clk_ve_axi/clk_rate"
	cpuClkPathBm1684 = "/sys/kernel/debug/clk/clk_div_a53_1/clk_rate"
	cpuClkPathBm1688 = "/sys/kernel/debug/clk/clk_a53pll/clk_rate"
	cpuClkPathCv84x6 = "/sys/kernel/debug/clk/clk_ap_ca55/clk_rate"

	// CV84X2 的 TPU 实时运行频率（DVFS 驱动上报，单位 MHz）。debugfs 的
	// clk_tpu_ip 报的是分频前基准，只有真实值的一半，不能直接当频率用。
	tpuFreqSysfsCv84x6 = "/sys/devices/platform/cv84x2-dvfs/tpu_freq_mhz"
)

// TPUFrequencyClk 读取 TPU 时钟频率（Hz → MHz）。
// 对齐 pget_info TPU_CLK。CV84X2 时钟名为 clk_tpu_ip。
func (c *Collector) TPUFrequencyClk() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = tpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = tpuClkPathBm1688
	case "cv84x6":
		return c.tpuFrequencyCv84x6()
	default:
		return 0
	}
	return c.readClkRate(path)
}

// tpuFrequencyCv84x6 返回 CV84X2 的 TPU 频率（MHz）。
//
// 两个来源在真机上不一致且单位不同：
//   - sysfs tpu_freq_mhz：DVFS 上报的当前运行频率，单位 MHz，服务账号可读。首选。
//   - debugfs clk_tpu_ip/clk_rate：单位 Hz，是 TPU 时钟域的分频前基准，只有真实
//     运行频率的一半（真机对照：debugfs 1000000000 ↔ sysfs 2000 MHz）。
//
// 因此 debugfs 仅作兜底，且必须 ×2 校正后再返回；两者都取不到返回 0。
func (c *Collector) tpuFrequencyCv84x6() int64 {
	if mhz, ok := c.readSysfsMHz(tpuFreqSysfsCv84x6); ok {
		return mhz
	}
	if hz, ok := c.readSysfsHz(tpuClkPathCv84x6); ok {
		return hz / 1000000 * 2 // Hz → MHz，再按实测倍率校正
	}
	return 0
}

// VPUFrequency 读取 VPU 时钟频率 (Hz → MHz)。
// 对齐 pget_info VPU_CLK。bm1688/cv186ah 需 /2；CV84X2 的 clk_ve_axi 是 AXI 总线时钟，
// 语义不同不除（真机实测核对后可调整）。
func (c *Collector) VPUFrequency() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = vpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = vpuClkPathBm1688
	case "cv84x6":
		path = vpuClkPathCv84x6
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
// CV84X2 时钟名为 clk_ap_ca55。
func (c *Collector) CPUFrequencyClk() int64 {
	chip := c.ChipType()
	var path string
	switch chip {
	case "bm1684", "bm1684x":
		path = cpuClkPathBm1684
	case "bm1688", "cv186ah":
		path = cpuClkPathBm1688
	case "cv84x6":
		path = cpuClkPathCv84x6
	default:
		return 0
	}
	return c.readClkRate(path)
}

func (c *Collector) readClkRate(path string) int64 {
	hz, ok := c.readSysfsHz(path)
	if !ok {
		return 0
	}
	return hz / 1000000 // Hz → MHz
}

// readSysfsHz 读一个以 Hz 为单位、只含整数的节点；读不到或非整数时 ok=false。
// 与 readClkRate 的区别是保留 Hz 原值，供需要先换算倍率再折算 MHz 的场景使用
// （如 CV84X2 的 clk_tpu_ip 需 ×2 校正）。
func (c *Collector) readSysfsHz(path string) (int64, bool) {
	s := c.readStr(path)
	if s == "" {
		return 0, false
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil || v <= 0 {
		return 0, false
	}
	return v, true
}

// readSysfsMHz 读一个已经是 MHz 的节点（如 cv84x2-dvfs/tpu_freq_mhz）。
func (c *Collector) readSysfsMHz(path string) (int64, bool) {
	s := c.readStr(path)
	if s == "" {
		return 0, false
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil || v <= 0 {
		return 0, false
	}
	return v, true
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
