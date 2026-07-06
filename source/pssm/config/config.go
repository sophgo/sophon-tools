// Package config 用 viper 加载 ssm.yaml，提供带读写锁的全局配置与热加载。
package config

import (
	"os"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"

	"ssm/logger"
)

const DefaultConfigPath = "/etc/ssm/conf"

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

// LoadConfig 从 SSM_CONF 环境变量（优先）、默认路径 /etc/ssm/conf、或 ./config 回退加载。
func LoadConfig() {
	if env := os.Getenv("SSM_CONF"); env != "" {
		LoadFromDir(env)
		return
	}
	if LoadFromDir(DefaultConfigPath) {
		return
	}
	LoadFromDir("./config")
}

// LoadFromDir 从指定目录加载 ssm.yaml（测试与本地开发用）。
// 返回 true 表示成功读取到配置文件。dir 之外不做任何路径回退。
func LoadFromDir(dir string) bool {
	Conf = Config{v: viper.New()}
	v := Conf.v

	v.SetDefault("server.port", "9779")
	v.SetDefault("server.auth", true)
	v.SetDefault("server.listenIP", "")
	v.SetDefault("server.authSecret", "ssm-dev-secret")
	v.SetDefault("server.defaultPassword", "admin")
	v.SetDefault("server.deviceName", "device_1")
	v.SetDefault("log.level", "info")
	v.SetDefault("log.path", "/var/log/ssm")
	v.SetDefault("alarmThreshold.boardTemperature", 90)
	v.SetDefault("alarmThreshold.coreTemperature", 90)
	v.SetDefault("alarmThreshold.cpuRate", 0.95)
	v.SetDefault("alarmThreshold.diskRate", 0.95)
	v.SetDefault("alarmThreshold.externalHardDiskRate", 0.95)
	v.SetDefault("alarmThreshold.fanSpeed", 9999)
	v.SetDefault("alarmThreshold.systemScale", 0.95)
	v.SetDefault("alarmThreshold.totalMemoryScale", 0.95)
	v.SetDefault("alarmThreshold.tpuRate", 0.95)
	v.SetDefault("alarmThreshold.tpuScale", 0.95)
	v.SetDefault("alarmThreshold.videoScale", 0.95)

	v.SetDefault("db.driver", "sqlite3")
	v.SetDefault("db.path", "/var/lib/ssm/ssm.db")

	// OTA dryRun：true 时只记录不实刷（真机验证用，避免变砖/断 SSH）
	v.SetDefault("ota.dryRun", false)

	v.AddConfigPath(dir)
	v.SetConfigName("ssm")
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
