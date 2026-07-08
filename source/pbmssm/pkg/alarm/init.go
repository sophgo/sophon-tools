// Package alarm 初始化入口。Init() 由 initialization.InitBase 在设备信息就绪后调用，
// 启动后台监控 goroutine，每 30s 采集指标→比对阈值→POST 到 compat 订阅 callback。
package alarm

import (
	"context"
	"time"

	"bmssm/config"
	"bmssm/global"
	"bmssm/logger"
	"bmssm/mvc/compat"
	"bmssm/pkg/metrics"
)

// defaultInterval 默认采集间隔，对齐 bmssm agencyModule.parameter.interval≤0 时 30s。
const defaultInterval = 30 * time.Second

// Init 创建并启动告警引擎（生产装配）。
//   - 指标：metrics.NewDefaultCollector（CPU 双采样约 100ms，30s 间隔无压力）
//   - 订阅：compat.DefaultCompatService（适配为 CallbackURLs）
//   - 阈值：config alarmThreshold（0-1 小数 *100 转整数百分比）
//   - 设备信息：global.DeviceSnEx / ChipSn（InitBase 已填充）
//   - recorder：告警历史落库器（nil=不落库），由 initialization 注入 mvc/alarm 实现
func Init(recorder Recorder) {
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
	if recorder != nil {
		eng.SetRecorder(recorder)
	}
	// 每 tick 从配置实时加载阈值，使 SetAlarm API / 配置文件热更无需重启即生效。
	eng.SetThresholdsLoader(loadThresholds)

	// 后台运行，进程生命周期内不退出
	go eng.Start(context.Background(), defaultInterval)
	logger.Info("alarm engine initialized, interval=%v", defaultInterval)
}

// loadThresholds 从 config 读取 alarmThreshold 并转为整数百分比/℃。
// rateToPercent 归一化：≤1 视为 0-1 小数（*100），否则视为已是 0-100 百分比——
// 兼容 bmssm.yaml 旧默认值 0.95 与前端 threshold 页直接发送的 0-100 整数。
// 温度直接取 int℃；未配置字段用 bmssm.yaml 默认值（config.LoadConfig 已 SetDefault）。
func loadThresholds() Thresholds {
	config.Conf.RLock()
	defer config.Conf.RUnlock()
	v := config.Conf.GetViper()
	return Thresholds{
		CpuRate:          rateToPercent(v.GetFloat64("alarmThreshold.cpuRate")),
		TotalMemoryScale: rateToPercent(v.GetFloat64("alarmThreshold.totalMemoryScale")),
		DiskRate:         rateToPercent(v.GetFloat64("alarmThreshold.diskRate")),
		BoardTemperature: int(v.GetFloat64("alarmThreshold.boardTemperature")),
		CoreTemperature:  int(v.GetFloat64("alarmThreshold.coreTemperature")),
		TpuRate:          rateToPercent(v.GetFloat64("alarmThreshold.tpuRate")),
	}
}

// rateToPercent 把比例/百分比阈值归一化为 0-100 整数百分比。
// f≤1（如 0.95）视为 0-1 小数，*100；f>1（如 90）视为已是百分比，取整。
func rateToPercent(f float64) int {
	if f <= 1 {
		return int(f * 100)
	}
	return int(f)
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
