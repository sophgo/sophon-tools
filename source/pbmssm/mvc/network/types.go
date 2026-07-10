// Package network 提供网络管理 MVC 模块：IP 查询/配置 + NAT 规则。
package network

// SetIPRequest IP 配置请求（字段对齐前端：ipType/subnetMask + ipv6*）。
//   - IPType 1=静态 2=DHCP；IPv6Type 0=不配置 1=静态 2=DHCP（与 IPv4 独立）
//   - Mask/Prefix6 为 CIDR 或点分掩码，透传给 bm_set_ip
type SetIPRequest struct {
	Device     string `json:"device" binding:"required"`
	IPType     int    `json:"ipType"`
	IP         string `json:"ip"`
	SubnetMask string `json:"subnetMask"`
	Gateway    string `json:"gateway"`
	DNS        string `json:"dns"`
	IPv6Type   int    `json:"ipv6Type"`
	IPv6       string `json:"ipv6"`
	Prefix6    string `json:"prefix6"`
	Gateway6   string `json:"gateway6"`
	DNS6       string `json:"dns6"`
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
