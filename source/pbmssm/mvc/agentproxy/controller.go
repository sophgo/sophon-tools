package agentproxy

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"bmssm/pkg/response"
)

// ServiceStatus Reasonix 进程服务状态快照（供前端「服务管理」展示）。
// 语义对齐旧 sophpicoclaw 上报结构，前端无需大改。
type ServiceStatus struct {
	Active       bool   `json:"active"`       // Reasonix 进程是否存活
	ActiveState  string `json:"activeState"`  // 语义值：running / stopped
	SubState     string `json:"subState"`     // process manager 生命周期状态串
	EnabledState string `json:"enabledState"` // agentproxy.enabled → enabled / disabled
	MainPID      string `json:"mainPid"`      // reasonix acp 进程 pid
	Ports        []int  `json:"ports"`        // 监听端口（agentproxy WS 端口）
	Running      bool   `json:"running"`      // 端口可达/进程存活
	Healthy      bool   `json:"healthy"`      // 健康检查（initialize 成功 + stdin 可写）
	LogTail      string `json:"logTail"`      // reasonix 最近 stderr 日志尾部
	SessionCount int    `json:"sessionCount"` // 当前活动会话数
}

// currentModule 返回全局 agentproxy 单例（与 module.go 同一包，直接用 globalMod）。
func currentModule() *Module {
	globalMu.Lock()
	defer globalMu.Unlock()
	return globalMod
}

// GetServiceStatus GET /api/v1/agent/service/status
// 返回 Reasonix（agentproxy）进程的服务状态。
func (c *Controller) GetServiceStatus(g *gin.Context) {
	st := c.buildStatus()
	g.JSON(http.StatusOK, response.OK(st))
}

func (c *Controller) buildStatus() *ServiceStatus {
	mod := currentModule()
	out := &ServiceStatus{
		Active:  false,
		Ports:   []int{},
		Running: false,
	}
	if mod == nil {
		out.ActiveState = "stopped"
		out.SubState = "not_started"
		out.EnabledState = "disabled"
		return out
	}

	sts := mod.Status()
	enabled, _ := sts["enabled"].(bool)
	alive, _ := sts["alive"].(bool)
	healthy, _ := sts["healthy"].(bool)
	pid, _ := sts["pid"].(int)
	sessionCount, _ := sts["sessionCount"].(int)
	stderr, _ := sts["stderr"].(string)

	out.Active = alive
	out.Running = alive
	out.Healthy = healthy
	out.SessionCount = sessionCount
	out.MainPID = intToStr(pid)
	out.LogTail = stderr
	out.Ports = []int{mod.cfg.Port}
	if enabled {
		out.EnabledState = "enabled"
	} else {
		out.EnabledState = "disabled"
	}
	if alive {
		out.ActiveState = "active"
		out.SubState = "running"
	} else if enabled {
		out.ActiveState = "inactive"
		out.SubState = "stopped"
	} else {
		out.ActiveState = "inactive"
		out.SubState = "disabled"
	}
	return out
}

// ServiceAction POST /api/v1/agent/service/action  body: {"action":"restart"}
// 对 Reasonix（agentproxy 托管进程）执行 start/stop/restart。
// Reasonix 由 bmssm 进程内 ProcessManager 托管（非 systemd），故
// enable/disable 由 bmssm 配置 agentproxy.enabled 决定，此处不支持（返回提示）。
func (c *Controller) ServiceAction(g *gin.Context) {
	var req struct {
		Action string `json:"action" binding:"required"`
	}
	if err := g.ShouldBindJSON(&req); err != nil {
		g.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	if err := c.action(req.Action); err != nil {
		g.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}
	g.JSON(http.StatusOK, response.OK(gin.H{"message": "action " + req.Action + " executed"}))
}

func (c *Controller) action(action string) error {
	mod := currentModule()
	if mod == nil {
		return errModuleNotStarted
	}
	switch action {
	case "start":
		// 持久化 enabled=true 并启动进程（跨 bmssm 重启保持）
		return mod.SetEnabled(true)
	case "stop":
		// 持久化 enabled=false 并停止进程（supervise 不再自愈重启）
		return mod.SetEnabled(false)
	case "restart":
		pm := mod.Process()
		if pm == nil {
			return errModuleNotStarted
		}
		pm.Restart()
		return nil
	case "enable":
		return errNoDisableSupport(action)
	case "disable":
		return errNoDisableSupport(action)
	default:
		return errInvalidAction(action)
	}
}

var (
	errModuleNotStarted = fmt.Errorf("agent 服务未启动（agentproxy 未初始化）")
	errNoDisableSupport = func(a string) error {
		return fmt.Errorf("Reasonix 随 bmssm 托管，不支持 %s；请通过 bmssm 配置 agentproxy.enabled 控制", a)
	}
	errInvalidAction = func(a string) error {
		return fmt.Errorf("invalid action: %q", a)
	}
)

// Controller Reasonix（agentproxy）服务状态与操作 handler。
// 通过全局 module（currentModule）读取/驱动 reasonix 进程。
type Controller struct{}

// DefaultController 创建 Controller。
func DefaultController() *Controller {
	return &Controller{}
}

func intToStr(n int) string { return strconv.Itoa(n) }
