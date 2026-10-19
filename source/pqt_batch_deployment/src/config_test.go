package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// 旧版内置预设文件的真实内容（resources/batchConf/inSE6conf.json 片段）。
// 新版必须能原样读取，不得要求用户迁移。
const legacyJSON = `{
    "remoteInf": [
        {"IP": "172.16.140.11", "Password": "linaro", "Port": 22, "Username": "linaro"},
        {"IP": "172.16.140.12", "Password": "linaro", "Port": 22, "Username": "linaro"}
    ],
    "operationInf": [
        {"name": "检查时间", "type": 0, "commandStr": "date",
         "checkSuccessStr": "", "checkErrorStr": "",
         "transferFileSourcePath": "", "transferFileDestinationPath": "", "checkFile": 0}
    ]
}`

func TestLoadLegacyJSON(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "legacy.json")
	if err := os.WriteFile(p, []byte(legacyJSON), 0o644); err != nil {
		t.Fatal(err)
	}
	c, err := LoadConfig(p)
	if err != nil {
		t.Fatalf("读取旧格式配置失败: %v", err)
	}
	if len(c.RemoteInf) != 2 {
		t.Fatalf("设备数 = %d, 期望 2", len(c.RemoteInf))
	}
	if c.RemoteInf[0].IP != "172.16.140.11" || c.RemoteInf[0].Port != 22 {
		t.Fatalf("设备解析错误: %+v", c.RemoteInf[0])
	}
	if len(c.OperationInf) != 1 || c.OperationInf[0].CommandStr != "date" {
		t.Fatalf("操作解析错误: %+v", c.OperationInf)
	}
	if c.OperationInf[0].TypeName() != "下发命令" {
		t.Fatalf("类型名 = %q", c.OperationInf[0].TypeName())
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "rt.json")
	orig := &Config{
		RemoteInf: []RemoteInf{{IP: "10.0.0.1", Port: 22, Username: "u", Password: "p"}},
		OperationInf: []OperationInf{{
			Name: "cmd", Type: OpCommand, CommandStr: "date", CheckFile: CheckMD5,
		}},
	}
	if err := SaveConfig(p, orig); err != nil {
		t.Fatal(err)
	}
	got, err := LoadConfig(p)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.RemoteInf) != 1 || got.RemoteInf[0].IP != "10.0.0.1" {
		t.Fatalf("round-trip 设备丢失: %+v", got.RemoteInf)
	}
	if len(got.OperationInf) != 1 || got.OperationInf[0].CommandStr != "date" {
		t.Fatalf("round-trip 操作丢失: %+v", got.OperationInf)
	}
}

// 写出的 JSON 字段名必须与旧版完全一致（大写 IP/Port/Username/Password）。
func TestSaveUsesLegacyFieldNames(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "f.json")
	if err := SaveConfig(p, &Config{
		RemoteInf: []RemoteInf{{IP: "1.2.3.4", Port: 22, Username: "u", Password: "p"}},
	}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatal(err)
	}
	arr, ok := raw["remoteInf"].([]any)
	if !ok || len(arr) != 1 {
		t.Fatalf("remoteInf 结构错误: %s", data)
	}
	dev := arr[0].(map[string]any)
	for _, k := range []string{"IP", "Port", "Username", "Password"} {
		if _, ok := dev[k]; !ok {
			t.Fatalf("缺少旧版字段 %q，实际: %v", k, dev)
		}
	}
	for _, k := range []string{"ip", "port", "username", "password"} {
		if _, ok := dev[k]; ok {
			t.Fatalf("出现了新版小写字段 %q，破坏兼容", k)
		}
	}
}

// 旧版在 remoteInf 为空数组时会走到空指针崩溃（已复现 SIGSEGV）。
// 新版必须返回明确错误。
func TestValidateRejectsEmptyRemotes(t *testing.T) {
	c := &Config{
		RemoteInf:    []RemoteInf{},
		OperationInf: []OperationInf{{Name: "a", Type: OpCommand, CommandStr: "date"}},
	}
	if err := c.Validate(); err == nil {
		t.Fatal("remoteInf 为空时 Validate 应报错")
	}
}

func TestValidateRejectsEmptyOperations(t *testing.T) {
	c := &Config{
		RemoteInf:    []RemoteInf{{IP: "1.2.3.4", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{},
	}
	if err := c.Validate(); err == nil {
		t.Fatal("operationInf 为空时 Validate 应报错")
	}
}

func TestValidateRejectsBadPort(t *testing.T) {
	for _, port := range []int{0, -1, 70000} {
		c := &Config{
			RemoteInf:    []RemoteInf{{IP: "1.2.3.4", Port: port, Username: "u"}},
			OperationInf: []OperationInf{{Name: "a", Type: OpCommand, CommandStr: "date"}},
		}
		if err := c.Validate(); err == nil {
			t.Fatalf("端口 %d 应被拒绝", port)
		}
	}
}

// 不完整的操作应被跳过而不是崩溃或执行空命令。
func TestIncompleteOperationSkipped(t *testing.T) {
	c := &Config{
		RemoteInf: []RemoteInf{{IP: "1.2.3.4", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{
			{Name: "good", Type: OpCommand, CommandStr: "date"},
			{Name: "bad-no-command", Type: OpCommand, CommandStr: "   "},
			{Name: "bad-no-path", Type: OpUpFile, TransferFileSourcePath: ""},
			{Name: "", Type: OpCommand, CommandStr: "ls"},
		},
	}
	got := c.CompleteOperations()
	if len(got) != 1 || got[0].Name != "good" {
		t.Fatalf("应只保留 1 条完整操作，实际: %+v", got)
	}
}

func TestOperationTypeNames(t *testing.T) {
	cases := map[int]string{
		OpCommand:  "下发命令",
		OpUpFile:   "上传文件",
		OpDownFile: "下载文件",
	}
	for typ, want := range cases {
		if got := (OperationInf{Type: typ}).TypeName(); got != want {
			t.Errorf("type %d 名称 = %q, 期望 %q", typ, got, want)
		}
	}
}

func TestLoadConfigMissingFile(t *testing.T) {
	if _, err := LoadConfig(filepath.Join(t.TempDir(), "nope.json")); err == nil {
		t.Fatal("文件不存在时应报错")
	}
}

func TestLoadConfigMalformed(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "bad.json")
	if err := os.WriteFile(p, []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfig(p); err == nil {
		t.Fatal("非法 JSON 应报错")
	}
}

// GUI 与 CLI 必须使用同一套校验语义：不完整的操作是"跳过"，不是"配置无效"。
// 旧版两端口径不一致（GUI 放过、CLI 直接报错），同一份配置行为不同。
func TestValidateAllowsIncompleteOpsAsLongAsOneComplete(t *testing.T) {
	c := &Config{
		RemoteInf: []RemoteInf{{IP: "1.2.3.4", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{
			{Name: "good", Type: OpCommand, CommandStr: "date"},
			{Name: "incomplete", Type: OpCommand, CommandStr: ""},
		},
	}
	if err := c.Validate(); err != nil {
		t.Fatalf("有不完整操作但有完整操作时应可执行, got %v", err)
	}

	inc := c.IncompleteOperations()
	if len(inc) != 1 {
		t.Fatalf("不完整操作数 = %d, 期望 1", len(inc))
	}
	if _, ok := inc[1]; !ok {
		t.Fatalf("应标记下标 1 为不完整, got %v", inc)
	}
	if !strings.Contains(inc[1].Error(), "命令为空") {
		t.Fatalf("原因应说明缺什么, got %v", inc[1])
	}
}

// 全是空操作时不可执行（否则会"成功执行 0 条操作"）。
func TestValidateRejectsAllIncomplete(t *testing.T) {
	c := &Config{
		RemoteInf:    []RemoteInf{{IP: "1.2.3.4", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{{Name: "x", Type: OpCommand, CommandStr: "  "}},
	}
	if err := c.Validate(); err == nil {
		t.Fatal("全部操作不完整时应报错")
	}
}

// 设备校验独立可用：GUI 需要先单独校验设备再提示操作问题。
func TestValidateDevicesIndependent(t *testing.T) {
	c := &Config{
		RemoteInf:    []RemoteInf{{IP: "", Port: 22, Username: "u"}},
		OperationInf: []OperationInf{{Name: "x", Type: OpCommand, CommandStr: "date"}},
	}
	if err := c.ValidateDevices(); err == nil {
		t.Fatal("空 IP 应被拒绝")
	}
	if err := c.Validate(); err == nil {
		t.Fatal("整体校验也应失败")
	}
}
