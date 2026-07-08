package ota

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ---------------------------------------------------------------
// diskUsage
// ---------------------------------------------------------------

func TestDiskUsageRoot(t *testing.T) {
	used, err := diskUsage("/")
	if err != nil {
		t.Fatalf("diskUsage /: %v", err)
	}
	if used < 0 || used > 1 {
		t.Errorf("diskUsage / = %v, want [0,1]", used)
	}
}

func TestDiskUsageNonExistent(t *testing.T) {
	_, err := diskUsage("/nonexistent/path/12345")
	if err == nil {
		t.Fatal("expected error for nonexistent path")
	}
}

// ---------------------------------------------------------------
// runMultiNodeCtrl（mock runner + 磁盘检查）
// ---------------------------------------------------------------

func TestRunMultiNodeCtrlDefault(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.CtrlOTADir = t.TempDir()
	// 创建 local_update.sh 供 chmod
	localSh := filepath.Join(e.paths.CtrlOTADir, "local_update.sh")
	os.WriteFile(localSh, []byte("#!/bin/sh\n"), 0o644)

	flow := Workflow{Product: "SE6", ModuleName: "controller", Type: TypeUpgrade}
	if err := e.runMultiNode(flow); err != nil {
		t.Fatalf("runMultiNode: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 || calls[0].Name != "bash" {
		t.Fatalf("expected 1 bash call, got %+v", calls)
	}
	want := localSh + " md5.txt 0"
	if len(calls[0].Args) != 2 || calls[0].Args[0] != "-c" || calls[0].Args[1] != want {
		t.Errorf("args = %+v, want [-c %q]", calls[0].Args, want)
	}
}

func TestRunMultiNodeCtrlCmdFlag(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.CtrlOTADir = t.TempDir()
	os.WriteFile(filepath.Join(e.paths.CtrlOTADir, "local_update.sh"), []byte("x"), 0o644)

	flow := Workflow{Product: "SE6", ModuleName: "ctrl", CmdFlag: "/data/ota/local_update.sh arg1"}
	if err := e.runMultiNode(flow); err != nil {
		t.Fatalf("runMultiNode: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("got %d calls", len(calls))
	}
	if calls[0].Args[1] != "/data/ota/local_update.sh arg1" {
		t.Errorf("cmd = %q, want whitelisted cmdflag", calls[0].Args[1])
	}
}

func TestRunMultiNodeCtrlCmdFlagRejected(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.paths.CtrlOTADir = t.TempDir()
	os.WriteFile(filepath.Join(e.paths.CtrlOTADir, "local_update.sh"), []byte("x"), 0o644)

	flow := Workflow{Product: "SE6", ModuleName: "ctrl", CmdFlag: "/custom/upgrade.sh arg1"}
	err := e.runMultiNode(flow)
	if err == nil {
		t.Fatal("expected error for invalid ctrl cmdFlag")
	}
}

func TestRunMultiNodeCtrlDiskFull(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.CtrlOTADir = t.TempDir()
	e.diskUsageFn = func(string) (float64, error) { return 0.99, nil }

	flow := Workflow{Product: "SE6", ModuleName: "controller"}
	err := e.runMultiNode(flow)
	if err == nil || !strings.Contains(err.Error(), "full") {
		t.Fatalf("expected disk full error, got %v", err)
	}
	// 磁盘满时不应执行升级命令
	if calls := runner.calls_(); len(calls) != 0 {
		t.Errorf("runner should not be called when disk full, got %+v", calls)
	}
}

// ---------------------------------------------------------------
// runMultiNodeCore
// ---------------------------------------------------------------

func TestRunMultiNodeCoreCmdFlag(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SE8", ModuleName: "core", CmdFlag: "ssh root@192.168.1.10 mk_bootscr.sh"}
	if err := e.runMultiNode(flow); err != nil {
		t.Fatalf("runMultiNode: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 || calls[0].Name != "bash" {
		t.Fatalf("expected bash call, got %+v", calls)
	}
	if calls[0].Args[1] != "ssh root@192.168.1.10 mk_bootscr.sh" {
		t.Errorf("cmd = %q", calls[0].Args[1])
	}
}

func TestRunMultiNodeCoreCmdFlagRejected(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SE8", ModuleName: "core", CmdFlag: "rm -rf /"}
	err := e.runMultiNode(flow)
	if err == nil {
		t.Fatal("expected error for invalid core cmdFlag")
	}
}

func TestRunMultiNodeCoreDefault(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SE8", ModuleName: "core"}
	if err := e.runMultiNode(flow); err != nil {
		t.Fatalf("runMultiNode: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("got %d calls", len(calls))
	}
	want := "/data/ota/local_update.sh md5.txt 0"
	if calls[0].Args[1] != want {
		t.Errorf("default core cmd = %q, want %q", calls[0].Args[1], want)
	}
}

func TestRunMultiNodeUnknownModule(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SE6", ModuleName: "unknown"}
	if err := e.runMultiNode(flow); err == nil {
		t.Fatal("expected error for unknown module")
	}
}

// ---------------------------------------------------------------
// 多节点端到端：ctrl flash 成功 → reboot → Success
// ---------------------------------------------------------------

func TestMultiNodeFlowRebootSuccess(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.paths.CtrlOTADir = t.TempDir()
	os.WriteFile(filepath.Join(e.paths.CtrlOTADir, "local_update.sh"), []byte("#!/bin/sh\n"), 0o644)
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SE6", ModuleName: "controller", Type: TypeUpgrade}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)

	calls := runner.calls_()
	names := make([]string, len(calls))
	for i, c := range calls {
		names[i] = c.Name
	}
	// bash (local_update) + sync + shutdown
	if !sliceContains(names, "bash") || !sliceContains(names, "sync") || !sliceContains(names, "shutdown") {
		t.Errorf("expected bash+sync+shutdown, got %v", names)
	}
}

// 多节点 core 失败 → Fail
func TestMultiNodeFlowCoreFail(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.Start()
	defer e.Stop()
	runner.fail = true

	flow := Workflow{Product: "SE8", ModuleName: "core", CmdFlag: "ssh x mk_bootscr.sh"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusFail, 3*time.Second)
}
