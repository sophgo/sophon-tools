package metrics

// CPU CPU 指标快照（镜像 compat.CPU 字段，但属 metrics 包，避免与 compat 循环依赖）。
type CPU struct {
	Frequency       int     // MHz
	Cores           float64 // 核数
	UtilizationRate float64 // 百分比
	Type            string  // 型号
	Arch            string  // 架构
}

// Memory 内存指标快照（MB，对齐 bmssm：kB/1024）。
type Memory struct {
	Total     float64
	Free      float64
	Available float64
}

// Disk 磁盘指标快照（MB，对齐 bmssm：df KB/1024）。
type Disk struct {
	DiskName string
	DiskSn   string
	Total    float64
	Free     float64
	IoRate   int
	MountOn  string
	ReadOnly int
}

// NetCard 网卡指标快照。
type NetCard struct {
	Name      string
	IP        string // 首个 IPv4（扁平，向后兼容）
	Mask      string
	Mac       string
	Bandwidth int
	NetRx     float64
	NetTx     float64
	IPs       []string // 全部地址（"ip/prefix" 形式，含 IPv4+IPv6）
}

// MemRegion 一个内存区域的总量/已用/使用率（MB / 百分比 0-100）。
type MemRegion struct {
	TotalMB  float64 `json:"totalMB"`
	UsedMB   float64 `json:"usedMB"`
	UsagePct float64 `json:"usagePct"`
}

// MemoryLayout 设备内存布局：系统 + TPU + VPU + VPP 四区域。
// VPU 在无该堆的芯片（如 BM1688/CV186AH）上全 0，前端据 ChipType 隐藏；
// VPP 在 BM1688 前端称 VPSS。MB 单位，使用率 0-100。
type MemoryLayout struct {
	System   MemRegion `json:"system"`
	TPU      MemRegion `json:"tpu"`
	VPU      MemRegion `json:"vpu"`
	VPP      MemRegion `json:"vpp"`
	ChipType string    `json:"chipType"`
}

// DiskLayout 设备磁盘布局：eMMC 整体 + 各 eMMC 分区（MB + 使用率 0-100）。
// eMMC 整体 = 所有 /dev/mmcblk0* 分区之和；Partitions 为各分区（排除 p3/p4），
// 按分区号升序。缺失项（无 eMMC）时整体全 0、列表空。
type DiskLayout struct {
	EmmcOverall MemRegion  `json:"emmcOverall"`
	Partitions  []DiskPart `json:"partitions"`
}

// DiskPart 一个 eMMC 分区的使用情况（MB + 使用率）+ 设备名/挂载点。
// MemRegion 字段经 JSON 提升扁平输出（totalMB/usedMB/usagePct）。
type DiskPart struct {
	Device  string `json:"device"`  // /dev/mmcblk0p1
	MountOn string `json:"mountOn"` // /boot
	MemRegion
}
