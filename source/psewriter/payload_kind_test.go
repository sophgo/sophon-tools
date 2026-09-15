// 内置数据源种类判定 单测 (MYS-1062 十九轮, Linux 可跑)
//
// 这一组测试对应现场事故: 内置载荷是 .txz 文件包, 工具却把它当整盘镜像写进了卡。
// 这里把"内置载荷 → 判定结果"钉死, 保证内置路径与手选文件路径给出同样的结论。
package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/ulikunitz/xz"
)

// fakePayload 把一段字节当成"exe 尾部载荷"喂给判定函数
func fakePayload(t *testing.T, name string, data []byte, compressed bool) *Payload {
	t.Helper()
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return &Payload{
		Meta:     PayloadMeta{File: name, Bytes: int64(len(data)), Compressed: compressed},
		SelfPath: p,
		Offset:   0,
		Size:     int64(len(data)),
	}
}

// tarBytes 造一个 tar 流 (含卡根目录该有的特征文件)
func tarBytes(t *testing.T) []byte {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	files := []struct {
		name string
		data []byte
	}{
		{"fip.bin", bytes.Repeat([]byte{0x5A}, 1024)},
		{"boot.scr", []byte("boot\n")},
		{"sdbootrecovery.itb", []byte("itb")},
		{"ai/resnet50_int8_1b.bmodel", bytes.Repeat([]byte{1}, 512)},
	}
	for _, f := range files {
		if err := tw.WriteHeader(&tar.Header{Name: f.name, Mode: 0o644, Size: int64(len(f.data))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(f.data); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func gzipBytes(t *testing.T, raw []byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(raw); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func xzBytes(t *testing.T, raw []byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	xw, err := xz.NewWriter(&buf)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := xw.Write(raw); err != nil {
		t.Fatal(err)
	}
	if err := xw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestPayloadKindClassify(t *testing.T) {
	// 1MiB 随机-ish 数据冒充整盘镜像 (不能全零: 全零 gzip 后太小看不出问题, 无所谓)
	imgData := make([]byte, 1<<20)
	for i := range imgData {
		imgData[i] = byte(i*7 + i>>8)
	}

	cases := []struct {
		name       string
		file       string
		data       []byte
		compressed bool
		wantPkg    bool
		wantKind   string
	}{
		{"裸整盘镜像 payload", "recovery.img", imgData, false, false, "img"},
		{"gzip 包着的整盘镜像 (.img.gz)", "recovery.img.gz", gzipBytes(t, imgData), true, false, "gz"},
		{"tar.gz 文件包", "sdbootrecoveryfiles.tar.gz", gzipBytes(t, tarBytes(t)), false, true, "tar.gz"},
		{"tar.xz 文件包 (.txz)", "se7-recovery-files.txz", xzBytes(t, tarBytes(t)), false, true, "tar.xz"},
		{"xz 包着的整盘镜像", "recovery.img.xz", xzBytes(t, imgData), false, false, "xz"},
		{"tar 文件包 (未压缩)", "cardfiles.tar", tarBytes(t), false, true, "tar"},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := fakePayload(t, c.file, c.data, c.compressed)
			isPkg, kind, err := payloadKind(p)
			if err != nil {
				t.Fatalf("判定失败: %v", err)
			}
			if isPkg != c.wantPkg || kind != c.wantKind {
				t.Errorf("判定 = (pkg=%v, kind=%q), 期望 (pkg=%v, kind=%q)",
					isPkg, kind, c.wantPkg, c.wantKind)
			}
		})
	}
}

// zip 归档一律按"文件包"对待 (内部只有一个 .img 时由归档探测再判成整盘)
func TestPayloadKindZip(t *testing.T) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, err := zw.Create("fip.bin")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte("fip")); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	p := fakePayload(t, "pkg.zip", buf.Bytes(), false)
	isPkg, kind, err := payloadKind(p)
	if err != nil {
		t.Fatal(err)
	}
	if !isPkg || kind != "zip" {
		t.Errorf("zip 应为文件包, 得 pkg=%v kind=%q", isPkg, kind)
	}
}

// 关键回归: .txz 文件包**不能**被判成整盘镜像 —— 判错就会把压缩字节原样写进卡
func TestPayloadKindTxzIsNotRawImage(t *testing.T) {
	p := fakePayload(t, "se7-recovery-files-1.6.0-2026-09-15-noaging.txz", xzBytes(t, tarBytes(t)), false)
	isPkg, _, err := payloadKind(p)
	if err != nil {
		t.Fatal(err)
	}
	if !isPkg {
		t.Fatal("回归: .txz 文件包被判成了整盘镜像 (现场事故根因)")
	}
}

// 落临时副本: 内容逐字节一致, 文件名保持原名 (卷标/展示名依赖它)
func TestEmbeddedPackageFileRoundTrip(t *testing.T) {
	data := xzBytes(t, tarBytes(t))
	p := fakePayload(t, "se7-recovery-files.txz", data, false)

	// 直接测落盘逻辑 (不走 OpenSelfPayload: 单测进程本身没有内置载荷)
	tmp, cleanup, err := materializePayload(p)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if filepath.Base(tmp) != "se7-recovery-files.txz" {
		t.Errorf("临时副本应保留原名, 得 %q", filepath.Base(tmp))
	}
	got, err := os.ReadFile(tmp)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, data) {
		t.Error("临时副本内容与载荷不一致")
	}
	// 落下来的副本必须能被正常探测成文件包 (内置 → 临时文件 → probeAny 这一链路的关键一环)
	a, err := ProbeArchive(tmp, nil, nil)
	if err != nil {
		t.Fatalf("探临时副本失败: %v", err)
	}
	if a.Mode != ModeFilePackage {
		t.Errorf("临时副本应被探测成文件包, 得 %v", a.Mode)
	}
	for _, want := range []string{"fip.bin", "boot.scr", "sdbootrecovery.itb"} {
		if !has(a.Files, want) {
			t.Errorf("探测结果应含 %s", want)
		}
	}
	if _, err := io.Copy(io.Discard, mustOpen(t, tmp)); err != nil {
		t.Fatal(err)
	}
}

func mustOpen(t *testing.T, p string) io.ReadCloser {
	t.Helper()
	f, err := os.Open(p)
	if err != nil {
		t.Fatal(err)
	}
	return f
}
