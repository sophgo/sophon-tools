package database

import (
	"strings"
	"time"
)

// MetricSelection 存储性能历史页的指标勾选选择（单例，ID 固定为 1）。
// sophliteos 自管理本机设备，选择属本实例，无需按 device_sn 分片。
type MetricSelection struct {
	ID        uint      `gorm:"primary_key" json:"-"`
	Fields    string    `gorm:"column:fields" json:"fields"` // 逗号分隔的字段名
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

// TableName 指定表名。
func (MetricSelection) TableName() string { return "metric_selection" }

// LoadMetricSelection 读取已存选择；无记录返空切片。
func LoadMetricSelection() []string {
	if DB == nil {
		return nil
	}
	var m MetricSelection
	if err := DB.First(&m, 1).Error; err != nil {
		return nil
	}
	if strings.TrimSpace(m.Fields) == "" {
		return nil
	}
	parts := strings.Split(m.Fields, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if s := strings.TrimSpace(p); s != "" {
			out = append(out, s)
		}
	}
	return out
}

// SaveMetricSelection 保存选择（upsert 到 ID=1）。
func SaveMetricSelection(fields []string) error {
	if DB == nil {
		return ErrDBNil
	}
	m := MetricSelection{
		ID:        1,
		Fields:    strings.Join(fields, ","),
		UpdatedAt: time.Now(),
	}
	return DB.Save(&m).Error
}

// ErrDBNil 数据库未初始化。
var ErrDBNil = &dbError{"database is nil"}

type dbError struct{ msg string }

func (e *dbError) Error() string { return e.msg }
