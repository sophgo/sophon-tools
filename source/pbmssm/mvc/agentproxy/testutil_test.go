package agentproxy

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"testing"
	"time"
)

// mockReasonix 是一个独立的 reasonix acp 模拟器（真实子进程，NDJSON 循环）。
// 用法：
//
//	path := mockReasonixPath(t, script)   // 生成 sh 脚本路径
//	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
//	pm.Start()
//
// mock script 是一个 shell 脚本，逐行读 stdin，按请求 method 响应。
// 内建 mock 通过 REASONIX_MOCK_CRASH_AFTER 环境变量控制启动后 N 行输出后崩溃。
func mockReasonixPath(t *testing.T, body string) string {
	t.Helper()
	dir := t.TempDir()
	path := dir + "/reasonix-acp-mock.sh"
	// handle_line 必须先于主循环定义（sh 函数需在使用前定义）。
	script := `#!/bin/sh
# mock reasonix acp：NDJSON 循环
trap 'exit 0' TERM INT   # 让 SIGTERM/SIGINT 能退出（sh read 循环默认不退出）
` + buildMockHandler(body) + `
count=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  count=$((count+1))
  # 模拟崩溃：输出 N 行后退出（诊断用，经 stderr）
  if [ -n "$REASONIX_MOCK_CRASH_AFTER" ] && [ "$count" -ge "$REASONIX_MOCK_CRASH_AFTER" ]; then
    echo "mock crash at $count" >&2
    exit 3
  fi
  handle_line "$line"
done
`
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write mock script: %v", err)
	}
	return path
}

// buildMockHandler 构造每行请求的分发逻辑（shell 函数 handle_line）。
func buildMockHandler(body string) string {
	return `handle_line() {
  line="$1"
  method=$(printf '%s' "$line" | sed -n 's/.*"method":"\([^"]*\)".*/\1/p')
  id=$(printf '%s' "$line" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
  case "$method" in
    initialize)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{"protocolVersion":1,"agentCapabilities":{}}}'
      ;;
` + body + `
    *)
      echo '{"jsonrpc":"2.0","id":'"$id"',"error":{"code":-32601,"message":"Method not found"}}'
      ;;
  esac
}
`
}

// runMockReasonix 启动真实 reasonix mock 子进程并返回句柄。
// 用于完整链路集成测试（client + process + session）。
func runMockReasonix(t *testing.T, handler string) (*exec.Cmd, io.WriteCloser, *bufio.Scanner, string) {
	t.Helper()
	path := mockReasonixPath(t, handler)
	cmd := exec.Command("sh", path)
	stdin, _ := cmd.StdinPipe()
	stdout, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		t.Fatalf("start mock: %v", err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill() })
	return cmd, stdin, bufio.NewScanner(stdout), path
}

// waitFor 轮询等待条件成立（超时返回错误）。
func waitFor(t *testing.T, timeout time.Duration, desc string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timeout waiting for %s", desc)
}

// promptHandler 构造支持 session/new、session/prompt、session/cancel 的 mock 分发体。
// prompt 响应前先发一条 session/update（agent_message_chunk）通知，再回 stopReason。
func promptHandler() string {
	return `
    session/new)
      sid="mock-acp-session-'"$id"'"
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{"sessionId":"'"$sid"'"}}'
      ;;
    session/prompt)
      echo '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"mock","update":{"sessionUpdate":{"agent_message_chunk":{"messageId":"m1","content":{"text":"你好，Reasonix！"}}}}}}'
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{"stopReason":"end_turn"}}'
      ;;
    session/cancel)
      echo '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"mock","update":{"sessionUpdate":{"agent_message_chunk":{"messageId":"m2","content":{"text":"已取消"}}}}}}'
      ;;
    session/resume)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{}}'
      ;;
    session/load)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{}}'
      ;;
    session/close)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{}}'
      ;;
    session/delete)
      echo '{"jsonrpc":"2.0","id":'"$id"',"result":{}}'
      ;;
`
}

// writeLine 向 stdin 写一行 NDJSON（测试辅助）。
func writeLine(w io.WriteCloser, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "%s\n", b)
	return err
}

// readRPCLine 从 scanner 读一行并解析为 RPCResponse（测试辅助）。
func readRPCLine(t *testing.T, sc *bufio.Scanner) (*RPCResponse, error) {
	t.Helper()
	if !sc.Scan() {
		return nil, io.EOF
	}
	var resp RPCResponse
	if err := json.Unmarshal(sc.Bytes(), &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// stdIOTransport 提供基于真实管道对（mock 进程）的进程传输：
// 用 sh 管道对实现读写，满足 ProcessManager 接口语义的测试替身。
type stdIOTransport struct {
	pm  *ProcessManager
	in  *os.File  // 读方向（从传输读到行）
	out *os.File  // 写方向（向传输写行）
}

// newStdIOTransport 创建双向管道对：一端给被测 ProcessManager，
// 另一端给测试（模拟 reasonix 进程）。
func newStdIOTransport(t *testing.T) (*stdIOTransport, *ProcessManager) {
	t.Helper()
	r1, w1, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe1: %v", err)
	}
	r2, w2, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe2: %v", err)
	}
	// 被测进程：stdin=w1（写请求），stdout=r2（读响应）
	pm := &ProcessManager{
		stdin:  w1,
		stdout: bufio.NewReader(r2),
		state:  StateRunning,
		backoff: time.Second,
		stderrB: &safeBuffer{},
	}
	// 测试侧：读 r1（请求），写 w2（响应）
	return &stdIOTransport{pm: pm, in: r1, out: w2}, pm
}

// readRequest 从测试侧读一行（被测进程发出的请求）。
func (tr *stdIOTransport) readRequest(t *testing.T, sc *bufio.Scanner) *RPCRequest {
	t.Helper()
	req, err := tr.readRequestErr(sc)
	if err != nil {
		t.Fatalf("no request line: %v", err)
	}
	return req
}

// readRequestErr 从测试侧读一行，EOF 返回错误（供 goroutine 优雅退出）。
func (tr *stdIOTransport) readRequestErr(sc *bufio.Scanner) (*RPCRequest, error) {
	if !sc.Scan() {
		return nil, sc.Err()
	}
	var req RPCRequest
	if err := json.Unmarshal(sc.Bytes(), &req); err != nil {
		return nil, err
	}
	return &req, nil
}

// reply 从测试侧回一行响应。
func (tr *stdIOTransport) reply(v any) error {
	b, _ := json.Marshal(v)
	_, err := fmt.Fprintf(tr.out, "%s\n", b)
	return err
}

// readRawLine 从测试侧读一行原始 NDJSON（用于校验被测进程发出的帧）。
func (tr *stdIOTransport) readRawLine(t *testing.T, sc *bufio.Scanner) []byte {
	t.Helper()
	if !sc.Scan() {
		t.Fatalf("no frame line")
	}
	return append([]byte(nil), sc.Bytes()...)
}

// readRawLineErr 与 readRawLine 相同，但 EOF 返回错误而非 fatal（供 goroutine 优雅退出）。
func (tr *stdIOTransport) readRawLineErr(sc *bufio.Scanner) ([]byte, error) {
	if !sc.Scan() {
		return nil, sc.Err()
	}
	return append([]byte(nil), sc.Bytes()...), nil
}

// contains 判断子串。
func contains(s, sub string) bool {
	return strings.Contains(s, sub)
}

// writeFile 写文件（测试辅助）。
func writeFile(path, content string) error {
	return os.WriteFile(path, []byte(content), 0o755)
}

// killProcess 向指定 pid 发 SIGKILL（模拟崩溃）。
func killProcess(pid int) error {
	return syscall.Kill(pid, syscall.SIGKILL)
}
