package systemd

import (
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	sysdpkg "bmssm/pkg/systemd"
	"bmssm/pkg/response"
)

// Controller systemd 模块 gin handler 集合。
type Controller struct{}

// DefaultController 构建默认控制器。
func DefaultController() *Controller { return &Controller{} }

// ListServices GET /api/v1/systemd/services
func (ctrl *Controller) ListServices(c *gin.Context) {
	svcs, err := sysdpkg.ListServices()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(svcs))
}

// ShowService GET /api/v1/systemd/services/:name
func (ctrl *Controller) ShowService(c *gin.Context) {
	name := c.Param("name")
	d, err := sysdpkg.ShowStatus(name)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(d))
}

// Action POST /api/v1/systemd/services/:name/action
func (ctrl *Controller) Action(c *gin.Context) {
	name := c.Param("name")
	var req ActionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	err := sysdpkg.Action(name, req.Action)
	if err != nil {
		status := http.StatusInternalServerError
		switch {
		case errors.Is(err, sysdpkg.ErrProtected):
			status = http.StatusForbidden
		case errors.Is(err, sysdpkg.ErrInvalidUnitName), errors.Is(err, sysdpkg.ErrInvalidAction):
			status = http.StatusBadRequest
		}
		c.JSON(status, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "action " + req.Action + " executed"}))
}

// DaemonReload POST /api/v1/systemd/daemon-reload
func (ctrl *Controller) DaemonReload(c *gin.Context) {
	if err := sysdpkg.DaemonReload(); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "daemon-reload done"}))
}

// BootReport GET /api/v1/systemd/boot-report
func (ctrl *Controller) BootReport(c *gin.Context) {
	r, err := sysdpkg.GetBootReport()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(r))
}

// ExportReport GET /api/v1/systemd/boot-report/export?format=text|svg
func (ctrl *Controller) ExportReport(c *gin.Context) {
	format := c.DefaultQuery("format", "text")
	if format == "svg" {
		svg, err := sysdpkg.BootReportSVG()
		if err != nil {
			c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
			return
		}
		c.Header("Content-Disposition", "attachment; filename=boot-report.svg")
		c.Data(http.StatusOK, "image/svg+xml", svg)
		return
	}
	r, err := sysdpkg.GetBootReport()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.Header("Content-Disposition", "attachment; filename=boot-report.txt")
	c.Data(http.StatusOK, "text/plain; charset=utf-8", []byte(formatTextReport(r)))
}

// formatTextReport 把 BootReport 格式化为可读文本。
func formatTextReport(r *sysdpkg.BootReport) string {
	var b strings.Builder
	fmt.Fprintf(&b, "=== Boot Time Analysis ===\n")
	fmt.Fprintf(&b, "Total:      %.3fs\n", r.TotalSeconds)
	fmt.Fprintf(&b, "Kernel:     %.3fs\n", r.KernelSeconds)
	fmt.Fprintf(&b, "Userspace:  %.3fs\n", r.UserspaceSeconds)
	fmt.Fprintf(&b, "\n=== Blame (per-unit startup time) ===\n")
	for _, it := range r.Blame {
		fmt.Fprintf(&b, "%9.3fs  %s\n", it.Time, it.Unit)
	}
	fmt.Fprintf(&b, "\n=== Critical Chain ===\n")
	b.WriteString(r.CriticalChain)
	return b.String()
}
