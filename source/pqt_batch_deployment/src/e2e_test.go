package main

// 走真实 SSH/SFTP 协议的功能测试（对端是本仓库的 testSSHServer）。
//
// 这些用例覆盖此前完全没有自动化覆盖的路径：命令执行与关键字判定、
// 上传 + MD5 校验、下载 + MD5 校验、以及传输超时。

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func execAgainst(t *testing.T, s *testSSHServer, root string, ops []OperationInf, e *Executor) []DeviceResult {
	t.Helper()
	cfg := &Config{
		RemoteInf:    []RemoteInf{{IP: "127.0.0.1", Port: s.Port(), Username: "u", Password: "p"}},
		OperationInf: ops,
	}
	if e == nil {
		e = &Executor{}
	}
	e.RootDir = root
	e.MaxParallel = 1
	e.DialTimeout = 3 * time.Second
	e.CommandTimeout = 5 * time.Second
	e.TransferTimeout = 5 * time.Second
	return e.Run(t.Context(), cfg)
}

// 命令下发：真实 SSH 会话 + 成功关键字。
func TestSSHCommandSuccessKeyword(t *testing.T) {
	s := newTestSSHServer(t)
	s.commands["echo ready"] = "ready\n"

	res := execAgainst(t, s, t.TempDir(), []OperationInf{{
		Name: "c", Type: OpCommand, CommandStr: "echo ready", CheckSuccessStr: "ready",
	}}, nil)

	if !res[0].OK || res[0].Err != nil {
		t.Fatalf("应成功, got err=%v log=%s", res[0].Err, res[0].Log.String())
	}
	if !strings.Contains(res[0].Log.String(), "ready") {
		t.Fatalf("日志应包含命令输出, got %q", res[0].Log.String())
	}
}

// 命令下发：未命中成功关键字必须判失败（旧版这个分支判断错了字段）。
func TestSSHCommandSuccessKeywordMissFails(t *testing.T) {
	s := newTestSSHServer(t)
	s.commands["echo other"] = "other\n"

	res := execAgainst(t, s, t.TempDir(), []OperationInf{{
		Name: "c", Type: OpCommand, CommandStr: "echo other", CheckSuccessStr: "ready",
	}}, nil)

	if res[0].OK {
		t.Fatal("未命中成功关键字应判失败")
	}
	if !strings.Contains(res[0].Err.Error(), "未命中成功关键字") {
		t.Fatalf("错误信息不符: %v", res[0].Err)
	}
}

// 命令下发：命中失败关键字必须判失败。
func TestSSHCommandErrorKeywordFails(t *testing.T) {
	s := newTestSSHServer(t)
	s.commands["boom"] = "PANIC: exploded\n"

	res := execAgainst(t, s, t.TempDir(), []OperationInf{{
		Name: "c", Type: OpCommand, CommandStr: "boom", CheckErrorStr: "panic",
	}}, nil)

	if res[0].OK {
		t.Fatal("命中失败关键字应判失败")
	}
	if !strings.Contains(res[0].Err.Error(), "失败关键字") {
		t.Fatalf("错误信息不符: %v", res[0].Err)
	}
}

// 上传：真实 SFTP 写远端 + MD5 校验。
func TestSSHUploadAndMD5Verify(t *testing.T) {
	s := newTestSSHServer(t)
	root := t.TempDir()
	content := bytes.Repeat([]byte("sophon-upload-"), 4096) // ~56KB，多轮读写
	if err := os.WriteFile(filepath.Join(root, "payload.bin"), content, 0o644); err != nil {
		t.Fatal(err)
	}

	res := execAgainst(t, s, root, []OperationInf{{
		Name:                        "up",
		Type:                        OpUpFile,
		TransferFileSourcePath:      "payload.bin", // 相对根目录
		TransferFileDestinationPath: "/tmp/payload.bin",
		CheckFile:                   CheckMD5,
	}}, nil)

	if !res[0].OK {
		t.Fatalf("上传应成功, err=%v log=%s", res[0].Err, res[0].Log.String())
	}
	if got := s.File("/tmp/payload.bin"); !bytes.Equal(got, content) {
		t.Fatalf("远端内容不一致: got %d 字节, want %d", len(got), len(content))
	}
	if !strings.Contains(res[0].Log.String(), "校验通过") {
		t.Fatalf("日志应包含校验通过, got %q", res[0].Log.String())
	}
}

// 上传到以 / 结尾的目标时，应拼上本地文件名（与旧版一致）。
func TestSSHUploadToDirectoryJoinsBaseName(t *testing.T) {
	s := newTestSSHServer(t)
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "a.bin"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}

	res := execAgainst(t, s, root, []OperationInf{{
		Name: "up", Type: OpUpFile,
		TransferFileSourcePath:      "a.bin",
		TransferFileDestinationPath: "/tmp/dir/",
		CheckFile:                   CheckSize,
	}}, nil)

	if !res[0].OK {
		t.Fatalf("上传应成功, err=%v", res[0].Err)
	}
	if got := s.File("/tmp/dir/a.bin"); len(got) != 1 {
		t.Fatalf("目标路径未拼上文件名, 实际文件: %q", string(got))
	}
}

// 下载：真实 SFTP 读远端 + 落盘 + MD5 校验，文件名带设备标识。
func TestSSHDownloadAndMD5Verify(t *testing.T) {
	s := newTestSSHServer(t)
	content := bytes.Repeat([]byte("sophon-download-"), 4096)
	s.SetFile("/remote/data.bin", content)

	root := t.TempDir()
	res := execAgainst(t, s, root, []OperationInf{{
		Name: "down", Type: OpDownFile,
		TransferFileSourcePath:      "/remote/data.bin",
		TransferFileDestinationPath: "out", // 相对根目录
		CheckFile:                   CheckMD5,
	}}, nil)

	if !res[0].OK {
		t.Fatalf("下载应成功, err=%v log=%s", res[0].Err, res[0].Log.String())
	}

	entries, err := os.ReadDir(filepath.Join(root, "out"))
	if err != nil {
		t.Fatalf("下载目录不存在: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("下载目录应有 1 个文件, 实际 %d", len(entries))
	}
	name := entries[0].Name()
	// 旧版命名规则：<ip>_<port>_<时间戳>_<原名>
	if !strings.HasPrefix(name, "127.0.0.1_") || !strings.HasSuffix(name, "_data.bin") {
		t.Fatalf("文件名不符合命名规则: %s", name)
	}
	got, err := os.ReadFile(filepath.Join(root, "out", name))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, content) {
		t.Fatalf("下载内容不一致: got %d 字节, want %d", len(got), len(content))
	}
}

// 多操作顺序执行：任一失败即停止该设备（旧版同样是短路语义）。
func TestSSHStopsAtFirstFailedOperation(t *testing.T) {
	s := newTestSSHServer(t)
	s.commands["ok"] = "ok\n"
	s.commands["fail"] = "ok\n"

	res := execAgainst(t, s, t.TempDir(), []OperationInf{
		{Name: "first", Type: OpCommand, CommandStr: "ok"},
		{Name: "second", Type: OpCommand, CommandStr: "fail", CheckSuccessStr: "never"},
		{Name: "third", Type: OpCommand, CommandStr: "ok"},
	}, nil)

	if res[0].OK {
		t.Fatal("第二条失败后整体应为失败")
	}
	if !strings.Contains(res[0].Err.Error(), "second") {
		t.Fatalf("错误应指向第二条操作, got %v", res[0].Err)
	}
	if strings.Contains(res[0].Log.String(), "执行: third") {
		t.Fatal("第二条失败后不应继续执行第三条")
	}
}

// 传输卡死必须被超时打断——这是审阅指出的「transferTimeout 声明了但没用」。
func TestSFTPTransferHangIsInterruptedByTimeout(t *testing.T) {
	s := newTestSSHServer(t)
	s.SetHangSFTP(true)

	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "x.bin"), []byte("hello"), 0o644); err != nil {
		t.Fatal(err)
	}

	e := &Executor{}
	done := make(chan []DeviceResult, 1)
	go func() {
		done <- execAgainst(t, s, root, []OperationInf{{
			Name: "up", Type: OpUpFile,
			TransferFileSourcePath:      "x.bin",
			TransferFileDestinationPath: "/tmp/x.bin",
			CheckFile:                   CheckNone,
		}}, e)
	}()

	select {
	case res := <-done:
		if res[0].OK || res[0].Err == nil {
			t.Fatal("传输卡死应判失败")
		}
	case <-time.After(25 * time.Second):
		t.Fatal("传输卡死没有被超时打断：transferTimeout 仍未生效")
	}
}
