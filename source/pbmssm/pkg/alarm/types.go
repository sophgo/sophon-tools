// Package alarm 实现设备告警监控引擎：周期采集 pkg/metrics 指标，对比 config
// alarmThreshold 阈值，超限生成告警并 POST 到 compat 订阅存储的 callback URL。
//
// 设计对齐 bmssm pkg/configure/alarm.go 的 eventProcess：
//   - code 体系、ComponentType 派生（Abs(code/100000)）、边沿检测（恢复发正 code）
//   - payload 用 AlarmRec 形状，匹配 sophliteos api/v1/system/sys_base.go AlarmListen
//     实际 unmarshal 的 database.AlarmRec 契约（deviceSn/componentType/boardSn/
//     chipSn/diskName/dateTime/code/msg）。
//
// 引擎只 POST 记录，不 reboot/flash。所有指标读取降级安全（失败返零值不 panic）。
package alarm

import (
	"bmssm/pkg/metrics"
)

// ---------------------------------------------------------------
// code 体系（对齐 bmssm parseAlarmCode）
// ---------------------------------------------------------------
//
// 负 code = 告警；正 code = 恢复。ComponentType = Abs(code/100000)：
//   101xxx/102xxx/103xxx → 1（中央处理单元）
//   201xxx/202xxx        → 2（核心计算单元）
const (
	CodeCPURateAlarm    = -101001
	CodeCPURateRecover  = 101001
	CodeMemRateAlarm    = -102001
	CodeMemRateRecover  = 102001
	CodeDiskRateAlarm   = -103001
	CodeDiskRateRecover = 103001
	CodeBoardTempAlarm  = -201001
	CodeBoardTempRecover = 201001
	CodeChipTempAlarm   = -202001
	CodeChipTempRecover = 202001
	CodeTPURateAlarm    = -202003
	CodeTPURateRecover  = 202003
)

// EventId 告警类别（边沿检测用）。
type EventId int

const (
	CPU_RATE EventId = iota
	MEM_RATE
	DISK_RATE
	BOARD_TEMP
	TPU_TEMP
	TPU_RATE
	numEventIds
)

// AlarmRec 告警 payload，json 字段对齐 sophliteos database.AlarmRec（AlarmListen 入站契约）。
// 注意 ChipIdx 在 bmssm 出站结构里 json tag 是 "chipSn"，sophliteos 入站也是 "chipSn"。
type AlarmRec struct {
	DeviceSn      string `json:"deviceSn"`
	ComponentType int    `json:"componentType"`
	ChipSn        string `json:"chipSn"`
	DiskName      string `json:"diskName"`
	BoardSn       string `json:"boardSn"`
	DateTime      string `json:"dateTime"`
	Code          int    `json:"code"`
	Msg           string `json:"msg"`
}

// Thresholds 告警阈值（已转为整数：百分比 0-100，温度 ℃）。
// 引擎从 config alarmThreshold 读取（0-1 小数 *100）。
type Thresholds struct {
	CpuRate          int // %
	TotalMemoryScale int // %
	DiskRate         int // %
	BoardTemperature int // ℃
	CoreTemperature  int // ℃
	TpuRate          int // %
}

// MetricsReader 告警引擎所需的指标采集子集（*metrics.Collector 实现之）。
type MetricsReader interface {
	CPUInfo() metrics.CPU
	Memory() metrics.Memory
	Disks() []metrics.Disk
	ChipTemp() int
	BoardTemp() int
	TPUUsage() int
}

// SubscriptionLister 提供告警订阅 callback URL 列表。
// 生产实现由 compat.CompatService 适配（ListSubscriptions → NotificationURL）。
type SubscriptionLister interface {
	CallbackURLs() []string
}

// Poster POST 告警 payload 到 callback URL。失败仅记日志不阻断。
type Poster interface {
	Post(url string, payload []byte) error
}

// Logger 日志接口（避免直接依赖 logger 包，便于测试）。
type Logger interface {
	Infof(format string, v ...interface{})
	Errorf(format string, v ...interface{})
}

// Recorder 告警历史落库接口（依赖注入，由 mvc/alarm 实现）。
// Record 应为 best-effort：失败仅返错，由引擎记日志不阻断。
// pkg/alarm 不依赖 mvc/alarm，避免循环依赖；wiring 在 initialization。
type Recorder interface {
	Record(rec AlarmRec) error
}

// errPostFailed 测试用哨兵错误。
var errPostFailed = &postError{}

type postError struct{}

func (e *postError) Error() string { return "post failed" }
