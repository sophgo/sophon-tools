//go:build !linux

package main

// 非 Linux 平台：不支持主动 ARP 扫描。
//
// Windows 发原始以太帧需要 Npcap 之类的额外驱动，与"单二进制、零外部依赖"
// 的交付方式冲突；因此这里明确报错，而不是假装成功。

import (
	"context"
	"errors"
	"net"
	"time"
)

type ifaceInfo struct {
	Name string
	IP   net.IP
	MAC  net.HardwareAddr
}

var errScanUnsupported = errors.New("当前平台不支持主动 ARP 扫描（仅 Linux 支持）")

func pickInterface(want string, ipnet *net.IPNet, hosts []net.IP) (*ifaceInfo, error) {
	return nil, errScanUnsupported
}

func arpScan(ctx context.Context, ifc *ifaceInfo, hosts []net.IP,
	timeout time.Duration, workers int) (map[string]string, error) {
	return nil, errScanUnsupported
}

func readARPTablePlatform() (map[string]string, error) {
	return nil, errScanUnsupported
}

func isPrivilegedForRawSocket() bool { return false }
