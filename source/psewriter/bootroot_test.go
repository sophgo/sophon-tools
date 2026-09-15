// 刷机包根目录自动定位 单测 (MYS-1062 十五轮, Linux 可跑)
package main

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"
)

// probeZip 打一个 zip 并探测 (返回探测结果)
func probeZip(t *testing.T, files []fakeFile, withDirs bool) *Archive {
	t.Helper()
	zp := filepath.Join(t.TempDir(), "pkg.zip")
	zipFiles(t, zp, files, withDirs)
	a, err := ProbeArchive(zp, nil, nil)
	if err != nil {
		t.Fatalf("探测失败: %v", err)
	}
	return a
}

func names(entries []ArchiveEntry) []string {
	out := make([]string, 0, len(entries))
	for _, e := range entries {
		out = append(out, e.Name)
	}
	return out
}

func has(entries []ArchiveEntry, name string) bool {
	for _, e := range entries {
		if e.Name == name {
			return true
		}
	}
	return false
}

// 现场最常见的形态: 压缩包里多套了一层目录, 刷机包在里面
func TestBootRootStripsWrapperDir(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"sdbootrecoveryfiles/boot.scr", []byte("boot\n")},
		{"sdbootrecoveryfiles/fip.bin", bytes.Repeat([]byte{0x5A}, 1024)},
		{"sdbootrecoveryfiles/sdbootrecovery.itb", []byte("itb")},
		{"sdbootrecoveryfiles/recovery-ui/run-ui.sh", []byte("#!/bin/sh\n")},
	}, true)

	if !a.BootRoot.Stripped || a.BootRoot.Prefix != "sdbootrecoveryfiles" {
		t.Fatalf("应剥掉 sdbootrecoveryfiles/ 这层, 得 %+v", a.BootRoot)
	}
	// 关键: fip.bin / boot.scr 必须落到卡根目录
	for _, want := range []string{"boot.scr", "fip.bin", "sdbootrecovery.itb", "recovery-ui/run-ui.sh"} {
		if !has(a.Files, want) {
			t.Errorf("卡根目录应有 %s, 实际文件: %v", want, names(a.Files))
		}
	}
	for _, f := range a.Files {
		if strings.HasPrefix(f.Name, "sdbootrecoveryfiles/") {
			t.Errorf("不应再有带前缀的路径: %s", f.Name)
		}
	}
	// 目录条目也要跟着剥
	if !has(a.Dirs, "recovery-ui") {
		t.Errorf("目录 recovery-ui 应保留, 实际: %v", names(a.Dirs))
	}
	if a.BootRoot.Outsiders != 0 {
		t.Errorf("没有包外文件, Outsiders 应为 0, 得 %d", a.BootRoot.Outsiders)
	}
}

// 特征文件本来就在根目录 → 一个字节都不动
func TestBootRootLeavesRootLevelPackageAlone(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"boot.scr", []byte("boot\n")},
		{"fip.bin", []byte("fip")},
		{"recovery-ui/run-ui.sh", []byte("#!/bin/sh\n")},
	}, false)

	if a.BootRoot.Stripped || a.BootRoot.Prefix != "" {
		t.Fatalf("特征文件已在根目录时不应做任何调整, 得 %+v", a.BootRoot)
	}
	if !has(a.Files, "boot.scr") || !has(a.Files, "fip.bin") {
		t.Errorf("文件应保持原样: %v", names(a.Files))
	}
	if len(a.BootRoot.Candidates) != 0 {
		t.Errorf("不应报歧义: %v", a.BootRoot.Candidates)
	}
}

// 嵌套但不在根: 选**最像**刷机包的那一层 (fip.bin 权重最高)
func TestBootRootNestedDeep(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"release/2026-09/se7/sdbootrecoveryfiles/boot.scr", []byte("boot\n")},
		{"release/2026-09/se7/sdbootrecoveryfiles/fip.bin", []byte("fip")},
		{"release/2026-09/se7/sdbootrecoveryfiles/recovery-ui/run-ui.sh", []byte("x")},
	}, false)

	if !a.BootRoot.Stripped || a.BootRoot.Prefix != "release/2026-09/se7/sdbootrecoveryfiles" {
		t.Fatalf("应剥到最内层刷机包目录, 得 %+v", a.BootRoot)
	}
	if !has(a.Files, "fip.bin") || !has(a.Files, "boot.scr") {
		t.Errorf("文件应落到卡根目录: %v", names(a.Files))
	}
}

// 两个目录都像刷机包 → 不猜, 不调整, 但必须明确报出来
func TestBootRootReportsAmbiguity(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"se5/fip.bin", []byte("fip5")},
		{"se5/boot.scr", []byte("b5")},
		{"se7/fip.bin", []byte("fip7")},
		{"se7/boot.scr", []byte("b7")},
	}, false)

	if a.BootRoot.Stripped {
		t.Fatal("有歧义时不应擅自剥某一层")
	}
	if len(a.BootRoot.Candidates) != 2 {
		t.Fatalf("应报出 2 个候选, 得 %v", a.BootRoot.Candidates)
	}
	if !strings.Contains(a.BootRoot.Note, "se5") || !strings.Contains(a.BootRoot.Note, "se7") {
		t.Errorf("说明里应点名候选目录: %q", a.BootRoot.Note)
	}
	// 路径保持原样
	if !has(a.Files, "se5/fip.bin") || !has(a.Files, "se7/fip.bin") {
		t.Errorf("歧义时路径不应变动: %v", names(a.Files))
	}
}

// 没有特征文件 → 不动 (不能靠"只有一层目录"这种猜测)
func TestBootRootNoMarkers(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"data/a.txt", []byte("a")},
		{"data/b.txt", []byte("b")},
	}, false)

	if a.BootRoot.Stripped {
		t.Fatal("没有特征文件时不应剥离目录")
	}
	if !has(a.Files, "data/a.txt") {
		t.Errorf("路径应保持原样: %v", names(a.Files))
	}
}

// 包外文件保留原路径, 并如实计数
func TestBootRootKeepsOutsiders(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"sdbootrecoveryfiles/fip.bin", []byte("fip")},
		{"sdbootrecoveryfiles/boot.scr", []byte("b")},
		{"说明.txt", []byte("hi")},
	}, false)

	if !a.BootRoot.Stripped {
		t.Fatalf("应剥掉前缀, 得 %+v", a.BootRoot)
	}
	if !has(a.Files, "fip.bin") {
		t.Errorf("包内文件应落到根: %v", names(a.Files))
	}
	if !has(a.Files, "说明.txt") {
		t.Errorf("包外文件应保留原路径: %v", names(a.Files))
	}
	if a.BootRoot.Outsiders != 1 {
		t.Errorf("包外文件应计为 1, 得 %d", a.BootRoot.Outsiders)
	}
}

// 剥前缀导致重名 → 直接报错, 不能一个覆盖另一个
func TestBootRootRejectsCollision(t *testing.T) {
	zp := filepath.Join(t.TempDir(), "pkg.zip")
	zipFiles(t, zp, []fakeFile{
		{"pkg/fip.bin", []byte("inner")},
		{"pkg/boot.scr", []byte("inner-boot")},
		{"boot.scr", []byte("outer-boot")}, // 剥前缀后与 pkg/boot.scr 撞名
	}, false)
	_, err := ProbeArchive(zp, nil, nil)
	if err == nil {
		t.Fatal("剥前缀后重名应报错")
	}
	if !strings.Contains(err.Error(), "重名") {
		t.Errorf("错误信息应说明重名: %v", err)
	}
}

// 端到端: 多套一层目录的压缩包建出来的卡, 卡根目录必须就是刷机包内容
func TestCardRootHasBootFilesAfterStrip(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"sdbootrecoveryfiles/boot.scr", append(append([]byte("boot-script\n"), marker...), '\n')},
		{"sdbootrecoveryfiles/fip.bin", bytes.Repeat([]byte{0x5A}, 200000)},
		{"sdbootrecoveryfiles/recovery-ui/run-ui.sh", []byte("#!/bin/sh\n")},
	}, true)

	if !a.BootRoot.Stripped {
		t.Fatalf("应剥掉前缀, 得 %+v", a.BootRoot)
	}
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	defer dev.Close()
	if _, err := BuildCardOnDevice(dev, a, plan, nil); err != nil {
		t.Fatalf("建卡失败: %v", err)
	}
	// 从卡上按"根目录路径"找得到 fip.bin / boot.scr, 才算真的落到了卡根目录
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !fv.OK() {
		t.Fatalf("文件级校验应通过: %s / %s", fv.Summary(), fv.FirstError())
	}
	for _, want := range []string{"fip.bin", "boot.scr", "recovery-ui/run-ui.sh"} {
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

// 界面/命令行说明行必须能反映出"剥了哪一层"或"有歧义"
func TestBootRootLines(t *testing.T) {
	a := probeZip(t, []fakeFile{
		{"sdbootrecoveryfiles/fip.bin", []byte("fip")},
		{"sdbootrecoveryfiles/boot.scr", []byte("b")},
	}, false)
	lines := a.BootRootLines()
	if len(lines) == 0 {
		t.Fatal("应有说明行")
	}
	if !strings.Contains(lines[0][1], "sdbootrecoveryfiles") {
		t.Errorf("说明行应点名目录: %v", lines)
	}
	if !strings.Contains(lines[0][0], "刷机包") {
		t.Errorf("说明行标签应提到刷机包: %v", lines)
	}
}
