package metrics

import "strings"

// ChipDisplayName 芯片对外显示名（SE13 产品命名，一处定义：
// sophliteos 前端透传 memoryLayout.chipType 显示"芯片名称"，不重复造映射）。
// cv84x6（SDK/内核标识）对外显示 CV84X6（2026-08-27 MYSWY 指示：型号名称统一用 CV84X6）；
// 其余芯片显示大写型号（bm1684x → BM1684X）。
func ChipDisplayName(chip string) string {
	if chip == "cv84x6" {
		return "CV84X6"
	}
	return strings.ToUpper(chip)
}

// MemoryLayout 返回设备内存布局：系统 + TPU + VPU + VPP 四区域（MB + 使用率 0-100）。
// 复用 Memory()/TpuMemory/VpuMemory/VppMemory（均经 c.readStr，root 可读 debugfs）。
// bytes→MB（/1024/1024，与 Memory().Total 的 kB→MB 口径区分：ion heap 原值是字节）。
func (c *Collector) MemoryLayout() MemoryLayout {
	chip := c.ChipType()
	sys := c.Memory()

	// 系统"已用"= total - available（buff/cache 可回收不计入真实占用）；
	// available 缺失时回退 free。
	sysAvail := sys.Available
	if sysAvail <= 0 {
		sysAvail = sys.Free
	}
	layout := MemoryLayout{
		// 对外输出显示名（cv84x6 → CV84X2），前端"芯片名称"透传此值
		ChipType: ChipDisplayName(chip),
		System:   memRegionMBFloat(sys.Total, sys.Total-sysAvail),
	}
	tpuT, tpuU := c.TpuMemory(chip)
	layout.TPU = memRegionMB(tpuT, tpuU)
	vpuT, vpuU := c.VpuMemory(chip)
	layout.VPU = memRegionMB(vpuT, vpuU)
	vppT, vppU := c.VppMemory(chip)
	layout.VPP = memRegionMB(vppT, vppU)
	return layout
}

// memRegionMB 字节 (total,used) → MemRegion（MB + 使用率）。
func memRegionMB(totalB, usedB int64) MemRegion {
	return memRegionMBFloat(float64(totalB)/1024/1024, float64(usedB)/1024/1024)
}

// memRegionKB KB (used,avail) → MemRegion（MB + 使用率）。total = used+avail，对齐 Disks 口径。
func memRegionKB(usedKB, availKB int64) MemRegion {
	usedMB := float64(usedKB) / 1024
	totalMB := float64(usedKB+availKB) / 1024
	return MemRegion{TotalMB: totalMB, UsedMB: usedMB, UsagePct: usagePct(totalMB, usedMB)}
}

// memRegionMBFloat MB (total,used) → MemRegion（+ 使用率，夹到 0-100）。
func memRegionMBFloat(totalMB, usedMB float64) MemRegion {
	return MemRegion{TotalMB: totalMB, UsedMB: usedMB, UsagePct: usagePct(totalMB, usedMB)}
}

// usagePct used/total*100，total<=0 返 0，结果夹到 [0,100]。
func usagePct(total, used float64) float64 {
	if total <= 0 {
		return 0
	}
	pct := used / total * 100
	if pct < 0 {
		pct = 0
	}
	if pct > 100 {
		pct = 100
	}
	return pct
}
