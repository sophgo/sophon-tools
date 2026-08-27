package database

import (
	"crypto/rand"
	"encoding/hex"
	"time"
)

// MetricsForward 指标转发配置（单例，ID 固定为 1）。
// sophliteos 经 :8080/metrics 反代 bmssm 9779 的 Prometheus 端点；
// 无记录 = 默认关闭（fail-safe）。token 供 Prometheus 抓取鉴权。
type MetricsForward struct {
	ID        uint      `gorm:"primary_key" json:"-"`
	Enabled   bool      `gorm:"column:enabled" json:"enabled"`
	Token     string    `gorm:"column:token" json:"token"`
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

// TableName 指定表名。
func (MetricsForward) TableName() string { return "metrics_forward" }

// LoadMetricsForward 读取转发配置；无记录返回零值（关闭态、无 token）。
func LoadMetricsForward() MetricsForward {
	if DB == nil {
		return MetricsForward{}
	}
	var m MetricsForward
	if err := DB.First(&m, 1).Error; err != nil {
		return MetricsForward{}
	}
	return m
}

// SaveMetricsForward 保存配置（upsert 到 ID=1）。
func SaveMetricsForward(m MetricsForward) error {
	if DB == nil {
		return ErrDBNil
	}
	m.ID = 1
	m.UpdatedAt = time.Now()
	return DB.Save(&m).Error
}

// NewForwardToken 生成抓取 token：crypto/rand 32 字节 → 64 位 hex。
func NewForwardToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand 失败属系统级异常，fallback 到时间熵（极罕见路径）
		now := time.Now().UnixNano()
		for i := range b {
			b[i] = byte(now >> (uint(i%8) * 8))
		}
	}
	return hex.EncodeToString(b)
}

// EnsureForwardToken 返回当前配置；若开启但无 token（如旧数据/首次开启）则自动生成并落库。
func EnsureForwardToken() (MetricsForward, error) {
	m := LoadMetricsForward()
	if m.Enabled && m.Token == "" {
		m.Token = NewForwardToken()
		if err := SaveMetricsForward(m); err != nil {
			return m, err
		}
	}
	return m, nil
}
