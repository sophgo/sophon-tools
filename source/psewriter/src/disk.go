// 磁盘信息模型 + 安全分级策略 (平台无关)
//
// 安全策略 (需求: "自动避开本地磁盘"):
//  1. 含系统卷 (Windows 目录所在盘) → 危险, 永不可选
//  2. 可移动介质 / USB / SD / MMC 总线 → 安全, 默认可选
//  3. 其余 (SATA/NVMe/RAID/iSCSI 等固定盘) → 未确认, 默认隐藏, 需显式"显示全部"
//
// 无论哪一级, 烧录前都必须通过"详情+分区核对"二次确认。
package main

import (
	"fmt"
	"strings"
)

// Safety 安全分级
type Safety int

const (
	SafetySafe      Safety = iota // 可移动介质 / USB / SD: 默认可选
	SafetyUnknown                 // 固定盘等: 默认隐藏, 需人工放开
	SafetyDangerous               // 系统盘: 永不可选
)

func (s Safety) String() string {
	switch s {
	case SafetySafe:
		return "可安全烧录"
	case SafetyUnknown:
		return "需人工确认"
	default:
		return "系统盘(禁止)"
	}
}

// Partition 分区 (烧录会全部覆盖, 二次确认时展示)
type Partition struct {
	Index       int
	Offset      int64
	Size        int64
	FSType      string
	Label       string
	DriveLetter string // Windows: "E:"; Linux: 挂载点
}

// DiskInfo 物理磁盘
type DiskInfo struct {
	Index      int
	Path       string // \\.\PhysicalDriveN (Windows) / /dev/sdX (Linux)
	Model      string
	Size       int64
	BusType    string
	Removable  bool
	System     bool // 含系统卷
	Safety     Safety
	Reason     string
	Partitions []Partition
}

// DescribeLine 列表单行
func (d *DiskInfo) DescribeLine() string {
	flag := "[安全]"
	switch d.Safety {
	case SafetyDangerous:
		flag = "[禁止]"
	case SafetyUnknown:
		flag = "[确认]"
	}
	rm := "固定"
	if d.Removable {
		rm = "可移动"
	}
	return fmt.Sprintf("%s 磁盘%d | %-24s | %8s | %s(%s) | %d 个分区 | %s",
		flag, d.Index, truncate(d.Model, 24), HumanBytes(d.Size), d.BusType, rm, len(d.Partitions), d.Reason)
}

// DetailText 二次确认用详情 (命令行输出; 标签按显示宽度对齐, 中文双宽不再错位)
func (d *DiskInfo) DetailText() string {
	var b strings.Builder
	for _, kv := range d.PropertyRows() {
		fmt.Fprintf(&b, "%s: %s\n", padRight(kv[0], 12), kv[1])
	}
	fmt.Fprintf(&b, "\n分区现状 (烧录后将被全部覆盖):\n")
	rows := d.PartitionRows()
	if len(rows) == 0 {
		b.WriteString("  (无分区信息 / 空盘)\n")
	}
	for _, r := range rows {
		fmt.Fprintf(&b, "  %s  %10s @ %10s  %-8s %s %s\n", r[0], r[1], r[2], r[3], r[4], r[5])
	}
	return b.String()
}

// PropertyRows 目标磁盘的「项目/内容」两列信息 (界面表格与命令行共用, 单元测试覆盖)
func (d *DiskInfo) PropertyRows() [][2]string {
	removable := "固定"
	if d.Removable {
		removable = "可移动"
	}
	return [][2]string{
		{"设备路径", d.Path},
		{"磁盘号", fmt.Sprintf("磁盘 %d", d.Index)},
		{"型号", orDash(d.Model)},
		{"容量", HumanBytes(d.Size)},
		{"总线 / 介质", fmt.Sprintf("%s / %s", orDash(d.BusType), removable)},
		{"安全判定", fmt.Sprintf("%s（%s）", d.Safety, d.Reason)},
		{"分区数量", fmt.Sprintf("%d", len(d.Partitions))},
	}
}

// PartitionRows 分区现状 (界面表格列: #/大小/起始偏移/文件系统/卷标/盘符)
func (d *DiskInfo) PartitionRows() [][]string {
	if len(d.Partitions) == 0 {
		return nil
	}
	out := make([][]string, 0, len(d.Partitions))
	for _, p := range d.Partitions {
		out = append(out, []string{
			fmt.Sprintf("#%d", p.Index),
			HumanBytes(p.Size),
			HumanBytes(p.Offset),
			orDash(p.FSType),
			orDash(p.Label),
			orDash(p.DriveLetter),
		})
	}
	return out
}

// Classify 计算安全等级
func Classify(d *DiskInfo) {
	switch {
	case d.System:
		d.Safety, d.Reason = SafetyDangerous, "含系统盘卷 — 禁止选择"
	case d.Removable:
		d.Safety, d.Reason = SafetySafe, "可移动介质"
	case isRemovableBus(d.BusType):
		d.Safety, d.Reason = SafetySafe, d.BusType+" 总线"
	default:
		d.Safety, d.Reason = SafetyUnknown, d.BusType+" 固定盘 — 请人工确认"
	}
}

func isRemovableBus(bus string) bool {
	b := strings.ToUpper(bus)
	for _, k := range []string{"USB", "SD", "MMC", "1394"} {
		if strings.Contains(b, k) {
			return true
		}
	}
	return false
}

// VolumeExtent 系统卷在物理盘上占用的一段 (Windows 侧由 IOCTL 填充)
type VolumeExtent struct {
	DiskNumber     uint32
	StartingOffset int64
}

// markSystemDiskByOffset 兜底判定: 目标盘上若有分区的起始偏移与**同一块盘上**的
// 系统卷分区重合, 也算系统盘。
//
// 盘号必须一起比: 分区起始偏移在**各盘之间是会重复的** —— MBR 惯例从 LBA 2048
// 起分区, 每块盘的分区 1 都落在偏移 1 MiB (本工具自己写出来的卡就是这个偏移)。
// 只比偏移, 任何"用本工具做过或被标准工具分过"的可移动盘都会被误判成系统盘; 而
// SafetyDangerous 是**没有出口**的 (SelectableDisks 无条件剔除、"显示全部"救不回、
// CLI 的 --force 只对 SafetyUnknown 生效), 卡会直接从设备列表里消失, 用户会以为
// 工具坏了。跨盘比偏移在定义上也不成立 —— 系统卷只在它自己那块盘上。
func markSystemDiskByOffset(d *DiskInfo, sysParts []VolumeExtent) {
	for _, sp := range sysParts {
		if int(sp.DiskNumber) != d.Index {
			continue
		}
		for _, p := range d.Partitions {
			if p.Offset == sp.StartingOffset {
				d.System = true // Reason 由随后的 Classify 统一填
				return
			}
		}
	}
}

func truncate(s string, n int) string {
	r := []rune(strings.TrimSpace(s))
	if len(r) <= n {
		return string(r)
	}
	return string(r[:n-1]) + "…"
}

func orDash(s string) string {
	if strings.TrimSpace(s) == "" {
		return "-"
	}
	return s
}

// SelectableDisks 过滤出默认可见的磁盘 (安全 + 未确认; 系统盘恒排除; showAll 时含未确认)
func SelectableDisks(all []*DiskInfo, showAll bool) []*DiskInfo {
	out := make([]*DiskInfo, 0, len(all))
	for _, d := range all {
		if d.Safety == SafetyDangerous {
			continue
		}
		if d.Safety == SafetyUnknown && !showAll {
			continue
		}
		out = append(out, d)
	}
	return out
}
