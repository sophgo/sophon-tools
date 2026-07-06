package ota

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ---------------------------------------------------------------
// pcieTarget / pcieFilePath / pcieFull 纯函数
// ---------------------------------------------------------------

func TestPcieTarget(t *testing.T) {
	cases := []struct {
		module string
		want   string
	}{
		{"a53", "a53"},
		{"MCU", "mcu"},
		{"mcu", "mcu"},
		{"", "a53"},
		{"unknown", "a53"},
	}
	for _, tt := range cases {
		if got := pcieTarget(tt.module); got != tt.want {
			t.Errorf("pcieTarget(%q) = %q, want %q", tt.module, got, tt.want)
		}
	}
}

func TestPcieFull(t *testing.T) {
	cases := []struct {
		cmd  string
		want bool
	}{
		{"", false},
		{"--full", true},
		{"FULL", true},
		{"other", false},
	}
	for _, tt := range cases {
		if got := pcieFull(tt.cmd); got != tt.want {
			t.Errorf("pcieFull(%q) = %v, want %v", tt.cmd, got, tt.want)
		}
	}
}

func TestPcieFilePath(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	// upgrade a53 → bootrom
	p, err := e.pcieFilePath(Workflow{FileName: "fw.bin", Type: TypeUpgrade}, "a53")
	if err != nil {
		t.Fatalf("pcieFilePath: %v", err)
	}
	if p != filepath.Join(e.paths.PCIEBootromDir, "fw.bin") {
		t.Errorf("upgrade a53 path = %q", p)
	}
	// upgrade mcu → firmware
	p, err = e.pcieFilePath(Workflow{FileName: "fw.bin", Type: TypeUpgrade}, "mcu")
	if err != nil {
		t.Fatalf("pcieFilePath: %v", err)
	}
	if p != filepath.Join(e.paths.PCIEFirmwareDir, "fw.bin") {
		t.Errorf("upgrade mcu path = %q", p)
	}
	// rollback → backup
	p, err = e.pcieFilePath(Workflow{FileName: "fw.bin", Type: TypeRollback}, "a53")
	if err != nil {
		t.Fatalf("pcieFilePath: %v", err)
	}
	if p != filepath.Join(e.paths.PCIEBackupDir, "fw.bin") {
		t.Errorf("rollback path = %q", p)
	}
}

func TestPcieFilePathTraversal(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	// 路径穿越应返回空（sanitizeFileName 截断 base 后白名单不匹配或返回 ""）
	p, err := e.pcieFilePath(Workflow{FileName: "../../etc/passwd", Type: TypeUpgrade}, "a53")
	if err == nil {
		t.Errorf("expected error for path traversal, got path=%q", p)
	}
}

// ---------------------------------------------------------------
// RunPCIE（mock runner 断言参数）
// ---------------------------------------------------------------

func TestRunPCIEUpgradeA53(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Type: TypeUpgrade}
	if err := e.runPCIE(flow); err != nil {
		t.Fatalf("runPCIE: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 || calls[0].Name != "bm_firmware_update" {
		t.Fatalf("expected 1 bm_firmware_update call, got %+v", calls)
	}
	wantArgs := []string{"--dev=0xff", "--file=" + filepath.Join(e.paths.PCIEBootromDir, "fw.bin"), "--target=a53"}
	if !equalArgs(calls[0].Args, wantArgs) {
		t.Errorf("args = %+v, want %+v", calls[0].Args, wantArgs)
	}
}

func TestRunPCIEMcuFirmware(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC7", ModuleName: "mcu", FileName: "fw.bin", Type: TypeUpgrade}
	if err := e.runPCIE(flow); err != nil {
		t.Fatalf("runPCIE: %v", err)
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("got %d calls", len(calls))
	}
	if !argContains(calls[0].Args, "--target=mcu") {
		t.Errorf("missing --target=mcu: %+v", calls[0].Args)
	}
	if !argContains(calls[0].Args, "--file="+filepath.Join(e.paths.PCIEFirmwareDir, "fw.bin")) {
		t.Errorf("wrong mcu file path: %+v", calls[0].Args)
	}
}

func TestRunPCIERollbackBackup(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Type: TypeRollback}
	if err := e.runPCIE(flow); err != nil {
		t.Fatalf("runPCIE: %v", err)
	}
	calls := runner.calls_()
	if !argContains(calls[0].Args, "--file="+filepath.Join(e.paths.PCIEBackupDir, "fw.bin")) {
		t.Errorf("rollback should use backup dir: %+v", calls[0].Args)
	}
}

func TestRunPCIEFullFlag(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Type: TypeUpgrade, CmdFlag: "--full"}
	if err := e.runPCIE(flow); err != nil {
		t.Fatalf("runPCIE: %v", err)
	}
	calls := runner.calls_()
	if !argContains(calls[0].Args, "--full") {
		t.Errorf("expected --full flag: %+v", calls[0].Args)
	}
}

func TestRunPCIEFail(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	runner.fail = true
	flow := Workflow{Product: "SC5", FileName: "fw.bin", Type: TypeUpgrade}
	if err := e.runPCIE(flow); err == nil {
		t.Fatal("expected error when runner fails")
	}
}

func TestRunPCIEInvalidCmdFlag(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC5", FileName: "fw.bin", Type: TypeUpgrade, CmdFlag: "rm -rf /"}
	if err := e.runPCIE(flow); err == nil {
		t.Fatal("expected error for invalid cmdFlag in pcie")
	}
}

func TestRunPCIEInvalidFileName(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	flow := Workflow{Product: "SC5", FileName: "../../etc/passwd", Type: TypeUpgrade}
	if err := e.runPCIE(flow); err == nil {
		t.Fatal("expected error for path traversal in fileName")
	}
}

// ---------------------------------------------------------------
// PCIE 端到端：flash 成功 → reboot 步骤 → Success
// ---------------------------------------------------------------

func TestPCIEFlowRebootSuccess(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, false)
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SC5", ModuleName: "a53", FileName: "fw.bin", Type: TypeUpgrade}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)

	calls := runner.calls_()
	// 期望：bm_firmware_update + sync + shutdown
	names := make([]string, len(calls))
	for i, c := range calls {
		names[i] = c.Name
	}
	if !sliceContains(names, "bm_firmware_update") {
		t.Errorf("expected bm_firmware_update call, got %v", names)
	}
	if !sliceContains(names, "sync") {
		t.Errorf("expected sync call, got %v", names)
	}
	if !sliceContains(names, "shutdown") {
		t.Errorf("expected shutdown call, got %v", names)
	}

	wf, _ := e.Query(flow.WorkflowID)
	if !strings.Contains(wf.Strategy, "reboot") {
		t.Errorf("Strategy = %q, should contain reboot", wf.Strategy)
	}
	if wf.LastRebootTime.IsZero() {
		t.Error("LastRebootTime should be set")
	}
}

// 辅助
func equalArgs(got, want []string) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range got {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}

func argContains(args []string, s string) bool {
	for _, a := range args {
		if a == s {
			return true
		}
	}
	return false
}

func sliceContains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
