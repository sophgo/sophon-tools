// Package hardware 提供硬件管理 MVC 模块：健康/重启/LED/卡信息。
package hardware

// HealthResponse 硬件健康状态响应。
type HealthResponse struct {
	CPUTemp string `json:"cpuTemp,omitempty"` // sysfs 温度读数，取不到为空
	Uptime  string `json:"uptime"`
}

// RebootRequest 重启请求。
type RebootRequest struct {
	Delay int `json:"delay,omitempty"` // 0-300 秒延迟，0 或不填表示立即重启
	// ConfirmCode 二次确认码（MYS-389）：先 POST /api/v1/ops/confirm 获取
	// 一次性码（绑定用户与 reboot 动作，60s 有效），高危操作必须携带。
	ConfirmCode string `json:"confirmCode,omitempty"`
}

// LEDResponse LED 状态响应。
type LEDResponse struct {
	Available bool   `json:"available"`
	State     string `json:"state,omitempty"`
	Reason    string `json:"reason,omitempty"`
}

// LEDRequest LED 设置请求。
type LEDRequest struct {
	State string `json:"state" binding:"required"` // "on" / "off" / "blink"
}

// CardResponse BM 卡信息响应（bmlib 占位）。
type CardResponse struct {
	Available bool   `json:"available"`
	Reason    string `json:"reason,omitempty"`
}

// ErrorResponse 统一错误响应。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}
