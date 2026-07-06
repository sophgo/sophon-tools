// Package software 提供已装软件扫描、软件包安装/升级、OTA 固件管理的 MVC 模块。
package software

import "time"

// ---------------------------------------------------------------
// 软件列表
// ---------------------------------------------------------------

// SoftwareInfo 已安装软件模块摘要。
type SoftwareInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Path    string `json:"path"`
}

// ---------------------------------------------------------------
// 安装 / 升级
// ---------------------------------------------------------------

// InstallResponse 软件包安装/升级结果。
type InstallResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Package string `json:"package,omitempty"`
	Output  string `json:"output,omitempty"`
}

// ---------------------------------------------------------------
// OTA 固件
// ---------------------------------------------------------------

// OTAUploadResponse OTA 固件上传成功响应。
type OTAUploadResponse struct {
	UploadID   string `json:"uploadId"`
	FileName   string `json:"fileName"`
	FileSize   int64  `json:"fileSize"`
	UploadedAt string `json:"uploadedAt"`
}

// OTADownloadResponse OTA 固件下载/进度查询响应。
type OTADownloadResponse struct {
	UploadID   string `json:"uploadId"`
	FileName   string `json:"fileName"`
	FileSize   int64  `json:"fileSize"`
	UploadedAt string `json:"uploadedAt"`
	Status     string `json:"status"` // uploaded, upgrading, completed, failed
}

// OTAUpgradeResponse OTA 固件升级执行响应。
// 无升级脚本时返回 200 + Available=false，不 500。
type OTAUpgradeResponse struct {
	Success   bool   `json:"success"`
	Available bool   `json:"available"`
	Message   string `json:"message,omitempty"`
	Output    string `json:"output,omitempty"`
	Reason    string `json:"reason,omitempty"`
}

// ---------------------------------------------------------------
// 通用
// ---------------------------------------------------------------

// ErrorResponse 统一错误响应（与现有模块保持一致）。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}

// ---------------------------------------------------------------
// 内部类型
// ---------------------------------------------------------------

// otaRecord 内存中的 OTA 固件上传记录。
type otaRecord struct {
	UploadID   string
	FileName   string
	FilePath   string
	FileSize   int64
	UploadedAt time.Time
	Status     string // uploaded, upgrading, completed, failed
}
