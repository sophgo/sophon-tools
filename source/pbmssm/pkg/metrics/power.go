package metrics

import (
	"os"
	"strconv"
	"strings"
)

const (
	i2cBus   = "1"
	i2cAddr  = "0x17"
	i2cRegHi = "0x25"
	i2cRegLo = "0x24"
)

// PowerUsage 通过 i2cget 读取功耗（W）。仅 BM1684/BM1684X SOC 模式支持。
// 对齐 Rust collect_power_info：i2cget 读 0x25(hi) 和 0x24(lo)，
// power = (hi*256 + lo) / 1000。
func (c *Collector) PowerUsage() float64 {
	chip := c.ChipType()
	if chip != "bm1684" && chip != "bm1684x" {
		return 0
	}
	if c.cmd == nil {
		return 0
	}

	// 检查 i2cget 是否存在
	if _, err := c.cmd.Run("which", "i2cget"); err != nil {
		return 0
	}

	hi := c.i2cgetHex(i2cRegHi)
	lo := c.i2cgetHex(i2cRegLo)
	if hi < 0 || lo < 0 {
		return 0
	}
	return float64(hi*256+lo) / 1000.0
}

func (c *Collector) i2cgetHex(reg string) int {
	out, err := c.cmd.Run("i2cget", "-f", "-y", i2cBus, i2cAddr, reg)
	if err != nil {
		return -1
	}
	out = strings.TrimSpace(out)
	out = strings.TrimPrefix(out, "0x")
	v, err := strconv.ParseInt(out, 16, 64)
	if err != nil {
		return -1
	}
	return int(v)
}

// PowerMultiRail 通过 pmbus 采集多路功耗（VTPU/VDDC, 需 GET_INFO_PMBUS_ENABLE 环境变量）。
// 对齐 pget_info VTPU_POWER/VTPU_VOLTAGE/VDDC_POWER/VDDC_VOLTAGE。
// 不支持芯片或 pmbus 不可用返全零。
func (c *Collector) PowerMultiRail() (vtpupower, vtpuppoltage, vddcPower, vddcVoltage, v12Power float64) {
	if os.Getenv("GET_INFO_PMBUS_ENABLE") != "1" {
		return 0, 0, 0, 0, 0
	}
	chip := c.ChipType()
	if chip != "bm1684" && chip != "bm1684x" {
		return 0, 0, 0, 0, 0
	}
	if c.cmd == nil {
		return 0, 0, 0, 0, 0
	}

	// 检测 i2c 设备
	bus := "0"
	addr := "0x50"
	out, err := c.cmd.Run("i2cdetect", "-y", "-r", bus, addr, addr)
	if err != nil || !strings.Contains(out, "50") {
		addr = "0x55"
		out, err = c.cmd.Run("i2cdetect", "-y", "-r", bus, addr, addr)
		if err != nil || !strings.Contains(out, "55") {
			return 0, 0, 0, 0, 0
		}
	}

	// pmbus -d 0 -s <addr> -i
	pmOut, err := c.cmd.Run("pmbus", "-d", bus, "-s", addr, "-i")
	if err != nil {
		return 0, 0, 0, 0, 0
	}

	lines := strings.Split(pmOut, "\n")
	var powers, voltages []float64
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.Contains(line, "output power:") {
			// " output power: 12.5W" → 12.5
			v := parseMetricFloat(line, "W")
			powers = append(powers, v)
		}
		if strings.Contains(line, "output voltage:") {
			// " output voltage: 0.85V" → 850mV; " output voltage: 850mV" → 850
			v := parseMetricFloat(line, "mV")
			if v == 0 {
				v = parseMetricFloat(line, "V") * 1000
			}
			voltages = append(voltages, v)
		}
	}
	// pget_info: 奇数行 VTPU, 偶数行 VDDC
	if len(powers) >= 1 {
		vtpupower = powers[0]
	}
	if len(powers) >= 2 {
		vddcPower = powers[1]
	}
	if len(voltages) >= 1 {
		vtpuppoltage = voltages[0]
	}
	if len(voltages) >= 2 {
		vddcVoltage = voltages[1]
	}

	// V12 power: i2cget 读取 (复用现有 PowerUsage 的 i2cget 逻辑)
	v12Power = float64(c.PowerUsage()) * 1000 // W → mW

	return
}

// parseMetricFloat 从 "key: valueUNIT" 提取浮点值。
func parseMetricFloat(line, unit string) float64 {
	if strings.Index(line, ":") < 0 {
		return 0
	}
	line = strings.TrimPrefix(line, strings.TrimSpace(line[:strings.Index(line, ":")+1]))
	line = strings.TrimSpace(line)
	line = strings.TrimSuffix(line, unit)
	v, err := strconv.ParseFloat(line, 64)
	if err != nil {
		return 0
	}
	return v
}
