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
	IP        string
	Mask      string
	Mac       string
	Bandwidth int
	NetRx     float64
	NetTx     float64
}
