// Package health 提供 /healthz 端点。
package health

import (
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/global"
)

type response struct {
	Status       string `json:"status"`
	DeviceType   string `json:"deviceType"`
	Role         string `json:"role"`
	DeviceTypeEx string `json:"deviceTypeEx,omitempty"`
	SN           string `json:"sn"`
	ChipSn       string `json:"chipSn"`
	ModuleType   string `json:"moduleType"`
	Version      string `json:"version"`
	Uptime       string `json:"uptime"`
}

// Health 处理 GET /healthz。
func Health(c *gin.Context) {
	uptime := time.Since(global.Started).Truncate(time.Second).String()
	c.JSON(200, response{
		Status:       "ok",
		DeviceType:   global.DeviceType,
		Role:         global.DeviceRole,
		DeviceTypeEx: global.DeviceTypeEx,
		SN:           global.DeviceSnEx,
		ChipSn:       global.ChipSn,
		ModuleType:   global.ModuleType,
		Version:      global.Version.Version,
		Uptime:       uptime,
	})
}
