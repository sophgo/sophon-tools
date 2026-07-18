// Package config 用 viper 加载 bmssm.yaml，提供带读写锁的全局配置与热加载。
package config

import (
	"os"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"

	"bmssm/logger"
)

const DefaultConfigPath = "/opt/sophon/bmssm/config"

var Conf Config

// Config 包装 viper，带 RWMutex 供并发安全访问。
type Config struct {
	v  *viper.Viper
	mu sync.RWMutex
}

func (c *Config) GetViper() *viper.Viper { return c.v }
func (c *Config) RLock()                 { c.mu.RLock() }
func (c *Config) RUnlock()               { c.mu.RUnlock() }
func (c *Config) Lock()                  { c.mu.Lock() }
func (c *Config) Unlock()                { c.mu.Unlock() }

// LoadConfig 从 BMSSM_CONF 环境变量（优先）、默认路径 /opt/sophon/bmssm/config、或 ./config 回退加载。
func LoadConfig() {
	if env := os.Getenv("BMSSM_CONF"); env != "" {
		LoadFromDir(env)
		return
	}
	if LoadFromDir(DefaultConfigPath) {
		return
	}
	LoadFromDir("./config")
}

// LoadFromDir 从指定目录加载 bmssm.yaml（测试与本地开发用）。
// 返回 true 表示成功读取到配置文件。dir 之外不做任何路径回退。
func LoadFromDir(dir string) bool {
	Conf = Config{v: viper.New()}
	v := Conf.v

	v.SetDefault("server.port", "9779")
	v.SetDefault("server.auth", true)
	v.SetDefault("server.listenIP", "")
	v.SetDefault("server.authSecret", "bmssm-dev-secret")
	v.SetDefault("server.defaultPassword", "admin")
	v.SetDefault("server.deviceName", "device_1")
	v.SetDefault("log.level", "info")
	v.SetDefault("log.path", "/var/log/bmssm")
	v.SetDefault("alarmThreshold.boardTemperature", 90)
	v.SetDefault("alarmThreshold.coreTemperature", 90)
	v.SetDefault("alarmThreshold.cpuRate", 0.95)
	v.SetDefault("alarmThreshold.diskRate", 0.95)
	v.SetDefault("alarmThreshold.totalMemoryScale", 0.95)
	v.SetDefault("alarmThreshold.tpuRate", 0.95)
	v.SetDefault("alarmThreshold.tpuScale", 0.95)

	v.SetDefault("db.driver", "sqlite3")
	v.SetDefault("db.path", "/var/lib/bmssm/bmssm.db")

	// OTA dryRun：true 时只记录不实刷（真机验证用，避免变砖/断 SSH）
	v.SetDefault("ota.dryRun", false)

	// Prometheus metrics 后台采集
	v.SetDefault("metrics.enabled", true)
	v.SetDefault("metrics.updateIntervalSeconds", 20)
	v.SetDefault("metrics.temperatureThresholds.critical", 90)
	v.SetDefault("metrics.temperatureThresholds.warning", 85)

	// Firewall 防火墙管理
	v.SetDefault("firewall.enabled", true)
	v.SetDefault("firewall.persistPath", "/etc/iptables/rules.v4")
	v.SetDefault("firewall.rollbackSeconds", 300)
	v.SetDefault("firewall.protectPorts", []int{})

	// Metrics 历史存档
	v.SetDefault("metrics.archive.enabled", true)
	v.SetDefault("metrics.archive.path", "/var/lib/bmssm/metrics")
	v.SetDefault("metrics.archive.maxSizeMB", 100)
	v.SetDefault("metrics.archive.channelBufferSize", 16)

	v.AddConfigPath(dir)
	v.SetConfigName("bmssm")
	v.SetConfigType("yaml")

	if err := v.ReadInConfig(); err != nil {
		logger.Warn("load config from %s failed: %v (using defaults)", dir, err)
		return false
	}
	logger.Info("loaded config from %s, port=%s", dir, v.GetString("server.port"))

	v.OnConfigChange(func(in fsnotify.Event) {
		logger.Info("config file changed: %s", in.Name)
	})
	v.WatchConfig()
	return true
}
