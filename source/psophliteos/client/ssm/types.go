package ssm

import (
	types "sophliteos/mvc/types"
	"time"
)

const (
	TimeFormat = "2006-01-02 15:04:05"
	Reboot     = 1
	Shutdown   = 2
	Awaken     = 3
)

// SSM 结果集
type SsmResult struct {
	Code         int         `json:"code"`
	Msg          string      `json:"msg"`
	ErrorCode    int         `json:"error_code"`
	ErrorMessage string      `json:"error_message"`
	DeviceSn     string      `json:"deviceSn"`
	Result       interface{} `json:"result"`
}

// SSM 授权
type SsmAuth struct {
	Auth       string
	Token      string
	LoginTime  time.Time
	ExpireTime time.Time
}

// SSM IPSetting参数
type IPSettings struct {
	Device  string `json:"device" validate:"required"` // 网卡名称
	Policy  string `json:"policy" validate:"required"` // IP 分配方式(dhcp 或 static)
	IP      string `json:"ip"`                         // 指定静态 IP
	Mask    string `json:"mask"`                       // 指定子网掩码
	Gateway string `json:"gateway"`                    // 指定网关
	DNS     string `json:"dns"`                        // 指定 DNS 服务器
}

// SSM BasicSetting参数
type BasicSettings struct {
	Name string `json:"deviceName" validate:"required"`
	Type string `json:"deviceType" validate:"required"`
}

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
}

type Se6Ip struct {
	Enp3S0 Ip `json:"enp3s0"`
	Enp4S0 Ip `json:"enp4s0"`
	Enp6S0 Ip `json:"enp6s0"`
	Eth0   Ip `json:"eth0"`
	Eth1   Ip `json:"eth1"`
}

// 控制板基础信息
type CtrlBasic struct {
	ChipSn    string `json:"chipSn"`
	Configure struct {
		AgencyModule []struct {
			Module    string `json:"module"`
			Parameter struct {
				CacheNum int `json:"cacheNum"`
				Interval int `json:"interval"`
			} `json:"parameter"`
			Switch string `json:"switch"`
		} `json:"agencyModule"`
		AlarmThreshold AlarmThreshold `json:"alarmThreshold"`
		Basic          struct {
			DeviceName string `json:"deviceName"`
			DeviceType string `json:"deviceType"`
		} `json:"basic"`
		ServiceAddress struct {
			Event                 interface{} `json:"event"`
			Keepalive             interface{} `json:"keepalive"`
			OperatingNotification interface{} `json:"operatingNotification"`
			Register              interface{} `json:"register"`
		} `json:"serviceAddress"`
	} `json:"configure"`

	IpList []types.IPInfo `json:"ipList"`

	System struct {
		AgencyServiceRunTime string `json:"agencyServiceRunTime"`
		OperatingSystem      string `json:"operatingSystem"`
		Runtime              string `json:"runtime"`
		BmssmVersion         string `json:"bmssmVersion"`
		BuildTime            string `json:"buildTime"`
		SdkVersion           string `json:"sdkVersion"`
	} `json:"system"`
}

type AlarmThreshold struct {
	BoardTemperature     int     `json:"boardTemperature"`
	CoreTemperature      int     `json:"coreTemperature"`
	CpuRate              float64 `json:"cpuRate"`
	DiskRate             float64 `json:"diskRate"`
	ExternalHardDiskRate float64 `json:"externalHardDiskRate"`
	FanSpeed             int     `json:"fanSpeed"`
	SystemScale          float64 `json:"systemScale"`
	TotalMemoryScale     float64 `json:"totalMemoryScale"`
	TpuScale             float64 `json:"tpuScale"`
	TpuRate              float64 `json:"tpuRate"`
	VideoScale           float64 `json:"videoScale"`
}

// 控制板算力信息
type CtrlResource struct {
	DeviceSn              string                `json:"deviceSn"`
	DeviceModel           string                `json:"deviceModel"`
	CollectDateTime       string                `json:"collectDateTime"`
	Sslots                []interface{}         `json:"sslots"`
	CentralProcessingUnit CentralProcessingUnit `json:"centralProcessingUnit"`
	CoreComputingUnit     CoreComputingUnit     `json:"coreComputingUnit"`
}

type CentralProcessingUnit struct {
	BmssmVersion string    `json:"bmssmVersion"`
	BuildTime    string    `json:"buildTime"`
	Cpu          CPU       `json:"cpu"`
	Memory       Memory    `json:"memory"`
	Disk         []Disk    `json:"disk"`
	NetCard      []NetCard `json:"netCard"`
}

type CPU struct {
	Frequency       int     `json:"frequency"`       // 主频(MHz)
	Cores           float64 `json:"cores"`           // 核心数
	UtilizationRate float64 `json:"utilizationRate"` // 使用率
	Type            string  `json:"type"`
	Arch            string  `json:"arch"`
}

type Memory struct {
	Total     float64 `json:"total"`
	Free      float64 `json:"free"`
	Available float64 `json:"available"`
	// Cached    float64 `json:"cached"`
	// Buffers   float64 `json:"buffers"`
}

type Disk struct {
	DiskName string  `json:"diskName"`
	DiskSn   string  `json:"diskSn"`
	Total    float64 `json:"total"`
	Free     float64 `json:"free"`
	IoRate   int     `json:"ioRate"`
	MountOn  string  `json:"mountOn"`
}

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
}

type CoreComputingUnit struct {
	Board []struct {
		BoardSn    string `json:"boardSn"`
		SdkVersion string `json:"sdkVersion"`
		BoardType  string `json:"boardType"`
		BoardHost  string `json:"boardHost"`
		UpdateTime string `json:"updateTime"`
		// BoardHost         string `json:"boardHost"`
		// BoardHost         string `json:"boardHost"`
		CurrentBoardPower int `json:"currentBoardPower"`
		FanspeedPercent   int `json:"fanspeedPercent"`
		MaxBoardPower     int `json:"maxBoardPower"`
		Temperature       int `json:"temperature"`
		Chip              []struct {
			ChipIndex               string  `json:"chipSn"`
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
		} `json:"chip"`
		CoreSys struct {
			BmssmVersion string    `json:"bmssmVersion"`
			BuildTime    string    `json:"buildTime"`
			Cpu          CPU       `json:"cpu"`
			Mem          Memory    `json:"memory"`
			Disks        []Disk    `json:"disk"`
			NetCards     []NetCard `json:"netCard"`
		} `json:"coreSys"`
	} `json:"board"`
}

type AlarmSubscribe struct {
	Platform            string `json:"platform"`
	SubscribeDetailType []int  `json:"subscribeDetailType"`
	NotificationURL     string `json:"notificationUrl"`
}

type Scp2Core struct {
	SrcCtrl  string `json:"src"`
	DstCore  string `json:"dst"`
	CtrlUser string `json:"ctrl_user"`
	CtrlPwd  string `json:"ctrl_pwd"`
	CoreUser string `json:"core_user"`
	CorePwd  string `json:"core_pwd"`
}

type ExecCorex struct {
	Cmd   string `json:"cmd"`
	User  string `json:"user"`
	Pwd   string `json:"pwd"`
	DevId string `json:"dev_id"`
}
type AlarmNotice struct {
	DeviceSn            string `json:"deviceSn"`
	ComponentType       int    `json:"componentType"`       //1中央处理单元部分，2核心计算单元部分
	ControllerUnitSn    string `json:"contorllerUnitSn"`    // componentType=1，此字段生效
	CoreUnitBoardSn     string `json:"coreUnitBoardSn"`     // componentType=2，此字段生效
	CoreUnitBoardChipSn string `json:"coreUnitBoardChipSn"` //如果是PCIE插卡模式，此字段生效
	Code                int    `json:"code"`
	Msg                 string `json:"msg"`
}

type OtaFile struct {
	Body     []byte `json:"file"`
	Module   string `json:"module"`
	Filename string `json:"filename"`
}

type OtaVersion struct {
	Name       string `json:"name"`
	Product    string `json:"product"`
	FileName   string `json:"fileName"`
	ModuleName string `json:"moduleName"`
	CmdFlag    string `json:"cmdFlag"`
}

type OtaTask struct {
	LastRebootTime Time   `json:"LastRebootTime"`
	CmdFlag        string `json:"cmdFlag"`
	CreateTime     Time   `json:"createTime"`
	FileName       string `json:"fileName"`
	Info           string `json:"info"`
	ModuleName     string `json:"moduleName"`
	Name           string `json:"name"`
	Product        string `json:"product"`
	Status         int    `json:"status"`
	Step           string `json:"step"`
	Strategy       string `json:"strategy"`
	Type           int    `json:"type"`
	UserID         string `json:"userId"`
	Version        string `json:"version"`
	WorkflowID     int    `json:"workflowId"`
}

type CoreOpe struct {
	Id int `json:"id"`
}

type SystemLoginResponse struct {
	Token string `json:"token"`
	Role  string `json:"role"`
}

type DeviceLoginResponse struct {
	DeviceIPList []string `json:"deviceIpList"`
	DeviceName   string   `json:"deviceName"`
	DeviceSn     string   `json:"deviceSn"`
	DeviceType   string   `json:"deviceType"`
	Token        string   `json:"token"`
}

type CoreOperation struct {
	Type   int `json:"type"`    // 操作类型： 1：重启 2：关机 3：唤醒（暂不支持）
	Number int `json:"devices"` // 核心板序号
}

type Time time.Time

func (t *Time) UnmarshalJSON(data []byte) (err error) {
	now, err := time.ParseInLocation(`"`+time.RFC3339Nano+`"`, string(data), time.Local)
	*t = Time(now)
	return
}

func (t Time) MarshalJSON() ([]byte, error) {
	b := make([]byte, 0, len(TimeFormat)+2)
	b = append(b, '"')
	b = time.Time(t).AppendFormat(b, TimeFormat)
	b = append(b, '"')
	return b, nil
}

func (t Time) String() string {
	return time.Time(t).Format(TimeFormat)
}

type AddTable struct {
	Dirt     string `json:"dirt"`
	Op       string `json:"op"`
	Src      string `json:"src"`
	SrcPort  string `json:"srcPort"`
	Dst      string `json:"dst"`
	DstPort  string `json:"dstPort"`
	Protocol string `json:"protocol"`
}
