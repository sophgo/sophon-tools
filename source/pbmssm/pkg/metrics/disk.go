package metrics

import (
	"sort"
	"strconv"
	"strings"
)

const (
	dfCmd     = "df"
	mountsPath = "/proc/mounts"
)

// Disks 采集磁盘列表，按物理块设备聚合（同一设备的多个分区合并为一条）。
//
// 源：df -Tk 输出，行首 /dev 且不含 loop；overlay / 单独处理（见下）。
// 聚合：/dev/mmcblk0p1 与 /dev/mmcblk0p5 归并到 /dev/mmcblk0，total/free 取各分区之和。
// 根分区：/ 若为 overlay，解析 upperdir 所属分区→其物理设备，MountOn 标 "/" 并排首位；
//
//	/ 若直接挂在某 /dev 分区，同理。这样"硬盘空间"反映整片 eMMC 而非仅 overlay/根分区。
//
// 字段：diskName=物理设备(如 /dev/mmcblk0), total=Σ(Used+Avail)/1024→MB,
//
//	free=Σ(Avail)/1024→MB, mountOn(根设备为 /), readOnly=所有分区皆 ro 则 1。
//	Total = Used + Avail（不含 ext4 reserved），使 (1-Free/Total) = df Use%，与 pget_info 一致。
//	diskSn 留空，ioRate 留 0（对齐 bmssm）。
//
// 失败返空切片。
func (c *Collector) Disks() []Disk {
	if c.cmd == nil {
		return nil
	}
	out, err := c.cmd.Run(dfCmd, "-Tk")
	if err != nil || out == "" {
		return nil
	}
	mounts := c.readStr(mountsPath)

	// 1. 收集各 /dev 分区信息；记录 overlay / 的 upperdir（用于定位根所属物理设备）
	parts := map[string]partInfo{}
	var partOrder []string
	overlayUpper := ""
	for _, line := range strings.Split(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 7 {
			continue
		}
		dev := fields[0]
		mountOn := strings.Join(fields[6:], " ")
		isDev := strings.HasPrefix(dev, "/dev") && !strings.Contains(dev, "loop")
		isRootOverlay := dev == "overlay" && mountOn == "/"
		if !isDev && !isRootOverlay {
			continue
		}
		usedKB, err1 := strconv.ParseInt(fields[3], 10, 64)
		availKB, err2 := strconv.ParseInt(fields[4], 10, 64)
		if err1 != nil || err2 != nil {
			continue
		}
		if isRootOverlay {
			// overlay / 的空间其实是 upperdir 所在分区；不单独入表，由底层物理设备代表 /
			overlayUpper = overlayUpperDir(mounts)
			continue
		}
		parts[dev] = partInfo{usedKB + availKB, availKB, mountOn, diskReadOnly(mounts, dev)}
		partOrder = append(partOrder, dev)
	}

	// 2. 定位根 / 所属物理设备（直接挂载或 overlay upperdir 所属分区）
	rootDev := resolveRootDevice(mounts, parts, overlayUpper)

	// 3. 按物理设备聚合
	type agg struct {
		totalKB, availKB int64
		mountOn          string
		allRO            bool
		any              bool
	}
	aggs := map[string]*agg{}
	var aggOrder []string
	for _, dev := range partOrder {
		base := baseDevice(dev)
		a := aggs[base]
		if a == nil {
			a = &agg{allRO: true}
			aggs[base] = a
			aggOrder = append(aggOrder, base)
		}
		p := parts[dev]
		a.totalKB += p.totalKB
		a.availKB += p.availKB
		if base == rootDev {
			a.mountOn = "/"
		} else if !a.any {
			a.mountOn = p.mountOn
		}
		if p.ro == 0 {
			a.allRO = false
		}
		a.any = true
	}
	// 根设备排首位，其余按设备名稳定排序
	sort.SliceStable(aggOrder, func(i, j int) bool {
		if aggOrder[i] == rootDev {
			return true
		}
		if aggOrder[j] == rootDev {
			return false
		}
		return aggOrder[i] < aggOrder[j]
	})

	disks := make([]Disk, 0, len(aggOrder))
	for _, base := range aggOrder {
		a := aggs[base]
		ro := 0
		if a.allRO {
			ro = 1
		}
		disks = append(disks, Disk{
			DiskName: base,
			Total:    float64(a.totalKB / 1024), // 整数除法→MB，对齐 bmssm
			Free:     float64(a.availKB / 1024),
			MountOn:  a.mountOn,
			ReadOnly: ro,
		})
	}
	return disks
}

// baseDevice 由分区设备名推物理块设备名：
//
//	/dev/mmcblk0p1 → /dev/mmcblk0（p+数字 后缀，p 前为数字）
//	/dev/nvme0n1p1 → /dev/nvme0n1
//	/dev/sda1 → /dev/sda（末尾数字，前一位非数字）
//	/dev/sda → /dev/sda（无分区后缀，整盘）
//
// df 列出的是已挂载分区（带分区号），故不会出现 /dev/mmcblk0 整盘被误剥 "0" 的情况。
func baseDevice(dev string) string {
	name := strings.TrimPrefix(dev, "/dev/")
	// 形如 xxx<digit>p<digits>：剥 p+数字
	if i := strings.LastIndex(name, "p"); i > 0 && i < len(name)-1 {
		if isAllDigit(name[i+1:]) && name[i-1] >= '0' && name[i-1] <= '9' {
			return "/dev/" + name[:i]
		}
	}
	// 形如 xxx<digits>：剥末尾数字（sda1→sda）
	if last := name[len(name)-1]; last >= '0' && last <= '9' {
		j := len(name)
		for j > 0 && name[j-1] >= '0' && name[j-1] <= '9' {
			j--
		}
		if j > 0 {
			return "/dev/" + name[:j]
		}
	}
	return "/dev/" + name
}

func isAllDigit(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// overlayUpperDir 解析 /proc/mounts 中 "overlay / overlay ...,upperdir=<path>,..." 的 upperdir。
// 用于定位 overlay 根的 upper 层所属分区。未找到返空串。
func overlayUpperDir(mounts string) string {
	for _, line := range strings.Split(mounts, "\n") {
		f := strings.Fields(line)
		if len(f) < 4 || f[0] != "overlay" || f[1] != "/" {
			continue
		}
		for _, o := range strings.Split(f[3], ",") {
			if strings.HasPrefix(o, "upperdir=") {
				return strings.TrimPrefix(o, "upperdir=")
			}
		}
	}
	return ""
}

// resolveRootDevice 定位 / 所属物理块设备：
//
//	overlay 根 → upperdir 所属分区（mountOn 是 upperdir 最长前缀）→ baseDevice
//	直接挂载  → mountOn=="/" 的分区 → baseDevice
//
// 找不到返空串（根在 tmpfs 等虚拟 fs，无物理设备）。
func resolveRootDevice(mounts string, parts map[string]partInfo, overlayUpper string) string {
	if overlayUpper != "" {
		var best string
		bestLen := -1
		for dev, p := range parts {
			if strings.HasPrefix(overlayUpper, p.mountOn) && len(p.mountOn) > bestLen {
				best = dev
				bestLen = len(p.mountOn)
			}
		}
		if best != "" {
			return baseDevice(best)
		}
	}
	for dev, p := range parts {
		if p.mountOn == "/" {
			return baseDevice(dev)
		}
	}
	return ""
}

// partInfo 供 resolveRootDevice 引用（Disks 内部 pinfo 的导出镜像）。
type partInfo struct {
	totalKB, availKB int64
	mountOn          string
	ro               int
}

// diskReadOnly 解析 /proc/mounts 中 dev 对应挂载项的 options 是否含 "ro"。
func diskReadOnly(mounts, dev string) int {
	if mounts == "" || dev == "" {
		return 0
	}
	for _, line := range strings.Split(mounts, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}
		if fields[0] != dev {
			continue
		}
		opts := fields[3]
		for _, o := range strings.Split(opts, ",") {
			if o == "ro" {
				return 1
			}
		}
		return 0 // 找到该设备但非 ro
	}
	return 0
}
