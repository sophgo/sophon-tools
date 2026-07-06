package metrics

import (
	"strconv"
	"strings"
)

const (
	dfCmd     = "df"
	mountsPath = "/proc/mounts"
)

// Disks 采集磁盘列表。
// 源：df -Tk 输出，行首 /dev 且不含 loop。
// 字段：diskName=$1, total=(Used+Avail)/1024→MB, free=Avail/1024→MB,
//
//	Total = Used + Avail（不含 ext4 reserved），使 (1-Free/Total) = df Use%，
//	与 pget_info 口径一致。
//	mountOn=$7(Mounted on)。readOnly 从 /proc/mounts 解析对应设备 options 是否含 "ro"。
//	diskSn 留空（bmssm 亦始终为空），ioRate 留 0（bmssm 未实现）。
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
	var disks []Disk
	for _, line := range strings.Split(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 7 {
			continue
		}
		dev := fields[0]
		// 仅 /dev 设备，跳过 loop
		if !strings.HasPrefix(dev, "/dev") {
			continue
		}
		if strings.Contains(dev, "loop") {
			continue
		}
		usedKB, err := strconv.ParseInt(fields[3], 10, 64)
		if err != nil {
			continue
		}
		availKB, err := strconv.ParseInt(fields[4], 10, 64)
		if err != nil {
			continue
		}
		// 总容量 = Used + Avail（不含 ext4 reserved blocks），
		// 使 sophliteos usage = (1 - Free/Total) 与 df Use% 一致。
		totalKB := usedKB + availKB
		// mountOn：fields[6:] 拼接（防挂载点含空格）
		mountOn := strings.Join(fields[6:], " ")
		disks = append(disks, Disk{
			DiskName: dev,
			Total:    float64(totalKB / 1024), // 整数除法→MB，对齐 bmssm
			Free:     float64(availKB / 1024),
			MountOn:  mountOn,
			ReadOnly: diskReadOnly(mounts, dev),
		})
	}
	return disks
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
