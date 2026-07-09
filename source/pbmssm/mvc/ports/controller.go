// Package ports 提供监听端口查询 MVC handler。
package ports

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	portspkg "bmssm/pkg/ports"
	"bmssm/pkg/response"
)

// Controller 端口模块 gin handler 集合。
type Controller struct{}

// DefaultController 构建默认控制器。
func DefaultController() *Controller { return &Controller{} }

// Listening GET /api/v1/ports/listening?proto=tcp|udp
func (ctrl *Controller) Listening(c *gin.Context) {
	proto := c.Query("proto")
	socks, err := portspkg.ListListening()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	if proto == "tcp" || proto == "udp" {
		filtered := make([]portspkg.Socket, 0, len(socks))
		for _, s := range socks {
			if strings.HasPrefix(s.Proto, proto) {
				filtered = append(filtered, s)
			}
		}
		socks = filtered
	}
	c.JSON(http.StatusOK, response.OK(socks))
}
