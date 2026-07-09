// Package ports 解析 /proc/net/{tcp,tcp6,udp,udp6} 列出监听套接字及归属进程。
// 纯 Go，cgo-free；/proc 根参数化（默认 /proc），便于单测。
package ports

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Socket 一个监听套接字及其归属进程。
type Socket struct {
	Proto     string `json:"proto"`
	LocalIP   string `json:"local_ip"`
	LocalPort uint16 `json:"local_port"`
	Pid       int    `json:"pid"`
	Process   string `json:"process"`
	Cmdline   string `json:"cmdline"`
	Inode     uint64 `json:"inode"`
}

// ListListening 列出所有监听套接字（TCP LISTEN + 全部 UDP）及进程信息。
func ListListening() ([]Socket, error) {
	return ListListeningAt("/proc")
}

// ListListeningAt 在指定 /proc 根下列出监听套接字（测试传入样本目录）。
func ListListeningAt(procRoot string) ([]Socket, error) {
	files := []struct{ path, proto string }{
		{"tcp", "tcp"}, {"tcp6", "tcp6"}, {"udp", "udp"}, {"udp6", "udp6"},
	}
	var sockets []Socket
	for _, f := range files {
		content, err := os.ReadFile(filepath.Join(procRoot, "net", f.path))
		if err != nil {
			continue // 文件缺失（如无 IPv6）跳过
		}
		sockets = append(sockets, parseProcNet(string(content), f.proto)...)
	}
	inodeToPid := buildInodePidMap(procRoot)
	for i := range sockets {
		if pid, ok := inodeToPid[sockets[i].Inode]; ok {
			sockets[i].Pid = pid
			sockets[i].Process = readComm(procRoot, pid)
			sockets[i].Cmdline = readCmdline(procRoot, pid)
		}
	}
	return sockets, nil
}

// parseProcNet 解析 /proc/net/tcp(6)/udp(6) 内容，返回监听套接字。
// TCP 仅取 state==0A(LISTEN)；UDP 无连接态，全部列出。
func parseProcNet(content, proto string) []Socket {
	var out []Socket
	isUDP := strings.HasPrefix(proto, "udp")
	lines := strings.Split(content, "\n")
	for i, line := range lines {
		if i == 0 {
			continue // 表头
		}
		fields := strings.Fields(line)
		if len(fields) < 10 {
			continue
		}
		local := fields[1]
		state := fields[3]
		inode, _ := strconv.ParseUint(fields[9], 10, 64)
		if !isUDP && state != "0A" {
			continue // TCP 非 LISTEN 跳过
		}
		ipStr, port := parseAddr(local, strings.HasSuffix(proto, "6"))
		out = append(out, Socket{
			Proto: proto, LocalIP: ipStr, LocalPort: port, Inode: inode,
		})
	}
	return out
}

// parseAddr 解析 "IPHex:PortHex"，返回可读 IP 与端口。
func parseAddr(addr string, v6 bool) (string, uint16) {
	parts := strings.SplitN(addr, ":", 2)
	if len(parts) != 2 {
		return addr, 0
	}
	port, _ := strconv.ParseUint(parts[1], 16, 32)
	if v6 {
		return parseIPv6(parts[0]), uint16(port)
	}
	return parseIPv4(parts[0]), uint16(port)
}

// parseIPv4 解析 8 hex（小端 32 位）为点分十进制。"0100007F" -> "127.0.0.1"。
func parseIPv4(hex string) string {
	if len(hex) != 8 {
		return hex
	}
	o0, _ := strconv.ParseUint(hex[6:8], 16, 8) // 高字节
	o1, _ := strconv.ParseUint(hex[4:6], 16, 8)
	o2, _ := strconv.ParseUint(hex[2:4], 16, 8)
	o3, _ := strconv.ParseUint(hex[0:2], 16, 8) // 低字节
	return fmt.Sprintf("%d.%d.%d.%d", o0, o1, o2, o3)
}

// parseIPv6 解析 32 hex（4 个小端 32 位字）为冒号十六进制（非压缩，合法可读）。
func parseIPv6(hex string) string {
	if len(hex) != 32 {
		return hex
	}
	var groups [8]string
	for w := 0; w < 4; w++ {
		word := hex[w*8 : (w+1)*8] // 8 hex = 4 字节，小端字
		b0, b1, b2, b3 := word[0:2], word[2:4], word[4:6], word[6:8]
		groups[w*2] = b3 + b2   // 高 16 位（大端）
		groups[w*2+1] = b1 + b0 // 低 16 位
	}
	for i, g := range groups {
		groups[i] = strings.TrimLeft(g, "0")
		if groups[i] == "" {
			groups[i] = "0"
		}
	}
	return strings.Join(groups[:], ":")
}

// buildInodePidMap 遍历 /proc/<pid>/fd/* readlink，建 inode→pid 反查表。
func buildInodePidMap(procRoot string) map[uint64]int {
	out := make(map[uint64]int)
	entries, err := os.ReadDir(procRoot)
	if err != nil {
		return out
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		pid, err := strconv.Atoi(e.Name())
		if err != nil || pid <= 0 {
			continue
		}
		fdDir := filepath.Join(procRoot, e.Name(), "fd")
		fds, err := os.ReadDir(fdDir)
		if err != nil {
			continue
		}
		for _, fd := range fds {
			link, err := os.Readlink(filepath.Join(fdDir, fd.Name()))
			if err != nil {
				continue
			}
			if !strings.HasPrefix(link, "socket:[") {
				continue
			}
			inodeStr := strings.TrimSuffix(strings.TrimPrefix(link, "socket:["), "]")
			inode, err := strconv.ParseUint(inodeStr, 10, 64)
			if err != nil {
				continue
			}
			if _, exists := out[inode]; !exists {
				out[inode] = pid
			}
		}
	}
	return out
}

func readComm(procRoot string, pid int) string {
	b, err := os.ReadFile(filepath.Join(procRoot, strconv.Itoa(pid), "comm"))
	if err != nil {
		return ""
	}
	return strings.TrimRight(string(b), "\n\x00")
}

func readCmdline(procRoot string, pid int) string {
	b, err := os.ReadFile(filepath.Join(procRoot, strconv.Itoa(pid), "cmdline"))
	if err != nil {
		return ""
	}
	s := strings.ReplaceAll(string(b), "\x00", " ")
	return strings.TrimRight(s, " \n")
}
