// CV84X2（SDK 标识 cv84x6）芯片型号识别，对齐 pget_info get_info.sh 的两级识别。
package system

import (
	"io/fs"
	"os"
	"strings"
	"sync"
)

// DeviceTreeRoot 设备树根（compatible 扫描用）。
const DeviceTreeRoot = "/proc/device-tree"

// cv84x6CompatPrefix CV84X2 内核 dts 专属 compatible 前缀
// （如 cvitek,cv84x6-clk / cvitek,cv84x6-emmc；真实 bm1688/cv186ah 的 dts 不含）。
const cv84x6CompatPrefix = "cvitek,cv84x6-"

// cortexA55Part CPU part（MIDR）值：Cortex-A55(0xd05) 仅 CV84X2/CV84X6 搭载，
// 其余 SDK 芯片（bm1684x/bm1684/bm1688/cv186ah）均为 Cortex-A53(0xd03)，天然分开。
const cortexA55Part = "0xd05"

// dtsScanCache compatible 扫描结果缓存：ChipType 等高频采集路径每次都会调用
// DetectCpuModel，设备树内容运行期不变，扫描一次后缓存（按 root 记忆化）。
var (
	dtsScanMu    sync.Mutex
	dtsScanCache = map[string]bool{}
)

// DetectCpuModel 返回规范化芯片型号（小写），两级识别均不依赖 model name 的准确值：
//
//  1. 首选 CPU part（MIDR 硬件直读，无条件打印）：Cortex-A55(0xd05) → cv84x6。
//     model name 在 CV84X2 上不可靠——内核 cpuinfo.c 仅 32-bit compat 模式打印此行，
//     且取 CHIP_INFO(0x27102014)&0x7 判定，可能输出 null/缺行/cv186ah/bm1688。
//  2. 兜底 dts 信号：dtsRoot 下任一 compatible 文件含 "cvitek,cv84x6-" → cv84x6。
//
// 未命中时返回 model name（小写）；无 model name 返空串。
func DetectCpuModel(cpuinfoContent, dtsRoot string) string {
	model := parseModelName(cpuinfoContent)
	if strings.Contains(strings.ToLower(parseCpuPart(cpuinfoContent)), cortexA55Part) {
		return "cv84x6"
	}
	if model != "cv84x6" && dtsRoot != "" && dtsHasCv84x6Compat(dtsRoot) {
		return "cv84x6"
	}
	return model
}

// parseModelName 取 cpuinfo "model name" 行的值（小写）。
func parseModelName(content string) string {
	for _, line := range strings.Split(content, "\n") {
		if !strings.HasPrefix(line, "model name") {
			continue
		}
		idx := strings.Index(line, ":")
		if idx >= 0 {
			return strings.ToLower(strings.TrimSpace(line[idx+1:]))
		}
	}
	return ""
}

// parseCpuPart 取 cpuinfo "CPU part" 行的值（如 "0xd05"）。
func parseCpuPart(content string) string {
	for _, line := range strings.Split(content, "\n") {
		if !strings.HasPrefix(line, "CPU part") {
			continue
		}
		idx := strings.Index(line, ":")
		if idx >= 0 {
			return strings.TrimSpace(line[idx+1:])
		}
	}
	return ""
}

// dtsHasCv84x6Compat 扫描 dtsRoot 下所有 compatible 文件，任一含 cv84x6 前缀即 true。
// 结果按 dtsRoot 记忆化（设备树运行期不变）。
func dtsHasCv84x6Compat(dtsRoot string) bool {
	dtsScanMu.Lock()
	if hit, ok := dtsScanCache[dtsRoot]; ok {
		dtsScanMu.Unlock()
		return hit
	}
	dtsScanMu.Unlock()

	hit := scanCompatible(dtsRoot)

	dtsScanMu.Lock()
	dtsScanCache[dtsRoot] = hit
	dtsScanMu.Unlock()
	return hit
}

// scanCompatible 递归扫描 compatible 文件（NUL 分隔字符串，按字节包含匹配）。
func scanCompatible(dtsRoot string) bool {
	fsys := os.DirFS(dtsRoot)
	found := false
	_ = fs.WalkDir(fsys, ".", func(path string, d fs.DirEntry, err error) error {
		if err != nil || found {
			return fs.SkipAll
		}
		if d.IsDir() || d.Name() != "compatible" {
			return nil
		}
		data, err := fs.ReadFile(fsys, path)
		if err != nil {
			return nil
		}
		if strings.Contains(string(data), cv84x6CompatPrefix) {
			found = true
			return fs.SkipAll
		}
		return nil
	})
	return found
}
