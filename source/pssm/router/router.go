// Package router 注册全部路由。
package router

import (
	"time"

	"github.com/gin-gonic/gin"

	"ssm/middleware"
	"ssm/mvc/audit"
	"ssm/mvc/compat"
	"ssm/mvc/docker"
	"ssm/mvc/hardware"
	"ssm/mvc/health"
	"ssm/mvc/network"
	"ssm/mvc/software"
	"ssm/mvc/user"
)

// Register 在 engine 上注册所有路由。
func Register(r *gin.Engine) {
	// 公开端点
	r.GET("/healthz", health.Health)

	// 用户模块控制器（使用 database.DB()）
	userCtrl := user.DefaultController()
	auditCtrl := audit.DefaultController()
	netCtrl := network.DefaultController()
	dockerCtrl := docker.DefaultController()
	softwareCtrl := software.DefaultController()
	hwCtrl := hardware.DefaultController()

	// 公开：仅 login（含独立防爆破限流，约 5 次/12s/IP）
	public := r.Group("/api/v1")
	public.Use(middleware.IPRateLimit(5, 12*time.Second))
	{
		public.POST("/login", userCtrl.Login)
	}

	// ---------------------------------------------------------------
	// 兼容路由：bmssm 旧路径 /bitmain/v1/ssm/*
	// /login 公开+限流，其余路由受 JWT Auth 保护
	// ---------------------------------------------------------------
	compatCtrl := compat.DefaultController()
	compatGroup := r.Group("/bitmain/v1/ssm")
	compatGroup.POST("/login", middleware.IPRateLimit(5, 12*time.Second), compatCtrl.Login)

	protected := compatGroup.Group("", middleware.Auth())
	{
		protected.GET("/software/device/basic", compatCtrl.GetCtrlBasic)
		protected.GET("/software/device/resource/list", compatCtrl.GetCtrlResource)
		protected.GET("/hardware/ip", compatCtrl.GetIP)
		protected.POST("/hardware/ip", compatCtrl.SetIP)
		protected.GET("/hardware/nat", compatCtrl.GetNAT)
		protected.POST("/hardware/nat", compatCtrl.AddNAT)
		protected.DELETE("/hardware/nat/PREROUTING-:num", compatCtrl.DeleteNAT)
		protected.POST("/hardware/devices/reset", compatCtrl.Reboot)
		protected.POST("/hardware/devices/down", compatCtrl.Shutdown)
		protected.POST("/software/notify/subscribe", compatCtrl.SubscribeAlarm)
		protected.POST("/software/notify/unsubscribe", compatCtrl.UnsubscribeAlarm)
		protected.GET("/software/notify/subscribe/:name", compatCtrl.GetSubscription)
		protected.POST("/software/device/configure/basic", compatCtrl.SetBasic)
		protected.POST("/software/device/configure/alarm", compatCtrl.SetAlarm)
		protected.POST("/file/ota", compatCtrl.UploadFirmware)
		protected.POST("/workflow/upgrade", compatCtrl.ExecuteUpgrade)
		protected.GET("/workflow/upgrade", compatCtrl.ListWorkflows)
		protected.GET("/workflow/upgrade/:id", compatCtrl.GetWorkflow)
		protected.POST("/workflow/rollback", compatCtrl.Rollback)
		protected.POST("/hardware/devices/scp", compatCtrl.SCP)
		protected.POST("/hardware/devices/exec", compatCtrl.Exec)
	}

	// 受保护：其余都需要 Auth 中间件
	// logout 也在此组，便于读 c.Get("user") 记审计
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	{
		api.POST("/logout", userCtrl.Logout)

		// 用户管理
		api.GET("/user", userCtrl.ListUsers)
		api.POST("/user", userCtrl.CreateUser)
		api.DELETE("/user/:name", userCtrl.DeleteUser)

		// 审计日志
		api.GET("/audit", auditCtrl.ListLogs)

		// 网络
		api.GET("/network/ip", netCtrl.GetIP)
		api.PUT("/network/ip", netCtrl.SetIP)
		api.POST("/network/nat", netCtrl.AddNAT)

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
		api.POST("/ota/upload", softwareCtrl.OTAUpload)
		api.GET("/ota/download/:id", softwareCtrl.OTADownload)
		api.POST("/ota/upgrade", softwareCtrl.OTAUpgrade)

		// 硬件
		api.GET("/hardware/health", hwCtrl.GetHealth)
		api.POST("/hardware/reboot", hwCtrl.Reboot)
		api.GET("/hardware/led", hwCtrl.GetLED)
		api.PUT("/hardware/led", hwCtrl.SetLED)
		api.GET("/hardware/card", hwCtrl.GetCard)
	}
}
