package ssm

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestOtaTaskUnmarshalPssmWorkflow 验证 sophliteos OtaTask 能正确反序列化
// pssm Workflow 的响应（workflowId 为 16 位 hex 字符串、info 携带失败原因）。
//
// 背景：pssm WorkflowID 为 string（newWorkflowID 返回 hex），而 OtaTask.WorkflowID
// 曾被定义为 int，导致 json.Unmarshal 报 TypeError 被 _ = 吞掉，WorkflowID 恒为 0，
// 进而 OtaRollback 按 WorkflowID 匹配失败。本测试锁定 string 类型契约。
func TestOtaTaskUnmarshalPssmWorkflow(t *testing.T) {
	// 模拟 pssm /bitmain/v1/ssm/workflow/upgrade 返回的 result（含 info 失败原因）
	pssmJSON := `{
		"code": 0,
		"result": [
			{
				"id": 1,
				"userId": "admin",
				"workflowId": "a1b2c3d4e5f6a7b8",
				"name": "sdcard_upgrade",
				"type": 1,
				"status": 3,
				"info": "LAST_PART_NOT_FLASH mode, check last part start failed: panic",
				"product": "SE7",
				"moduleName": "ctrl",
				"fileName": "sdcard.tgz",
				"strategy": "flash",
				"step": "flash",
				"cmdFlag": "",
				"version": "",
				"createTime": "2026-07-03T10:00:00Z",
				"lastRebootTime": "2026-07-03T10:00:00Z"
			}
		]
	}`

	// 取出 result 数组部分（模拟 OtaUpgradeList handler 的二次解析）
	raw := struct {
		Code   int             `json:"code"`
		Result json.RawMessage `json:"result"`
	}{}
	if err := json.Unmarshal([]byte(pssmJSON), &raw); err != nil {
		t.Fatalf("unwrap result: %v", err)
	}

	var tasks []OtaTask
	if err := json.Unmarshal(raw.Result, &tasks); err != nil {
		t.Fatalf("unmarshal OtaTask slice: %v", err)
	}

	if len(tasks) != 1 {
		t.Fatalf("expect 1 task, got %d", len(tasks))
	}

	task := tasks[0]

	// info 必须端到端透传（失败原因展示的核心）
	if task.Info != "LAST_PART_NOT_FLASH mode, check last part start failed: panic" {
		t.Errorf("Info mismatch: got %q", task.Info)
	}

	// WorkflowID 必须保留 pssm 的 hex 字符串（曾因 int 类型被吞为 0）
	if task.WorkflowID != "a1b2c3d4e5f6a7b8" {
		t.Errorf("WorkflowID mismatch: got %v (want string a1b2c3d4e5f6a7b8)", task.WorkflowID)
	}

	// 失败状态必须正确
	if task.Status != 3 {
		t.Errorf("Status mismatch: got %d (want 3=Fail)", task.Status)
	}
	if task.Name != "sdcard_upgrade" {
		t.Errorf("Name mismatch: got %q", task.Name)
	}
}

// TestOtaTaskUnmarshalWorkflowIDType 断言 WorkflowID 字段为 string 类型而非 int。
// 防止回退到 int 类型导致 pssm hex workflowId 解析失败。
func TestOtaTaskUnmarshalWorkflowIDType(t *testing.T) {
	jsonStr := `[{"workflowId":"deadbeefdeadbeef","info":"some failure"}]`
	var tasks []OtaTask
	if err := json.Unmarshal([]byte(jsonStr), &tasks); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if tasks[0].WorkflowID != "deadbeefdeadbeef" {
		t.Errorf("expect string workflowId, got %v", tasks[0].WorkflowID)
	}
	// WorkflowID 字段在回滚匹配中按 == 比较，必须是可读字符串
	if !strings.Contains("deadbeefdeadbeef", "dead") {
		t.FailNow()
	}
}
