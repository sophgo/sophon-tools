// Package router 注册全部路由。
package router

import (
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/middleware"
	"bmssm/mvc/alarm"
	"bmssm/mvc/audit"
	"bmssm/mvc/compat"
	"bmssm/mvc/docker"
	"bmssm/mvc/filemanage"
	firewallCtrl "bmssm/mvc/firewall"
	"bmssm/mvc/hardware"
	"bmssm/mvc/health"
	"bmssm/mvc/logs"
	metricsCtrl "bmssm/mvc/metrics"
	"bmssm/mvc/network"
	portsCtrl "bmssm/mvc/ports"
	"bmssm/mvc/software"
	systemdCtrl "bmssm/mvc/systemd"
	"bmssm/mvc/user"
	"bmssm/pkg/metrics"
)

// Register 在 engine 上注册所有路由。
func Register(r *gin.Engine) {
	// 公开端点
	r.GET("/healthz", health.Health)

	// Prometheus metrics 端点（公开，Prometheus scrape 不加 Authorization header）
	r.GET("/metrics", metrics.PromHandler())
	// /health JSON 端点（公开）
	r.GET("/health", metrics.HealthHandler())

	// 用户模块控制器（使用 database.DB()）
	userCtrl := user.DefaultController()
	auditCtrl := audit.DefaultController()
	logsCtrl := logs.DefaultController()
	alarmCtrl := alarm.DefaultController()
	netCtrl := network.DefaultController()
	dockerCtrl := docker.DefaultController()
	softwareCtrl := software.DefaultController()
	hwCtrl := hardware.DefaultController()
	fileCtrl := filemanage.DefaultController()
	compatCtrl := compat.DefaultController()
	systemdC := systemdCtrl.DefaultController()
	portsC := portsCtrl.DefaultController()
	fwCtrl := firewallCtrl.DefaultController()

	// 公开：仅 login（含独立防爆破限流，约 5 次/12s/IP）
	public := r.Group("/api/v1")
	public.Use(middleware.IPRateLimit(5, 12*time.Second))
	{
		public.POST("/login", userCtrl.Login)
	}

	// WebSocket 实时终端：不走 Auth 中间件（浏览器无法加 Authorization header），
	// handler 内从 query ?token= 手动鉴权。
	r.GET("/api/v1/hardware/terminal", compatCtrl.TerminalWS)

	// 文件下载：不走 Auth 中间件，handler 内从 query ?token= 或 Authorization 头
	// 鉴权。<a download> 无法带 Authorization 头，故走 query token；浏览器原生
	// 流式落盘，避免 XHR blob 把大文件整块读入内存。
	r.GET("/api/v1/files/download", fileCtrl.Download)

	// 受保护：其余都需要 Auth 中间件
	// logout 也在此组，便于读 c.Get("user") 记审计
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	{
		api.POST("/logout", userCtrl.Logout)
		api.POST("/password", userCtrl.ChangePassword)

		// 用户管理（仅 superuser/admin）
		api.GET("/user", userCtrl.ListUsers)
		api.POST("/user", userCtrl.CreateUser)
		api.DELETE("/user/:name", userCtrl.DeleteUser)

		// 审计日志
		api.GET("/audit", auditCtrl.ListLogs)

		// 系统日志下载（流式 tar.gz: /var/log/kern* + syslog*）
		api.GET("/logs/download", logsCtrl.DownloadLogs)

		// 告警历史
		api.GET("/alarms", alarmCtrl.ListAlarms)

		// 性能指标历史
		metricsC := metricsCtrl.DefaultController()
		api.GET("/metrics/fields", metricsC.GetFields)
		api.GET("/metrics/history", metricsC.GetHistory)
		api.GET("/metrics/export", metricsC.GetExport)

		// 网络
		api.GET("/network/ip", netCtrl.GetIP)
		// NAT（compat 形态：sophliteos 使用 AddTable/Dirt）
		api.GET("/network/nat", compatCtrl.GetNAT)

		// 服务管理
		api.GET("/systemd/services", systemdC.ListServices)
		api.GET("/systemd/services/:name", systemdC.ShowService)
		api.GET("/systemd/boot-report", systemdC.BootReport)
		api.GET("/systemd/boot-report/export", systemdC.ExportReport)

		// 端口状态
		api.GET("/ports/listening", portsC.Listening)

		// Docker
		api.GET("/docker/container", dockerCtrl.ListContainers)
		api.GET("/docker/image", dockerCtrl.ListImages)
		api.GET("/docker/logs/:name", dockerCtrl.GetLogs)

		// 软件/OTA（列表读操作）
		api.GET("/software", softwareCtrl.ListSoftware)
		// 保留旧 uploadId 查询端点（不破坏既有调用方）
		api.GET("/ota/download/:id", softwareCtrl.OTADownload)
		api.GET("/ota/workflow", compatCtrl.ListWorkflows)
		api.GET("/ota/workflow/:id", compatCtrl.GetWorkflow)

		// 硬件
		api.GET("/hardware/health", hwCtrl.GetHealth)
		api.GET("/hardware/led", hwCtrl.GetLED)
		api.GET("/hardware/card", hwCtrl.GetCard)

		// 设备信息 / 配置（读）
		api.GET("/device/basic", compatCtrl.GetCtrlBasic)
		api.GET("/device/resource", compatCtrl.GetCtrlResource)
		api.GET("/device/configure/alarm", compatCtrl.GetAlarm)

		// 告警订阅
		api.GET("/software/notify/subscribe/:name", compatCtrl.GetSubscription)

		// 防火墙
		api.GET("/firewall/status", fwCtrl.Status)
		api.GET("/firewall/intent", fwCtrl.ListIntents)
	}

	// adminOnly：高风险写/执行操作，仅 superuser/admin 可调。
	admin := r.Group("/api/v1")
	admin.Use(middleware.Auth(), middleware.RequireAdmin())
	{
		// 网络（写）
		admin.PUT("/network/ip", netCtrl.SetIP)
		admin.POST("/network/nat", compatCtrl.AddNAT)
		admin.DELETE("/network/nat/:num", compatCtrl.DeleteNAT)

		// 服务管理（写）
		admin.POST("/systemd/services/:name/action", systemdC.Action)
		admin.POST("/systemd/daemon-reload", systemdC.DaemonReload)

		// Docker（写）
		admin.POST("/docker/container/:name/start", dockerCtrl.StartContainer)
		admin.POST("/docker/container/:name/stop", dockerCtrl.StopContainer)
		admin.DELETE("/docker/container/:name", dockerCtrl.RemoveContainer)
		admin.DELETE("/docker/image/:id", dockerCtrl.RemoveImage)

		// 软件/OTA（写）
		admin.POST("/software/install", softwareCtrl.Install)
		admin.POST("/software/upgrade", softwareCtrl.Upgrade)
		admin.POST("/ota/upload", compatCtrl.UploadFirmware)
		admin.POST("/ota/upgrade", compatCtrl.ExecuteUpgrade)
		admin.POST("/ota/rollback", compatCtrl.Rollback)

		// 硬件（写）
		admin.POST("/hardware/reboot", hwCtrl.Reboot)
		admin.POST("/hardware/shutdown", compatCtrl.Shutdown)
		admin.PUT("/hardware/led", hwCtrl.SetLED)
		admin.POST("/hardware/exec", compatCtrl.Exec)
		admin.POST("/hardware/scp", compatCtrl.SCP)

		// 设备配置（写）
		admin.POST("/device/configure/basic", compatCtrl.SetBasic)
		admin.POST("/device/configure/alarm", compatCtrl.SetAlarm)

		// 告警订阅（写）
		admin.POST("/software/notify/subscribe", compatCtrl.SubscribeAlarm)
		admin.POST("/software/notify/unsubscribe", compatCtrl.UnsubscribeAlarm)

		// 文件管理（读 + 写均需 admin：涉及设备敏感文件）
		// 注：download 保留在公开区（<a download> 需 query token 鉴权），见 public 段。
		admin.GET("/files", fileCtrl.List)
		admin.GET("/files/content", fileCtrl.ReadContent)
		admin.POST("/files/upload", fileCtrl.Upload)
		admin.POST("/files/chmod", fileCtrl.Chmod)
		admin.POST("/files/chown", fileCtrl.Chown)
		admin.POST("/files/mkdir", fileCtrl.Mkdir)
		admin.POST("/files/rename", fileCtrl.Rename)
		admin.DELETE("/files", fileCtrl.Delete)

		// 防火墙（写）
		admin.POST("/firewall/intent", fwCtrl.AddIntent)
		admin.DELETE("/firewall/intent/:id", fwCtrl.DeleteIntent)
		admin.POST("/firewall/rebuild", fwCtrl.Rebuild)
	}
}
