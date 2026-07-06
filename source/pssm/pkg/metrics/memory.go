package metrics

import (
	"strconv"
	"strings"
)

// memInfoPath /proc/meminfo 路径常量。
const memInfoPath = "/proc/meminfo"

// Memory 读取 /proc/meminfo 的 MemTotal/MemFree/MemAvailable，kB → MB（对齐 bmssm）。
// 各字段缺失时单独返 0，不阻断。
func (c *Collector) Memory() Memory {
	content := c.readStr(memInfoPath)
	m := Memory{}
	if content == "" {
		return m
	}
	for _, line := range strings.Split(content, "\n") {
		switch {
		case strings.HasPrefix(line, "MemTotal:"):
			m.Total = memLineMB(line)
		case strings.HasPrefix(line, "MemFree:"):
			m.Free = memLineMB(line)
		case strings.HasPrefix(line, "MemAvailable:"):
			m.Available = memLineMB(line)
		}
	}
	return m
}

// memLineMB 从形如 "MemTotal:       6427708 kB" 的行提取 kB 并转 MB。
// 对齐 bmssm/pget_info：整数除法（截断），如 6427708 kB → 6277 MB。
func memLineMB(line string) float64 {
	// "MemTotal:" 前缀后，取第一个数字段
	fields := strings.Fields(line)
	if len(fields) < 2 {
		return 0
	}
	v, err := strconv.ParseInt(fields[1], 10, 64)
	if err != nil {
		return 0
	}
	return float64(v / 1024) // 整数除法，对齐 bmssm
}
