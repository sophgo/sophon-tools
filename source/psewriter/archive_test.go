// 归档识别 / 文件包 → FAT32 卡镜像 单测 (Linux 可跑)
package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/rand"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/diskfs/go-diskfs"
	"github.com/klauspost/compress/zstd"
	"github.com/ulikunitz/xz"
	"golang.org/x/text/encoding/simplifiedchinese"
)

// ---------- 构造测试归档 ----------

func writeRaw(t *testing.T, p string, size int) []byte {
	t.Helper()
	b := make([]byte, size)
	rand.Read(b)
	if err := os.WriteFile(p, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return b
}

func gzFile(t *testing.T, src, dst string) {
	t.Helper()
	in, err := os.Open(src)
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		t.Fatal(err)
	}
	defer out.Close()
	zw := gzip.NewWriter(out)
	io.Copy(zw, in)
	zw.Close()
}

func xzFile(t *testing.T, src, dst string) {
	t.Helper()
	in, _ := os.Open(src)
	defer in.Close()
	out, _ := os.Create(dst)
	defer out.Close()
	zw, err := xz.NewWriter(out)
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(zw, in)
	zw.Close()
}

func zstdFile(t *testing.T, src, dst string) {
	t.Helper()
	in, _ := os.Open(src)
	defer in.Close()
	out, _ := os.Create(dst)
	defer out.Close()
	zw, err := zstd.NewWriter(out)
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(zw, in)
	zw.Close()
}

type fakeFile struct {
	name string
	data []byte
}

func zipFiles(t *testing.T, dst string, files []fakeFile, withDirs bool) {
	t.Helper()
	f, err := os.Create(dst)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	zw := zip.NewWriter(f)
	if withDirs {
		for _, d := range []string{"recovery-ui/"} {
			if _, err := zw.Create(d); err != nil {
				t.Fatal(err)
			}
		}
	}
	for _, ff := range files {
		w, err := zw.Create(ff.name)
		if err != nil {
			t.Fatal(err)
		}
		w.Write(ff.data)
	}
	zw.Close()
}

func tarFiles(t *testing.T, dst string, files []fakeFile, compress string) {
	t.Helper()
	f, err := os.Create(dst)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var w io.Writer = f
	var closers []io.Closer
	switch compress {
	case "gz":
		zw := gzip.NewWriter(f)
		w, closers = zw, append(closers, zw)
	case "xz":
		xw, err := xz.NewWriter(f)
		if err != nil {
			t.Fatal(err)
		}
		w, closers = xw, append(closers, xw)
	}
	tw := tar.NewWriter(w)
	closers = append(closers, tw)
	for _, ff := range files {
		if err := tw.WriteHeader(&tar.Header{
			Name: ff.name, Mode: 0o644, Size: int64(len(ff.data)), Typeflag: tar.TypeReg,
		}); err != nil {
			t.Fatal(err)
		}
		tw.Write(ff.data)
	}
	for i := len(closers) - 1; i >= 0; i-- {
		closers[i].Close()
	}
}

// ---------- 格式识别 ----------

func TestDetectFormatByMagic(t *testing.T) {
	cases := []struct {
		name string
		head []byte
		want string
	}{
		{"gzip", []byte{0x1f, 0x8b, 0x08, 0x00}, "gz"},
		{"xz", []byte{0xfd, '7', 'z', 'X', 'Z', 0x00, 0x00}, "xz"},
		{"bzip2", []byte{'B', 'Z', 'h', '9'}, "bz2"},
		{"zstd", []byte{0x28, 0xb5, 0x2f, 0xfd, 0x00}, "zst"},
		{"zip", []byte{'P', 'K', 0x03, 0x04}, "zip"},
		{"7z", []byte{'7', 'z', 0xbc, 0xaf, 0x27, 0x1c}, "7z"},
		{"rar4", []byte{'R', 'a', 'r', '!', 0x1a, 0x07, 0x00}, "rar"},
		{"rar5", []byte{'R', 'a', 'r', '!', 0x1a, 0x07, 0x01, 0x00}, "rar"},
	}
	for _, c := range cases {
		if got := detectFormat(c.head); got != c.want {
			t.Errorf("%s: 识别为 %q, 期望 %q", c.name, got, c.want)
		}
	}
	// tar: ustar 魔数在偏移 257
	tarHead := make([]byte, 512)
	copy(tarHead[257:], "ustar")
	if got := detectFormat(tarHead); got != "tar" {
		t.Errorf("tar 识别为 %q", got)
	}
	// 认不出 → 裸镜像
	if got := detectFormat([]byte{0x00, 0x11, 0x22}); got != "img" {
		t.Errorf("未知格式应为 img, 得 %q", got)
	}
}

func TestLooksLikeDiskImage(t *testing.T) {
	yes := []string{"disk.img", "disk.raw", "sdcard.img", "a.img.gz", "a.img.xz", "DIR/B.IMG", "card.iso"}
	no := []string{"boot.scr", "readme.txt", "fip.bin.gz", "notes.md", "data.bin"}
	for _, n := range yes {
		if !looksLikeDiskImage(n) {
			t.Errorf("%q 应判定为磁盘镜像", n)
		}
	}
	for _, n := range no {
		if looksLikeDiskImage(n) {
			t.Errorf("%q 不应判定为磁盘镜像", n)
		}
	}
}

func TestNormalizeEntryNameRejectsEscape(t *testing.T) {
	cases := map[string]string{
		"a/b.txt":      "a/b.txt",
		"/abs/x":       "abs/x",
		"a\\b\\c.txt":  "a/b/c.txt",
		"./x":          "x",
		"../evil":      "",
		"a/../../evil": "",
		"C:/win.txt":   "win.txt",
		"./":           "",
		"a/./b":        "a/b",
		"":             "",
	}
	for in, want := range cases {
		if got := normalizeEntryName(in); got != want {
			t.Errorf("normalizeEntryName(%q) = %q, 期望 %q", in, got, want)
		}
	}
}

// ---------- 模式判定 ----------

func TestProbeRawImageVariants(t *testing.T) {
	dir := t.TempDir()
	img := filepath.Join(dir, "disk.img")
	want := writeRaw(t, img, 9000)

	variants := []struct {
		name   string
		path   string
		format string
	}{
		{"裸镜像", img, "img"},
	}
	gz := filepath.Join(dir, "disk.img.gz")
	gzFile(t, img, gz)
	variants = append(variants, struct {
		name   string
		path   string
		format string
	}{"gzip 单流", gz, "gz"})

	xzp := filepath.Join(dir, "disk.img.xz")
	xzFile(t, img, xzp)
	variants = append(variants, struct {
		name   string
		path   string
		format string
	}{"xz 单流", xzp, "xz"})

	zp := filepath.Join(dir, "disk.img.zst")
	zstdFile(t, img, zp)
	variants = append(variants, struct {
		name   string
		path   string
		format string
	}{"zstd 单流", zp, "zst"})

	zipPath := filepath.Join(dir, "single.zip")
	zipFiles(t, zipPath, []fakeFile{{"disk.img", want}}, false)
	variants = append(variants, struct {
		name   string
		path   string
		format string
	}{"zip 内含单个镜像", zipPath, "zip"})

	tgz := filepath.Join(dir, "single.tar.gz")
	tarFiles(t, tgz, []fakeFile{{"disk.img", want}}, "gz")
	variants = append(variants, struct {
		name   string
		path   string
		format string
	}{"tar.gz 内含单个镜像", tgz, "tar.gz"})

	for _, v := range variants {
		a, err := ProbeArchive(v.path, nil, nil)
		if err != nil {
			t.Fatalf("%s: %v", v.name, err)
		}
		if a.Mode != ModeRawDisk {
			t.Errorf("%s: 应判定为整盘镜像, 得 %v", v.name, a.Mode)
			continue
		}
		if a.Format != v.format {
			t.Errorf("%s: 格式 %q, 期望 %q", v.name, a.Format, v.format)
		}
		// 解出来的内容必须与原始镜像一致
		rc, err := a.ImageOpenFunc()()
		if err != nil {
			t.Fatalf("%s: 打开镜像失败 %v", v.name, err)
		}
		got, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			t.Fatalf("%s: 读取镜像失败 %v", v.name, err)
		}
		if !bytes.Equal(got, want) {
			t.Errorf("%s: 解出的镜像内容不一致 (%d vs %d 字节)", v.name, len(got), len(want))
		}
	}
}

func TestProbeFilePackageVariants(t *testing.T) {
	dir := t.TempDir()
	files := []fakeFile{
		{"boot.scr", []byte("boot-script")},
		{"fip.bin", bytes.Repeat([]byte{0xAB}, 4096)},
		{"recovery-ui/run-ui.sh", []byte("#!/bin/sh\n")},
	}

	zp := filepath.Join(dir, "pkg.zip")
	zipFiles(t, zp, files, true)
	tgz := filepath.Join(dir, "pkg.tar.gz")
	tarFiles(t, tgz, files, "gz")
	txz := filepath.Join(dir, "pkg.tar.xz")
	tarFiles(t, txz, files, "xz")
	tarOnly := filepath.Join(dir, "pkg.tar")
	tarFiles(t, tarOnly, files, "")

	for _, p := range []string{zp, tgz, txz, tarOnly} {
		a, err := ProbeArchive(p, nil, nil)
		if err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		if a.Mode != ModeFilePackage {
			t.Errorf("%s: 应判定为文件包, 得 %v", p, a.Mode)
			continue
		}
		if len(a.Files) != 3 {
			t.Errorf("%s: 文件数 %d, 期望 3", p, len(a.Files))
		}
		names := map[string]bool{}
		for _, f := range a.Files {
			names[f.Name] = true
		}
		for _, want := range []string{"boot.scr", "fip.bin", "recovery-ui/run-ui.sh"} {
			if !names[want] {
				t.Errorf("%s: 缺少条目 %q (实得 %v)", p, want, names)
			}
		}
	}
}

func TestProbeForceMode(t *testing.T) {
	dir := t.TempDir()
	// 单个非镜像文件: 自动判定是文件包, 强制 raw 时应取最大文件当镜像
	p := filepath.Join(dir, "weird.zip")
	zipFiles(t, p, []fakeFile{{"data.bin", bytes.Repeat([]byte{7}, 2048)}}, false)
	a, err := ProbeArchive(p, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a.Mode != ModeFilePackage {
		t.Fatalf("data.bin 不匹配镜像扩展名, 应为文件包, 得 %v", a.Mode)
	}
	raw := ModeRawDisk
	a2, err := ProbeArchive(p, &raw, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a2.Mode != ModeRawDisk || a2.Image != "data.bin" {
		t.Fatalf("强制整盘模式应取最大文件, 得 mode=%v image=%q", a2.Mode, a2.Image)
	}
}

// ---------- 卡镜像构建 ----------

func TestVolumeLabelSanitize(t *testing.T) {
	cases := map[string]string{
		"/x/my-package.zip":            "MY-PACKAGE",
		"/x/se7 recovery 1.5.1.tar.gz": "SE7-RECOVER",
		"/x/中文包.zip":                   "SE",   // 取不出有效字符时的兜底卷标
		"/x/a.zip":                     "A",
	}
	for in, want := range cases {
		if got := volumeLabel(&Archive{Path: in}); got != want {
			t.Errorf("volumeLabel(%q) = %q, 期望 %q", in, got, want)
		}
	}
}

func TestPlanCardImageSizing(t *testing.T) {
	pkg := &Archive{Path: "/x/pkg.zip", Files: []ArchiveEntry{
		{Name: "a.bin", Size: 100 << 20},
	}}
	// 按内容: 100MiB + 余量 → ≥ 116MiB, 且 ≥ 最小 64MiB
	plan, err := PlanCardImage(pkg, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	if plan.TotalSize < 100<<20 {
		t.Errorf("卡镜像应能容纳内容, 得 %s", HumanBytes(plan.TotalSize))
	}
	if plan.TotalSize%(1<<20) != 0 {
		t.Errorf("卡镜像尺寸应 1MiB 对齐, 得 %d", plan.TotalSize)
	}
	// 整卡: 用目标盘容量
	plan2, err := PlanCardImage(pkg, 4<<30, true)
	if err != nil {
		t.Fatal(err)
	}
	if plan2.TotalSize != 4<<30 {
		t.Errorf("整卡模式应等于盘容量, 得 %d", plan2.TotalSize)
	}
	// 目标盘比内容还小 → 取盘容量 (后续容量检查会拦)
	plan3, err := PlanCardImage(pkg, 32<<20, false)
	if err == nil && plan3.TotalSize > 32<<20 {
		t.Errorf("不应超过目标盘容量, 得 %d", plan3.TotalSize)
	}
}

func TestBuildCardImageWritesFiles(t *testing.T) {
	dir := t.TempDir()
	files := []fakeFile{
		{"boot.scr", []byte("boot-script-content")},
		{"fip.bin", bytes.Repeat([]byte{0x5A}, 300000)},
		{"recovery-ui/run-ui.sh", []byte("#!/bin/sh\necho hi\n")},
	}
	zp := filepath.Join(dir, "pkg.zip")
	zipFiles(t, zp, files, true)

	a, err := ProbeArchive(zp, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if a.Mode != ModeFilePackage {
		t.Fatalf("应为文件包, 得 %v", a.Mode)
	}
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "card.img")
	if err := BuildCardImage(a, plan, out, nil); err != nil {
		t.Fatalf("构建卡镜像失败: %v", err)
	}
	st, _ := os.Stat(out)
	if st.Size() != plan.TotalSize {
		t.Errorf("卡镜像尺寸 %d, 期望 %d", st.Size(), plan.TotalSize)
	}
	// 回读校验: 分区表 + FAT32 + 文件内容
	verifyCardImage(t, out, plan.Label, files)
}

// 中文/日文等 BMP 名字应当能正常写入 (上游 rune→byte 截断 bug 已打补丁)
func TestBuildCardImageAcceptsCJKNames(t *testing.T) {
	dir := t.TempDir()
	files := []fakeFile{
		{"中文文件.bin", []byte("cjk-content")},
		{"测试.txt", []byte("test-content")},
		{"目录/中文脚本.sh", []byte("#!/bin/sh\n")},
		{"日本語ファイル.txt", []byte("jp")},
	}
	zp := filepath.Join(dir, "pkg.zip")
	zipFiles(t, zp, files, false)
	a, err := ProbeArchive(zp, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "card.img")
	if err := BuildCardImage(a, plan, out, nil); err != nil {
		t.Fatalf("含中文名的文件包应能建卡, 实得错误: %v", err)
	}
	// 名字与内容都要能按原路径读回来
	d, err := diskfs.Open(out)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	fs, err := d.GetFilesystem(1)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		rc, err := fs.OpenFile("/"+f.name, os.O_RDONLY)
		if err != nil {
			t.Errorf("卡上按原名打不开 %q: %v", f.name, err)
			continue
		}
		got, _ := io.ReadAll(rc)
		rc.Close()
		if !bytes.Equal(got, f.data) {
			t.Errorf("%q 内容不一致 (%d vs %d 字节)", f.name, len(got), len(f.data))
		}
	}
}

// 短名被改写成同一串下划线时, 必须用 ~N 去重 (否则同目录出现重复 8.3 名)
func TestBuildCardImageShortNameCollision(t *testing.T) {
	dir := t.TempDir()
	// "中文" 与 "英文" 的短名都会被改写成下划线 → 必须去重, 两个文件都要能读回
	files := []fakeFile{
		{"中文.bin", []byte("AAAA")},
		{"英文.bin", []byte("BBBB")},
	}
	zp := filepath.Join(dir, "pkg.zip")
	zipFiles(t, zp, files, false)
	a, _ := ProbeArchive(zp, nil, nil)
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "card.img")
	if err := BuildCardImage(a, plan, out, nil); err != nil {
		t.Fatalf("建卡失败: %v", err)
	}
	d, _ := diskfs.Open(out)
	defer d.Close()
	fs, _ := d.GetFilesystem(1)
	for _, f := range files {
		rc, err := fs.OpenFile("/"+f.name, os.O_RDONLY)
		if err != nil {
			t.Errorf("打不开 %q: %v", f.name, err)
			continue
		}
		got, _ := io.ReadAll(rc)
		rc.Close()
		if !bytes.Equal(got, f.data) {
			t.Errorf("%q 内容串了 (%q vs %q) — 短名冲突未去重", f.name, got, f.data)
		}
	}
}

// FAT32 真正存不下的名字仍要前置拦下: emoji 与非法字符
func TestBuildCardImageRejectsUnrepresentableNames(t *testing.T) {
	dir := t.TempDir()
	cases := []string{"emoji😀.bin", "bad*name.bin", "colon:name.bin"}
	for _, bad := range cases {
		zp := filepath.Join(dir, "pkg.zip")
		os.Remove(zp)
		zipFiles(t, zp, []fakeFile{{bad, []byte("x")}}, false)
		a, err := ProbeArchive(zp, nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		plan, err := PlanCardImage(a, 0, false)
		if err != nil {
			t.Fatal(err)
		}
		err = BuildCardImage(a, plan, filepath.Join(dir, "card.img"), nil)
		if err == nil {
			t.Errorf("%q 应被拒绝 (FAT32 无法表示)", bad)
			continue
		}
		if !strings.Contains(err.Error(), "FAT32 无法表示") {
			t.Errorf("%q 的报错信息应说明原因, 得 %v", bad, err)
		}
	}
}

// verifyCardImage 回读卡镜像: 分区表 + 逐个文件内容比对
//
// 不用 fs.ReadDir —— 该库这版对根目录路径会报 invalid argument;
// 直接按已知路径 OpenFile 即可证明"文件确实写进了 FAT32 且内容正确"。
func verifyCardImage(t *testing.T, imgPath, wantLabel string, files []fakeFile) {
	t.Helper()
	d, err := diskfs.Open(imgPath)
	if err != nil {
		t.Fatalf("打开卡镜像失败: %v", err)
	}
	defer d.Close()
	tbl, err := d.GetPartitionTable()
	if err != nil {
		t.Fatalf("读分区表失败: %v", err)
	}
	// MBR 固定 4 个槽位, 空槽 Type=0 → 只数有效分区
	used := 0
	for _, p := range tbl.GetPartitions() {
		if p.GetSize() > 0 {
			used++
		}
	}
	if used != 1 {
		t.Fatalf("应有 1 个有效分区, 得 %d (表内共 %d 槽)", used, len(tbl.GetPartitions()))
	}
	fs, err := d.GetFilesystem(1)
	if err != nil {
		t.Fatalf("挂载 FAT32 失败: %v", err)
	}
	for _, want := range files {
		rc, err := fs.OpenFile("/"+want.name, os.O_RDONLY)
		if err != nil {
			t.Errorf("卡镜像内打开 %q 失败: %v", want.name, err)
			continue
		}
		got, _ := io.ReadAll(rc)
		rc.Close()
		if !bytes.Equal(got, want.data) {
			t.Errorf("%q 内容不一致 (%d vs %d 字节)", want.name, len(got), len(want.data))
		}
	}
}

// Windows 中文环境下打出的 zip 常用 GBK 存名 (未置 UTF-8 标志) —— 必须解对
func TestZipGBKNamesDecoded(t *testing.T) {
	dir := t.TempDir()
	zp := filepath.Join(dir, "gbk.zip")
	// 手工构造一个不带 UTF-8 标志、名字是 GBK 字节的 zip
	name := "中文说明.txt"
	gbk, err := simplifiedchinese.GBK.NewEncoder().Bytes([]byte(name))
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.Create(zp)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	hdr := &zip.FileHeader{Name: string(gbk), Method: zip.Deflate}
	hdr.NonUTF8 = true
	w, err := zw.CreateHeader(hdr)
	if err != nil {
		t.Fatal(err)
	}
	w.Write([]byte("content"))
	zw.Close()
	f.Close()

	a, err := ProbeArchive(zp, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(a.Files) != 1 {
		t.Fatalf("应有 1 个文件, 得 %d", len(a.Files))
	}
	if a.Files[0].Name != name {
		t.Errorf("GBK 名字应被解码为 %q, 实得 %q", name, a.Files[0].Name)
	}
	// 建卡后按原中文名应能读回
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "card.img")
	if err := BuildCardImage(a, plan, out, nil); err != nil {
		t.Fatal(err)
	}
	d, _ := diskfs.Open(out)
	defer d.Close()
	fs, _ := d.GetFilesystem(1)
	rc, err := fs.OpenFile("/"+name, os.O_RDONLY)
	if err != nil {
		t.Fatalf("卡上按中文名打不开: %v", err)
	}
	got, _ := io.ReadAll(rc)
	rc.Close()
	if string(got) != "content" {
		t.Errorf("内容不符: %q", got)
	}
}

// ---------- 探测进度与取消 (MYS-1062 十三轮) ----------

// tar.xz 解析要整条流走一遍 —— 必须能报进度, 否则界面只能干等
func TestProbeReportsReadProgress(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "pkg.tar.xz")
	tarFiles(t, p, []fakeFile{
		{"a.bin", bytes.Repeat([]byte("x"), 6<<20)},
		{"b.bin", bytes.Repeat([]byte("y"), 6<<20)},
	}, "xz")

	var last, total int64
	var calls int
	ctl := &ProbeCtl{Progress: func(phase string, done, tot int64) {
		if phase != "read" {
			return
		}
		calls++
		last, total = done, tot
	}}
	a, err := ProbeArchive(p, nil, ctl)
	if err != nil {
		t.Fatal(err)
	}
	if a.Mode != ModeFilePackage {
		t.Fatalf("应为文件包, 得 %v", a.Mode)
	}
	if calls == 0 {
		t.Fatal("应至少报告一次读取进度")
	}
	st, _ := os.Stat(p)
	if total != st.Size() {
		t.Errorf("进度总量应为源文件大小 %d, 得 %d", st.Size(), total)
	}
	if last <= 0 || last > total {
		t.Errorf("进度 %d 不在 (0, %d] 内", last, total)
	}
}

// 取消要能真的中断 (返回 ErrProbeCanceled), 而不是白等它跑完
func TestProbeCancelStopsAnalysis(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "pkg.tar.xz")
	tarFiles(t, p, []fakeFile{{"a.bin", bytes.Repeat([]byte("x"), 6<<20)}}, "xz")

	ctl := &ProbeCtl{Canceled: func() bool { return true }}
	if _, err := ProbeArchive(p, nil, ctl); !errors.Is(err, ErrProbeCanceled) {
		t.Fatalf("应返回 ErrProbeCanceled, 得 %v", err)
	}
	// 中途取消: 报过进度之后再取消
	var n int
	ctl2 := &ProbeCtl{
		Progress: func(phase string, done, tot int64) { n++ },
		Canceled: func() bool { return n > 1 },
	}
	if _, err := ProbeArchive(p, nil, ctl2); !errors.Is(err, ErrProbeCanceled) {
		t.Fatalf("中途取消也应返回 ErrProbeCanceled, 得 %v", err)
	}
}

// 容器格式 (zip/7z/rar) 走随机访问, 没有字节进度 → 用条目数报告 (total=0)
func TestProbeContainerReportsScanProgress(t *testing.T) {
	dir := t.TempDir()
	zp := filepath.Join(dir, "pkg.zip")
	var files []fakeFile
	for i := 0; i < 40; i++ {
		files = append(files, fakeFile{name: "f" + string(rune('a'+i%26)) + string(rune('0'+i/26)) + ".bin", data: []byte("z")})
	}
	zipFiles(t, zp, files, false)

	sawScan := false
	ctl := &ProbeCtl{Progress: func(phase string, done, tot int64) {
		if phase == "scan" {
			sawScan = true
			if tot != 0 {
				t.Errorf("容器格式的 scan 进度 total 应为 0, 得 %d", tot)
			}
		}
	}}
	if _, err := ProbeArchive(zp, nil, ctl); err != nil {
		t.Fatal(err)
	}
	if !sawScan {
		t.Error("容器格式应报告 scan 进度")
	}
}

// ---------- 7z 容器端到端 (sevenzip 依赖被降到 Go 1.20 可编译的版本, 这里实测解压) ----------

// sevenZipFiles 用系统 7z 打一个 .7z; 没有 7z 就跳过 (测试机可能没装)
func sevenZipFiles(t *testing.T, dst string, files []fakeFile) bool {
	t.Helper()
	if _, err := exec.LookPath("7z"); err != nil {
		return false
	}
	dir := t.TempDir()
	for _, f := range files {
		p := filepath.Join(dir, f.name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, f.data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	cmd := exec.Command("7z", "a", "-t7z", "-bso0", "-bsp0", dst, ".")
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("7z 打包失败: %v\n%s", err, out)
	}
	return true
}

func TestSevenZipContainersRoundTrip(t *testing.T) {
	// 文件包形态
	dir := t.TempDir()
	pkg := filepath.Join(dir, "pkg.7z")
	files := []fakeFile{
		{"boot.scr", []byte("boot-script\n" + string(marker) + "\n")},
		{"fip.bin", bytes.Repeat([]byte{0x5A}, 300000)},
		{"recovery-ui/run-ui.sh", []byte("#!/bin/sh\necho setf\n")},
	}
	if !sevenZipFiles(t, pkg, files) {
		t.Skip("未安装 7z, 跳过")
	}
	a, err := ProbeArchive(pkg, nil, nil)
	if err != nil {
		t.Fatalf("7z 探测失败: %v", err)
	}
	if a.Mode != ModeFilePackage {
		t.Fatalf("应为文件包, 得 %v", a.Mode)
	}
	if len(a.Files) != len(files) {
		t.Errorf("应识别 %d 个文件, 得 %d", len(files), len(a.Files))
	}
	// 建卡 + 逐文件校验 (走完整的解压路径)
	plan, err := PlanCardImage(a, 0, false)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	defer dev.Close()
	if _, err := BuildCardOnDevice(dev, a, plan, nil); err != nil {
		t.Fatalf("7z 文件包建卡失败: %v", err)
	}
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !fv.OK() {
		t.Fatalf("7z 文件包校验失败: %s / %s", fv.Summary(), fv.FirstError())
	}

	// 整盘镜像形态: 7z 里只有一个 .img
	imgDir := t.TempDir()
	imgPath := filepath.Join(imgDir, "disk.img")
	raw := writeRaw(t, imgPath, 200000)
	imgPkg := filepath.Join(t.TempDir(), "disk.7z")
	if !sevenZipFiles(t, imgPkg, []fakeFile{{"disk.img", raw}}) {
		t.Skip("未安装 7z, 跳过")
	}
	a2, err := ProbeArchive(imgPkg, nil, nil)
	if err != nil {
		t.Fatalf("7z 整盘镜像探测失败: %v", err)
	}
	if a2.Mode != ModeRawDisk || a2.Image != "disk.img" {
		t.Fatalf("应判定为整盘镜像 disk.img, 得 %v / %q", a2.Mode, a2.Image)
	}
	rc, err := a2.ImageOpenFunc()()
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(rc)
	rc.Close()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, raw) {
		t.Error("从 7z 里解出来的镜像与源不一致")
	}
}
