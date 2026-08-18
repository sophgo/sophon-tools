package ota

import (
	"strings"
	"sync"
	"testing"
	"time"

	"bmssm/pkg/hazard"
)

// ---------------------------------------------------------------
// MYS-451：刷机/回滚窗口全程持 hazard 互斥锁
//
// 契约：flow 从 handleFlash 入口（非 dryRun）开始持锁（holder=HazardHolderFlash），
// 直到该 flow 到达终态（Success/Fail）才释放。窗口内任何 reboot/shutdown/
// 其他 OTA/软件安装等危险操作 → TryAcquire 冲突（HTTP 层表现为 409）。
// ---------------------------------------------------------------

// waitHazardFree 轮询直到互斥锁可获取——断言 flow 终态后锁已释放。
func waitHazardFree(t *testing.T, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		g, err := hazard.HazardOps.TryAcquire("reboot")
		if err == nil {
			g.Release()
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("hazard lock still held after timeout (expected release at flow terminal)")
}

// blockingRunner 可按命令名阻塞 runner，精确控制刷机/重启窗口的时序。
// blockOn(name) 注册信号量：命令首次执行时关闭 entered，等待 release 放行。
type blockingRunner struct {
	mu      sync.Mutex
	calls   []string
	entered map[string]chan struct{}
	release map[string]chan struct{}
}

func newBlockingRunner() *blockingRunner {
	return &blockingRunner{
		entered: map[string]chan struct{}{},
		release: map[string]chan struct{}{},
	}
}

// blockOn 让指定命令在首次执行时阻塞；返回 entered（已执行）与 release（放行）。
func (r *blockingRunner) blockOn(name string) (<-chan struct{}, chan struct{}) {
	entered := make(chan struct{})
	release := make(chan struct{})
	r.mu.Lock()
	r.entered[name] = entered
	r.release[name] = release
	r.mu.Unlock()
	return entered, release
}

func (r *blockingRunner) run(name string, args ...string) (string, string, error) {
	r.mu.Lock()
	r.calls = append(r.calls, name)
	entered := r.entered[name]
	release := r.release[name]
	r.mu.Unlock()
	if entered != nil {
		close(entered)
		<-release
	}
	return "ok", "", nil
}

// ---------------------------------------------------------------
// 用例 1：SOC 刷机窗口持锁 → 终态释放
// ---------------------------------------------------------------

// TestFlashWindowHoldsHazardLock 覆盖：
//  1. SOC 刷机中（flow Running、worker 已持锁）→ reboot / 再次 upgrade 的
//     TryAcquire 均被拒，冲突错误点名持有者 HazardHolderFlash
//  2. flow 到达终态（success 标志出现，pollSOC 判定）→ 锁释放 → reboot 可正常申请
func TestFlashWindowHoldsHazardLock(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()
	t.Cleanup(hazard.HazardOps.Release) // 兜底：断言失败也不把锁泄漏给后续用例

	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{"md5.txt": "x\n"})
	// 无 success/error 标志 → flow 保持 Running（ota.sh 异步执行中）
	flags.mark(false, false)

	flow := Workflow{Product: "SE7", FileName: "fw.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	// 进入 Running 前 handleFlash 已 TryAcquire 持锁（锁先于状态写入，无竞态）
	waitForStatus(t, e, flow.WorkflowID, StatusRunning, 3*time.Second)

	// 刷机窗口内：reboot / shutdown / 再次 OTA 等危险操作一律被拒（TryAcquire 冲突）
	if _, err := hazard.HazardOps.TryAcquire("reboot"); err == nil {
		t.Fatal("reboot should be blocked while flash window open")
	} else if !strings.Contains(err.Error(), HazardHolderFlash) {
		t.Errorf("conflict error should name holder %q, got: %v", HazardHolderFlash, err)
	}
	if _, err := hazard.HazardOps.TryAcquire("ota.upgrade"); err == nil {
		t.Fatal("another upgrade should be blocked while flash window open")
	}

	// 刷机终态（success 标志出现）→ pollSOC 判定终态并释放锁
	flags.mark(true, false)
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)
	waitHazardFree(t, 3*time.Second)

	// 窗口关闭后 reboot 可正常申请（HTTP 层即 200）
	guard, err := hazard.HazardOps.TryAcquire("reboot")
	if err != nil {
		t.Fatalf("reboot should be acquirable after flow terminal: %v", err)
	}
	guard.Release()
}

// ---------------------------------------------------------------
// 用例 2：刷机中（Running）→ 新的 upgrade/rollback 流被快速拒绝
// ---------------------------------------------------------------

// TestSecondFlowRejectedWhileFlashRunning 覆盖：
// 已有 Running/刷机中的流持锁时，新 upgrade/rollback 流到执行点
// （controller 入队已放行的场景）TryAcquire 失败 → 快速标 Fail，不并发刷机。
func TestSecondFlowRejectedWhileFlashRunning(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()
	t.Cleanup(hazard.HazardOps.Release)

	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{"md5.txt": "x\n"})
	flags.mark(false, false)

	// flow A：SOC 刷机中（持锁）
	a := Workflow{Product: "SE7", FileName: "fw.tgz", Name: "flash-A"}
	if err := e.EnqueueFlow(&a); err != nil {
		t.Fatalf("EnqueueFlow A: %v", err)
	}
	waitForStatus(t, e, a.WorkflowID, StatusRunning, 3*time.Second)

	// flow B：另一个升级，到执行点时锁仍在 → StatusFail，Info 点名 ota.flash
	b := Workflow{Product: "SE7", FileName: "fw.tgz", Name: "flash-B"}
	if err := e.EnqueueFlow(&b); err != nil {
		t.Fatalf("EnqueueFlow B: %v", err)
	}
	waitForStatus(t, e, b.WorkflowID, StatusFail, 3*time.Second)
	wf, _ := e.Query(b.WorkflowID)
	if !strings.Contains(wf.Info, HazardHolderFlash) {
		t.Errorf("flow B Info = %q, want mention %q", wf.Info, HazardHolderFlash)
	}

	// flow C：回滚同理被拒
	c := Workflow{Product: "SC5", FileName: "fw.bin", Type: TypeRollback, Name: "rb-C"}
	if err := e.EnqueueFlow(&c); err != nil {
		t.Fatalf("EnqueueFlow C: %v", err)
	}
	waitForStatus(t, e, c.WorkflowID, StatusFail, 3*time.Second)

	// A 终态后锁释放，后续 flow 恢复执行（这里 A 走 SOC success 终态）
	flags.mark(true, false)
	waitForStatus(t, e, a.WorkflowID, StatusSuccess, 3*time.Second)
	waitHazardFree(t, 3*time.Second)
}

// ---------------------------------------------------------------
// 用例 3：PCIE/多节点路径 —— 锁经 reboot 步骤保持到 flow 终态
// ---------------------------------------------------------------

// TestPCIEFlashWindowHoldsLockThroughRebootStep 覆盖 advanceToReboot 重新入队
// 的锁延续：刷机成功后 lock 不释放，reboot 步骤（doReboot 的 shutdown）执行期间
// 仍被持有；shutdown 返回后（flow 终态）才释放。
func TestPCIEFlashWindowHoldsLockThroughRebootStep(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	br := newBlockingRunner()
	e.runner = br.run
	e.Start()
	defer e.Stop()
	t.Cleanup(hazard.HazardOps.Release)

	// 卡住 doReboot 的最后一步 shutdown，制造"reboot 步骤执行中"的观测窗口
	entered, release := br.blockOn("shutdown")
	// 兜底：断言失败也要放行 worker，否则 e.Stop() 会死锁（worker 阻塞在 runner 上）
	var releaseOnce sync.Once
	releaseNow := func() { releaseOnce.Do(func() { close(release) }) }
	t.Cleanup(releaseNow)

	flow := Workflow{Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Type: TypeUpgrade}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}

	// 等到 shutdown 命令正在执行（刷机已完成、reboot 步骤进行中）：锁必须仍被持有
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for shutdown command during reboot step")
	}
	if _, err := hazard.HazardOps.TryAcquire("reboot"); err == nil {
		t.Fatal("reboot should be blocked while reboot step executing")
	} else if !strings.Contains(err.Error(), HazardHolderFlash) {
		t.Errorf("conflict error should name holder %q, got: %v", HazardHolderFlash, err)
	}

	// 放行 shutdown → doReboot 返回 → flow 终态 → 锁释放
	releaseNow()
	waitHazardFree(t, 3*time.Second)
}

// ---------------------------------------------------------------
// 用例 4：回滚窗口同样持锁
// ---------------------------------------------------------------

// TestRollbackWindowHoldsHazardLock 回滚（SOC Rollback 类型）刷机窗口持锁、
// 终态释放，与升级同语义。
func TestRollbackWindowHoldsHazardLock(t *testing.T) {
	e, _, flags, _ := newTestEngine(t, false)
	e.paths.SOCOTADir = t.TempDir()
	e.paths.SOCWorkRoot = t.TempDir()
	e.Start()
	defer e.Stop()
	t.Cleanup(hazard.HazardOps.Release)

	createOTAFixture(t, e.paths.SOCOTADir, "fw.tgz", map[string]string{"md5.txt": "x\n"})
	flags.mark(false, false)

	flow := Workflow{Product: "SE7", FileName: "fw.tgz", Type: TypeRollback}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusRunning, 3*time.Second)

	if _, err := hazard.HazardOps.TryAcquire("shutdown"); err == nil {
		t.Fatal("shutdown should be blocked while rollback window open")
	}

	flags.mark(true, false)
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)
	waitHazardFree(t, 3*time.Second)
}
