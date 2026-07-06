package network

import (
	"ssm/pkg/network"
)

// NetworkService 封装网络操作业务逻辑。
type NetworkService struct{}

// NewService 创建 NetworkService。
func NewService() *NetworkService {
	return &NetworkService{}
}

// GetIPList 查询网卡 IP 列表。
func (s *NetworkService) GetIPList() ([]network.NetCard, error) {
	return network.GetNetCards()
}

// SetIP 配置网卡 IP（按 policy 分发：dhcp 或 static）。
func (s *NetworkService) SetIP(policy, device, ip, mask, gateway, dns string) error {
	if policy == "dhcp" {
		return network.SetDynamicIP(device)
	}
	return network.SetStaticIP(device, ip, mask, gateway, dns)
}

// AddNAT 添加或删除 NAT 规则。
func (s *NetworkService) AddNAT(rule network.NatRule) error {
	return network.AddNATRule(rule)
}

// GetNATRules 查询当前 NAT 表规则。
func (s *NetworkService) GetNATRules() ([]string, error) {
	return network.GetNATRules()
}
