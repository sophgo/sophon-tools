// Package network 提供网络管理 MVC 模块：IP 查询/配置 + NAT 规则。
package network

// SetIPRequest IP 配置请求。
type SetIPRequest struct {
	Device  string `json:"device" binding:"required"`
	Policy  string `json:"policy"` // "static" or "dhcp"
	IP      string `json:"ip"`
	Mask    string `json:"mask"`
	Gateway string `json:"gateway"`
	DNS     string `json:"dns"`
}

// NatRequest NAT 规则请求。
type NatRequest struct {
	Direction string `json:"direction" binding:"required"` // "in" or "out"
	Op        string `json:"op" binding:"required"`        // "append" or "delete"
	Src       string `json:"src"`
	Dst       string `json:"dst"`
	SrcPort   string `json:"srcPort,omitempty"`
	DstPort   string `json:"dstPort,omitempty"`
	Protocol  string `json:"protocol,omitempty"`
	Flags     string `json:"flags,omitempty"`
}

// ErrorResponse 统一错误响应。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}
