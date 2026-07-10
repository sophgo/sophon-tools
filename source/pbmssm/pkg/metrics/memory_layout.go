package metrics

// MemoryLayout 返回设备内存布局：系统 + TPU + VPU + VPP 四区域（MB + 使用率 0-100）。
// 复用 Memory()/TpuMemory/VpuMemory/VppMemory（均经 c.readStr，root 可读 debugfs）。
// bytes→MB（/1024/1024，与 Memory().Total 的 kB→MB 口径区分：ion heap 原值是字节）。
func (c *Collector) MemoryLayout() MemoryLayout {
	chip := c.ChipType()
	sys := c.Memory()

	// 系统"已用"= total - free（free 缺失时回退 available），对齐前端旧逻辑。
	sysFree := sys.Free
	if sysFree <= 0 {
		sysFree = sys.Available
	}
	layout := MemoryLayout{
		ChipType: chip,
		System:   memRegionMBFloat(sys.Total, sys.Total-sysFree),
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
