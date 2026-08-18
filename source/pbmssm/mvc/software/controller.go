package software

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"

	"bmssm/database"
	"bmssm/mvc/audit"
	"bmssm/pkg/hazard"
	"bmssm/pkg/response"
)

// Controller 软件/OTA 模块 gin handler 集合。
type Controller struct {
	svc *SoftwareService
	aud *audit.AuditService
}

// NewController 创建软件/OTA 控制器。
func NewController(svc *SoftwareService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认控制器（使用包级 service）。
func DefaultController() *Controller {
	ctrl := NewController(DefaultService())
	ctrl.aud = audit.NewService(database.DB())
	return ctrl
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// requireHazardGuard 校验二次确认码并占用高危互斥锁（MYS-389）。
// 返回 guard 与 bool：false 时已写出错误响应，直接 return。
func (ctrl *Controller) requireHazardGuard(c *gin.Context, holder, action string, confirm string) (*hazard.Guard, bool) {
	username, _ := c.Get("user")
	uname, _ := username.(string)
	if !hazard.VerifyConfirmCode(confirm) {
		ctrl.auditWrite(c, uname, action, "software", "confirmation_failed")
		c.JSON(http.StatusForbidden, response.Fail("confirmation required: fetch /api/v1/hazard/challenge first"))
		return nil, false
	}
	guard, err := hazard.HazardOps.TryAcquire(holder)
	if err != nil {
		ctrl.auditWrite(c, uname, action, "software", "blocked")
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return nil, false
	}
	return guard, true
}

// ---------------------------------------------------------------
// 软件列表
// ---------------------------------------------------------------

// ListSoftware 处理 GET /api/v1/software（受保护）。
func (ctrl *Controller) ListSoftware(c *gin.Context) {
	software, err := ctrl.svc.ListSoftware()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(software))
}

// ---------------------------------------------------------------
// 软件安装 / 升级
// ---------------------------------------------------------------

// Install 处理 POST /api/v1/software/install（受保护）。
// 接收 multipart file，落盘后调用 service 安装。
func (ctrl *Controller) Install(c *gin.Context) {
	ctrl.handleSoftwareUpload(c, "install")
}

// Upgrade 处理 POST /api/v1/software/upgrade（受保护）。
func (ctrl *Controller) Upgrade(c *gin.Context) {
	ctrl.handleSoftwareUpload(c, "upgrade")
}

// handleSoftwareUpload 处理软件包上传与安装/升级。
func (ctrl *Controller) handleSoftwareUpload(c *gin.Context, action string) {
	// MYS-389：二次确认 + 审计；软件安装允许并发（holder 为空不占排它锁）
	guard, ok := ctrl.requireHazardGuard(c, "", "software."+action, c.PostForm("confirm"))
	if !ok {
		return
	}
	defer guard.Release()

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("missing file field"))
		return
	}
	defer file.Close()

	// 文件名校验
	origName := header.Filename
	if !isValidPackageName(origName) {
		c.JSON(http.StatusBadRequest, response.Fail("invalid package filename (only letters, digits, _, -, . allowed, no path separators)"))
		return
	}

	// 大小限制
	if ctrl.svc.maxSize > 0 && header.Size > ctrl.svc.maxSize {
		c.JSON(http.StatusBadRequest, response.Fail(fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.svc.maxSize)))
		return
	}

	// 安全文件名
	safeName := sanitizeFileName(origName)
	savePath := filepath.Join(ctrl.svc.pkgDir, safeName)

	// 落盘
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(fmt.Sprintf("save file: %v", err)))
		return
	}

	// 调用 service 安装
	resp, err := ctrl.svc.InstallPackage(savePath, origName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	if !resp.Success {
		username, _ := c.Get("user")
		uname, _ := username.(string)
		ctrl.auditWrite(c, uname, "software."+action, "software", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(resp.Message))
		return
	}

	username, _ := c.Get("user")
	uname, _ := username.(string)
	ctrl.auditWrite(c, uname, "software."+action, "software", "success")
	c.JSON(http.StatusOK, response.OK(resp))
}

// ---------------------------------------------------------------
// OTA 固件
// ---------------------------------------------------------------

// OTAUpload 处理 POST /api/v1/ota/upload（受保护）。
func (ctrl *Controller) OTAUpload(c *gin.Context) {
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("missing file field"))
		return
	}
	defer file.Close()

	origName := header.Filename

	// 固件名称校验
	if !isValidFirmwareName(origName) {
		c.JSON(http.StatusBadRequest, response.Fail(fmt.Sprintf("invalid firmware filename: %s (allowed: .tgz, .bin)", origName)))
		return
	}

	// 大小限制
	if ctrl.svc.maxSize > 0 && header.Size > ctrl.svc.maxSize {
		c.JSON(http.StatusBadRequest, response.Fail(fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.svc.maxSize)))
		return
	}

	// 落盘到临时路径
	savePath := filepath.Join(ctrl.svc.otaDir, "tmp_"+sanitizeFileName(origName))
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(fmt.Sprintf("save file: %v", err)))
		return
	}

	resp, err := ctrl.svc.UploadFirmware(savePath, origName, header.Size)
	if err != nil {
		os.Remove(savePath) // 清理临时文件
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(resp))
}

// OTADownload 处理 GET /api/v1/ota/download/:id（受保护）。
// 返回固件上传元信息。
func (ctrl *Controller) OTADownload(c *gin.Context) {
	uid := c.Param("id")
	if uid == "" {
		c.JSON(http.StatusBadRequest, response.Fail("missing upload id"))
		return
	}

	resp, err := ctrl.svc.GetFirmwareInfo(uid)
	if err != nil {
		c.JSON(http.StatusNotFound, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(resp))
}

// OTAUpgrade 处理 POST /api/v1/ota/upgrade（受保护）。
// 执行固件升级：解包 → 找升级脚本 → 执行。
// 找不到脚本返回 200 + available=false（降级），不 500。
func (ctrl *Controller) OTAUpgrade(c *gin.Context) {
	uid := c.Query("uploadId")
	if uid == "" {
		c.JSON(http.StatusBadRequest, response.Fail("missing uploadId query parameter"))
		return
	}

	// MYS-389：二次确认 + 高危互斥 + 审计
	guard, ok := ctrl.requireHazardGuard(c, "ota.upgrade", "ota.upgrade", c.Query("confirm"))
	if !ok {
		return
	}
	defer guard.Release()

	resp, err := ctrl.svc.ExecuteUpgrade(uid)
	if err != nil {
		username, _ := c.Get("user")
		uname, _ := username.(string)
		ctrl.auditWrite(c, uname, "ota.upgrade", "ota", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	username, _ := c.Get("user")
	uname, _ := username.(string)
	ctrl.auditWrite(c, uname, "ota.upgrade", "ota", "success")
	c.JSON(http.StatusOK, response.OK(resp))
}
