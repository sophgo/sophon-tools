// Package filemanage 提供文件管理 HTTP handler（list/content/download/upload/
// chmod/chown/mkdir/rename/delete）。仅操作当前账户家目录可达路径，禁 /proc /sys /dev。
package filemanage

import "time"

// FileInfo 文件条目信息（列目录返回）。
type FileInfo struct {
	Name    string `json:"name"`
	Size    int64  `json:"size"`
	Mode    string `json:"mode"`
	ModTime int64  `json:"modTime"`
	IsDir   bool   `json:"isDir"`
	Owner   string `json:"owner"`
	Group   string `json:"group"`
}

// ChmodRequest 改权限请求。
type ChmodRequest struct {
	Path string `json:"path" binding:"required"`
	Mode string `json:"mode" binding:"required"`
}

// ChownRequest 改所有权请求。
type ChownRequest struct {
	Path  string `json:"path" binding:"required"`
	Owner string `json:"owner"`
	Group string `json:"group"`
}

// MkdirRequest 新建目录请求。
type MkdirRequest struct {
	Path string `json:"path" binding:"required"`
}

// RenameRequest 重命名请求。
type RenameRequest struct {
	OldPath string `json:"oldPath" binding:"required"`
	NewPath string `json:"newPath" binding:"required"`
}

// 避免未使用 import 警告（ModTime 用 int64 而非 time.Time，time 仅占位以备扩展）。
var _ = time.Time{}
