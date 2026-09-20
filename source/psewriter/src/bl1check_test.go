// 卡根短名 / BL1 可读性 回归测试 (MYS-1062 二十三轮, Linux 可跑)
//
// 现场事故: 用本工具写的卡, BL1 上电打印 "fip not found on SD" 后回退 SPI flash。
// 卡本身没问题 (f_mount 成功), 坏在 **fip.bin 的 8.3 短名被写成了 "FIP~1.BIN"** ——
// BM1684X 的 BL1 用 FatFs 且 FF_USE_LFN=0, 只按短名 "FIP     BIN" 找, 于是找不到。
//
// 这两个测试分别守住两头:
//  1. 本工具写出来的卡, 关键短名必须与 Windows/Linux 工具一致 (fip.bin → FIP.BIN)
//  2. 检查器本身必须真的会报错 (对退化的卡报错), 不能是个恒真的摆设
package main

import (
	"strings"
	"testing"
)

// 1) 工具写出来的卡: 关键短名正确, BL1 能认
func TestCardBL1ShortNames(t *testing.T) {
	_, _, dev, _ := buildCardOnFakeDevice(t)

	chk, err := CheckCardBL1(dev)
	if err != nil {
		t.Fatalf("核对卡根短名失败: %v", err)
	}
	got := map[string]string{} // 长名 → 短名
	for _, e := range chk.Entries {
		name := e.DisplayName()
		got[name] = e.Short
		if e.Long != "" && e.Long != name {
			got[e.Long] = e.Short
		}
	}
	// fip.bin 必须落在标准的 FIP     BIN 上 —— BL1 认的就是这一串
	if s := got["fip.bin"]; s != "FIP     BIN" {
		t.Errorf("fip.bin 的短名应为 %q, 实得 %q (BL1 只认短名)", "FIP     BIN", s)
	}
	if s := got["boot.scr"]; s != "BOOT    SCR" {
		t.Errorf("boot.scr 的短名应为 %q, 实得 %q", "BOOT    SCR", s)
	}
	if !chk.OK() {
		t.Errorf("BL1 可读性检查未通过: %s", chk.Note())
	}
	if len(chk.Degraded) > 0 {
		t.Errorf("有本可无损的 8.3 名被写成了 ~N: %v", chk.Degraded)
	}
	// 长名要保留 (Windows/Linux 挂载时看到的名字不变)
	for _, want := range []string{"fip.bin", "boot.scr"} {
		if _, ok := got[want]; !ok {
			t.Errorf("卡上找不到长名 %q (LFN 条目丢了)", want)
		}
	}
}

// 2) 检查器必须真的能报错: 把卡上短名改成修复前的 "FIP~1" 退化形态
func TestBL1CheckCatchesDegradedShortName(t *testing.T) {
	_, _, dev, _ := buildCardOnFakeDevice(t)

	chk, err := CheckCardBL1(dev)
	if err != nil {
		t.Fatal(err)
	}
	// 在根目录簇里找到 FIP.BIN 那条目录项, 把短名改成 "FIP~1   "
	root := make([]byte, 4096)
	if _, err := dev.ReadAt(root, chk.RootOffset); err != nil {
		t.Fatal(err)
	}
	fixed := false
	for off := 0; off+32 <= len(root); off += 32 {
		if root[off] == 0x00 {
			break
		}
		if root[off] == 0xE5 || root[off+11]&0x0F == 0x0F {
			continue
		}
		if string(root[off:off+8]) == "FIP     " && string(root[off+8:off+11]) == "BIN" {
			copy(root[off:off+8], "FIP~1   ")
			if _, err := dev.WriteAt(root[off:off+32], chk.RootOffset+int64(off)); err != nil {
				t.Fatal(err)
			}
			fixed = true
			break
		}
	}
	if !fixed {
		t.Fatal("卡根目录里没找到 FIP.BIN 条目, 测试前提不成立")
	}

	chk2, err := CheckCardBL1(dev)
	if err != nil {
		t.Fatal(err)
	}
	if chk2.OK() {
		t.Fatal("短名已被改成 FIP~1, 检查器却没报错 (恒真检查等于没有)")
	}
	if !strings.Contains(chk2.Note(), "fip not found on SD") {
		t.Errorf("报错文案应点明后果, 实得: %s", chk2.Note())
	}
	// 写后校验也要因此失败 (而不是只写进日志)
	fv, err := VerifyCardFiles(dev, mustTestPkg(t), 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if fv.OK() {
		t.Fatal("卡上短名已坏, 文件级校验却报通过")
	}
	if !strings.Contains(fv.FirstError(), "FIP.BIN") {
		t.Errorf("校验失败原因应指向短名, 实得: %s", fv.FirstError())
	}
	if !strings.Contains(fv.Summary(), "BL1") {
		t.Errorf("摘要里应带 BL1 结论, 实得: %s", fv.Summary())
	}
}

func mustTestPkg(t *testing.T) *Archive {
	t.Helper()
	a, _ := buildTestPkg(t)
	return a
}

func TestLossless83(t *testing.T) {
	cases := []struct {
		name      string
		stem, ext string
		ok        bool
	}{
		{"fip.bin", "FIP", "BIN", true},
		{"boot.scr", "BOOT", "SCR", true},
		{"ai", "AI", "", true},
		{"sdbootrecovery.itb", "", "", false}, // stem 超 8
		{"README-卡内容.txt", "", "", false},     // 非 ASCII
		{"a b.txt", "", "", false},            // 含空格
		{"noext_but_long_name", "", "", false},
	}
	for _, c := range cases {
		stem, ext, ok := lossless83(c.name)
		if ok != c.ok || (ok && (stem != c.stem || ext != c.ext)) {
			t.Errorf("lossless83(%q) = (%q,%q,%v), 期望 (%q,%q,%v)", c.name, stem, ext, ok, c.stem, c.ext, c.ok)
		}
	}
}

func TestShortToDotted(t *testing.T) {
	cases := map[string]string{
		"FIP     BIN": "FIP.BIN",
		"BOOT    SCR": "BOOT.SCR",
		"AI         ": "AI",
		"SDBOOT~1ITB": "SDBOOT~1.ITB",
	}
	for in, want := range cases {
		if got := shortToDotted(in); got != want {
			t.Errorf("shortToDotted(%q) = %q, 期望 %q", in, got, want)
		}
	}
}
