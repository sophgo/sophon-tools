// Package alarm 初始化入口。Init() 由 initialization.InitBase 在设备信息就绪后调用，
// 启动后台监控 goroutine，每 30s 采集指标→比对阈值→POST 到 compat 订阅 callback。
package alarm

import (
	"context"
	"time"

	"ssm/config"
	"ssm/global"
	"ssm/logger"
	"ssm/mvc/compat"
	"ssm/pkg/metrics"
)

// defaultInterval 默认采集间隔，对齐 bmssm agencyModule.parameter.interval≤0 时 30s。
const defaultInterval = 30 * time.Second

// Init 创建并启动告警引擎（生产装配）。
//   - 指标：metrics.NewDefaultCollector（CPU 双采样约 100ms，30s 间隔无压力）
//   - 订阅：compat.DefaultCompatService（适配为 CallbackURLs）
//   - 阈值：config alarmThreshold（0-1 小数 *100 转整数百分比）
//   - 设备信息：global.DeviceSnEx / ChipSn（InitBase 已填充）
func Init() {
	deviceSn := global.DeviceSnEx
	boardSn := global.ChipSn
	if boardSn == "" {
		boardSn = deviceSn
	}
	chipSn := global.ChipSn
	if chipSn == "" {
		chipSn = deviceSn
	}

	th := loadThresholds()

	eng := NewEngine(
		metrics.NewDefaultCollector(),
		&compatSubLister{svc: compat.DefaultCompatService()},
		NewHTTPPoster(),
		th,
		deviceSn,
		boardSn,
		chipSn,
	)
	eng.SetLogger(pssmLogger{})

	// 后台运行，进程生命周期内不退出
	go eng.Start(context.Background(), defaultInterval)
	logger.Info("alarm engine initialized, interval=%v", defaultInterval)
}

// loadThresholds 从 config 读取 alarmThreshold 并转为整数百分比/℃。
// 0-1 小数阈值 *100（对齐 bmssm int(subV.GetFloat64("cpuRate")*100)）；
// 温度直接取 int℃；未配置字段用 ssm.yaml 默认值（config.LoadConfig 已 SetDefault）。
func loadThresholds() Thresholds {
	config.Conf.RLock()
	defer config.Conf.RUnlock()
	v := config.Conf.GetViper()
	return Thresholds{
		CpuRate:          int(v.GetFloat64("alarmThreshold.cpuRate") * 100),
		TotalMemoryScale: int(v.GetFloat64("alarmThreshold.totalMemoryScale") * 100),
		DiskRate:         int(v.GetFloat64("alarmThreshold.diskRate") * 100),
		BoardTemperature: int(v.GetFloat64("alarmThreshold.boardTemperature")),
		CoreTemperature:  int(v.GetFloat64("alarmThreshold.coreTemperature")),
		TpuRate:          int(v.GetFloat64("alarmThreshold.tpuRate") * 100),
	}
}

// ---------------------------------------------------------------
// 适配器
// ---------------------------------------------------------------

// compatSubLister 把 compat.CompatService.ListSubscriptions 适配为 alarm.SubscriptionLister。
type compatSubLister struct {
	svc interface {
		ListSubscriptions() []compat.SubscribeRequest
	}
}

// CallbackURLs 提取所有订阅的 NotificationURL，跳过空值。
func (c *compatSubLister) CallbackURLs() []string {
	subs := c.svc.ListSubscriptions()
	urls := make([]string, 0, len(subs))
	for _, s := range subs {
		if s.NotificationURL != "" {
			urls = append(urls, s.NotificationURL)
		}
	}
	return urls
}

// pssmLogger 适配 alarm.Logger 到 pssm 包级 logger。
type pssmLogger struct{}

func (pssmLogger) Infof(format string, v ...interface{})  { logger.Info(format, v...) }
func (pssmLogger) Errorf(format string, v ...interface{}) { logger.Error(format, v...) }
