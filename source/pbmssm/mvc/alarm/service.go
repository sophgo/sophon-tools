package alarm

import (
	"github.com/jinzhu/gorm"
)

// AlarmService 封装告警历史业务逻辑。
type AlarmService struct {
	db *gorm.DB
}

// NewService 创建 AlarmService。
func NewService(db *gorm.DB) *AlarmService {
	return &AlarmService{db: db}
}

// PaginatedResult 分页查询结果。
type PaginatedResult struct {
	Total  int     `json:"total"`
	Offset int     `json:"offset"`
	Limit  int     `json:"limit"`
	Items  []Alarm `json:"items"`
}

// ListFilters 可选过滤条件（零值=不过滤）。
type ListFilters struct {
	ComponentType string // 精确匹配 component_type
	Code          int    // 精确匹配 code
}

// SaveAlarm 写入一条告警历史。
func (s *AlarmService) SaveAlarm(a Alarm) error {
	return s.db.Create(&a).Error
}

// ListAlarms 分页查询告警历史（offset=0/limit=50 默认，按 id desc）。
func (s *AlarmService) ListAlarms(offset, limit int, f ListFilters) (*PaginatedResult, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}

	q := s.db.Model(&Alarm{})
	if f.ComponentType != "" {
		q = q.Where("component_type = ?", f.ComponentType)
	}
	if f.Code != 0 {
		q = q.Where("code = ?", f.Code)
	}

	var total int
	if err := q.Count(&total).Error; err != nil {
		return nil, err
	}

	var items []Alarm
	if err := q.Order("id desc").Offset(offset).Limit(limit).Find(&items).Error; err != nil {
		return nil, err
	}

	return &PaginatedResult{
		Total:  total,
		Offset: offset,
		Limit:  limit,
		Items:  items,
	}, nil
}
