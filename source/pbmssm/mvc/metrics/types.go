// Package metrics_controller 提供指标历史存档的 API handler。
// 包名加 _controller 后缀避免与 bmssm/pkg/metrics 冲突。
package metrics_controller

// HistoryQuery 查询参数。
type HistoryQuery struct {
	From   int64  `form:"from" binding:"required"`
	To     int64  `form:"to" binding:"required"`
	Fields string `form:"fields"`
}

// ExportQuery 导出参数。
type ExportQuery struct {
	From   int64  `form:"from" binding:"required"`
	To     int64  `form:"to" binding:"required"`
	Format string `form:"format"` // "csv" (default)
}
