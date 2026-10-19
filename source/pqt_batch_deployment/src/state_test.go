package main

import "testing"

// 旧版崩溃点：删到空表后 currentRow()==-1，代码直接 item(-1,N)->data() 崩溃。
// 新状态层对越界下标一律返回 false / ok=false。
func TestRemoveLastDeviceDoesNotPanic(t *testing.T) {
	s := NewGUIState()
	for s.DeviceCount() > 0 {
		if !s.RemoveDevice(0) {
			t.Fatal("删除首行应成功")
		}
	}
	if s.DeviceCount() != 0 {
		t.Fatalf("设备数 = %d", s.DeviceCount())
	}
	if got := s.SelectedDevice(); got != -1 {
		t.Fatalf("删空后 SelectedDevice = %d, 期望 -1", got)
	}
	if _, ok := s.SelectedDeviceInf(); ok {
		t.Fatal("无选中设备时 ok 必须为 false（旧版在此崩溃）")
	}
	// 越界操作一律安全返回
	if s.RemoveDevice(0) {
		t.Fatal("空表删除应返回 false")
	}
	if s.CloneDevice(0) {
		t.Fatal("空表克隆应返回 false")
	}
	if s.UpdateDevice(0, RemoteInf{IP: "x"}) {
		t.Fatal("空表更新应返回 false")
	}
	if s.SetDeviceStatus(0, "x") {
		t.Fatal("空表设置状态应返回 false")
	}
}

// 旧版崩溃点：未选中就点"储存该项"，currentRow()==-1 直接解引用。
func TestSelectedDeviceInfWithoutSelection(t *testing.T) {
	s := NewGUIState()
	if _, ok := s.SelectedDeviceInf(); ok {
		t.Fatal("初始无选中，应返回 false")
	}
	s.SelectDevice(99) // 非法下标
	if _, ok := s.SelectedDeviceInf(); ok {
		t.Fatal("非法下标应返回 false")
	}
	s.SelectDevice(0)
	inf, ok := s.SelectedDeviceInf()
	if !ok || inf.IP != "192.168.150.1" {
		t.Fatalf("合法选中应返回值, got %+v ok=%v", inf, ok)
	}
}

// 旧版崩溃点：读取空配置后 emit itemChanged(item(0,0))，item 为空仍解引用。
func TestLoadEmptyConfigThenAccessSafe(t *testing.T) {
	s := NewGUIState()
	s.LoadConfig(&Config{RemoteInf: []RemoteInf{}, OperationInf: []OperationInf{}})
	if s.DeviceCount() != 0 {
		t.Fatal("应加载为空")
	}
	if _, ok := s.SelectedDeviceInf(); ok {
		t.Fatal("空配置下不应有选中设备")
	}
	// 导出不应 panic；设备为空是预期的，操作保留（预设只含设备清单时不清操作）
	c := s.ToConfig()
	if len(c.RemoteInf) != 0 {
		t.Fatalf("设备应为空, 实际 %d", len(c.RemoteInf))
	}
}

func TestCloneDeviceCopiesFields(t *testing.T) {
	s := NewGUIState()
	if !s.CloneDevice(0) {
		t.Fatal("克隆应成功")
	}
	d := s.Devices()
	if len(d) != 2 {
		t.Fatalf("设备数 = %d", len(d))
	}
	if d[1].Inf.IP != d[0].Inf.IP {
		t.Fatal("克隆内容不一致")
	}
	if d[1].Status != "" {
		t.Fatal("克隆应清空执行状态")
	}
}

func TestOpsEditAndValidate(t *testing.T) {
	s := NewGUIState()
	if !s.UpdateOp(0, OperationInf{Name: "x", Type: OpCommand, CommandStr: ""}) {
		t.Fatal("更新应成功")
	}
	if s.CompleteOpCount() != 0 {
		t.Fatal("空命令应算不完整")
	}
	s.UpdateOp(0, OperationInf{Name: "x", Type: OpCommand, CommandStr: "date"})
	if s.CompleteOpCount() != 1 {
		t.Fatal("完整命令应计数")
	}
}

func TestToConfigRoundTrip(t *testing.T) {
	s := NewGUIState()
	s.AppendDevice(RemoteInf{IP: "10.0.0.9", Port: 2222, Username: "u", Password: "p"})
	s.AppendOp(OperationInf{Name: "up", Type: OpUpFile,
		TransferFileSourcePath: "a", TransferFileDestinationPath: "/tmp/a"})
	c := s.ToConfig()
	if len(c.RemoteInf) != 2 || len(c.OperationInf) != 2 {
		t.Fatalf("导出数量错误: %+v", c)
	}
	s2 := NewGUIState()
	s2.LoadConfig(c)
	if s2.DeviceCount() != 2 || len(s2.Ops()) != 2 {
		t.Fatal("重新载入后数量不一致")
	}
}

func TestMaxParallelGuard(t *testing.T) {
	s := NewGUIState()
	s.SetMaxParallel(0)
	if s.MaxParallel() <= 0 {
		t.Fatal("非法并发数应被忽略并保留原值")
	}
	s.SetMaxParallel(7)
	if s.MaxParallel() != 7 {
		t.Fatal("合法并发数应生效")
	}
}

func TestRemoveOpAndCloneOpBounds(t *testing.T) {
	s := NewGUIState()
	if !s.CloneOp(0) {
		t.Fatal("克隆操作应成功")
	}
	if len(s.Ops()) != 2 {
		t.Fatalf("操作数 = %d", len(s.Ops()))
	}
	if !s.RemoveOp(0) {
		t.Fatal("删除操作应成功")
	}
	if len(s.Ops()) != 1 {
		t.Fatalf("操作数 = %d", len(s.Ops()))
	}
	if s.RemoveOp(5) {
		t.Fatal("越界删除应返回 false")
	}
	if s.UpdateOp(-1, OperationInf{}) {
		t.Fatal("负数下标应返回 false")
	}
}
