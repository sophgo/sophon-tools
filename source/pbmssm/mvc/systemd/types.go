// Package systemd 提供 systemd 服务管理 MVC handler。
package systemd

// ActionRequest 服务操作请求。
type ActionRequest struct {
	Action string `json:"action" binding:"required"` // start|stop|restart|reload|enable|disable
}
