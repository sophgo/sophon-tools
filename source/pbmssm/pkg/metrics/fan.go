package metrics

import (
	"os"
	"strconv"
	"strings"

	"bmssm/logger"
)

const (
	fanEnablePath = "/sys/class/bm-tach/bm-tach-0/enable"
	fanSpeedPath  = "/sys/class/bm-tach/bm-tach-0/fan_speed"
)

// FanFrequency 读取风扇频率 (Hz)。
// 对齐 pget_info FAN_FREQUENCY。
// 仅 BM1684/BM1684X 支持；失败返 0。
func (c *Collector) FanFrequency() float64 {
	chip := c.ChipType()
	if chip != "bm1684" && chip != "bm1684x" {
		return 0
	}
	// 写 enable
	if err := os.WriteFile(fanEnablePath, []byte("1"), 0644); err != nil {
		logger.Warn("metrics: write fan enable: %v", err)
	}

	content := c.readStr(fanSpeedPath)
	if content == "" {
		return 0
	}
	content = strings.TrimPrefix(content, "fan_speed:")
	content = strings.TrimSpace(content)
	freq, err := strconv.ParseFloat(content, 64)
	if err != nil {
		return 0
	}
	return freq
}

// FanSpeed 读取风扇转速（RPM）。仅 BM1684/BM1684X 支持。
// 对齐 Rust collect_fan_speed：写 enable→读 fan_speed→60/(1/freq*2)。
// 不支持芯片或失败返 0。
func (c *Collector) FanSpeed() int64 {
	chip := c.ChipType()
	if chip != "bm1684" && chip != "bm1684x" {
		return 0
	}

	// 写 enable（对齐 Rust write_to_file("1")）
	if err := os.WriteFile(fanEnablePath, []byte("1"), 0644); err != nil {
		return 0
	}

	content := c.readStr(fanSpeedPath)
	if content == "" {
		return 0
	}
	// 内容形如 "fan_speed:0.5"
	content = strings.TrimPrefix(content, "fan_speed:")
	content = strings.TrimSpace(content)
	freq, err := strconv.ParseFloat(content, 64)
	if err != nil || freq == 0.0 {
		return 0
	}
	// RPM = 60 / (1/freq * 2) = 30*freq
	return int64(30.0 * freq)
}
