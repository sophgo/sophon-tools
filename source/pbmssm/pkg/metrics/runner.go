package metrics

import (
	"time"

	"bmssm/config"
	"bmssm/logger"
)

var (
	defaultRegistry *MetricsRegistry
	defaultArchiver *ArchiveWriter
)

// Registry 返回全局 MetricsRegistry（供 /metrics handler）。
func Registry() *MetricsRegistry { return defaultRegistry }

// Archiver 返回全局 ArchiveWriter（供查询 handler）。
func Archiver() *ArchiveWriter { return defaultArchiver }

// StartCollection 启动后台指标采集 goroutine。
// 首次立即采集一次，之后按 updateIntervalSeconds 周期采集。
// dev 为设备标签信息（从 device 包获取，避免循环依赖）。
// 若 archive.enabled 为 true，同时启动异步存档写入。
func StartCollection(conf *config.Config, dev DeviceLabels) {
	conf.RLock()
	enabled := conf.GetViper().GetBool("metrics.enabled")
	interval := conf.GetViper().GetInt("metrics.updateIntervalSeconds")
	archEnabled := conf.GetViper().GetBool("metrics.archive.enabled")
	archPath := conf.GetViper().GetString("metrics.archive.path")
	archMaxMB := conf.GetViper().GetInt("metrics.archive.maxSizeMB")
	archChanSize := conf.GetViper().GetInt("metrics.archive.channelBufferSize")
	conf.RUnlock()

	if !enabled {
		logger.Info("metrics collection disabled")
		return
	}
	if interval <= 0 {
		interval = 20
	}

	defaultRegistry = NewMetricsRegistry()
	collector := NewDefaultCollector()

	// 启动存档 writer（异步）
	if archEnabled {
		if archPath == "" {
			archPath = "/var/lib/bmssm/metrics"
		}
		if archMaxMB <= 0 {
			archMaxMB = 100
		}
		if archChanSize <= 0 {
			archChanSize = 16
		}
		defaultArchiver = NewArchiveWriter()
		defaultArchiver.Start(archPath, archMaxMB, archChanSize)
	}

	go func() {
		collectOne(collector, defaultRegistry, dev)
		ticker := time.NewTicker(time.Duration(interval) * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			collectOne(collector, defaultRegistry, dev)
		}
	}()
	logger.Info("metrics collection started, interval=%ds archive=%v", interval, archEnabled)
}

func collectOne(c *Collector, r *MetricsRegistry, dev DeviceLabels) {
	hw := c.CollectAll()
	r.Update(hw, dev)
	r.SetDeviceCount(1)

	// 异步投递存档
	if defaultArchiver != nil && defaultArchiver.started {
		ts := uint32(time.Now().Unix())
		rec := hw.ToArchRecord()
		defaultArchiver.Submit(ts, rec)
	}
}
