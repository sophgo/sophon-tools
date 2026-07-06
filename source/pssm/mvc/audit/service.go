package audit

import (
	"github.com/jinzhu/gorm"
)

// AuditService 封装审计日志业务逻辑。
type AuditService struct {
	db *gorm.DB
}

// NewService 创建 AuditService。
func NewService(db *gorm.DB) *AuditService {
	return &AuditService{db: db}
}

// PaginatedResult 分页查询结果。
type PaginatedResult struct {
	Total  int        `json:"total"`
	Offset int        `json:"offset"`
	Limit  int        `json:"limit"`
	Logs   []AuditLog `json:"logs"`
}

// ListLogs 分页查询审计日志（默认 offset=0, limit=50）。
func (s *AuditService) ListLogs(offset, limit int) (*PaginatedResult, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}

	var total int
	if err := s.db.Model(&AuditLog{}).Count(&total).Error; err != nil {
		return nil, err
	}

	var logs []AuditLog
	if err := s.db.Order("id desc").Offset(offset).Limit(limit).Find(&logs).Error; err != nil {
		return nil, err
	}

	return &PaginatedResult{
		Total:  total,
		Offset: offset,
		Limit:  limit,
		Logs:   logs,
	}, nil
}

// Write 写入一条审计日志（辅助方法，供其他模块调用）。
func (s *AuditService) Write(username, action, resource, ip, result string) error {
	entry := AuditLog{
		Username: username,
		Action:   action,
		Resource: resource,
		IP:       ip,
		Result:   result,
	}
	return s.db.Create(&entry).Error
}

// WriteAudit 快捷写入（包级函数，忽略错误）。
func WriteAudit(svc *AuditService, username, action, resource, ip, result string) {
	_ = svc.Write(username, action, resource, ip, result)
}
