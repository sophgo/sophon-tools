package filemanage

import (
	"fmt"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/pkg/auth"
	"bmssm/pkg/response"
)

// getSecret 从配置获取 JWT secret（与 compat.getSecret 同源）。
// 配置未加载（如测试）时回退 auth.DefaultSecret。
func getSecret() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()
	if v != nil {
		if s := v.GetString("server.authSecret"); s != "" {
			return s
		}
	}
	return auth.DefaultSecret
}

// authToken 校验 query ?token= 或 Authorization: Bearer 头。
// <a download> 无法带 Authorization 头，故支持 query token；其余调用仍可用头。
// 与 Auth 中间件一致：临时 token（temp=true，默认密码登录态）拒绝，需先改密。
func authToken(c *gin.Context) bool {
	tokenStr := c.Query("token")
	if tokenStr == "" {
		h := c.GetHeader("Authorization")
		tokenStr = strings.TrimPrefix(h, "Bearer ")
		tokenStr = strings.TrimSpace(tokenStr)
	}
	if tokenStr == "" {
		c.JSON(http.StatusUnauthorized, response.Fail("missing token"))
		return false
	}
	_, temp, err := auth.ParseToken(tokenStr, getSecret())
	if err != nil {
		c.JSON(http.StatusUnauthorized, response.Fail("invalid token"))
		return false
	}
	if temp {
		c.JSON(http.StatusForbidden, response.Fail("must change password first"))
		return false
	}
	return true
}

// Controller 文件管理 gin handler 集合。
type Controller struct {
	svc *Service
}

// NewController 创建文件管理控制器。
func NewController(svc *Service) *Controller { return &Controller{svc: svc} }

// DefaultController 使用默认 Service 构建控制器。
func DefaultController() *Controller { return NewController(DefaultService()) }

// List GET /api/v1/files?path=<dir>
// 列出目录条目。返回 {path, files}。
func (ctrl *Controller) List(c *gin.Context) {
	dir := c.Query("path")
	abs, files, err := ctrl.svc.List(dir)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"path": abs, "files": files}))
}

// ReadContent GET /api/v1/files/content?path=<file>
// 读取小文件文本内容（限 1MB）。
func (ctrl *Controller) ReadContent(c *gin.Context) {
	path := c.Query("path")
	content, err := ctrl.svc.ReadContent(path)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"content": content}))
}

// Download GET /api/v1/files/download?path=<file>[&token=<jwt>]
// 流式下载文件。鉴权：query ?token= 或 Authorization 头（<a download> 用 query）。
func (ctrl *Controller) Download(c *gin.Context) {
	if !authToken(c) {
		return
	}
	path := c.Query("path")
	name, size, err := ctrl.svc.DownloadName(path)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filepath.Base(name)))
	c.Header("Content-Length", strconv.FormatInt(size, 10))
	c.Header("Content-Type", "application/octet-stream")
	if _, err := ctrl.svc.StreamDownload(path, c.Writer); err != nil {
		// 响应已开始写头，无法再改 JSON；记录日志即可。
		_ = err
		return
	}
}

// Upload POST /api/v1/files/upload?path=<dir>  multipart file
// 上传文件到指定目录。
func (ctrl *Controller) Upload(c *gin.Context) {
	dir := c.Query("path")
	fileHeader, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("missing file: " + err.Error()))
		return
	}
	src, err := fileHeader.Open()
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("open upload: " + err.Error()))
		return
	}
	defer src.Close()
	dst, n, err := ctrl.svc.SaveUpload(dir, fileHeader.Filename, src)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"path": dst, "size": n}))
}

// Chmod POST /api/v1/files/chmod  body ChmodRequest
// 修改文件权限（八进制串如 "0755"）。
func (ctrl *Controller) Chmod(c *gin.Context) {
	var req ChmodRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := ctrl.svc.Chmod(req.Path, req.Mode); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
}

// Chown POST /api/v1/files/chown  body ChownRequest
// 修改文件所有权（owner/group，需 root）。
func (ctrl *Controller) Chown(c *gin.Context) {
	var req ChownRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := ctrl.svc.Chown(req.Path, req.Owner, req.Group); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
}

// Mkdir POST /api/v1/files/mkdir  body MkdirRequest
// 递归创建目录（拒建根下一级目录）。
func (ctrl *Controller) Mkdir(c *gin.Context) {
	var req MkdirRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := ctrl.svc.Mkdir(req.Path); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
}

// Rename POST /api/v1/files/rename  body RenameRequest
// 重命名/移动文件或目录。
func (ctrl *Controller) Rename(c *gin.Context) {
	var req RenameRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := ctrl.svc.Rename(req.OldPath, req.NewPath); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
}

// Delete DELETE /api/v1/files?path=<file>
// 删除**单个文件**：拒绝目录、不递归。
func (ctrl *Controller) Delete(c *gin.Context) {
	path := c.Query("path")
	if err := ctrl.svc.Delete(path); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"ok": true}))
}
