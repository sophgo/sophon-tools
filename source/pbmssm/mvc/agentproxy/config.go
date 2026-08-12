package agentproxy

import (
	"strconv"
	"strings"
	"time"

	"github.com/jinzhu/gorm"

	"bmssm/config"
)

// LoadConfig 读取 agentproxy 配置：sqlite 持久化的 enabled 优先，viper 兜底。
// 其余字段目前仍由 viper（bmssm.yaml agentproxy 段）+ 默认值提供。
// db 可为 nil（DB 未就绪的非致命降级，仅用 viper）。
func LoadConfig(db *gorm.DB) Config {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()

	cfg := Config{
		Enabled:    v.GetBool("agentproxy.enabled"),
		ListenIP:   v.GetString("agentproxy.listenIP"),
		Port:       v.GetInt("agentproxy.port"),
		BinaryPath: v.GetString("agentproxy.binaryPath"),
		WorkDir:    v.GetString("agentproxy.workDir"),
		Model:      v.GetString("agentproxy.model"),
		RestartBackoffMax: v.GetString("agentproxy.restartBackoffMax"),
	}
	// 若已通过「启用」开关持久化过状态，以持久化值为准（兼容 viper 未配置 enabled 的情形）。
	if persisted, ok := loadConfigEnabled(db); ok {
		cfg.Enabled = persisted
	}
	return cfg
}

// DefaultConfig 返回默认配置。
func DefaultConfig() Config {
	return Config{
		Enabled:    true,
		ListenIP:   "127.0.0.1",
		Port:       DefaultPort,
		BinaryPath: DefaultBinary,
		WorkDir:    DefaultWorkDir,
	}
}

// Normalize 补齐默认值。
func (c *Config) Normalize() {
	if c.ListenIP == "" {
		c.ListenIP = "127.0.0.1"
	}
	if c.Port == 0 {
		c.Port = DefaultPort
	}
	if strings.TrimSpace(c.BinaryPath) == "" {
		c.BinaryPath = DefaultBinary
	}
	if strings.TrimSpace(c.WorkDir) == "" {
		c.WorkDir = DefaultWorkDir
	}
}

// BackoffMax 解析重启退避上限（人类可读时长，失败用默认）。
func (c *Config) BackoffMax() time.Duration {
	if c.RestartBackoffMax == "" {
		return DefaultBackoffMax
	}
	if d, err := time.ParseDuration(c.RestartBackoffMax); err == nil {
		return d
	}
	return DefaultBackoffMax
}

// Addr 返回 WS 监听地址（S3 使用）。
func (c *Config) Addr() string {
	return c.ListenIP + ":" + strconv.Itoa(c.Port)
}
