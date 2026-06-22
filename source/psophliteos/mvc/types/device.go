package types

import (
	"time"
)

// Name设置
type NameSetting struct {
	Name string `json:"deviceName" validate:"required"`
	Type string `json:"deviceType" validate:"required"`
}

// IP设置
type IpSetting struct {
	// wan lan
	Device string `json:"device" validate:"required"`
	Name   string `json:"name"`
	//ip类型 1静态ip 2动态ip
	IPType int `json:"ipType" validate:"required"`
	//ip地址
	IP string `json:"ip"`
	//子网掩码
	SubnetMask string `json:"subnetMask"`
	//网关
	Gateway string `json:"gateway"`
	//dns
	DNS string `json:"dns"`
}

// 设备信息
type Resource struct {
	DeviceSn          string            `json:"deviceSn"`
	TpuMax            string            `json:"tpuMax"`
	CtrlBoardSn       string            `json:"ctrlBoardSn"`
	DeviceName        string            `json:"deviceName"`
	DeviceType        string            `json:"deviceType"`
	SdkVersion        string            `json:"sdkVersion"`
	WanIP             string            `json:"wanIp"`
	LanIP             string            `json:"lanIp"`
	OperatingSystem   string            `json:"operatingSystem"`
	RunTime           string            `json:"runTime"`
	BuildTime         string            `json:"buildTime"`
	BmssmVersion      string            `json:"bmssmVersion"`
	DeviceIP          string            `json:"deviceIp"`
	IPList            []IPInfo          `json:"ipList"`
	Cpu               CPU               `json:"cpu"`
	Memory            Memory            `json:"memory"`
	Disk              []Disk            `json:"disk"`
	NetCard           []NetCard         `json:"netCard"`
	CoreComputingUnit CoreComputingUnit `json:"coreComputingUnit"`
	Int8Count         ResourceCount     `json:"int8Count"`
	Fp16Count         ResourceCount     `json:"fp16Count"`
	Fp32Count         ResourceCount     `json:"fp32Count"`
	CpuCount          ResourceCount     `json:"cpuCount"`
	MemoryCount       ResourceCount     `json:"memoryCount"`
	EMMCCount         ResourceCount     `json:"eMMCCount"`
	DiskCount         ResourceCount     `json:"diskCount"`
}

type ResourceCount struct {
	Health    int     `json:"health"`
	UnHealth  int     `json:"unHealth"`
	Available float64 `json:"available"`
	Total     float64 `json:"total"`
	Unit      string  `json:"unit"`
	Desc      string  `json:"desc"`
}

type CPU struct {
	Cores     float64 `json:"cores"`
	Frequency int     `json:"frequency"`
	Usage     float64 `json:"usage"`
	Type      string  `json:"type"`
	Arch      string  `json:"arch"`
}

type Memory struct {
	Total float64 `json:"total"`
	Usage float64 `json:"usage"`
}

type Disk struct {
	ID    string  `json:"id"`
	Total float64 `json:"total"`
	Usage float64 `json:"usage"`
}

type NetCard struct {
	Ip        string  `json:"ip"`
	Name      string  `json:"name"`
	Bandwidth int     `json:"bandwidth"`
	Mac       string  `json:"mac"`
	NetIn     float64 `json:"netIn"`
	NetOut    float64 `json:"netOut"`
}

type CoreComputingUnit struct {
	Board []Board `json:"board"`
}

type IPInfo struct {
	IP string `json:"ip"`
}

type Board struct {
	BoardSn     string    `json:"boardSn"`
	SdkVersion  string    `json:"sdkVersion"`
	BoardType   string    `json:"boardType"`
	Temperature int       `json:"temperature"`
	FanSpeed    int       `json:"fanSpeed"`
	Cpu         CPU       `json:"cpu"`
	Memory      Memory    `json:"memory"`
	Disk        []Disk    `json:"disk"`
	NetCard     []NetCard `json:"netCard"`
	Chip        []Chip    `json:"chip"`
	Number      int       `json:"number"`
}

type Chip struct {
	Slot                          string   `json:"slot"`
	ChipIndex                     int      `json:"chipIndex"`
	Health                        int      `json:"health"`
	Temperature                   int      `json:"temperature"`
	MemoryUsedBytes               int64    `json:"memoryUsedBytes"`
	MemoryTotalBytes              int64    `json:"memoryTotalBytes"`
	ChipTemperatureCelsius        int      `json:"chipTemperatureCelsius"`
	TpuUtililizationRate          int      `json:"tpuUtililizationRate"`
	TheoretialCalculationCapacity float64  `json:"theoretialCalculationCapacity"`
	Deploys                       []Deploy `json:"deploys"`
}

type Deploy struct {
	AppID  string        `json:"appId"`
	Status int           `json:"status"`
	Chips  []interface{} `json:"chips"`
}

type AlarmSetting struct {
	FanSpeed             int     `json:"fanSpeed"`             // 	风扇转速
	BoardTemperature     float64 `json:"boardTemperature"`     //	主板温度
	CoreTemperature      float64 `json:"coreTemperature"`      //	芯片结温
	CPURate              float64 `json:"cpuRate"`              //  cpu使用率
	TotalMemoryScale     float64 `json:"totalMemoryScale"`     //  总内存使用率
	SystemScale          float64 `json:"systemScale"`          //  system内存使用率
	VideoScale           float64 `json:"videoScale"`           //  video内存使用率
	TpuScale             float64 `json:"tpuScale"`             //  tpu内存使用率
	DiskRate             float64 `json:"diskRate"`             //  外挂存储使用率
	ExternalHardDiskRate float64 `json:"externalHardDiskRate"` //  存储使用率
}

type SsmList struct {
	CtrlSsm struct {
		DeviceSn string `json:"deviceSn"`
		Ip       string `json:"host"`
		Version  string `json:"version"`
	} `json:"ctrlSsm"`
	CoreSsm []SsmVersion `json:"coreSsm"`
}

type SsmVersion struct {
	ChipIndex int    `json:"chipIndex"`
	Ip        string `json:"host"`
	DeviceSn  string `json:"deviceSn"`
	Version   string `json:"version"`
}

type AlarmQuery struct {
	StartTime time.Time `json:"startTime"`
	EndTime   time.Time `json:"endTime"`
	EventType int       `json:"eventType"`
	PageNo    int       `json:"pageNo"`
	PageSize  int       `json:"pageSize"`
}

type PasswordModify struct {
	Password    string `json:"password" validate:"required"`
	NewPassword string `json:"newPassword" validate:"required"`
}
