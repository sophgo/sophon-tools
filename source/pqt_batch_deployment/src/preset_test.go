package main

import "testing"

// 内置预设必须能被解析（旧版资源文件原样内嵌）。
// 注意：两个 SE6 预设只含 remoteInf、不含 operationInf，这是历史事实，
// 载入时必须保留用户已配置的操作（见 GUIState.LoadConfig）。
func TestBuiltinPresetsLoad(t *testing.T) {
	names := BuiltinPresets()
	if len(names) == 0 {
		t.Fatal("没有内置预设")
	}
	for _, n := range names {
		c, err := LoadBuiltinPreset(n)
		if err != nil {
			t.Fatalf("%s 解析失败: %v", n, err)
		}
		if len(c.RemoteInf) == 0 {
			t.Fatalf("%s 没有设备", n)
		}
		t.Logf("%s: %d 台设备, %d 条操作", n, len(c.RemoteInf), len(c.OperationInf))
	}
}

// 载入只含设备清单的预设，不能清空已配置的操作。
func TestLoadDeviceOnlyPresetKeepsOps(t *testing.T) {
	s := NewGUIState()
	s.AppendOp(OperationInf{Name: "保留我", Type: OpCommand, CommandStr: "date"})
	before := len(s.Ops())

	c, err := LoadBuiltinPreset(BuiltinPresets()[0])
	if err != nil {
		t.Fatal(err)
	}
	s.LoadConfig(c)

	if len(s.Ops()) != before {
		t.Fatalf("载入设备清单后操作数从 %d 变成 %d（不应被清空）", before, len(s.Ops()))
	}
	if s.DeviceCount() != len(c.RemoteInf) {
		t.Fatalf("设备数 = %d, 期望 %d", s.DeviceCount(), len(c.RemoteInf))
	}
}

// 含 operationInf 的完整配置应整体替换（包括操作）。
func TestLoadFullConfigReplacesOps(t *testing.T) {
	s := NewGUIState()
	s.AppendOp(OperationInf{Name: "旧操作", Type: OpCommand, CommandStr: "date"})
	c := &Config{
		RemoteInf:    []RemoteInf{{IP: "10.1.1.1", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{{Name: "新操作", Type: OpCommand, CommandStr: "ls"}},
	}
	s.LoadConfig(c)
	ops := s.Ops()
	if len(ops) != 1 || ops[0].Inf.Name != "新操作" {
		t.Fatalf("完整配置应替换操作表, 实际: %+v", ops)
	}
}
