package alarm

import (
	"context"
	"encoding/json"
	"time"

	"ssm/pkg/metrics"
)

// Engine 告警监控引擎。周期采集指标、对比阈值、边沿检测、POST 到订阅 callback。
type Engine struct {
	metrics     MetricsReader
	subs        SubscriptionLister
	poster      Poster
	thresholds  Thresholds
	// thresholdsLoader 可选：每 tick 重新从配置加载阈值。注入后 SetAlarm 改配置
	// 可在不重启进程的情况下生效（≤ interval）。nil 时用构造时传入的 thresholds 快照。
	thresholdsLoader func() Thresholds
	deviceSn         string
	boardSn         string
	chipSn          string
	eventStatus     map[EventId]bool
	logger          Logger
	recorder        Recorder
	now             func() time.Time
}

// NewEngine 创建引擎。deviceSn=设备 SN，boardSn=板卡 SN（SOC 单板=主控），
// chipSn=芯片 SN（芯片类告警定位用）。
func NewEngine(m MetricsReader, s SubscriptionLister, p Poster, t Thresholds,
	deviceSn, boardSn, chipSn string) *Engine {
	return &Engine{
		metrics:     m,
		subs:        s,
		poster:      p,
		thresholds:  t,
		deviceSn:    deviceSn,
		boardSn:     boardSn,
		chipSn:      chipSn,
		eventStatus: make(map[EventId]bool, numEventIds),
		logger:      noOpLogger{},
		now:         time.Now,
	}
}

// SetLogger 注入日志器（默认 no-op）。
func (e *Engine) SetLogger(l Logger) {
	if l != nil {
		e.logger = l
	}
}

// SetRecorder 注入告警历史落库器（默认 nil=不落库）。
func (e *Engine) SetRecorder(r Recorder) {
	e.recorder = r
}

// SetThresholdsLoader 注入阈值加载器。注入后 evaluate 每 tick 重读配置，
// 使运行时修改阈值（SetAlarm API / 配置文件热更）无需重启即生效。
func (e *Engine) SetThresholdsLoader(f func() Thresholds) {
	e.thresholdsLoader = f
}

// Start 在后台 goroutine 周期执行 Tick。间隔 ≤0 时默认 30s（对齐 bmssm）。
// ctx 取消后退出。
func (e *Engine) Start(ctx context.Context, interval time.Duration) {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	e.logger.Infof("alarm engine started, interval=%v", interval)
	for {
		select {
		case <-ctx.Done():
			e.logger.Infof("alarm engine stopped")
			return
		case <-ticker.C:
			e.Tick()
		}
	}
}

// Tick 执行一次采集→评估→分发。导出以便测试与外部触发。
func (e *Engine) Tick() {
	alarms := e.evaluate()
	for _, a := range alarms {
		e.record(a)
		e.dispatch(a)
	}
}

// record 落库告警历史（best-effort）。recorder 未注入或失败时不阻断。
func (e *Engine) record(a AlarmRec) {
	if e.recorder == nil {
		return
	}
	if err := e.recorder.Record(a); err != nil {
		e.logger.Errorf("alarm record: %v", err)
	}
}

// evaluate 采集指标并做边沿检测，返回本 tick 应发送的告警/恢复事件。
func (e *Engine) evaluate() []AlarmRec {
	now := e.now()
	var out []AlarmRec
	m := e.metrics
	// 每 tick 重读阈值：注入了 thresholdsLoader 时从配置实时加载，
	// 使 SetAlarm 改阈值无需重启即生效；否则用构造快照。
	th := e.thresholds
	if e.thresholdsLoader != nil {
		th = e.thresholdsLoader()
	}

	// --- CPU ---
	cpuUtil := roundInt(m.CPUInfo().UtilizationRate)
	cpuAlarm := cpuUtil > th.CpuRate
	if cpuAlarm {
		e.eventStatus[CPU_RATE] = true
		out = append(out, buildPayload(CodeCPURateAlarm, cpuUtil, e.deviceSn, e.boardSn, "", "", now))
	}
	if e.eventStatus[CPU_RATE] && !cpuAlarm {
		e.eventStatus[CPU_RATE] = false
		out = append(out, buildPayload(CodeCPURateRecover, -1, e.deviceSn, e.boardSn, "", "", now))
	}

	// --- 内存 ---
	memUse := memUsage(m.Memory())
	memAlarm := memUse > th.TotalMemoryScale
	if memAlarm {
		e.eventStatus[MEM_RATE] = true
		out = append(out, buildPayload(CodeMemRateAlarm, memUse, e.deviceSn, e.boardSn, "", "", now))
	}
	if e.eventStatus[MEM_RATE] && !memAlarm {
		e.eventStatus[MEM_RATE] = false
		out = append(out, buildPayload(CodeMemRateRecover, -1, e.deviceSn, e.boardSn, "", "", now))
	}

	// --- 磁盘（每分区；跳过 /boot /recovery ReadOnly）---
	diskAlarm := false
	for _, d := range m.Disks() {
		if d.MountOn == "/boot" || d.MountOn == "/recovery" || d.ReadOnly == 1 {
			continue
		}
		tr := diskUsage(d)
		if tr > th.DiskRate {
			diskAlarm = true
			e.eventStatus[DISK_RATE] = true
			out = append(out, buildPayload(CodeDiskRateAlarm, tr, e.deviceSn, e.boardSn, "", d.DiskName, now))
		}
	}
	if e.eventStatus[DISK_RATE] && !diskAlarm {
		e.eventStatus[DISK_RATE] = false
		out = append(out, buildPayload(CodeDiskRateRecover, -1, e.deviceSn, e.boardSn, "", "", now))
	}

	// --- 板温 ---
	bdTemp := m.BoardTemp()
	bdTempAlarm := bdTemp > th.BoardTemperature
	if bdTempAlarm {
		e.eventStatus[BOARD_TEMP] = true
		out = append(out, buildPayload(CodeBoardTempAlarm, bdTemp, e.deviceSn, e.boardSn, "", "", now))
	}
	if e.eventStatus[BOARD_TEMP] && !bdTempAlarm {
		e.eventStatus[BOARD_TEMP] = false
		out = append(out, buildPayload(CodeBoardTempRecover, -1, e.deviceSn, e.boardSn, "", "", now))
	}

	// --- 芯片温度 ---
	chipTemp := m.ChipTemp()
	chipTempAlarm := chipTemp > th.CoreTemperature
	if chipTempAlarm {
		e.eventStatus[TPU_TEMP] = true
		out = append(out, buildPayload(CodeChipTempAlarm, chipTemp, e.deviceSn, e.boardSn, e.chipSn, "", now))
	}
	if e.eventStatus[TPU_TEMP] && !chipTempAlarm {
		e.eventStatus[TPU_TEMP] = false
		out = append(out, buildPayload(CodeChipTempRecover, -1, e.deviceSn, e.boardSn, e.chipSn, "", now))
	}

	// --- TPU 使用率 ---
	tpuRate := m.TPUUsage()
	tpuAlarm := tpuRate > th.TpuRate
	if tpuAlarm {
		e.eventStatus[TPU_RATE] = true
		out = append(out, buildPayload(CodeTPURateAlarm, tpuRate, e.deviceSn, e.boardSn, e.chipSn, "", now))
	}
	if e.eventStatus[TPU_RATE] && !tpuAlarm {
		e.eventStatus[TPU_RATE] = false
		out = append(out, buildPayload(CodeTPURateRecover, -1, e.deviceSn, e.boardSn, e.chipSn, "", now))
	}

	return out
}

// dispatch 将告警 POST 到所有订阅 callback URL。失败仅记日志不阻断。
func (e *Engine) dispatch(a AlarmRec) {
	urls := e.subs.CallbackURLs()
	if len(urls) == 0 {
		return
	}
	data, err := json.Marshal(a)
	if err != nil {
		e.logger.Errorf("alarm marshal: %v", err)
		return
	}
	for _, u := range urls {
		if u == "" {
			continue
		}
		if err := e.poster.Post(u, data); err != nil {
			e.logger.Errorf("alarm post %s: %v", u, err)
		}
	}
}

// ---------------------------------------------------------------
// 指标计算辅助（对齐 bmssm 整数百分比 + 四舍五入）
// ---------------------------------------------------------------

// roundInt float64 → int 四舍五入。
func roundInt(f float64) int {
	return int(f + 0.5)
}

// memUsage 内存使用率 % = 100 - Avail*100/Total（四舍五入）。Total≤0 返 0。
func memUsage(m metrics.Memory) int {
	if m.Total <= 0 {
		return 0
	}
	return int(100.0 - m.Available*100.0/m.Total + 0.5)
}

// diskUsage 磁盘使用率 % = 100 - Free*100/Total（四舍五入）。Total≤0 返 0。
func diskUsage(d metrics.Disk) int {
	if d.Total <= 0 {
		return 0
	}
	return int(100.0 - d.Free*100.0/d.Total + 0.5)
}

// ---------------------------------------------------------------
// no-op logger
// ---------------------------------------------------------------

type noOpLogger struct{}

func (noOpLogger) Infof(format string, v ...interface{})  {}
func (noOpLogger) Errorf(format string, v ...interface{}) {}
