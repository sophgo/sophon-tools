package agentproxy

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"bmssm/mvc/llmproxy"
)

// TestProcessStartInitialize 用真实 mock 脚本验证：
// 启动进程 → onReady 回调 → client initialize 握手成功 → 进程存活。
func TestProcessStartInitialize(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	dir := t.TempDir()

	var pm *ProcessManager
	ready := make(chan struct{}, 4)
	pm = NewProcessManager(Config{BinaryPath: path, WorkDir: dir}, func() {
		select {
		case ready <- struct{}{}:
		default:
		}
	})
	// 直接启动，onReady 触发后重建 client 并 initialize
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()

	// onReady 触发（进程已起，stdin/stdout 就绪）
	select {
	case <-ready:
	case <-time.After(3 * time.Second):
		t.Fatal("onReady not fired")
	}

	// 用真实 client 走 initialize 握手
	client := NewClient(pm, nil, nil)
	defer client.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	res, err := client.Initialize(ctx)
	if err != nil {
		t.Fatalf("initialize: %v", err)
	}
	if res.ProtocolVersion != 1 {
		t.Fatalf("protocolVersion = %d", res.ProtocolVersion)
	}
	if !pm.Alive() {
		t.Fatal("process should be alive")
	}
}

// TestProcessCrashRestart 验证进程崩溃后自动重启：
// 用 timeout 包装脚本让 mock 进程 1s 后退出（模拟崩溃），
// supervise 检测退出 → 退避重启 → 新进程再次就绪。
func TestProcessCrashRestart(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	dir := t.TempDir()

	// 包装脚本：timeout 1s 后杀掉 mock（模拟进程崩溃）
	crashPath := dir + "/crash-wrapper.sh"
	content := "#!/bin/sh\ntimeout 1 sh \"$REASONIX_MOCK_PATH\"\n"
	if err := writeFile(crashPath, content); err != nil {
		t.Fatal(err)
	}
	t.Setenv("REASONIX_MOCK_PATH", path)

	started := make(chan struct{}, 8)
	pm := NewProcessManager(Config{BinaryPath: crashPath, WorkDir: dir}, func() {
		select {
		case started <- struct{}{}:
		default:
		}
	})

	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()

	// 等第一次就绪
	waitFor(t, 3*time.Second, "first ready", func() bool { return len(started) > 0 })
	// mock 在 1s 后崩溃；supervise 重启后再次就绪
	waitFor(t, 8*time.Second, "restart ready", func() bool { return len(started) >= 2 })
	if !pm.Alive() {
		t.Fatal("process not alive after crash restart")
	}
}

// TestProcessKillRestart 直接 kill 进程模拟崩溃，验证 supervise 自动重启。
func TestProcessKillRestart(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	dir := t.TempDir()

	started := make(chan struct{}, 8)
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: dir}, func() {
		select {
		case started <- struct{}{}:
		default:
		}
	})
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()

	// 等第一次就绪
	waitFor(t, 3*time.Second, "first ready", func() bool {
		return len(started) > 0
	})
	// 记第一个 pid
	firstPid := pm.Pid()
	if firstPid == 0 {
		t.Fatal("no pid after start")
	}

	// kill 进程（SIGKILL，不触发 graceful 路径）
	if err := killProcess(firstPid); err != nil {
		t.Fatalf("kill: %v", err)
	}

	// 等待自动重启：新 pid 出现且 != 旧 pid
	waitFor(t, 5*time.Second, "restart", func() bool {
		pid := pm.Pid()
		return pid != 0 && pid != firstPid
	})
	if !pm.Alive() {
		t.Fatal("process not alive after restart")
	}
}

// TestProcessManualStopStaysStopped 回归：手动 Stop 后 supervise 不应自动重启。
// 先前 Stop() 只停进程不置标志，supervise 检测退出后按崩溃退避重启，
// 导致「无法停止 Reasonix」。修复后 Stop() 置 runRequested=false，进程保持停止，
// 之后 Start() 可再次拉起。
func TestProcessManualStopStaysStopped(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	dir := t.TempDir()

	started := make(chan struct{}, 8)
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: dir}, func() {
		select {
		case started <- struct{}{}:
		default:
		}
	})
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()

	waitFor(t, 3*time.Second, "first ready", func() bool {
		return len(started) > 0
	})
	if !pm.Alive() {
		t.Fatal("process should be alive after start")
	}

	// 手动停止：进程退出且保持停止（不被 supervise 拉回）
	pm.Stop()
	if pm.Alive() {
		t.Fatal("process should be stopped after manual Stop")
	}
	// 给 supervise 足够退避时间，确认不会自动重启（若重启，Alive 会变 true）
	time.Sleep(1200 * time.Millisecond)
	if pm.Alive() {
		t.Fatal("process should remain stopped after Stop (supervise must not restart)")
	}
	// RunRequested 应反映停止意图
	if pm.RunRequested() {
		t.Fatal("RunRequested should be false after manual Stop")
	}

	// 再次 Start：进程应能重新拉起（Stop 是可逆的，非终态）
	if err := pm.Start(); err != nil {
		t.Fatalf("re-start after Stop: %v", err)
	}
	waitFor(t, 3*time.Second, "restart after Stop", pm.Alive)
	if !pm.Alive() {
		t.Fatal("process should be alive after Start following Stop")
	}
}

// TestProcessGracefulStop 验证优雅关闭：stopProc 后进程退出、状态 stopped。
func TestProcessGracefulStop(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	waitFor(t, 3*time.Second, "alive", pm.Alive)

	pm.GracefulStop()
	if pm.Alive() {
		t.Fatal("should be stopped after GracefulStop")
	}
	if pm.State() != StateStopped {
		t.Fatalf("state = %s", pm.State())
	}
}

// TestProcessDegradedState 验证连续 initialize 失败进入 degraded 状态。
func TestProcessDegradedState(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	pm := NewProcessManager(Config{BinaryPath: path, WorkDir: t.TempDir()}, nil)
	if err := pm.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer pm.GracefulStop()

	pm.MarkInitFailed()
	pm.MarkInitFailed()
	if pm.State() == StateDegraded {
		t.Fatal("should not be degraded after 2 fails")
	}
	pm.MarkInitFailed()
	if pm.State() != StateDegraded {
		t.Fatalf("state = %s, want degraded", pm.State())
	}
	pm.MarkInitOK()
	if pm.State() != StateRunning {
		t.Fatalf("state = %s, want running", pm.State())
	}
}

// TestModuleEndToEnd 用真实 mock 进程 + 完整 Module 验证链路：
// start → initialize（模块自动）→ session/new → prompt 流式。
// 需要 mock 支持 session/new 与 session/prompt。
func TestModuleEndToEnd(t *testing.T) {
	path := mockReasonixPath(t, promptHandler())
	dir := t.TempDir()

	events := make(chan *ACPSessionUpdate, 16)
	m := NewModule(Config{
		Enabled:    true,
		BinaryPath: path,
		WorkDir:    dir,
	}, nil, func(ev *ACPSessionUpdate) {
		events <- ev
	})
	if err := m.Start(); err != nil {
		t.Fatalf("module start: %v", err)
	}
	defer m.Shutdown()

	// 需求(MYS-210)：module.Start 不再自动拉起 reasonix（默认关闭，需手动启动）。
	// 测试模拟用户手动启动进程，驱动 initialize → client 就绪链路。
	if err := m.pm.Start(); err != nil {
		t.Fatalf("process start: %v", err)
	}

	// 等 client 就绪（initialize 完成）
	waitFor(t, 5*time.Second, "client ready", func() bool {
		return m.Client() != nil
	})
	waitFor(t, 5*time.Second, "process running", func() bool {
		return m.Process().State() == StateRunning
	})

	ctx := context.Background()
	client := m.Client()
	// 创建会话
	sess, err := m.Sessions().New(ctx, client, "测试会话")
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if sess.ACPSessionID == "" {
		t.Fatal("no acp session id")
	}

	// prompt 流式
	updates, cancel, err := client.Prompt(ctx, sess.ACPSessionID, "你好")
	if err != nil {
		t.Fatalf("Prompt: %v", err)
	}
	defer cancel()

	select {
	case ev := <-events:
		if ev.Discriminator != "agent_message_chunk" {
			t.Fatalf("disc = %s", ev.Discriminator)
		}
		if ev.Content == "" {
			t.Fatal("empty content")
		}
		t.Logf("stream event: %+v", ev)
	case <-time.After(3 * time.Second):
		t.Fatal("timeout waiting for stream event")
	}
	// 等 updates 关闭（响应到达）
	select {
	case _, ok := <-updates:
		if ok {
			t.Fatal("updates should be closed")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout waiting for prompt response")
	}

	// 会话状态与持久化
	if got, ok := m.Sessions().Get(sess.ID); !ok || got == nil {
		t.Fatal("session not found after prompt")
	}
}

// TestHomeDirDefault 验证 homeDir 默认指向 /data/sophon/reasonix-home（隔离定制 reasonix
// 与系统正常安装实例），且显式 SOPHON_REASONIX_HOME 优先。
func TestHomeDirDefault(t *testing.T) {
	prev := os.Getenv("SOPHON_REASONIX_HOME")
	t.Cleanup(func() { _ = os.Setenv("SOPHON_REASONIX_HOME", prev) })
	_ = os.Unsetenv("SOPHON_REASONIX_HOME")

	pm := &ProcessManager{}
	if got := pm.homeDir(); got != "/data/sophon/reasonix-home" {
		t.Fatalf("homeDir() = %q, want /data/sophon/reasonix-home", got)
	}

	_ = os.Setenv("SOPHON_REASONIX_HOME", "/var/custom/home")
	if got := pm.homeDir(); got != "/var/custom/home" {
		t.Fatalf("homeDir() with env = %q, want /var/custom/home", got)
	}
}

// TestBuildProcessEnvInjectForwardKey 验证 MYS-387 env 组装：
// 继承 base env + HOME 覆盖 + envExtra 注入（DEEPSEEK_API_KEY=forward key）。
func TestBuildProcessEnvInjectForwardKey(t *testing.T) {
	env := buildProcessEnv(
		[]string{"PATH=/usr/bin", "HOME=/real/home"},
		"/data/sophon/reasonix-home",
		func() []string { return []string{"DEEPSEEK_API_KEY=forward-key-abc"} },
	)
	joined := strings.Join(env, "\n")
	for _, want := range []string{
		"PATH=/usr/bin",
		"HOME=/data/sophon/reasonix-home", // HOME 应被定制 home 覆盖
		"DEEPSEEK_API_KEY=forward-key-abc",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("env missing %q: %v", want, env)
		}
	}
}

// TestNewModuleEnvInjectorUsesDBForwardKey 验证 NewModule 装配的 pm 注入器
// 动态读取 llm_proxy_config.forward_key（DB 可读/不可读两种路径）。
func TestNewModuleEnvInjectorUsesDBForwardKey(t *testing.T) {
	// DB 可用：注入器产出 DEEPSEEK_API_KEY=DB 中的 forward key
	db := newTestDB(t)
	if err := db.AutoMigrate(&llmproxy.Config{}).Error; err != nil {
		t.Fatalf("migrate llmproxy config: %v", err)
	}
	svc := llmproxy.NewService(db)
	if _, err := svc.SaveConfig(llmproxy.SaveRequest{
		LLMApiBase: "http://x/v1", LLMApiKey: "k", LLMModel: "m",
	}); err != nil {
		t.Fatalf("save: %v", err)
	}
	_ = db.Model(&llmproxy.Config{}).Where("id = ?", 1).Update("forward_key", "db-key-123").Error

	m := NewModule(Config{Enabled: true, Model: "test-model"}, db, nil)
	m.pm.mu.Lock()
	extra := m.pm.envExtra
	m.pm.mu.Unlock()
	if extra == nil {
		t.Fatal("env injector not set")
	}
	found := false
	for _, kv := range extra() {
		if kv == "DEEPSEEK_API_KEY=db-key-123" {
			found = true
		}
	}
	if !found {
		t.Fatalf("injector output = %v, want DEEPSEEK_API_KEY=db-key-123", extra())
	}

	// DB nil：注入器为空（不 panic，无 key 可注）
	m2 := NewModule(DefaultConfig(), nil, nil)
	m2.pm.mu.Lock()
	extra2 := m2.pm.envExtra
	m2.pm.mu.Unlock()
	if extra2 == nil {
		t.Fatal("injector should be present even with nil db")
	}
	if kv := extra2(); len(kv) != 0 {
		t.Fatalf("nil db injector should return nothing, got %v", kv)
	}

	// 轮换后：DB 更新 → 注入器动态读到新 key（进程重启后即生效，无需重启 bmssm）
	_ = db.Model(&llmproxy.Config{}).Where("id = ?", 1).Update("forward_key", "rotated-key-999").Error
	found2 := false
	for _, kv := range extra() {
		if kv == "DEEPSEEK_API_KEY=rotated-key-999" {
			found2 = true
		}
	}
	if !found2 {
		t.Fatalf("injector should read rotated key from DB, got %v", extra())
	}
}
