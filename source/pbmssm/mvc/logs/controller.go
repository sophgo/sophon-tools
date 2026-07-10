// Package logs 提供系统日志下载：流式打包整个 /var/log 目录为 tar.gz。
// tar+gzip 直接写到 http.ResponseWriter，不在设备上落盘整包，避免占用存储。
package logs

import (
	"archive/tar"
	"compress/gzip"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/pkg/response"
)

// 系统日志根目录（整个 /var/log 递归打包）。
const logRoot = "/var/log"

// Controller 系统日志 gin handler。
type Controller struct{}

// NewController 创建 Controller。
func NewController() *Controller { return &Controller{} }

// DefaultController 包级单例。
var defaultCtrl = NewController()

func DefaultController() *Controller { return defaultCtrl }

// DownloadLogs GET /api/v1/logs/download
// 流式打包整个 /var/log 目录为 tar.gz 下载：递归遍历，保留子目录结构，
// 符号链接作为 link 存储（不跟随，避免循环/重复）。
// tar→gzip→ResponseWriter 管道直写，设备端不生成整包临时文件；
// 单个文件用 io.Copy 流式写入，支持大日志文件；单项失败不中断整包。
func (ctrl *Controller) DownloadLogs(c *gin.Context) {
	c.Header("Content-Disposition", `attachment; filename="sys_log.tgz"`)
	c.Header("Content-Type", "application/gzip")
	c.Header("Cache-Control", "no-store")

	gw := gzip.NewWriter(c.Writer)
	defer gw.Close()
	tw := tar.NewWriter(gw)
	defer tw.Close()

	wrote := 0
	_ = filepath.WalkDir(logRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // 不可访问的子项：跳过，不中断整包
		}
		if path == logRoot {
			return nil
		}
		rel, err := filepath.Rel(logRoot, path)
		if err != nil {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		hdr, body, skip := tarEntry(path, rel, info)
		if skip {
			return nil
		}
		if err := tw.WriteHeader(hdr); err != nil {
			return nil // 头已写到响应，无法中断
		}
		if body != nil {
			defer body.Close()
			if _, err := io.Copy(tw, body); err != nil {
				return nil
			}
		}
		wrote++
		return nil
	})
	if wrote == 0 {
		// 无可读文件时写说明，避免下载空包让用户困惑。
		writeReadme(tw, "no readable files under /var/log")
	}
}

// tarEntry 为一个路径构造 tar 头；regular 文件返回打开的 body（调用方 Close）。
// 符号链接存为 link（Linkname=目标），不跟随；目录仅写头；其余（socket/device）跳过。
func tarEntry(path, rel string, info os.FileInfo) (*tar.Header, io.ReadCloser, bool) {
	var link string
	if info.Mode()&os.ModeSymlink != 0 {
		if l, err := os.Readlink(path); err == nil {
			link = l
		}
	}
	hdr, err := tar.FileInfoHeader(info, link)
	if err != nil {
		return nil, nil, true
	}
	hdr.Name = filepath.ToSlash(rel)
	hdr.Format = tar.FormatGNU
	if info.Mode().IsRegular() {
		f, err := os.Open(path)
		if err != nil {
			return nil, nil, true
		}
		return hdr, f, false
	}
	if info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return hdr, nil, false // 目录/符号链接：仅头，无 body
	}
	return nil, nil, true // socket/device/pipe 等跳过
}

// writeReadme 写一个文本说明文件到 tar。
func writeReadme(tw *tar.Writer, msg string) {
	content := []byte(fmt.Sprintf("ssm log download: %s\ngenerated at %s\n", msg, time.Now().Format(time.RFC3339)))
	_ = tw.WriteHeader(&tar.Header{
		Name:    "README.txt",
		Mode:    0644,
		Size:    int64(len(content)),
		ModTime: time.Now(),
		Format:  tar.FormatGNU,
	})
	_, _ = tw.Write(content)
}

// _ 保留 response 引用，便于未来错误响应统一信封（当前流式下载直接写 body）。
var _ = response.OK
