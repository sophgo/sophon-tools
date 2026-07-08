// Package global 存放进程级单例状态，由 initialization 在启动阶段填充。
package global

import "time"

var (
	// 设备信息，由 pkg/device.GetDeviceInfo 填充
	DeviceType   string // pcie / soc / unknown
	DeviceRole   string // SE / SE-CTRL / SE-CORE
	DeviceTypeEx string
	DeviceSnEx   string
	ChipSn       string
	ModuleType   string // CHIP 键（如 BM1688），供 metrics.ChipCapacity 查算力
	ModuleTypeEx string // MODULE_TYPE 键（如 16-BP1-11），供拼接 DEVICE_MODEL

	// 服务信息
	Started time.Time
)

// BuildInfo 由 ldflags 注入。
type BuildInfo struct {
	Version   string
	GitCommit string
	BuildTime string
}

func (b BuildInfo) String() string {
	return b.Version + " (" + b.GitCommit + " @ " + b.BuildTime + ")"
}