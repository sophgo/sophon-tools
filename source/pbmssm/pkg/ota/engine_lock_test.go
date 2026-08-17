package ota

import (
	"strings"
	"sync"
	"testing"
	"time"

	"bmssm/pkg/oplock"
)

// ---------------------------------------------------------------
// 危险操作互斥（MYS-389）：OTA 刷机从执行到终态持有全局 oplock，
// 与 reboot/shutdown/防火墙 rebuild 等互斥；被锁拦截时 workflow 置 Fail。
// 用例使用独立 oplock 实例，避免污染全局锁。
// ---------------------------------------------------------------

// TestEngineFlashBlockedByBusyOp 另一危险操作进行中时，OTA 刷机直接 Fail 且不执行任何命令。
func TestEngineFlashBlockedByBusyOp(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.opLock = oplock.New() // 独立锁，隔离测试
	e.Start()
	defer e.Stop()

	// 模拟设备正被其他危险操作占用（如 reboot 已触发）
	release, err := e.opLock.Acquire("reboot")
	if err != nil {
		t.Fatalf("acquire busy lock: %v", err)
	}
	defer release()

	flow := Workflow{Product: "SE7", FileName: "pkg.tgz", Type: TypeUpgrade, Name: "busy-test"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}

	waitForStatus(t, e, flow.WorkflowID, StatusFail, 3*time.Second)

	wf, err := e.Query(flow.WorkflowID)
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if !strings.Contains(wf.Info, "blocked") {
		t.Errorf("Info should mention blocked, got: %q", wf.Info)
	}
	// 被锁拦截发生在执行前：不得调用任何刷机命令
	if calls := runner.calls_(); len(calls) != 0 {
		t.Errorf("no runner calls expected when blocked, got %d: %+v", len(calls), calls)
	}
}

// TestEngineFlashReleasesLockOnFail 刷机失败进入终态后释放锁（不悬挂）。
func TestEngineFlashReleasesLockOnFail(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.opLock = oplock.New()
	e.Start()
	defer e.Stop()

	runner.fail = true // 刷机命令失败 → workflow Fail

	flow := Workflow{Product: "SE7", FileName: "pkg.tgz", Type: TypeUpgrade, Name: "fail-test"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusFail, 3*time.Second)

	// 终态后锁必须释放：外部可立即获取
	if _, err := e.opLock.Acquire("reboot"); err != nil {
		t.Fatalf("lock should be released after workflow reaches terminal state: %v", err)
	}
	e.opMu.Lock()
	left := len(e.opReleases)
	e.opMu.Unlock()
	if left != 0 {
		t.Errorf("opReleases should be empty, got %d", left)
	}
}

// blockingRunner 可阻塞的 runner：进入命令后通知 entered，等 release 放行。
type blockingRunner struct {
	entered chan struct{}
	release chan struct{}
	once    sync.Once
}

func (r *blockingRunner) run(name string, args ...string) (string, string, error) {
	r.once.Do(func() { close(r.entered) })
	<-r.release
	return "ok", "", nil
}

// TestEnginePcieFlashKeepsLockUntilReboot PCIE 刷机执行期间锁被持有，
// 刷机成功后（advanceToReboot→doReboot）锁释放（不悬挂，shutdown 失败也安全）。
func TestEnginePcieFlashKeepsLockUntilReboot(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.opLock = oplock.New() // 独立锁，隔离测试
	br := &blockingRunner{entered: make(chan struct{}), release: make(chan struct{})}
	e.runner = br.run
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SC5", FileName: "fw.bin", Type: TypeUpgrade, Name: "pcie-test"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}

	// 刷机命令（bm_firmware_update）执行中：锁必须已被 engine 持有
	<-br.entered
	if h := e.opLock.Holder(); h == "" {
		t.Fatal("lock should be held while flash is running")
	}

	// 放行 → flash 成功 → advanceToReboot → doReboot（同步/shutdown 模拟成功）
	close(br.release)

	// doReboot 完成后锁必须释放（否则后续危险操作被永久阻塞）
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if h := e.opLock.Holder(); h == "" {
			goto released
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("lock should be released after doReboot")
released:
	wf, err := e.Query(flow.WorkflowID)
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if wf.Status != StatusSuccess {
		t.Errorf("workflow status = %d, want %d", wf.Status, StatusSuccess)
	}
}

// TestEngineDryRunDoesNotTakeLock dryRun 模拟刷机不占用危险操作锁。
func TestEngineDryRunDoesNotTakeLock(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	e.opLock = oplock.New()
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SE7", FileName: "pkg.tgz", Type: TypeUpgrade, Name: "dry-test"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)

	if h := e.opLock.Holder(); h != "" {
		t.Errorf("dryRun must not hold the dangerous-op lock, holder=%q", h)
	}
}
