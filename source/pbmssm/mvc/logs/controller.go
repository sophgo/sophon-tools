// Package logs 提供系统日志下载：流式打包 /var/log/kern* + syslog* 为 tar.gz。
// tar+gzip 直接写到 http.ResponseWriter，不在设备上落盘整包，避免占用存储。
package logs

import (
	"archive/tar"
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/pkg/response"
)

// 系统日志 glob 模式（kern* + syslog*，与前端"系统日志下载"语义一致）。
var logGlobs = []string{"/var/log/kern*", "/var/log/syslog*"}

// Controller 系统日志 gin handler。
type Controller struct{}

// NewController 创建 Controller。
func NewController() *Controller { return &Controller{} }

// DefaultController 包级单例。
var defaultCtrl = NewController()

func DefaultController() *Controller { return defaultCtrl }

// DownloadLogs GET /api/v1/logs/download
// 流式打包 /var/log/kern* 与 /var/log/syslog* 为 tar.gz 下载。
// tar→gzip→ResponseWriter 管道直写，设备端不生成整包临时文件；
// 单个文件用 io.Copy 流式写入，支持大日志文件。
func (ctrl *Controller) DownloadLogs(c *gin.Context) {
	c.Header("Content-Disposition", `attachment; filename="sys_log.tgz"`)
	c.Header("Content-Type", "application/gzip")
	c.Header("Cache-Control", "no-store")

	gw := gzip.NewWriter(c.Writer)
	defer gw.Close()
	tw := tar.NewWriter(gw)
	defer tw.Close()

	// 收集匹配文件（去重，保持稳定顺序）
	seen := map[string]bool{}
	var files []string
	for _, pattern := range logGlobs {
		ms, err := filepath.Glob(pattern)
		if err != nil {
			continue
		}
		for _, f := range ms {
			if !seen[f] {
				seen[f] = true
				files = append(files, f)
			}
		}
	}

	wrote := 0
	for _, path := range files {
		st, err := os.Stat(path)
		if err != nil || st.IsDir() || !st.Mode().IsRegular() {
			continue
		}
		if err := writeTarFile(tw, path, st); err != nil {
			// 单文件失败不中断整包；响应头已写，只能跳过。
			continue
		}
		wrote++
	}
	if wrote == 0 {
		// 无可读日志文件时写一个说明文件，避免下载空包让用户困惑。
		writeReadme(tw, "no readable /var/log/kern* or syslog* files found")
	}
}

// writeTarFile 将单个文件流式写入 tar（header + io.Copy 内容）。
func writeTarFile(tw *tar.Writer, path string, fi os.FileInfo) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	hdr := &tar.Header{
		Name:    filepath.Base(path),
		Mode:    int64(fi.Mode().Perm()),
		Size:    fi.Size(),
		ModTime: fi.ModTime(),
		Format:  tar.FormatGNU,
	}
	if err := tw.WriteHeader(hdr); err != nil {
		return err
	}
	if _, err := io.Copy(tw, f); err != nil {
		return err
	}
	return nil
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
