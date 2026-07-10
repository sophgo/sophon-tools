// Package compat 提供 bmssm 旧路径兼容层。
// 这些类型镜像 sophliteos 客户端（psophliteos/client/ssm/types.go）中的 bmssm 契约类型，
// 复制结构体定义是合理兼容所需，不是代码重复。
//
// 兼容路由挂载在 /bitmain/v1/ssm/*，不走 JWT Auth（匹配 sophliteos 实际行为：
// 其 getUrlHeader 中 Bearer 逻辑被注释，调用时不带 Authorization 头）。
//
// 推荐新客户端使用受 JWT 保护的正路 /api/v1/*。
package compat

import "bmssm/pkg/metrics"

// ---------------------------------------------------------------
// 请求类型
// ---------------------------------------------------------------

// LoginRequest 登录请求（对应 bmssm ReqLogin/sophliteos LoginRequest）。
type LoginRequest struct {
	UserName string `json:"userName"`
	Password string `json:"password"`
}

// IPSettings IP 设置请求（字段名对齐 sophliteos 前端：ipType/subnetMask + ipv6*）。
//   - IPType 1=静态 2=DHCP；IPv6Type 0=不配置 1=静态 2=DHCP（与 IPv4 独立）
//   - Mask/Prefix6 为 CIDR 或点分掩码，透传给 bm_set_ip
type IPSettings struct {
	Device     string `json:"device" validate:"required"`
	IPType     int    `json:"ipType" validate:"required"`
	IP         string `json:"ip"`
	SubnetMask string `json:"subnetMask"`
	Gateway    string `json:"gateway"`
	DNS        string `json:"dns"`
	IPv6Type   int    `json:"ipv6Type"`
	IPv6       string `json:"ipv6"`
	Prefix6    string `json:"prefix6"`
	Gateway6   string `json:"gateway6"`
	DNS6       string `json:"dns6"`
}

// BasicSettings 基本信息设置请求（对应 sophliteos BasicSettings）。
type BasicSettings struct {
	Name string `json:"deviceName" validate:"required"`
	Type string `json:"deviceType" validate:"required"`
}

// AlarmThreshold 告警阈值配置（对应 sophliteos AlarmThreshold）。
type AlarmThreshold struct {
	BoardTemperature int     `json:"boardTemperature"`
	CoreTemperature  int     `json:"coreTemperature"`
	CpuRate          float64 `json:"cpuRate"`
	DiskRate         float64 `json:"diskRate"`
	TotalMemoryScale float64 `json:"totalMemoryScale"`
	TpuScale         float64 `json:"tpuScale"`
	TpuRate          float64 `json:"tpuRate"`
}

// SubscribeRequest 告警订阅请求（对应 sophliteos AlarmSubscribe）。
type SubscribeRequest struct {
	Platform            string `json:"platform"`
	SubscribeDetailType []int  `json:"subscribeDetailType"`
	NotificationURL     string `json:"notificationUrl"`
}

// AddTable NAT 规则添加请求（对应 sophliteos AddTable）。
type AddTable struct {
	Dirt     string `json:"dirt"`
	Op       string `json:"op"`
	Src      string `json:"src"`
	SrcPort  string `json:"srcPort"`
	Dst      string `json:"dst"`
	DstPort  string `json:"dstPort"`
	Protocol string `json:"protocol"`
}

// CoreOpe 核心板操作请求（对应 sophliteos CoreOpe）。
type CoreOpe struct {
	Id int `json:"id"`
}

// OtaVersion 固件升级版本请求（对应 sophliteos OtaVersion）。
type OtaVersion struct {
	Name       string `json:"name"`
	Product    string `json:"product"`
	FileName   string `json:"fileName"`
	ModuleName string `json:"moduleName"`
	CmdFlag    string `json:"cmdFlag"`
	Version    string `json:"version"`
	FlashData  bool   `json:"flashData"`
}

// ---------------------------------------------------------------
// 响应类型
// ---------------------------------------------------------------

// SystemLoginResponse 系统登录响应（对应 bmssm RespLogin/sophliteos SystemLoginResponse）。
type SystemLoginResponse struct {
	Token      string `json:"token"`
	Role       string `json:"role"`
	ChangePass bool   `json:"changePass,omitempty"`
}

// Ip IP 信息（对应 sophliteos Ip）。
type Ip struct {
	NetCardName string   `json:"netCardName"`
	Bandwidth   int      `json:"bandwidth"`
	DeltaRx     int      `json:"deltaRx"`
	DeltaTx     int      `json:"deltaTx"`
	DNS         []string `json:"dns"`
	Dynamic     int      `json:"dynamic"`
	Gateway     string   `json:"gateway"`
	IP          string   `json:"ip"`
	Mac         string   `json:"mac"`
	Name        string   `json:"name"`
	NetMask     string   `json:"netMask"`
	NetRx       float64  `json:"netRx"`
	NetTx       float64  `json:"netTx"`
	Rate        int      `json:"rate"`
	IPs         []string `json:"ips"` // 全部地址（ip/prefix，含 IPv4+IPv6）
}

// IPInfo IP 信息简单形式（对应 sophliteos IPInfo）。
type IPInfo struct {
	IP string `json:"ip"`
}

// CtrlBasic 控制板基础信息（对应 sophliteos CtrlBasic）。
type CtrlBasic struct {
	ChipSn    string             `json:"chipSn"`
	Configure CtrlBasicConfigure `json:"configure"`
	IpList    []IPInfo           `json:"ipList"`
	System    CtrlBasicSystem    `json:"system"`
}

// CtrlBasicConfigure 控制板配置信息。
type CtrlBasicConfigure struct {
	AgencyModule   []AgencyModuleItem   `json:"agencyModule"`
	AlarmThreshold AlarmThreshold       `json:"alarmThreshold"`
	Basic          BasicInfo            `json:"basic"`
	ServiceAddress ServiceAddressConfig `json:"serviceAddress"`
}

// AgencyModuleItem 代理模块配置项。
type AgencyModuleItem struct {
	Module    string                `json:"module"`
	Parameter AgencyModuleParameter `json:"parameter"`
	Switch    string                `json:"switch"`
}

// AgencyModuleParameter 代理模块参数。
type AgencyModuleParameter struct {
	CacheNum int `json:"cacheNum"`
	Interval int `json:"interval"`
}

// BasicInfo 基本信息。
type BasicInfo struct {
	DeviceName string `json:"deviceName"`
	DeviceType string `json:"deviceType"`
}

// ServiceAddressConfig 服务地址配置（bmlib 依赖字段，降级返空）。
type ServiceAddressConfig struct {
	Event                 interface{} `json:"event"`
	Keepalive             interface{} `json:"keepalive"`
	OperatingNotification interface{} `json:"operatingNotification"`
	Register              interface{} `json:"register"`
}

// CtrlBasicSystem 系统信息。
type CtrlBasicSystem struct {
	AgencyServiceRunTime string `json:"agencyServiceRunTime"`
	OperatingSystem      string `json:"operatingSystem"`
	Runtime              string `json:"runtime"`
	BmssmVersion         string `json:"bmssmVersion"`
	BuildTime            string `json:"buildTime"`
	SdkVersion           string `json:"sdkVersion"`
	DeviceType           string `json:"deviceType"`
	DeviceTypeEx         string `json:"deviceTypeEx"`
}

// CtrlResource 控制板算力信息（对应 sophliteos CtrlResource）。
type CtrlResource struct {
	DeviceSn              string                `json:"deviceSn"`
	DeviceType            string                `json:"deviceType"`
	DeviceModel           string                `json:"deviceModel"`
	CollectDateTime       string                `json:"collectDateTime"`
	Sslots                []interface{}         `json:"sslots"`
	CentralProcessingUnit CentralProcessingUnit `json:"centralProcessingUnit"`
	CoreComputingUnit     CoreComputingUnit     `json:"coreComputingUnit"`
	MemoryLayout          metrics.MemoryLayout  `json:"memoryLayout"`
	DiskLayout            metrics.DiskLayout    `json:"diskLayout"`
}

// CentralProcessingUnit 中央处理单元。
type CentralProcessingUnit struct {
	BmssmVersion string    `json:"bmssmVersion"`
	BuildTime    string    `json:"buildTime"`
	Cpu          CPU       `json:"cpu"`
	Memory       Memory    `json:"memory"`
	Disk         []Disk    `json:"disk"`
	NetCard      []NetCard `json:"netCard"`
}

// CPU CPU 信息。
type CPU struct {
	Frequency       int     `json:"frequency"`
	Cores           float64 `json:"cores"`
	UtilizationRate float64 `json:"utilizationRate"`
	Type            string  `json:"type"`
	Arch            string  `json:"arch"`
}

// Memory 内存信息。
type Memory struct {
	Total     float64 `json:"total"`
	Free      float64 `json:"free"`
	Available float64 `json:"available"`
}

// Disk 磁盘信息。
type Disk struct {
	DiskName string  `json:"diskName"`
	DiskSn   string  `json:"diskSn"`
	Total    float64 `json:"total"`
	Free     float64 `json:"free"`
	IoRate   int     `json:"ioRate"`
	MountOn  string  `json:"mountOn"`
}

// NetCard 网卡信息。
type NetCard struct {
	IP          string   `json:"ip"`
	Mask        string   `json:"netMask"`
	Mac         string   `json:"mac"`
	Dns         []string `json:"dns"`
	Gateway     string   `json:"gateway"`
	Bandwidth   int      `json:"bandwidth"`
	Dynamic     int      `json:"dynamic"`
	NetRx       float64  `json:"netRx"`
	NetTx       float64  `json:"netTx"`
	Rate        int      `json:"rate"`
	NetCardName string   `json:"netCardName"`
	IPs         []string `json:"ips"` // 全部地址（ip/prefix，含 IPv4+IPv6）
}

// CoreComputingUnit 核心计算单元（bmlib 依赖，降级为空）。
type CoreComputingUnit struct {
	Board []CoreBoard `json:"board"`
}

// CoreBoard 核心板信息。
type CoreBoard struct {
	BoardSn           string     `json:"boardSn"`
	SdkVersion        string     `json:"sdkVersion"`
	BoardType         string     `json:"boardType"`
	BoardHost         string     `json:"boardHost"`
	UpdateTime        string     `json:"updateTime"`
	CurrentBoardPower int        `json:"currentBoardPower"`
	FanspeedPercent   int        `json:"fanspeedPercent"`
	MaxBoardPower     int        `json:"maxBoardPower"`
	Temperature       int        `json:"temperature"`
	Chip              []ChipInfo `json:"chip"`
	CoreSys           CoreSystem `json:"coreSys"`
}

// ChipInfo 芯片信息。
type ChipInfo struct {
	ChipSn                  string  `json:"chipSn"`
	CalculationCapacity     float64 `json:"calculationCapacity"`
	CalculationCapacityInt8 float64 `json:"calculationCapacityInt8"`
	CalculationCapacityFp16 float64 `json:"calculationCapacityFp16"`
	CalculationCapacityFp32 float64 `json:"calculationCapacityFp32"`
	Memory                  Memory  `json:"memory"`
	Slot                    string  `json:"slot"`
	Health                  int     `json:"health"`
	Temperature             int     `json:"temperature"`
	UtilizationRate         int     `json:"utilizationRate"`
	ChipType                int     `json:"chipType"`
}

// CoreSystem 核心系统信息。
type CoreSystem struct {
	BmssmVersion string    `json:"bmssmVersion"`
	BuildTime    string    `json:"buildTime"`
	Cpu          CPU       `json:"cpu"`
	Mem          Memory    `json:"memory"`
	Disks        []Disk    `json:"disk"`
	NetCards     []NetCard `json:"netCard"`
}
