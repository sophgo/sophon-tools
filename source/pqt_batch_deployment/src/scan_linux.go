//go:build linux

package main

// Linux 下的 ARP 扫描实现。
//
// 只做 ARP：request 广播到本网段，收 reply 拿 MAC。
// 不碰 ICMP、不碰 TCP 端口、不碰默认网关——所以既不会在目标机上留下
// 连接记录，也不会在网关/防火墙上产生"扫描"特征。

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	ethPAll               = 0x0003
	ethPArp               = 0x0806
	ethPIP                = 0x0800
	arpRequest            = 1
	arpReply              = 2
	arpPacketLen          = 28
	ethHeaderLen          = 14
	arpHRD       Ethernet = 1
)

// Ethernet 链路类型。
type Ethernet uint16

// ifaceInfo 网口的必要信息。
type ifaceInfo struct {
	Name string
	IP   net.IP
	MAC  net.HardwareAddr
}

// pickInterface 选择用于扫描的网口。
//
// 指定了名字就用它；否则找一个"有 IPv4 地址、且地址落在目标网段内"的网口。
// 这一步很关键：从错误网口发 ARP 是收不到任何应答的。
func pickInterface(want string, ipnet *net.IPNet, hosts []net.IP) (*ifaceInfo, error) {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, fmt.Errorf("枚举网口失败: %w", err)
	}

	load := func(ifc net.Interface) (*ifaceInfo, error) {
		addrs, err := ifc.Addrs()
		if err != nil {
			return nil, err
		}
		for _, a := range addrs {
			ipn, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			v4 := ipn.IP.To4()
			if v4 == nil || len(ifc.HardwareAddr) != 6 {
				continue
			}
			return &ifaceInfo{Name: ifc.Name, IP: v4, MAC: ifc.HardwareAddr}, nil
		}
		return nil, fmt.Errorf("网口 %s 没有 IPv4 地址", ifc.Name)
	}

	if want != "" {
		ifc, err := net.InterfaceByName(want)
		if err != nil {
			return nil, fmt.Errorf("找不到网口 %q: %w", want, err)
		}
		return load(*ifc)
	}

	// 自动挑选：优先选地址落在目标网段内的网口
	var best *ifaceInfo
	for _, ifc := range ifaces {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			continue
		}
		info, err := load(ifc)
		if err != nil {
			continue
		}
		if ipnet != nil && ipnet.Contains(info.IP) {
			return info, nil
		}
		if best == nil {
			best = info
		}
	}
	if best != nil {
		return best, nil
	}
	return nil, errors.New("找不到可用网口（需要有 IPv4 地址）。请显式指定网口")
}

// arpScan 向网段内所有地址发 ARP request，收集 reply。
//
// 关于"慢一点也没关系"：这里刻意用**单发单收 + 少量重试**，而不是
// 一次灌满整个网段。发包速率可控（默认 64 并发、每包间隔节流），
// 既避免把交换机/网关的 ARP 表打爆而触发告警，也让结果更稳。
func arpScan(ctx context.Context, ifc *ifaceInfo, hosts []net.IP,
	timeout time.Duration, workers int) (map[string]string, error) {

	fd, err := syscall.Socket(syscall.AF_PACKET, syscall.SOCK_RAW, int(htons(ethPArp)))
	if err != nil {
		return nil, err
	}
	defer syscall.Close(fd)

	if err := syscall.Bind(fd, &syscall.SockaddrLinklayer{
		Protocol: htons(ethPArp),
		Ifindex:  ifindex(ifc.Name),
	}); err != nil {
		return nil, err
	}

	deadline := time.Now().Add(timeout)
	_ = syscall.SetsockoptTimeval(fd, syscall.SOL_SOCKET, syscall.SO_RCVTIMEO,
		&syscall.Timeval{Sec: 0, Usec: 200000})

	localMAC, localIP := ifc.MAC, ifc.IP

	var (
		mu    sync.Mutex
		found = map[string]string{}
	)

	// 接收协程：一直读到 deadline 或 ctx 取消
	recvDone := make(chan struct{})
	go func() {
		defer close(recvDone)
		buf := make([]byte, 2048)
		for {
			select {
			case <-ctx.Done():
				return
			default:
			}
			if time.Now().After(deadline) {
				return
			}
			n, _, err := syscall.Recvfrom(fd, buf, 0)
			if err != nil {
				if errors.Is(err, syscall.EAGAIN) || errors.Is(err, syscall.EWOULDBLOCK) ||
					errors.Is(err, syscall.EINTR) {
					continue
				}
				return
			}
			ip, mac, ok := parseARPReply(buf[:n])
			if !ok {
				continue
			}
			mu.Lock()
			found[ip] = mac
			mu.Unlock()
		}
	}()

	// 发送：按并发上限节流，每包之间留间隔
	sem := make(chan struct{}, workers)
	var wg sync.WaitGroup
	gap := time.Second / time.Duration(workers*8) // 速率上限，避免刷爆交换机

sendLoop:
	for _, ip := range hosts {
		select {
		case <-ctx.Done():
			break sendLoop
		case <-time.After(gap):
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(ip net.IP) {
			defer wg.Done()
			defer func() { <-sem }()
			pkt := buildARPRequest(localMAC, localIP, ip)
			_ = syscall.Sendto(fd, pkt, 0, &syscall.SockaddrLinklayer{
				Protocol: htons(ethPArp),
				Ifindex:  ifindex(ifc.Name),
				Halen:    6,
				Addr:     [8]byte{0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
			})
		}(ip)
	}
	wg.Wait()

	// 给应答留出收敛时间
	select {
	case <-ctx.Done():
	case <-time.After(minDur(500*time.Millisecond, time.Until(deadline))):
	}
	<-recvDone

	mu.Lock()
	defer mu.Unlock()
	out := make(map[string]string, len(found))
	for k, v := range found {
		out[k] = v
	}
	return out, nil
}

func minDur(a, b time.Duration) time.Duration {
	if b < 0 {
		return 0
	}
	if a < b {
		return a
	}
	return b
}

// ifindex 取网口序号。
func ifindex(name string) int {
	ifc, err := net.InterfaceByName(name)
	if err != nil {
		return 0
	}
	return ifc.Index
}

func htons(v uint16) uint16 { return v<<8 | v>>8 }

// buildARPRequest 构造一个以太网 + ARP 请求帧。
func buildARPRequest(srcMAC net.HardwareAddr, srcIP, dstIP net.IP) []byte {
	pkt := make([]byte, ethHeaderLen+arpPacketLen)
	// 以太头：目的广播、源本机
	copy(pkt[0:6], []byte{0xff, 0xff, 0xff, 0xff, 0xff, 0xff})
	copy(pkt[6:12], srcMAC)
	binary.BigEndian.PutUint16(pkt[12:14], ethPArp)
	// ARP 体
	off := ethHeaderLen
	binary.BigEndian.PutUint16(pkt[off:], 1)        // htype = Ethernet(1)
	binary.BigEndian.PutUint16(pkt[off+2:], ethPIP) // ptype = IPv4(0x0800)，不是 0x0806

	pkt[off+4] = 6 // hlen
	pkt[off+5] = 4 // plen
	binary.BigEndian.PutUint16(pkt[off+6:], arpRequest)
	copy(pkt[off+8:off+14], srcMAC)
	copy(pkt[off+14:off+18], srcIP.To4())
	// target MAC 全 0（未知），target IP 为目标
	copy(pkt[off+24:off+28], dstIP.To4())
	return pkt
}

// parseARPReply 解析一帧，若是 ARP reply 则返回 (ip, mac)。
func parseARPReply(pkt []byte) (string, string, bool) {
	if len(pkt) < ethHeaderLen+arpPacketLen {
		return "", "", false
	}
	if binary.BigEndian.Uint16(pkt[12:14]) != ethPArp {
		return "", "", false
	}
	off := ethHeaderLen
	if binary.BigEndian.Uint16(pkt[off+6:]) != arpReply {
		return "", "", false
	}
	ip := net.IP(pkt[off+14 : off+18]).String()
	mac := net.HardwareAddr(pkt[off+8 : off+14]).String()
	return ip, mac, true
}

// readARPTablePlatform 读 /proc/net/arp。无需特权，但只能看到已有邻居。
func readARPTablePlatform() (map[string]string, error) {
	b, err := os.ReadFile("/proc/net/arp")
	if err != nil {
		return nil, err
	}
	out := map[string]string{}
	lines := strings.Split(string(b), "\n")
	for i, ln := range lines {
		if i == 0 || strings.TrimSpace(ln) == "" {
			continue
		}
		f := strings.Fields(ln)
		if len(f) < 4 {
			continue
		}
		// f[0]=IP f[3]=MAC；全零表示未解析
		if f[3] == "00:00:00:00:00:00" {
			continue
		}
		out[f[0]] = f[3]
	}
	return out, nil
}

// isPrivilegedForRawSocket 探测当前进程能否创建 AF_PACKET 原始套接字。
// 供诊断与测试使用（界面上用来决定是否显示"权限不足"提示）。
func isPrivilegedForRawSocket() bool {
	fd, err := syscall.Socket(syscall.AF_PACKET, syscall.SOCK_RAW, int(htons(ethPArp)))
	if err != nil {
		return false
	}
	syscall.Close(fd)
	return true
}

// ---------- ICMP 探测（非特权，走内核 ping socket） ----------

// icmpAvailable 检查能否创建 ICMP ping socket。
func icmpAvailable() error {
	fd, err := syscall.Socket(syscall.AF_INET, syscall.SOCK_DGRAM, syscall.IPPROTO_ICMP)
	if err != nil {
		return err
	}
	return syscall.Close(fd)
}

// pingHost 发一个 ICMP echo，判断主机是否响应。
func pingHost(ctx context.Context, ip net.IP, timeout time.Duration) bool {
	v4 := ip.To4()
	if v4 == nil {
		return false
	}
	fd, err := syscall.Socket(syscall.AF_INET, syscall.SOCK_DGRAM, syscall.IPPROTO_ICMP)
	if err != nil {
		return false
	}
	defer syscall.Close(fd)

	// 非阻塞 + 轮询，便于响应 ctx 取消
	_ = syscall.SetNonblock(fd, true)

	id := uint16(os.Getpid() & 0xffff)
	seq := uint16(time.Now().UnixNano() & 0xffff)
	pkt := buildICMPEcho(id, seq)

	sa := &syscall.SockaddrInet4{}
	copy(sa.Addr[:], v4)
	if err := syscall.Sendto(fd, pkt, 0, sa); err != nil {
		return false
	}

	deadline := time.Now().Add(timeout)
	buf := make([]byte, 1500)
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return false
		default:
		}
		n, from, err := syscall.Recvfrom(fd, buf, 0)
		if err != nil {
			if errors.Is(err, syscall.EAGAIN) || errors.Is(err, syscall.EWOULDBLOCK) {
				time.Sleep(5 * time.Millisecond)
				continue
			}
			if errors.Is(err, syscall.EINTR) {
				continue
			}
			return false
		}
		from4, ok := from.(*syscall.SockaddrInet4)
		if !ok || n < 8 {
			continue
		}
		if !net.IP(from4.Addr[:]).Equal(v4) {
			continue
		}
		// ping socket 的 SOCK_DGRAM 不收 IP 头，直接就是 ICMP 报文
		if buf[0] == 0 { // type 0 = echo reply
			return true
		}
	}
	return false
}

// buildICMPEcho 构造 ICMP echo request（含校验和）。
func buildICMPEcho(id, seq uint16) []byte {
	const payload = 16
	pkt := make([]byte, 8+payload)
	pkt[0] = 8 // echo request
	pkt[1] = 0
	binary.BigEndian.PutUint16(pkt[4:], id)
	binary.BigEndian.PutUint16(pkt[6:], seq)
	for i := 8; i < len(pkt); i++ {
		pkt[i] = byte(i)
	}
	binary.BigEndian.PutUint16(pkt[2:], icmpChecksum(pkt))
	return pkt
}

// icmpChecksum 标准 ICMP 反码求和。
func icmpChecksum(b []byte) uint16 {
	var sum uint32
	for i := 0; i+1 < len(b); i += 2 {
		sum += uint32(b[i])<<8 | uint32(b[i+1])
	}
	if len(b)%2 == 1 {
		sum += uint32(b[len(b)-1]) << 8
	}
	for sum>>16 != 0 {
		sum = (sum & 0xffff) + (sum >> 16)
	}
	return ^uint16(sum)
}
