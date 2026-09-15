// 目录数据源 单测 (MYS-1062 十八轮④, Linux 可跑)
package main

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
)

// writeTree 在临时目录里铺一棵树
func writeTree(t *testing.T, files map[string][]byte) string {
	t.Helper()
	dir := t.TempDir()
	for name, data := range files {
		full := filepath.Join(dir, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func dirEntryNames(entries []ArchiveEntry) []string {
	out := make([]string, 0, len(entries))
	for _, e := range entries {
		out = append(out, e.Name)
	}
	return out
}

// 目录能当来源: 枚举出与压缩包同构的文件/目录清单
func TestProbeDirEnumerates(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"boot.scr":                  []byte("boot\n"),
		"fip.bin":                   bytes.Repeat([]byte{0x5A}, 4096),
		"sdbootrecovery.itb":        []byte("itb"),
		"recovery-ui/run-ui.sh":     []byte("#!/bin/sh\n"),
		"recovery-ui/data/font.bin": []byte("font"),
	})
	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a.Format != dirFormat {
		t.Errorf("格式应为 %q, 得 %q", dirFormat, a.Format)
	}
	if a.Mode != ModeFilePackage {
		t.Errorf("目录源默认应为文件包模式, 得 %v", a.Mode)
	}
	for _, want := range []string{"boot.scr", "fip.bin", "sdbootrecovery.itb",
		"recovery-ui/run-ui.sh", "recovery-ui/data/font.bin"} {
		if !has(a.Files, want) {
			t.Errorf("应枚举到文件 %s, 实得 %v", want, dirEntryNames(a.Files))
		}
	}
	for _, want := range []string{"recovery-ui", "recovery-ui/data"} {
		if !has(a.Dirs, want) {
			t.Errorf("应枚举到目录 %s, 实得 %v", want, dirEntryNames(a.Dirs))
		}
	}
	if a.Skipped != 0 {
		t.Errorf("没有特殊文件, 跳过数应为 0, 得 %d", a.Skipped)
	}
	// 内容大小如实统计 (供分区规划)
	var want int64
	for _, f := range a.Files {
		want += f.Size
	}
	if a.SrcFileSize != want {
		t.Errorf("内容大小 %d 与逐文件合计 %d 不符", a.SrcFileSize, want)
	}
}

// 目录里的"刷机包多套一层"也要被剥掉 —— 与压缩包同一条规则
func TestProbeDirStripsWrapperDir(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"se7/sdbootrecoveryfiles/boot.scr":         []byte("boot\n"),
		"se7/sdbootrecoveryfiles/fip.bin":          []byte("fip"),
		"se7/sdbootrecoveryfiles/recovery-ui/a.sh": []byte("x"),
	})
	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !a.BootRoot.Stripped || a.BootRoot.Prefix != "se7/sdbootrecoveryfiles" {
		t.Fatalf("应剥到最内层刷机包目录, 得 %+v", a.BootRoot)
	}
	if !has(a.Files, "fip.bin") || !has(a.Files, "boot.scr") {
		t.Errorf("文件应落到卡根: %v", dirEntryNames(a.Files))
	}
	if !has(a.Dirs, "recovery-ui") {
		t.Errorf("目录也要跟着剥: %v", dirEntryNames(a.Dirs))
	}
}

// 特征文件已在目录根 → 一个字节都不动
func TestProbeDirRootLevelUntouched(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"boot.scr": []byte("boot\n"),
		"fip.bin":  []byte("fip"),
	})
	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a.BootRoot.Stripped {
		t.Fatalf("特征文件已在根时不应调整, 得 %+v", a.BootRoot)
	}
}

// 软链按目标文件处理; FAT32 放不下的 (断链/命名管道) 跳过并计数
func TestProbeDirSymlinkAndSkip(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("软链/命名管道语义在 Windows 上不同")
	}
	dir := writeTree(t, map[string][]byte{
		"real/big.bmodel": bytes.Repeat([]byte{1}, 1234),
		"boot.scr":        []byte("b"),
	})
	if err := os.Symlink(filepath.Join(dir, "real", "big.bmodel"), filepath.Join(dir, "link.bmodel")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(dir, "nope-missing"), filepath.Join(dir, "broken.lnk")); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(dir, "pipe"), 0o644); err != nil {
		t.Skipf("造不了命名管道: %v", err)
	}

	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !has(a.Files, "link.bmodel") {
		t.Errorf("软链应按目标文件收进来: %v", dirEntryNames(a.Files))
	}
	for _, f := range a.Files {
		if f.Name == "link.bmodel" && f.Size != 1234 {
			t.Errorf("软链大小应取目标大小 1234, 得 %d", f.Size)
		}
	}
	if has(a.Files, "broken.lnk") || has(a.Files, "pipe") {
		t.Errorf("断链/管道不该被当成文件: %v", dirEntryNames(a.Files))
	}
	if a.Skipped != 2 {
		t.Errorf("应跳过 2 个条目 (断链 + 管道), 得 %d", a.Skipped)
	}
}

// 目录里只有一个磁盘镜像 → 仍按整盘写入 (与压缩包一致的自动判定)
func TestProbeDirSingleImageIsRawDisk(t *testing.T) {
	payload := bytes.Repeat([]byte{0x7E}, 8192)
	dir := writeTree(t, map[string][]byte{"se7-backup.img": payload})

	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a.Mode != ModeRawDisk {
		t.Fatalf("单个镜像文件应判为整盘模式, 得 %v", a.Mode)
	}
	if a.Image != "se7-backup.img" || a.RawSz != int64(len(payload)) {
		t.Fatalf("镜像条目/大小不对: image=%q rawSz=%d", a.Image, a.RawSz)
	}
	rc, err := a.ImageOpenFunc()()
	if err != nil {
		t.Fatal(err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, payload) {
		t.Error("从目录源读出的镜像内容不对")
	}
}

// 端到端: 目录 → 建卡 → 卡上逐文件校验 (证明写卡路径真的认目录源)
func TestBuildCardFromDirSource(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"boot.scr":              append(append([]byte("boot-script\n"), marker...), '\n'),
		"fip.bin":               bytes.Repeat([]byte{0x5A}, 200000),
		"recovery-ui/run-ui.sh": []byte("#!/bin/sh\n"),
		"recovery-ui/中文名.bin":   []byte("cjk-name"),
	})
	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	defer dev.Close()
	if _, err := BuildCardOnDevice(dev, a, plan, nil); err != nil {
		t.Fatalf("用目录源建卡失败: %v", err)
	}
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !fv.OK() {
		t.Fatalf("卡上文件级校验应通过: %s / %s", fv.Summary(), fv.FirstError())
	}
	for _, want := range []string{"fip.bin", "boot.scr", "recovery-ui/run-ui.sh", "recovery-ui/中文名.bin"} {
		found := false
		for _, f := range fv.Files {
			if f.Name == want {
				found = true
			}
		}
		if !found {
			t.Errorf("卡上应能按根目录路径找到 %s, 实得 %v", want, func() []string {
				var n []string
				for _, f := range fv.Files {
					n = append(n, f.Name)
				}
				return n
			}())
		}
	}
}

// 目录源 + 多套一层刷机包目录: 剥掉前缀后仍必须按**磁盘上的原始路径**读内容。
// 回归: 迭代器拿着剥过的卡上目标名去 <源目录>/ 下找文件 → ENOENT。
func TestBuildCardFromNestedDirSource(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"sdbootrecoveryfiles/boot.scr":              append(append([]byte("boot-script\n"), marker...), '\n'),
		"sdbootrecoveryfiles/fip.bin":               bytes.Repeat([]byte{0x5A}, 200000),
		"sdbootrecoveryfiles/recovery-ui/run-ui.sh": []byte("#!/bin/sh\n"),
		"说明.txt": []byte("读我"),
	})
	a, err := ProbeDir(dir, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !a.BootRoot.Stripped || a.BootRoot.Prefix != "sdbootrecoveryfiles" {
		t.Fatalf("应剥掉 sdbootrecoveryfiles/ 这层, 得 %+v", a.BootRoot)
	}
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	defer dev.Close()
	if _, err := BuildCardOnDevice(dev, a, plan, nil); err != nil {
		t.Fatalf("用嵌套目录源建卡失败: %v", err)
	}
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !fv.OK() {
		t.Fatalf("卡上文件级校验应通过: %s / %s", fv.Summary(), fv.FirstError())
	}
	for _, want := range []string{"fip.bin", "boot.scr", "recovery-ui/run-ui.sh", "说明.txt"} {
		found := false
		for _, f := range fv.Files {
			if f.Name == want {
				found = true
			}
		}
		if !found {
			t.Errorf("卡上应能按根目录路径找到 %s, 实得 %v", want, func() []string {
				var n []string
				for _, f := range fv.Files {
					n = append(n, f.Name)
				}
				return n
			}())
		}
	}
}

// PrepareSource 认目录入口 (GUI/CLI 都走这里)
func TestPrepareSourceAcceptsDir(t *testing.T) {
	dir := writeTree(t, map[string][]byte{
		"boot.scr": []byte("b"),
		"fip.bin":  []byte("f"),
	})
	prep, err := PrepareSource(dir, nil, 0, false, 0, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !prep.IsCard() {
		t.Fatal("目录源应为文件包(建卡)模式")
	}
	if prep.Src != nil {
		t.Error("目录源不应产生整盘镜像源")
	}
	if prep.TotalSize() <= 0 {
		t.Error("应算出卡镜像大小")
	}
	// 说明文字要标明是目录
	txt := SourceInfoText(prep.Archive, prep.Plan)
	if !strings.Contains(txt, "目录：") {
		t.Errorf("说明文字应标出目录来源: %q", txt)
	}

	// 空目录给出明确错误 (而不是"归档内没有任何文件")
	empty := t.TempDir()
	if _, err := PrepareSource(empty, nil, 0, false, 0, "", nil); err == nil {
		t.Error("空目录应报错")
	} else if !strings.Contains(err.Error(), "目录内没有任何文件") {
		t.Errorf("错误文案应针对目录: %v", err)
	}
}

// CLI 的 --dir 与 --image 是同一个入口 (避免两条路径各自演化)
func TestDirSourceFormatLabel(t *testing.T) {
	if got := formatLabel(dirFormat); got != "目录" {
		t.Errorf("formatLabel(dir) = %q, 期望 目录", got)
	}
}
