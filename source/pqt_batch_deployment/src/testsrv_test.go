package main

// 最小 SSH/SFTP 测试服务器，用于覆盖「命令与传输」这条真实路径。
//
// 为什么需要它：之前只有「连接被拒」与「握手超时」两类用例，上传/下载这两条
// 真正带数据传输的路径在自动化测试里完全没跑过——审阅里「传输没有超时」正是
// 因此漏掉的。这里起一个能认证、能开会话/SFTP 子系统的服务器，用来断言：
//  1. 命令成功/失败关键字判定走真实 SSH 会话；
//  2. 上传、下载真的落盘并按 MD5 校验；
//  3. 服务端「收下请求但永不回应」时，传输能被超时打断而不是永久挂住。

import (
	"crypto/ed25519"
	"crypto/md5"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"

	"golang.org/x/crypto/ssh"
)

// testSSHServer 一个可编程的 SSH 服务器。
type testSSHServer struct {
	t        *testing.T
	listener net.Listener
	config   *ssh.ServerConfig

	mu sync.Mutex
	// files 模拟远端文件系统（SFTP 走内存）。
	files map[string][]byte
	// hangSFTP 为 true 时，SFTP 子系统收下请求后不做任何回应（模拟传输卡死）。
	hangSFTP bool
	// commands 模拟命令执行：命令 -> (输出, 退出码)
	commands map[string]string
	// hangCommand 为 true 时命令会话收下请求后不回应。
	hangCommand bool

	wg sync.WaitGroup
}

func newTestSSHServer(t *testing.T) *testSSHServer {
	t.Helper()

	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("生成主机密钥失败: %v", err)
	}
	signer, err := ssh.NewSignerFromKey(priv)
	if err != nil {
		t.Fatalf("构造 signer 失败: %v", err)
	}

	s := &testSSHServer{
		t:        t,
		files:    map[string][]byte{},
		commands: map[string]string{},
	}
	s.config = &ssh.ServerConfig{
		PasswordCallback: func(c ssh.ConnMetadata, pass []byte) (*ssh.Permissions, error) {
			return nil, nil // 任意用户名/密码都接受
		},
	}
	s.config.AddHostKey(signer)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("监听失败: %v", err)
	}
	s.listener = ln

	s.wg.Add(1)
	go s.serve()
	t.Cleanup(s.Close)
	return s
}

func (s *testSSHServer) Port() int {
	return s.listener.Addr().(*net.TCPAddr).Port
}

func (s *testSSHServer) SetFile(path string, data []byte) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.files[path] = data
}

func (s *testSSHServer) File(path string) []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.files[path]
}

func (s *testSSHServer) SetHangSFTP(v bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.hangSFTP = v
}

func (s *testSSHServer) SetHangCommand(v bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.hangCommand = v
}

func (s *testSSHServer) Close() {
	_ = s.listener.Close()
	s.wg.Wait()
}

func (s *testSSHServer) serve() {
	defer s.wg.Done()
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			return
		}
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			s.handleConn(conn)
		}()
	}
}

func (s *testSSHServer) handleConn(conn net.Conn) {
	defer conn.Close()

	sc, chans, reqs, err := ssh.NewServerConn(conn, s.config)
	if err != nil {
		return
	}
	defer sc.Close()
	go ssh.DiscardRequests(reqs)

	for newCh := range chans {
		if newCh.ChannelType() != "session" {
			_ = newCh.Reject(ssh.UnknownChannelType, "仅支持 session")
			continue
		}
		ch, chReqs, err := newCh.Accept()
		if err != nil {
			continue
		}
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			s.handleSession(ch, chReqs)
		}()
	}
}

func (s *testSSHServer) handleSession(ch ssh.Channel, reqs <-chan *ssh.Request) {
	defer ch.Close()
	for req := range reqs {
		switch req.Type {
		case "subsystem":
			// 解析 subsystem 名称
			name := parseStringPayload(req.Payload)
			if name != "sftp" {
				_ = req.Reply(false, nil)
				continue
			}
			_ = req.Reply(true, nil)

			s.mu.Lock()
			hang := s.hangSFTP
			s.mu.Unlock()
			if hang {
				// 收下请求但永不回应：模拟"连接还在，但传输不动"。
				// 必须持续读，否则客户端写满窗口后会因为 TCP 反压而"看起来"卡住，
				// 那是另一种现象，不是我们要测的服务端不响应。
				_, _ = io.Copy(io.Discard, ch)
				return
			}
			s.serveSFTP(ch)
			return

		case "exec":
			cmd := parseStringPayload(req.Payload)
			_ = req.Reply(true, nil)

			s.mu.Lock()
			hang := s.hangCommand
			s.mu.Unlock()

			if hang {
				_, _ = io.Copy(io.Discard, ch)
				return
			}

			out, code := s.runCommand(cmd)
			_, _ = ch.Write([]byte(out))
			_, _ = ch.SendRequest("exit-status", false, exitStatus(code))
			return

		default:
			_ = req.Reply(false, nil)
		}
	}
}

func exitStatus(code uint32) []byte {
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, code)
	return b
}

// runCommand 模拟远端 shell。除测试显式登记的命令外，还实现本工具内部
// 真正会发出的两条校验命令（md5sum / stat -c %s），这样上传下载的校验
// 路径在测试里是真跑的，而不是被桩掉。
func (s *testSSHServer) runCommand(cmd string) (string, uint32) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if out, ok := s.commands[cmd]; ok {
		return out, 0
	}

	// 形如：md5sum '/tmp/payload.bin'
	if path, ok := commandArg(cmd, "md5sum "); ok {
		data, exists := s.files[path]
		if !exists {
			return "md5sum: " + path + ": No such file or directory\n", 1
		}
		sum := md5.Sum(data)
		return hex.EncodeToString(sum[:]) + "  " + path + "\n", 0
	}
	// 形如：stat -c %s '/tmp/payload.bin'
	if path, ok := commandArg(cmd, "stat -c %s "); ok {
		data, exists := s.files[path]
		if !exists {
			return "stat: cannot statx '" + path + "': No such file or directory\n", 1
		}
		return strconv.Itoa(len(data)) + "\n", 0
	}
	return "ok\n", 0
}

// commandArg 取 "<prefix><带引号路径>" 的路径参数。
func commandArg(cmd, prefix string) (string, bool) {
	if !strings.HasPrefix(cmd, prefix) {
		return "", false
	}
	arg := strings.TrimSpace(cmd[len(prefix):])
	return strings.Trim(arg, "'\""), true
}

func parseStringPayload(payload []byte) string {
	if len(payload) < 4 {
		return ""
	}
	n := binary.BigEndian.Uint32(payload[:4])
	if int(n) > len(payload)-4 {
		return ""
	}
	return string(payload[4 : 4+n])
}
