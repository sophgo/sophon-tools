// Package logs 提供系统日志下载：流式打包整个 /var/log 目录为 tar.gz。
// tar+gzip 直接写到 http.ResponseWriter，不在设备上落盘整包，避免占用存储。
package logs

import (
	"archive/tar"
	"compress/gzip"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/logger"
	"bmssm/pkg/auth"
	"bmssm/pkg/response"
)

// 系统日志根目录（整个 /var/log 递归打包）。var 便于测试覆盖真实路径。
var logRoot = "/var/log"

// logStreamTimeout 流式打包的写超时：bmssm http.Server 默认 WriteTimeout 30s，
// 大日志打包常超时导致连接被掐断、下载失败；此值给足打包窗口。
const logStreamTimeout = 30 * time.Minute

// Controller 系统日志 gin handler。
type Controller struct{}

// NewController 创建 Controller。
func NewController() *Controller { return &Controller{} }

// DefaultController 包级单例。
var defaultCtrl = NewController()

func DefaultController() *Controller { return defaultCtrl }

// getSecret 从配置获取 JWT secret（与 filemanage.getSecret 同源，空则回退 DefaultSecret）。
func getSecret() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()
	if v == nil {
		return auth.DefaultSecret
	}
	return auth.EffectiveSecret(v.GetString("server.authSecret"))
}

// authLogToken 校验 query ?token= 或 Authorization: Bearer 头。
// <a download> 无法带 Authorization 头，故支持 query token（sophliteos 以一次性
// 票据换发 ?token= 后转发）；其余调用仍可用头。仅要求有效登录 token（保留
// 原 Auth 中间件行为：任意登录用户可下载日志，不锁 admin）。
func authLogToken(c *gin.Context) bool {
	tokenStr := c.Query("token")
	if tokenStr == "" {
		h := c.GetHeader("Authorization")
		tokenStr = strings.TrimPrefix(h, "Bearer ")
		tokenStr = strings.TrimSpace(tokenStr)
	}
	if tokenStr == "" {
		c.Status(http.StatusUnauthorized)
		return false
	}
	username, temp, err := auth.ParseToken(tokenStr, getSecret())
	if err != nil {
		c.Status(http.StatusUnauthorized)
		return false
	}
	if temp {
		c.Status(http.StatusForbidden)
		return false
	}
	c.Set("user", username)
	return true
}

// DownloadLogs GET /api/v1/logs/download
// 流式打包整个 /var/log 目录为 tar.gz 下载：递归遍历，保留子目录结构，
// 符号链接作为 link 存储（不跟随，避免循环/重复）。
// tar→gzip→ResponseWriter 管道直写，设备端不生成整包临时文件；
// 单个文件用 io.Copy 流式写入，支持大日志文件；单项失败不中断整包。
// 鉴权在 handler 内完成（query ?token= 或 Authorization 头），支持浏览器
// 原生 <a download> 流式落盘（自带进度条、低内存）。
func (ctrl *Controller) DownloadLogs(c *gin.Context) {
	if !authLogToken(c) {
		return
	}
	// 覆盖 server 级 WriteTimeout（30s）：大日志流式打包需更长窗口，
	// 否则连接被掐断、下载中途失败。ResponseController 直写底层 conn。
	if err := http.NewResponseController(c.Writer).SetWriteDeadline(time.Now().Add(logStreamTimeout)); err != nil {
		logger.Debug("logs download set write deadline failed: %v", err)
	}

	c.Header("Content-Disposition", `attachment; filename="sys_log.tgz"`)
	c.Header("Content-Type", "application/gzip")
	c.Header("Cache-Control", "no-store")
	// 提示反向代理/中间层不要缓冲整包，随流转发（nginx 等默认会开缓冲）。
	c.Header("X-Accel-Buffering", "no")

	gw, err := gzip.NewWriterLevel(c.Writer, gzip.BestSpeed)
	if err != nil {
		// 响应尚未写头，可回 JSON 错误。
		c.JSON(http.StatusInternalServerError, response.Fail("gzip init failed"))
		return
	}
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
		writeReadme(tw, "no readable files under "+logRoot)
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

// OverviewEntry 日志下载清单的一项：按 /var/log 顶层目录聚合。
type OverviewEntry struct {
	Name    string `json:"name"`
	Path    string `json:"path"`
	Type    string `json:"type"`  // file / dir / symlink
	Size    int64  `json:"size"`  // 目录为递归合计（regular 文件）；symlink 为 0
	Files   int    `json:"files"` // 目录为递归条目数（含子目录/symlink）
	ModTime int64  `json:"mtime"` // Unix 秒
}

// LogOverview GET /api/v1/logs/overview
// 返回"将抓取哪些日志"：/var/log 顶层条目聚合（名称/类型/大小/文件数/时间），
// 供前端下载前展示。遍历规则与 DownloadLogs 一致（directory 递归汇总、
// symlink 计入条目但 size=0、socket/device 跳过），保证清单与实际的包一致。
func (ctrl *Controller) LogOverview(c *gin.Context) {
	overview, err := collectOverview(logRoot)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("collect logs overview: "+err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(overview))
}

// overview 顶层清单结构。
type overview struct {
	Root         string          `json:"root"`
	TotalSize    int64           `json:"total_size"`
	TotalEntries int             `json:"total_entries"`
	Entries      []OverviewEntry `json:"entries"`
}

// collectOverview 遍历 logRoot 顶层，逐项聚合大小/文件数。
func collectOverview(root string) (*overview, error) {
	ents, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	ov := &overview{Root: root, Entries: make([]OverviewEntry, 0, len(ents))}
	for _, e := range ents {
		p := filepath.Join(root, e.Name())
		info, err := e.Info()
		if err != nil {
			continue // 无法 stat 的子项跳过（与 DownloadLogs 一致）
		}
		en := OverviewEntry{Name: e.Name(), Path: p, ModTime: info.ModTime().Unix()}
		m := info.Mode()
		switch {
		case m.IsRegular():
			en.Type = "file"
			en.Size = info.Size()
			en.Files = 1
		case m.IsDir():
			en.Type = "dir"
			sumDir(p, &en)
		case m&os.ModeSymlink != 0:
			en.Type = "symlink"
			en.Files = 1
		default:
			continue // socket/device/pipe：跳过（与 DownloadLogs 一致）
		}
		ov.TotalSize += en.Size
		ov.TotalEntries += en.Files
		ov.Entries = append(ov.Entries, en)
	}
	sort.Slice(ov.Entries, func(i, j int) bool { return ov.Entries[i].Name < ov.Entries[j].Name })
	return ov, nil
}

// sumDir 递归汇总目录下 regular 文件大小与条目数（含子目录/符号链接；
// socket/device/pipe 跳过，与 DownloadLogs 一致）。
func sumDir(dir string, en *OverviewEntry) {
	var cnt int
	var size int64
	var mt int64
	_ = filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // 不可访问子项：跳过
		}
		if path == dir {
			return nil // 目录自身不计入
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		m := info.Mode()
		if !m.IsRegular() && !m.IsDir() && m&os.ModeSymlink == 0 {
			return nil // socket/device/pipe 跳过（与 DownloadLogs 一致）
		}
		if t := info.ModTime().Unix(); t > mt {
			mt = t
		}
		if m.IsRegular() {
			size += info.Size()
		}
		cnt++
		return nil
	})
	en.Size = size
	en.Files = cnt
	if mt > 0 {
		en.ModTime = mt
	}
}
