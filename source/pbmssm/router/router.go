// Package router 注册全部路由。
package router

import (
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/middleware"
	"bmssm/mvc/alarm"
	"bmssm/mvc/audit"
	"bmssm/mvc/logs"
	"bmssm/mvc/compat"
	"bmssm/mvc/docker"
	"bmssm/mvc/filemanage"
	"bmssm/mvc/hardware"
	"bmssm/mvc/health"
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

		// 用户管理
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
		api.PUT("/network/ip", netCtrl.SetIP)
		// NAT（compat 形态：sophliteos 使用 AddTable/Dirt）
		api.GET("/network/nat", compatCtrl.GetNAT)
		api.POST("/network/nat", compatCtrl.AddNAT)
		api.DELETE("/network/nat/:num", compatCtrl.DeleteNAT)

		// 服务管理
		api.GET("/systemd/services", systemdC.ListServices)
		api.GET("/systemd/services/:name", systemdC.ShowService)
		api.POST("/systemd/services/:name/action", systemdC.Action)
		api.POST("/systemd/daemon-reload", systemdC.DaemonReload)
		api.GET("/systemd/boot-report", systemdC.BootReport)
		api.GET("/systemd/boot-report/export", systemdC.ExportReport)

		// 端口状态
		api.GET("/ports/listening", portsC.Listening)

		// Docker
		api.GET("/docker/container", dockerCtrl.ListContainers)
		api.POST("/docker/container/:name/start", dockerCtrl.StartContainer)
		api.POST("/docker/container/:name/stop", dockerCtrl.StopContainer)
		api.DELETE("/docker/container/:name", dockerCtrl.RemoveContainer)
		api.GET("/docker/image", dockerCtrl.ListImages)
		api.DELETE("/docker/image/:id", dockerCtrl.RemoveImage)
		api.GET("/docker/logs/:name", dockerCtrl.GetLogs)

		// 软件/OTA
		api.GET("/software", softwareCtrl.ListSoftware)
		api.POST("/software/install", softwareCtrl.Install)
		api.POST("/software/upgrade", softwareCtrl.Upgrade)
		// OTA（compat 工作流：upload→upgrade→list/get workflow→rollback）
		api.POST("/ota/upload", compatCtrl.UploadFirmware)
		api.POST("/ota/upgrade", compatCtrl.ExecuteUpgrade)
		api.GET("/ota/workflow", compatCtrl.ListWorkflows)
		api.GET("/ota/workflow/:id", compatCtrl.GetWorkflow)
		api.POST("/ota/rollback", compatCtrl.Rollback)
		// 保留旧 uploadId 查询端点（不破坏既有调用方）
		api.GET("/ota/download/:id", softwareCtrl.OTADownload)

		// 硬件
		api.GET("/hardware/health", hwCtrl.GetHealth)
		api.POST("/hardware/reboot", hwCtrl.Reboot)
		api.POST("/hardware/shutdown", compatCtrl.Shutdown)
		api.GET("/hardware/led", hwCtrl.GetLED)
		api.PUT("/hardware/led", hwCtrl.SetLED)
		api.GET("/hardware/card", hwCtrl.GetCard)
		api.POST("/hardware/exec", compatCtrl.Exec)
		api.POST("/hardware/scp", compatCtrl.SCP)

		// 设备信息 / 配置（原 compat /bitmain/v1/ssm/* 迁移）
		api.GET("/device/basic", compatCtrl.GetCtrlBasic)
		api.GET("/device/resource", compatCtrl.GetCtrlResource)
		api.POST("/device/configure/basic", compatCtrl.SetBasic)
		api.GET("/device/configure/alarm", compatCtrl.GetAlarm)
		api.POST("/device/configure/alarm", compatCtrl.SetAlarm)

		// 告警订阅
		api.POST("/software/notify/subscribe", compatCtrl.SubscribeAlarm)
		api.POST("/software/notify/unsubscribe", compatCtrl.UnsubscribeAlarm)
		api.GET("/software/notify/subscribe/:name", compatCtrl.GetSubscription)

		// 文件管理（download 已上移至公开路由，支持 query token）
		api.GET("/files", fileCtrl.List)
		api.GET("/files/content", fileCtrl.ReadContent)
		api.POST("/files/upload", fileCtrl.Upload)
		api.POST("/files/chmod", fileCtrl.Chmod)
		api.POST("/files/chown", fileCtrl.Chown)
		api.POST("/files/mkdir", fileCtrl.Mkdir)
		api.POST("/files/rename", fileCtrl.Rename)
		api.DELETE("/files", fileCtrl.Delete)
	}
}
