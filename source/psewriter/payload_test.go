// payload / repack 单测 (Linux 可跑):
// 尾部结构编解码、剥离骨架、换镜像生成第二个程序、覆盖保护、损坏检测
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/rand"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// makeSkeleton 造一个"程序"文件 (内容任意, 结构上等价于纯骨架 exe)
func makeSkeleton(t *testing.T, dir, name string, size int) string {
	t.Helper()
	b := make([]byte, size)
	if _, err := rand.Read(b); err != nil {
		t.Fatal(err)
	}
	// 头部放可识别标记, 便于确认剥离后骨架字节完全保留
	copy(b, []byte("SE7FAKE-EXE\x00"))
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, b, 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

func makeImage(t *testing.T, dir, name string, size int, gz bool) (string, []byte) {
	t.Helper()
	raw := make([]byte, size)
	if _, err := rand.Read(raw); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(dir, name)
	if !gz {
		if err := os.WriteFile(p, raw, 0o644); err != nil {
			t.Fatal(err)
		}
		return p, raw
	}
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	zw := gzip.NewWriter(f)
	zw.Write(raw)
	zw.Close()
	f.Close()
	return p, raw
}

func writeFooterFile(t *testing.T, path string, skelSize int, meta PayloadMeta) {
	t.Helper()
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := writeFooter(f, meta); err != nil {
		t.Fatal(err)
	}
	_ = skelSize
}

func TestPayloadAbsentOnPlainFile(t *testing.T) {
	p := makeSkeleton(t, t.TempDir(), "plain.exe", 4096)
	if _, err := OpenPayloadFile(p); err != ErrNoPayload {
		t.Fatalf("纯骨架应返回 ErrNoPayload, 得 %v", err)
	}
	if HasEmbeddedImage() {
		t.Log("(当前测试二进制恰好带 payload — 不影响本用例)")
	}
}

func TestPayloadRoundTripAndStrip(t *testing.T) {
	dir := t.TempDir()
	skel := makeSkeleton(t, dir, "skel.exe", 8192)
	skelBytes, _ := os.ReadFile(skel)

	// 手工构造 [骨架][payload][meta][len][magic]
	payload := []byte("THIS-IS-THE-IMAGE-PAYLOAD-BYTES")
	sum := sha256.Sum256(payload)
	target := filepath.Join(dir, "packed.exe")
	if err := os.WriteFile(target, append(append([]byte{}, skelBytes...), payload...), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFooterFile(t, target, len(skelBytes), PayloadMeta{
		File: "x.img.gz", Bytes: 12345, SHA256: "deadbeef",
		StoredBytes: int64(len(payload)), StoredSHA256: fmt.Sprintf("%x", sum),
		Compressed: false, SkeletonBytes: int64(len(skelBytes)),
	})

	p, err := OpenPayloadFile(target)
	if err != nil {
		t.Fatalf("解析 payload 失败: %v", err)
	}
	if p.Offset != int64(len(skelBytes)) || p.Size != int64(len(payload)) {
		t.Fatalf("偏移/长度错误: off=%d size=%d", p.Offset, p.Size)
	}
	if p.Meta.File != "x.img.gz" || p.Meta.Bytes != 12345 {
		t.Fatalf("meta 错误: %+v", p.Meta)
	}

	// 剥离出的骨架必须与原骨架逐字节相同
	rc, err := p.Skeleton()
	if err != nil {
		t.Fatal(err)
	}
	defer rc.Close()
	got := make([]byte, len(skelBytes))
	if n, err := readFull(rc, got); err != nil || n != len(skelBytes) {
		t.Fatalf("读骨架失败: n=%d err=%v", n, err)
	}
	if !bytes.Equal(got, skelBytes) {
		t.Fatal("剥离出的骨架与原始骨架不一致")
	}

	// payload 内容读取
	img, err := p.open()
	if err != nil {
		t.Fatal(err)
	}
	defer img.Close()
	pb := make([]byte, len(payload))
	if _, err := readFull(img, pb); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(pb, payload) {
		t.Fatal("payload 内容不一致")
	}
}

func TestPayloadRejectsCorruptFooter(t *testing.T) {
	dir := t.TempDir()
	p := makeSkeleton(t, dir, "bad.exe", 4096)
	// 尾部 20 字节是随机数据 → 不应被误判为带 payload
	if _, err := OpenPayloadFile(p); err != ErrNoPayload {
		t.Fatalf("随机尾部不应识别为 payload, 得 %v", err)
	}
	// magic 对但 skeleton_bytes 不匹配 → 同样拒绝
	f, _ := os.OpenFile(p, os.O_APPEND|os.O_WRONLY, 0)
	writeFooter(f, PayloadMeta{StoredBytes: 100, SkeletonBytes: 999999, File: "x"})
	f.Close()
	if _, err := OpenPayloadFile(p); err != ErrNoPayload {
		t.Fatalf("交叉校验失败应拒绝, 得 %v", err)
	}
}

func TestRepackProducesSecondProgram(t *testing.T) {
	dir := t.TempDir()
	skel := makeSkeleton(t, dir, "se7flash-skel.exe", 16384)
	skelBytes, _ := os.ReadFile(skel)
	imgPath, rawImg := makeImage(t, dir, "se7-recovery-9.9.9-2026-01-01-noaging.img.gz", 300000, true)
	out := filepath.Join(dir, "se7flash-new.exe")

	res, err := Repack(imgPath, out, skel, false, nil)
	if err != nil {
		t.Fatalf("repack 失败: %v", err)
	}
	if !res.Verified {
		t.Fatal("repack 应完成回读自检")
	}

	// 新程序 = 骨架 + payload + footer
	p, err := OpenPayloadFile(out)
	if err != nil {
		t.Fatalf("新程序不可解析: %v", err)
	}
	if p.Offset != int64(len(skelBytes)) {
		t.Fatalf("骨架长度错误: %d ≠ %d", p.Offset, len(skelBytes))
	}
	if !p.Meta.Compressed || p.Meta.Origin != "repack" {
		t.Fatalf("meta 标记错误: %+v", p.Meta)
	}
	if p.Meta.BuildVer != "9.9.9" {
		t.Errorf("镜像版本解析错误: %q", p.Meta.BuildVer)
	}
	if p.Meta.Bytes != int64(len(rawImg)) {
		t.Errorf("解压大小错误: %d ≠ %d", p.Meta.Bytes, len(rawImg))
	}
	wantSHA := sha256.Sum256(rawImg)
	if p.Meta.SHA256 != fmt.Sprintf("%x", wantSHA) {
		t.Errorf("解压 sha256 错误: %s", p.Meta.SHA256)
	}
	if p.Meta.StoredBytes != fileSize(t, imgPath) {
		t.Errorf("内置体积错误: %d", p.Meta.StoredBytes)
	}

	// 骨架字节完全保留
	rc, _ := p.Skeleton()
	gotSkel := make([]byte, len(skelBytes))
	readFull(rc, gotSkel)
	rc.Close()
	if !bytes.Equal(gotSkel, skelBytes) {
		t.Fatal("新程序骨架与模板不一致")
	}

	// 新程序的内置镜像可解出与源镜像一致的内容
	src := &ImageSource{Name: p.Meta.File, raw: p.Meta.Bytes, gzip: p.Meta.Compressed, openFn: p.open, embedded: true}
	if !src.Embedded() {
		t.Fatal("内置源应标记 Embedded()")
	}
	h, n, err := ExportImageSHA256Src(src)
	if err != nil {
		t.Fatal(err)
	}
	if n != int64(len(rawImg)) || h != fmt.Sprintf("%x", wantSHA) {
		t.Fatalf("内置镜像内容不一致: n=%d sha=%s", n, h)
	}
}

func TestRepackChainFromPackedProgram(t *testing.T) {
	// 已带镜像的程序再次 repack: 应剥离旧镜像, 新程序大小 = 骨架 + 新镜像 (不叠加)
	dir := t.TempDir()
	skel := makeSkeleton(t, dir, "se7flash.exe", 16384)
	skelSize := fileSize(t, skel)
	img1, _ := makeImage(t, dir, "img-1.0.0.img.gz", 200000, true)
	img2, _ := makeImage(t, dir, "img-2.0.0.img.gz", 300000, true)

	first := filepath.Join(dir, "first.exe")
	if _, err := Repack(img1, first, skel, false, nil); err != nil {
		t.Fatal(err)
	}
	second := filepath.Join(dir, "second.exe")
	res, err := Repack(img2, second, first, false, nil)
	if err != nil {
		t.Fatalf("二次 repack 失败: %v", err)
	}
	if res.SkeletonBytes != skelSize {
		t.Fatalf("二次 repack 骨架长度 %d ≠ 原始 %d (旧镜像未剥离?)", res.SkeletonBytes, skelSize)
	}
	if res.Image.BuildVer != "2.0.0" {
		t.Errorf("二次 repack 镜像版本错误: %q", res.Image.BuildVer)
	}
	// 体积应约等于 骨架 + 第二个镜像, 而不是叠加两个镜像
	if res.OutBytes > skelSize+fileSize(t, img2)+4096 {
		t.Fatalf("新程序体积异常 (疑似叠加): %d", res.OutBytes)
	}
}

func TestRepackGuards(t *testing.T) {
	dir := t.TempDir()
	skel := makeSkeleton(t, dir, "se7flash.exe", 8192)
	img, _ := makeImage(t, dir, "img.img.gz", 50000, true)

	// 输出 = 骨架自身 → 拒绝 (防止自毁)
	if _, err := Repack(img, skel, skel, true, nil); err == nil {
		t.Fatal("输出覆盖骨架自身应被拒绝")
	}
	// 已存在且未加 force → 拒绝
	out := filepath.Join(dir, "out.exe")
	if _, err := Repack(img, out, skel, false, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := Repack(img, out, skel, false, nil); err == nil {
		t.Fatal("已存在输出未加 force 应被拒绝")
	}
	if _, err := Repack(img, out, skel, true, nil); err != nil {
		t.Fatalf("force 覆盖应成功: %v", err)
	}
	// 镜像不存在 → 报错
	if _, err := Repack(filepath.Join(dir, "nope.img"), "", skel, true, nil); err == nil {
		t.Fatal("镜像不存在应报错")
	}
	// 未指定镜像 → 报错
	if _, err := Repack("", "", skel, true, nil); err == nil {
		t.Fatal("未指定镜像应报错")
	}
}

func TestRepackWithRawImage(t *testing.T) {
	// 未压缩 .img 输入: Compressed=false, 内置数据 = 原文件
	dir := t.TempDir()
	skel := makeSkeleton(t, dir, "skel.exe", 4096)
	img, raw := makeImage(t, dir, "plain-3.1.4.img", 12345, false)
	out := filepath.Join(dir, "out.exe")
	res, err := Repack(img, out, skel, false, nil)
	if err != nil {
		t.Fatal(err)
	}
	if res.Image.Compressed {
		t.Error("未压缩输入不应标记 Compressed")
	}
	if res.Image.Bytes != int64(len(raw)) || res.Image.SHA256 != res.Image.StoredSHA256 {
		t.Errorf("未压缩镜像 meta 错误: %+v", res.Image)
	}
	if res.Image.BuildVer != "3.1.4" {
		t.Errorf("版本解析错误: %q", res.Image.BuildVer)
	}
}

func TestDefaultOutPathUsesImageVersion(t *testing.T) {
	img := &ImageSource{Name: "se7-recovery-1.5.1-2026-09-14-noaging.img.gz"}
	got := DefaultOutPath("/tmp/se7flash.exe", img)
	if got != "/tmp/se7flash-1.5.1.exe" {
		t.Fatalf("默认输出名错误: %s", got)
	}
	if v := imgVersion(&ImageSource{Name: "no-version-here.img"}); v != "" {
		t.Fatalf("无版本名不应解析出版本: %q", v)
	}
}

func TestImgVersionPicksVersionNotDate(t *testing.T) {
	got := imgVersion(&ImageSource{Name: "se7-recovery-1.5.1-2026-09-14-noaging.img.gz"})
	if got != "1.5.1" {
		t.Fatalf("应取 1.5.1, 得 %q", got)
	}
	if !strings.HasPrefix(got, "1.") {
		t.Fatal("版本解析异常")
	}
}

func fileSize(t *testing.T, p string) int64 {
	t.Helper()
	st, err := os.Stat(p)
	if err != nil {
		t.Fatal(err)
	}
	return st.Size()
}
