package metrics

import (
	"strconv"
	"strings"
)

// osReleasePath /etc/os-release 路径常量。
const osReleasePath = "/etc/os-release"

// OSVersion 读取 /etc/os-release 的 PRETTY_NAME 字段，去首尾引号。
// 对齐 bmssm getOSInfo：取 PRETTY_NAME= 行，l[13:len-1] 去引号。
// 失败/缺失返空串。
func (c *Collector) OSVersion() string {
	content := c.readStr(osReleasePath)
	if content == "" {
		return ""
	}
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		const prefix = "PRETTY_NAME="
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		val := line[len(prefix):]
		// 去首尾引号
		if len(val) >= 2 && val[0] == '"' && val[len(val)-1] == '"' {
			val = val[1 : len(val)-1]
		}
		return val
	}
	return ""
}

// uptimePath /proc/uptime 路径常量。
const uptimePath = "/proc/uptime"

// Runtime 读取 /proc/uptime 首字段（秒，截到小数点前），格式化为 "H:MM:SS"。
// 对齐 bmssm GetRuntime：H 不补零，MM/SS 补零（sophliteos 前端 split(':') 算秒）。
// 失败返空串。
func (c *Collector) Runtime() string {
	content := c.readStr(uptimePath)
	if content == "" {
		return ""
	}
	// 首字段在第一个空格前；截到小数点前取整秒
	first := content
	if idx := strings.Index(content, " "); idx >= 0 {
		first = content[:idx]
	}
	if idx := strings.Index(first, "."); idx >= 0 {
		first = first[:idx]
	}
	secs, err := strconv.ParseInt(first, 10, 64)
	if err != nil {
		return ""
	}
	h := secs / 3600
	m := (secs % 3600) / 60
	s := secs % 60
	return strconv.FormatInt(h, 10) + ":" + twoDigit(m) + ":" + twoDigit(s)
}

// twoDigit 将 0-59 格式化为两位（补前导零）。
func twoDigit(n int64) string {
	if n < 10 {
		return "0" + strconv.FormatInt(n, 10)
	}
	return strconv.FormatInt(n, 10)
}

// bmVersionPath SophonSDK 版本真值来源（pget_info 走 /usr/sbin/bm_version）。
const bmVersionPath = "/usr/sbin/bm_version"

// buildInfoPath 4.9 内核 SOC 设备的 SDK 版本来源（pget_info SOC+bm1684x/bm1684+4.9 分支）。
const buildInfoPath = "/system/data/buildinfo.txt"

// driverVersionPath PCIE 模式驱动版本来源（pget_info PCIE 分支）。
const driverVersionPath = "/proc/bmsophon/driver_version"

// socModels SOC 模式芯片型号集合（pget_info SOC_MODE_CPU_MODEL）。
// model name 命中其中之一即 SOC 模式，否则按 PCIE 处理。
var socModels = map[string]bool{
	"bm1684x": true,
	"bm1684":  true,
	"bm1688":  true,
	"cv186ah": true,
}

// SdkVersion 获取 SophonSDK 版本（严格对齐 pget_info get_info.sh 的决策树）。
//
//	CPU_MODEL(/proc/cpuinfo model name) × KERNEL_VERSION(uname -r) × WORK_MODE：
//	  - SOC + bm1684x/bm1684 + 内核 5.4：bm_version "SophonSDK version:" 行
//	  - SOC + bm1684x/bm1684 + 内核 4.9：/system/data/buildinfo.txt 行首 "VERSION" 的第 2 字段
//	  - SOC + bm1688/cv186ah：bm_version "Gemini_SDK:" 行
//	  - PCIE（model name 非 SOC 型号）：/proc/bmsophon/driver_version 冒号第 2 字段再取第 1 词
//	主分支失败/不命中返空串（与 pget_info 一致；不返回 libsophon 版本，二者语义不同，
//	pbmsec 9_comInfo.sh 专门维护 libsophon→SDK 映射表正因如此，但其表已 stale 故不采用）。
func (c *Collector) SdkVersion() string {
	cpu := modelLine(c.readStr(cpuInfoPath))
	kernel := c.kernelVersion()

	if socModels[cpu] {
		switch cpu {
		case "bm1684x", "bm1684":
			if strings.HasPrefix(kernel, "5.4.") {
				return c.bmVersionLine("SophonSDK version:")
			} else if strings.HasPrefix(kernel, "4.9.") {
				return c.buildInfoVersion()
			}
		case "bm1688", "cv186ah":
			return c.bmVersionLine("Gemini_SDK:")
		}
	} else {
		// PCIE 模式：取驱动版本
		return c.driverReleaseVersion()
	}
	return ""
}

// kernelVersion 跑 uname -r 取内核版本（如 "5.4.217-bm1684-g..."）。
func (c *Collector) kernelVersion() string {
	if c.cmd == nil {
		return ""
	}
	out, err := c.cmd.Run("uname", "-r")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

// bmVersionLine 跑 bm_version，找 prefix 行，返回去前缀后的值（trim）。
// 用于 "SophonSDK version:"（bm1684x/bm1684）与 "Gemini_SDK:"（bm1688/cv186ah）两行。
func (c *Collector) bmVersionLine(prefix string) string {
	if c.cmd == nil {
		return ""
	}
	out, err := c.cmd.Run(bmVersionPath)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, prefix) {
			return strings.TrimSpace(line[len(prefix):])
		}
	}
	return ""
}

// buildInfoVersion 读 /system/data/buildinfo.txt，找行首字段为 "VERSION" 的行，取第 2 字段。
// 对齐 pget_info: grep "VERSION" /system/data/buildinfo.txt | awk '{print $2}'，但用行首精确
// 匹配避免 KERNEL_VERSION/LIBSOPHON_VERSION 等含 "VERSION" 子串的行污染单值结果
// （pget_info 的 grep 会多行匹配；ssm 取单值，故精确匹配行首 "VERSION"）。
func (c *Collector) buildInfoVersion() string {
	content := c.readStr(buildInfoPath)
	if content == "" {
		return ""
	}
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[0] == "VERSION" {
			return fields[1]
		}
	}
	return ""
}

// driverReleaseVersion 读 /proc/bmsophon/driver_version，冒号第 2 字段再取第 1 词。
// 对齐 pget_info: awk -F':' '{print $2}' | awk '{print $1}'
func (c *Collector) driverReleaseVersion() string {
	content := c.readStr(driverVersionPath)
	if content == "" {
		return ""
	}
	if idx := strings.Index(content, ":"); idx >= 0 {
		fields := strings.Fields(content[idx+1:])
		if len(fields) >= 1 {
			return fields[0]
		}
	}
	return ""
}
