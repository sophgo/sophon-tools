package agentproxy

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"bmssm/logger"
)

// ProcessManager 管理单个 reasonix acp 进程的生命周期：
// 启动、崩溃自愈（退避重启）、手动停止、优雅关闭。
// 参考 llmproxy/server.go 的 os/exec 模式，但改为单进程常驻 + 崩溃自愈模型。
//
// 并发模型：一个 wait goroutine 独占执行 cmd.Wait()，进程退出（崩溃或主动停止）
// 时关闭 waitCh；supervise goroutine 监听 waitCh，仅当 runRequested 仍为 true
// （未被手动 Stop 关闭且非 GracefulStop）时按退避重启。
// 所有字段读写经 pm.mu；runRequested/stopping 用原子量，避免带锁读。
type ProcessManager struct {
	cfg     Config
	onReady func() // 每次进程成功启动后被回调（acp client 重跑 initialize + 恢复会话）

	mu      sync.Mutex
	cmd     *exec.Cmd     // 当前进程（Wait goroutine 退出前有效）
	waitCh  chan struct{} // 当前进程退出信号（close 表示已退出）
	state   ProcessState
	started time.Time
	stdin   io.WriteCloser // 写请求（NDJSON 行），写时需加 writeMu
	stdout  *bufio.Reader  // 读响应（NDJSON 行）
	stderrB *safeBuffer    // stderr 诊断日志

	writeMu     sync.Mutex // 防并发写行交错
	backoff     time.Duration
	initFailCnt atomic.Int32
	stopping    atomic.Bool // 终态：bmssm 关闭/永久停止，置后不可再自愈
	runRequested atomic.Bool // 用户/managed 是否期望进程保持运行（false=手动停止，supervise 不再重启）
}

// safeBuffer 并发安全的 stderr 收集器：读循环写、健康检查/日志读。
type safeBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *safeBuffer) Write(p []byte) (int, error) {
	if s == nil {
		return len(p), nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *safeBuffer) String() string {
	if s == nil {
		return ""
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

func (s *safeBuffer) Reset() {
	if s == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.b.Reset()
}

// NewProcessManager 创建进程管理器。onReady 在每次进程成功启动后被回调
// （由 acp client 绑定，用于重跑 initialize 并恢复会话）。
func NewProcessManager(cfg Config, onReady func()) *ProcessManager {
	return &ProcessManager{
		cfg:     cfg,
		onReady: onReady,
		state:   StateStopped,
		backoff: time.Second,
		stderrB: &safeBuffer{},
	}
}

// Start 启动 reasonix acp 进程（幂等：已在运行则 no-op）。
// 置 runRequested=true，使 supervise 在进程崩溃时自动重启。
func (pm *ProcessManager) Start() error {
	pm.mu.Lock()
	if pm.waitCh != nil {
		pm.mu.Unlock()
		return nil // 已有进程在运行/启动中
	}
	pm.mu.Unlock()

	pm.stopping.Store(false)
	pm.runRequested.Store(true)
	if err := pm.startProc(); err != nil {
		return err
	}
	go pm.supervise()
	return nil
}

// startProc 实际启动一次进程并挂起 I/O。调用方负责启动 supervise。
func (pm *ProcessManager) startProc() error {
	binary := pm.cfg.BinaryPath
	if strings.TrimSpace(binary) == "" {
		binary = DefaultBinary
	}
	args := []string{"acp"}
	if pm.cfg.Model != "" {
		args = append(args, "--model", pm.cfg.Model)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, binary, args...)
	if pm.cfg.WorkDir != "" {
		cmd.Dir = pm.cfg.WorkDir
	}
	cmd.Env = os.Environ()
	if home := pm.homeDir(); home != "" {
		cmd.Env = append(cmd.Env, "HOME="+home)
	}

	stdin, err := cmd.StdinPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("create stdin pipe: %w", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("create stdout pipe: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("create stderr pipe: %w", err)
	}

	pm.stderrB.Reset()
	if err := cmd.Start(); err != nil {
		cancel()
		return fmt.Errorf("start reasonix acp: %w", err)
	}

	waitCh := make(chan struct{})
	pm.mu.Lock()
	pm.cmd = cmd
	pm.stdin = stdin
	pm.stdout = bufio.NewReader(stdout)
	pm.state = StateStarting
	pm.started = time.Now()
	pm.backoff = time.Second
	pm.waitCh = waitCh
	pm.mu.Unlock()

	// stderr 单独收集（不合并流；stdout 只承载 ACP NDJSON）
	go pm.readStderr(stderr)

	// wait goroutine：进程退出后关闭 waitCh（崩溃或主动停止都走这里）
	go func() {
		_ = cmd.Wait()
		cancel()
		close(waitCh)
	}()

	// onReady 异步执行（initialize + 会话恢复），不阻塞启动路径
	if pm.onReady != nil {
		go pm.onReady()
	}
	return nil
}

// supervise 监听当前进程退出；非手动停止时按退避重启。
// 进程退出后：若 stopping（终态关闭）或 !runRequested（用户手动停止）→ 保持停止；
// 否则视为崩溃，按退避重启。
func (pm *ProcessManager) supervise() {
	for {
		if pm.stopping.Load() || !pm.runRequested.Load() {
			return
		}
		pm.mu.Lock()
		waitCh := pm.waitCh
		pm.mu.Unlock()
		if waitCh == nil {
			return
		}
		<-waitCh

		if pm.stopping.Load() || !pm.runRequested.Load() {
			return
		}

		pm.mu.Lock()
		delay := pm.backoff
		pm.backoff *= 2
		if pm.backoff > DefaultBackoffMax {
			pm.backoff = DefaultBackoffMax
		}
		pm.mu.Unlock()
		logger.Warn("agentproxy: reasonix acp exited, restarting in %s", delay)
		time.Sleep(delay)

		if pm.stopping.Load() || !pm.runRequested.Load() {
			return
		}
		if err := pm.startProc(); err != nil {
			logger.Error("agentproxy: restart failed: %v", err)
			return
		}
	}
}

// readStderr 持续读取 stderr 到安全缓冲，周期性 flush 到诊断日志。
// 进程退出（pipe EOF）时做最终 flush 后返回。
func (pm *ProcessManager) readStderr(r io.Reader) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	lastFlush := time.Now()
	flush := func() {
		if s := strings.TrimSpace(pm.stderrB.String()); s != "" {
			logger.Info("agentproxy: reasonix stderr: %s", s)
		}
		pm.stderrB.Reset()
		lastFlush = time.Now()
	}
	for sc.Scan() {
		pm.stderrB.Write([]byte(sc.Text() + "\n"))
		if pm.stderrB.String() != "" && time.Since(lastFlush) >= 5*time.Second {
			flush()
		}
	}
	flush()
}

// restart 主动重启进程（配置变更 binaryPath/workDir 时调用）。
// 保持运行语义不变（不置 stopping，runRequested 保持 true）。
func (pm *ProcessManager) restart() {
	pm.runRequested.Store(true)
	pm.stopProc(false)
	if err := pm.startProc(); err != nil {
		logger.Error("agentproxy: restart failed: %v", err)
		pm.mu.Lock()
		pm.state = StateStopped
		pm.mu.Unlock()
		return
	}
	go pm.supervise()
}

// Alive 返回当前是否有存活进程。
func (pm *ProcessManager) Alive() bool {
	pm.mu.Lock()
	waitCh := pm.waitCh
	pm.mu.Unlock()
	if waitCh == nil {
		return false
	}
	select {
	case <-waitCh:
		return false
	default:
		return true
	}
}

// State 返回当前生命周期状态。
func (pm *ProcessManager) State() ProcessState {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	return pm.state
}

// RunRequested 返回进程是否处于「应保持运行」状态（用户未手动停止）。
// supervise 据此决定崩溃后是否自愈重启。
func (pm *ProcessManager) RunRequested() bool {
	return pm.runRequested.Load()
}

// Pid 返回当前进程 pid（无则 0）。
func (pm *ProcessManager) Pid() int {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	if pm.cmd == nil || pm.cmd.Process == nil {
		return 0
	}
	return pm.cmd.Process.Pid
}

// Healthy 健康检查：进程存活 + stdin 可写 + 最近 initialize 成功。
func (pm *ProcessManager) Healthy() bool {
	if !pm.Alive() {
		return false
	}
	if pm.initFailCnt.Load() > 0 {
		return false
	}
	pm.mu.Lock()
	defer pm.mu.Unlock()
	return pm.stdin != nil
}

// MarkInitFailed 记录一次 initialize 失败；连续超过阈值进入 degraded 状态。
func (pm *ProcessManager) MarkInitFailed() {
	cnt := pm.initFailCnt.Add(1)
	pm.mu.Lock()
	if int(cnt) >= initFailThreshold {
		pm.state = StateDegraded
	}
	pm.mu.Unlock()
}

// MarkInitOK 记录 initialize 成功（清零失败计数、恢复 running）。
func (pm *ProcessManager) MarkInitOK() {
	pm.initFailCnt.Store(0)
	pm.mu.Lock()
	pm.state = StateRunning
	pm.mu.Unlock()
}

// StderrSnapshot 返回最近 stderr 内容（诊断用，截断尾部）。
func (pm *ProcessManager) StderrSnapshot(max int) string {
	s := pm.stderrB.String()
	if max > 0 && len(s) > max {
		return s[len(s)-max:]
	}
	return s
}

// WriteRequest 向进程 stdin 写一行 NDJSON（加锁防并发写行交错）。
func (pm *ProcessManager) WriteRequest(line []byte) error {
	pm.mu.Lock()
	stdin := pm.stdin
	pm.mu.Unlock()
	if stdin == nil {
		return fmt.Errorf("reasonix acp process not started")
	}
	pm.writeMu.Lock()
	defer pm.writeMu.Unlock()
	_, err := stdin.Write(append(line, '\n'))
	return err
}

// ReadLine 从进程 stdout 读一行 NDJSON。进程退出返回 io.EOF。
func (pm *ProcessManager) ReadLine() ([]byte, error) {
	pm.mu.Lock()
	stdout := pm.stdout
	pm.mu.Unlock()
	if stdout == nil {
		return nil, io.EOF
	}
	line, err := stdout.ReadBytes('\n')
	if err != nil {
		return nil, err
	}
	return bytes.TrimRight(line, "\r\n"), nil
}

// GracefulStop 优雅关闭：SIGTERM，等待 5s，超时 Kill。会话清理由调用方负责。
// 置 stopping=true（终态）与 runRequested=false，supervise 不再重启。
func (pm *ProcessManager) GracefulStop() {
	pm.stopping.Store(true)
	pm.runRequested.Store(false)
	pm.stopProc(true)
}

// Stop 手动停止进程，且保持停止（runRequested=false，supervise 不再自愈重启）。
// 供服务管理接口「停止」用：之后调用 Start 可重新拉起；
// 不同于 GracefulStop（其置 stopping 后视为终态关闭）。
func (pm *ProcessManager) Stop() {
	pm.runRequested.Store(false)
	pm.stopProc(true)
}

// Restart 重启进程（stop + start）。供服务管理接口「重启」用。
// 保持运行语义：关闭可能残留的 stopping 终态、确保 runRequested=true。
func (pm *ProcessManager) Restart() {
	pm.stopping.Store(false)
	pm.runRequested.Store(true)
	pm.restart()
}

// stopProc 停止当前进程并等待退出（不改变 stopping 状态，由调用方决定）。
// graceful=true 时 SIGTERM 后等待 5s 再 Kill；false 直接 Kill。
func (pm *ProcessManager) stopProc(graceful bool) {
	pm.mu.Lock()
	cmd := pm.cmd
	waitCh := pm.waitCh
	pm.cmd = nil
	pm.waitCh = nil
	pm.stdin = nil
	pm.stdout = nil
	if pm.state != StateStopped {
		pm.state = StateStopped
	}
	pm.mu.Unlock()

	if cmd == nil || cmd.Process == nil {
		return // 无进程
	}

	if graceful {
		// 设计文档 §3.3：SIGTERM 优雅关闭；mock/真实 reasonix 都应能处理
		_ = cmd.Process.Signal(syscall.SIGTERM)
		select {
		case <-waitCh:
		case <-time.After(5 * time.Second):
			_ = cmd.Process.Kill()
			<-waitCh
		}
	} else {
		_ = cmd.Process.Kill()
		<-waitCh
	}
}

// DefaultReasonixHome 定制 reasonix 的默认运行主目录。所有 reasonix 会话数据、
// 配置（$HOME/.reasonix/）与预载 skill 都放这里，与系统正常安装的 reasonix
// （各用户 $HOME/.reasonix/）彻底隔离，互不影响。
const DefaultReasonixHome = "/data/sophon/reasonix-home"

// homeDir 探测 reasonix 运行主目录。SOPHON_REASONIX_HOME 显式设置时优先；
// 否则默认 DefaultReasonixHome（隔离定制实例，避免覆盖系统安装的 $HOME/.reasonix）。
func (pm *ProcessManager) homeDir() string {
	if h := os.Getenv("SOPHON_REASONIX_HOME"); h != "" {
		return h
	}
	return DefaultReasonixHome
}

// initFailThreshold 连续 initialize 失败阈值：超过进入 degraded 状态。
const initFailThreshold = 3
