package docker

import (
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

// Controller Docker 模块 gin handler 集合。
type Controller struct {
	svc *DockerService
}

// NewController 创建 Docker 控制器。
func NewController(svc *DockerService) *Controller {
	return &Controller{svc: svc}
}

// DefaultController 构建默认控制器（使用懒初始化的包级 service）。
func DefaultController() *Controller {
	return NewController(DefaultService())
}

// handleDegraded 写入降级响应（200 + available:false）。
func (ctrl *Controller) handleDegraded(c *gin.Context) {
	c.JSON(http.StatusOK, DegradedResponse{
		Available: false,
		Reason:    "docker not available",
	})
}

// handleDockerError 根据 docker 错误类型写入适当的 HTTP 错误响应。
func (ctrl *Controller) handleDockerError(c *gin.Context, err error) {
	if err == nil {
		return
	}
	c.JSON(http.StatusBadGateway, ErrorResponse{
		Error: err.Error(),
		Code:  "DOCKER_ERROR",
	})
}

// ListContainers 处理 GET /api/v1/docker/container（受保护）。
func (ctrl *Controller) ListContainers(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	status := c.Query("status")
	containers, err := ctrl.svc.ListContainers(status)
	if err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, containers)
}

// StartContainer 处理 POST /api/v1/docker/container/:name/start（受保护）。
func (ctrl *Controller) StartContainer(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	name := c.Param("name")
	if err := validateName(name); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "BAD_REQUEST"})
		return
	}

	if err := ctrl.svc.StartContainer(name); err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "container started"})
}

// StopContainer 处理 POST /api/v1/docker/container/:name/stop（受保护）。
func (ctrl *Controller) StopContainer(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	name := c.Param("name")
	if err := validateName(name); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "BAD_REQUEST"})
		return
	}

	timeout := uint(10) // 默认 10 秒
	if t := c.Query("timeout"); t != "" {
		parsed, err := strconv.ParseUint(t, 10, 32)
		if err != nil {
			c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid timeout", Code: "BAD_REQUEST"})
			return
		}
		timeout = uint(parsed)
	}

	if err := ctrl.svc.StopContainer(name, timeout); err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "container stopped"})
}

// RemoveContainer 处理 DELETE /api/v1/docker/container/:name（受保护）。
func (ctrl *Controller) RemoveContainer(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	name := c.Param("name")
	if err := validateName(name); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "BAD_REQUEST"})
		return
	}

	force := false
	if f := c.Query("force"); f == "true" || f == "1" {
		force = true
	}

	if err := ctrl.svc.RemoveContainer(name, force); err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "container removed"})
}

// ListImages 处理 GET /api/v1/docker/image（受保护）。
func (ctrl *Controller) ListImages(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	images, err := ctrl.svc.ListImages()
	if err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, images)
}

// RemoveImage 处理 DELETE /api/v1/docker/image/:id（受保护）。
func (ctrl *Controller) RemoveImage(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	id := c.Param("id")
	if err := validateID(id); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "BAD_REQUEST"})
		return
	}

	if err := ctrl.svc.RemoveImage(id); err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "image removed"})
}

// GetLogs 处理 GET /api/v1/docker/logs/:name（受保护）。
func (ctrl *Controller) GetLogs(c *gin.Context) {
	if !ctrl.svc.IsAvailable() {
		ctrl.handleDegraded(c)
		return
	}

	name := c.Param("name")
	if err := validateName(name); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{Error: err.Error(), Code: "BAD_REQUEST"})
		return
	}

	tail := c.DefaultQuery("tail", "100")
	sinceStr := c.Query("since")
	var since int64
	if sinceStr != "" {
		parsed, err := strconv.ParseInt(sinceStr, 10, 64)
		if err != nil {
			c.JSON(http.StatusBadRequest, ErrorResponse{Error: "invalid since parameter", Code: "BAD_REQUEST"})
			return
		}
		since = parsed
	}

	logs, err := ctrl.svc.GetLogs(name, tail, since)
	if err != nil {
		ctrl.handleDockerError(c, err)
		return
	}
	c.JSON(http.StatusOK, LogsResponse{Logs: logs})
}

// validateName 校验容器名称：只允许字母、数字、下划线、短横线、点号，最长 256 字符。
// Docker client 通过 API 参数化调用（非 shell），但本校验防止路径注入。
func validateName(name string) error {
	if name == "" {
		return errors.New("name is required")
	}
	if len(name) > 256 {
		return errors.New("name too long")
	}
	for _, r := range name {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || r == '_' || r == '-' || r == '.' {
			continue
		}
		return errors.New("name contains invalid characters")
	}
	return nil
}

// validateID 校验镜像 ID：hash 格式（字母数字 + : 允许 tag）
func validateID(id string) error {
	if id == "" {
		return errors.New("id is required")
	}
	if len(id) > 512 {
		return errors.New("id too long")
	}
	// 允许 sha256: 前缀和常见 hash 字符
	for _, r := range id {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || strings.ContainsRune(":_-.@/+", r) {
			continue
		}
		return errors.New("id contains invalid characters")
	}
	return nil
}
