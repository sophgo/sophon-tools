package main

// 无 MAC 的降级扫描：用 ICMP echo 判断主机是否在线。
//
// 什么时候用：
//   * 拿不到 MAC（无 CAP_NET_RAW、读不到 ARP 缓存）；
//   * 目标不在同一广播域（ARP 只在本网段有效，跨网段必须靠三层）；
//   * 用户显式选择「仅 ping」模式。
//
// 权限：Linux 上走内核 ping socket（SOCK_DGRAM + IPPROTO_ICMP），
// 受 /proc/sys/net/ipv4/ping_group_range 控制，默认对所有组开放，
// **普通用户可用，不需要 root**。

import (
	"context"
	"fmt"
	"net"
	"sync"
	"time"
)

// pingScan 并发探测网段内所有地址，返回在线主机（不含 MAC）。
//
// 刻意放慢（默认并发 32、包间留间隔），理由与 ARP 模式一致：
// 避免瞬时大量 ICMP 被 IDS 判定为扫描。用户已明确接受"慢一点"。
func pingScan(ctx context.Context, hosts []net.IP, timeout time.Duration, workers int) ([]ScanResult, error) {
	if workers <= 0 {
		workers = 32
	}
	if len(hosts) == 0 {
		return nil, nil
	}
	// 先确认 ICMP 到底能不能用：不能用就立刻返回明确错误，
	// 而不是把整个网段白扫一遍。
	if err := icmpAvailable(); err != nil {
		return nil, fmt.Errorf("无法创建 ICMP 套接字(%v)。请检查 "+
			"/proc/sys/net/ipv4/ping_group_range 是否包含当前用户组", err)
	}

	var (
		mu    sync.Mutex
		found []ScanResult
	)
	sem := make(chan struct{}, workers)
	var wg sync.WaitGroup
	gap := time.Second / time.Duration(workers*4)

loop:
	for _, ip := range hosts {
		select {
		case <-ctx.Done():
			break loop
		case <-time.After(gap):
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(ip net.IP) {
			defer wg.Done()
			defer func() { <-sem }()
			if pingHost(ctx, ip, timeout) {
				mu.Lock()
				found = append(found, ScanResult{IP: ip.String()})
				mu.Unlock()
			}
		}(ip)
	}
	wg.Wait()
	return found, nil
}
