package software

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
)

// Controller 软件/OTA 模块 gin handler 集合。
type Controller struct {
	svc *SoftwareService
}

// NewController 创建软件/OTA 控制器。
func NewController(svc *SoftwareService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认控制器（使用包级 service）。
func DefaultController() *Controller {
	return NewController(DefaultService())
}

// ---------------------------------------------------------------
// 软件列表
// ---------------------------------------------------------------

// ListSoftware 处理 GET /api/v1/software（受保护）。
func (ctrl *Controller) ListSoftware(c *gin.Context) {
	software, err := ctrl.svc.ListSoftware()
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Error: err.Error(),
			Code:  "SOFTWARE_LIST_ERROR",
		})
		return
	}
	c.JSON(http.StatusOK, software)
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
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: "missing file field",
			Code:  "BAD_REQUEST",
		})
		return
	}
	defer file.Close()

	// 文件名校验
	origName := header.Filename
	if !isValidPackageName(origName) {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: "invalid package filename (only letters, digits, _, -, . allowed, no path separators)",
			Code:  "BAD_REQUEST",
		})
		return
	}

	// 大小限制
	if ctrl.svc.maxSize > 0 && header.Size > ctrl.svc.maxSize {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.svc.maxSize),
			Code:  "FILE_TOO_LARGE",
		})
		return
	}

	// 安全文件名
	safeName := sanitizeFileName(origName)
	savePath := filepath.Join(ctrl.svc.pkgDir, safeName)

	// 落盘
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Error: fmt.Sprintf("save file: %v", err),
			Code:  "SAVE_ERROR",
		})
		return
	}

	// 调用 service 安装
	resp, err := ctrl.svc.InstallPackage(savePath, origName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Error: err.Error(),
			Code:  "INSTALL_ERROR",
		})
		return
	}

	if !resp.Success {
		c.JSON(http.StatusInternalServerError, resp)
		return
	}

	c.JSON(http.StatusOK, resp)
}

// ---------------------------------------------------------------
// OTA 固件
// ---------------------------------------------------------------

// OTAUpload 处理 POST /api/v1/ota/upload（受保护）。
func (ctrl *Controller) OTAUpload(c *gin.Context) {
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: "missing file field",
			Code:  "BAD_REQUEST",
		})
		return
	}
	defer file.Close()

	origName := header.Filename

	// 固件名称校验
	if !isValidFirmwareName(origName) {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: fmt.Sprintf("invalid firmware filename: %s (allowed: .tgz, .bin)", origName),
			Code:  "BAD_REQUEST",
		})
		return
	}

	// 大小限制
	if ctrl.svc.maxSize > 0 && header.Size > ctrl.svc.maxSize {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.svc.maxSize),
			Code:  "FILE_TOO_LARGE",
		})
		return
	}

	// 落盘到临时路径
	savePath := filepath.Join(ctrl.svc.otaDir, "tmp_"+sanitizeFileName(origName))
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Error: fmt.Sprintf("save file: %v", err),
			Code:  "SAVE_ERROR",
		})
		return
	}

	resp, err := ctrl.svc.UploadFirmware(savePath, origName, header.Size)
	if err != nil {
		os.Remove(savePath) // 清理临时文件
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: err.Error(),
			Code:  "UPLOAD_ERROR",
		})
		return
	}

	c.JSON(http.StatusOK, resp)
}

// OTADownload 处理 GET /api/v1/ota/download/:id（受保护）。
// 返回固件上传元信息。
func (ctrl *Controller) OTADownload(c *gin.Context) {
	uid := c.Param("id")
	if uid == "" {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: "missing upload id",
			Code:  "BAD_REQUEST",
		})
		return
	}

	resp, err := ctrl.svc.GetFirmwareInfo(uid)
	if err != nil {
		c.JSON(http.StatusNotFound, ErrorResponse{
			Error: err.Error(),
			Code:  "NOT_FOUND",
		})
		return
	}

	c.JSON(http.StatusOK, resp)
}

// OTAUpgrade 处理 POST /api/v1/ota/upgrade（受保护）。
// 执行固件升级：解包 → 找升级脚本 → 执行。
// 找不到脚本返回 200 + available=false（降级），不 500。
func (ctrl *Controller) OTAUpgrade(c *gin.Context) {
	uid := c.Query("uploadId")
	if uid == "" {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Error: "missing uploadId query parameter",
			Code:  "BAD_REQUEST",
		})
		return
	}

	resp, err := ctrl.svc.ExecuteUpgrade(uid)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Error: err.Error(),
			Code:  "UPGRADE_ERROR",
		})
		return
	}

	c.JSON(http.StatusOK, resp)
}
