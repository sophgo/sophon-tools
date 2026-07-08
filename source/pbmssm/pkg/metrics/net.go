package metrics

import (
	"fmt"
	"strconv"
	"strings"

	"bmssm/pkg/network"
)

// netStatsFmt sysfs 网卡统计路径格式。
const (
	netStatsFmt = "/sys/class/net/%s/statistics/%s"
	netSpeedFmt = "/sys/class/net/%s/speed"
)

// NetCards 采集网卡列表（bmssm NetCard 形状）。
// 复用 pkg/network.GetNetCards 获取 name/IPs/MAC，sysfs 补 bandwidth/tx/rx。
// DNS/Gateway/Dynamic 需 netplan 解析（降级留空，不影响 web 主显示）。
// 失败返空切片。
func (c *Collector) NetCards() []NetCard {
	cards, err := network.GetNetCards()
	if err != nil {
		return nil
	}
	return c.mapNetCards(cards)
}

// mapNetCards 把 network.NetCard 映射为 metrics.NetCard，并补 sysfs 统计。
// 跳过 loopback；IPv4 取首个，CIDR 转 netmask。
func (c *Collector) mapNetCards(cards []network.NetCard) []NetCard {
	out := make([]NetCard, 0, len(cards))
	for _, card := range cards {
		if card.IsLoopback {
			continue
		}
		nc := NetCard{
			Name: card.Name,
			Mac:  card.MAC,
		}
		// 取首个 IPv4（去 IPv6）
		for _, ipStr := range card.IPs {
			if strings.Contains(ipStr, ":") {
				continue
			}
			if idx := strings.Index(ipStr, "/"); idx >= 0 {
				nc.IP = ipStr[:idx]
				nc.Mask = cidrToMask(ipStr[idx+1:])
			} else {
				nc.IP = ipStr
			}
			break
		}
		nc.Bandwidth = int(c.readSysInt(fmt.Sprintf(netSpeedFmt, card.Name)))
		nc.NetTx = c.readSysInt(fmt.Sprintf(netStatsFmt, card.Name, "tx_bytes"))
		nc.NetRx = c.readSysInt(fmt.Sprintf(netStatsFmt, card.Name, "rx_bytes"))
		out = append(out, nc)
	}
	return out
}

// readSysInt 读 sysfs 路径并转 int64；失败返 0。
func (c *Collector) readSysInt(path string) float64 {
	s := c.readStr(path)
	if s == "" {
		return 0
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return float64(v)
}

// cidrToMask 将 CIDR 前缀长度转为点分十进制掩码。
// 对齐 compat.cidrToMask 行为；独立实现以避免与 compat 循环依赖。
func cidrToMask(cidr string) string {
	bits, err := strconv.Atoi(strings.TrimSpace(cidr))
	if err != nil || bits < 0 || bits > 32 {
		return ""
	}
	mask := uint32(0xffffffff) << (32 - bits)
	return fmt.Sprintf("%d.%d.%d.%d", byte(mask>>24), byte(mask>>16), byte(mask>>8), byte(mask))
}
