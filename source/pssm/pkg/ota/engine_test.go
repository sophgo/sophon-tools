package ota

import (
	"testing"
	"time"
)

// ---------------------------------------------------------------
// productClass 映射
// ---------------------------------------------------------------

func TestProductClass(t *testing.T) {
	cases := []struct {
		product string
		want    ProductClass
	}{
		{"SE5", ClassSOC},
		{"se7", ClassSOC},
		{"SE9", ClassSOC},
		{"SC5", ClassPCIE},
		{"sc7", ClassPCIE},
		{"SE6", ClassMultiNode},
		{"se8", ClassMultiNode},
		{"unknown", ClassUnknown},
		{"", ClassUnknown},
		{"SE7 ", ClassSOC}, // trim
		// 完整型号串（global.DeviceTypeEx 形如 "SE7 V01"）按前缀识别，不再报
		// "ota: path not implemented"。回归：用户 OTA 升级失败即因此触发。
		{"SE7 V01", ClassSOC},
		{"se9 v02", ClassSOC},
		{"SC5 pro", ClassPCIE},
		{"se8 v1", ClassMultiNode},
	}
	for _, tt := range cases {
		got := productClass(tt.product)
		if got != tt.want {
			t.Errorf("productClass(%q) = %v, want %v", tt.product, got, tt.want)
		}
	}
}

// ---------------------------------------------------------------
// Engine: dryRun flash → Success
// ---------------------------------------------------------------

func TestEngineDryRunFlashSuccess(t *testing.T) {
	e, runner, _, _ := newTestEngine(t, true)
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SE7", FileName: "pkg.tgz", Type: TypeUpgrade, Name: "ota-test"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}

	flows, err := e.QueryAll()
	if err != nil || len(flows) != 1 {
		t.Fatalf("QueryAll: err=%v len=%d", err, len(flows))
	}
	id := flows[0].WorkflowID
	if id == "" {
		t.Fatal("workflowId empty")
	}
	if flows[0].Status != StatusCommit {
		t.Errorf("initial status = %d, want %d", flows[0].Status, StatusCommit)
	}

	waitForStatus(t, e, id, StatusSuccess, 3*time.Second)

	// dryRun 不应调用任何破坏性 runner
	if calls := runner.calls_(); len(calls) != 0 {
		t.Errorf("dryRun should not call runner, got %d calls: %+v", len(calls), calls)
	}
}

// ---------------------------------------------------------------
// Engine: 非干跑 + 未知 Product → Fail（dispatch default 分支）
// ---------------------------------------------------------------

func TestEngineUnknownProductFail(t *testing.T) {
	e, _, _, _ := newTestEngine(t, false)
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "unknownXYZ", FileName: "pkg.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	id := flow.WorkflowID

	waitForStatus(t, e, id, StatusFail, 3*time.Second)

	wf, err := e.Query(id)
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if wf.Status != StatusFail {
		t.Errorf("status = %d, want %d", wf.Status, StatusFail)
	}
	if wf.Info == "" {
		t.Error("Info should contain failure reason")
	}
}

// ---------------------------------------------------------------
// Engine: Query / QueryAll
// ---------------------------------------------------------------

func TestEngineQueryNotFound(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	_, err := e.Query("nonexistent")
	if err == nil {
		t.Fatal("Query nonexistent should error")
	}
}

func TestEngineQueryAllEmpty(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	flows, err := e.QueryAll()
	if err != nil {
		t.Fatalf("QueryAll: %v", err)
	}
	if len(flows) != 0 {
		t.Errorf("expected empty, got %d", len(flows))
	}
}

// ---------------------------------------------------------------
// Engine: EnqueueFlow 默认值补全
// ---------------------------------------------------------------

func TestEnqueueFlowDefaults(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	// 不启动 worker goroutine，仅测试 EnqueueFlow 的默认值补全逻辑，避免竞态。

	// 只给 Product，其余由 EnqueueFlow 补全
	flow := Workflow{Product: "SE7"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	wf, err := e.Query(flow.WorkflowID)
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if wf.Type != TypeUpgrade {
		t.Errorf("Type = %d, want %d", wf.Type, TypeUpgrade)
	}
	if wf.Strategy != StrategyFlash {
		t.Errorf("Strategy = %q, want %q", wf.Strategy, StrategyFlash)
	}
	if wf.Step != StepFlash {
		t.Errorf("Step = %q, want %q", wf.Step, StepFlash)
	}
	if wf.Status != StatusCommit {
		t.Errorf("Status = %d, want %d", wf.Status, StatusCommit)
	}
	if wf.WorkflowID == "" {
		t.Error("WorkflowID should be auto-generated")
	}
	if wf.CreateTime.IsZero() {
		t.Error("CreateTime should be set")
	}
}

// ---------------------------------------------------------------
// Engine: Rollback 类型
// ---------------------------------------------------------------

func TestEnqueueFlowRollback(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	// 不启动 worker goroutine，仅测试 EnqueueFlow 的类型保留逻辑，避免竞态。

	flow := Workflow{Product: "SE7", Type: TypeRollback}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	wf, _ := e.Query(flow.WorkflowID)
	if wf.Type != TypeRollback {
		t.Errorf("Type = %d, want %d", wf.Type, TypeRollback)
	}
}

// ---------------------------------------------------------------
// Engine: dryRun 下 Rollback 也直接 Success
// ---------------------------------------------------------------

func TestEngineDryRunRollbackSuccess(t *testing.T) {
	e, _, _, _ := newTestEngine(t, true)
	e.Start()
	defer e.Stop()

	flow := Workflow{Product: "SC5", Type: TypeRollback, FileName: "fw.tgz"}
	if err := e.EnqueueFlow(&flow); err != nil {
		t.Fatalf("EnqueueFlow: %v", err)
	}
	waitForStatus(t, e, flow.WorkflowID, StatusSuccess, 3*time.Second)
}
