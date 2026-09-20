// 卡上直接建 FAT32 + 卡上结构/文件级校验 单测 (Linux 可跑)
package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// marker 用来在设备上定位某个文件的内容, 便于做"故意破坏"测试
var marker = []byte("SETF-MARKER-0123456789ABCDEF-XYZ")

// buildTestPkg 造一个文件包 (zip) 并解析成写入计划
func buildTestPkg(t *testing.T) (*Archive, *PackagePlan) {
	t.Helper()
	dir := t.TempDir()
	zp := filepath.Join(dir, "pkg.zip")
	files := []fakeFile{
		{"boot.scr", append(append([]byte("boot-script\n"), marker...), '\n')},
		{"fip.bin", bytes.Repeat([]byte{0x5A}, 200000)},
		{"recovery-ui/run-ui.sh", []byte("#!/bin/sh\necho setf\n")},
	}
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
	return a, plan
}

// buildCardOnFakeDevice 在模拟设备上直接建卡
func buildCardOnFakeDevice(t *testing.T) (*Archive, *PackagePlan, *fileDisk, *CardWriteResult) {
	t.Helper()
	a, plan := buildTestPkg(t)
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	t.Cleanup(func() { dev.Close() })
	res, err := BuildCardOnDevice(dev, a, plan, nil)
	if err != nil {
		t.Fatalf("卡上建 FAT32 失败: %v", err)
	}
	return a, plan, dev, res
}

func TestIsAllZero(t *testing.T) {
	if !isAllZero(make([]byte, 4096)) {
		t.Error("全零块应判为全零")
	}
	b := make([]byte, 4096)
	b[4095] = 1
	if isAllZero(b) {
		t.Error("含非零字节不应判为全零")
	}
}

// 核心诉求: 卡上直接建, 不再产生整卡尺寸的中间物 —— 只有元数据 + 文件数据被写下去
func TestBuildCardOnDeviceWritesOnlyUsedBytes(t *testing.T) {
	_, plan, _, res := buildCardOnFakeDevice(t)

	if res.TotalSize != plan.TotalSize {
		t.Errorf("卡容量应为 %d, 得 %d", plan.TotalSize, res.TotalSize)
	}
	if res.WrittenBytes <= 0 {
		t.Fatal("应当有写入")
	}
	// 内容只有 200 KiB 上下, 卡却是 64 MiB —— 实写必须远小于整卡
	if res.WrittenBytes >= plan.TotalSize/4 {
		t.Errorf("实写 %s 应远小于卡容量 %s (未用空间不该被写)",
			HumanBytes(res.WrittenBytes), HumanBytes(plan.TotalSize))
	}
	if res.SkippedBytes != plan.TotalSize-res.WrittenBytes {
		t.Errorf("跳过字节数 %d 与 总量-实写 %d 不符", res.SkippedBytes, plan.TotalSize-res.WrittenBytes)
	}
	if len(res.Extents) == 0 {
		t.Error("应记录写入区间 (供回读确认)")
	}
	// 区间不重叠
	for i := 1; i < len(res.Extents); i++ {
		if res.Extents[i].Off < res.Extents[i-1].Off+res.Extents[i-1].Len {
			t.Errorf("写入区间 %d 与前一个重叠", i)
		}
	}
	// 分区表与 FAT 必然被写过 (元数据不能省)
	if res.Extents[0].Off != 0 {
		t.Errorf("分区表所在的偏移 0 必须被写, 首个区间起点为 %d", res.Extents[0].Off)
	}
}

// 建出来的卡必须能被解析成 FAT32, 且文件逐个 sha256 一致
func TestBuildCardOnDeviceFilesVerifiable(t *testing.T) {
	a, _, dev, _ := buildCardOnFakeDevice(t)

	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatalf("文件级校验执行失败: %v", err)
	}
	if !fv.OK() {
		t.Fatalf("文件级校验应全部通过, 实得 %s / %s", fv.Summary(), fv.FirstError())
	}
	if fv.OKCount != len(a.Files) {
		t.Errorf("应校验 %d 个文件, 实得 %d", len(a.Files), fv.OKCount)
	}
	for _, f := range fv.Files {
		if len(f.WantSHA) != 64 || f.WantSHA != f.GotSHA {
			t.Errorf("%s: sha256 不一致 (%s vs %s)", f.Name, f.WantSHA, f.GotSHA)
		}
	}
}

func TestVerifyCardLayoutOK(t *testing.T) {
	_, plan, dev, _ := buildCardOnFakeDevice(t)
	lay, err := VerifyCardLayout(dev, plan, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !lay.OK() {
		t.Fatalf("结构核对应通过, 问题: %v", lay.Problems)
	}
	if lay.MetaEnd <= 0 || lay.MetaEnd >= plan.TotalSize {
		t.Errorf("元数据区边界 %d 不合理 (卡容量 %d)", lay.MetaEnd, plan.TotalSize)
	}
	if lay.FATBytes <= 0 {
		t.Error("应统计 FAT 两份副本字节数")
	}
	if lay.Label != plan.Label {
		t.Errorf("卷标应为 %q, 得 %q", plan.Label, lay.Label)
	}
}

// MBR 被破坏 → 结构核对必须报出来
func TestVerifyCardLayoutDetectsMBRCorruption(t *testing.T) {
	_, plan, dev, _ := buildCardOnFakeDevice(t)
	if _, err := dev.WriteAt([]byte{0x00}, 510); err != nil { // 打掉 0x55AA 签名
		t.Fatal(err)
	}
	lay, err := VerifyCardLayout(dev, plan, nil)
	if err != nil {
		t.Fatal(err)
	}
	if lay.OK() {
		t.Fatal("MBR 签名被破坏后不应通过")
	}
	if len(lay.Problems) == 0 {
		t.Error("应给出具体问题")
	}
}

// FAT 两份副本不一致 → 结构核对必须报出来 (证明真的逐字节比对了两份 FAT)
func TestVerifyCardLayoutDetectsFATCopyMismatch(t *testing.T) {
	_, plan, dev, _ := buildCardOnFakeDevice(t)
	lay, err := VerifyCardLayout(dev, plan, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !lay.OK() {
		t.Fatalf("前置条件: 结构本应完好, 问题 %v", lay.Problems)
	}
	// 第二份 FAT 的起点 = 第一份 + 一份的大小
	bpb := make([]byte, 512)
	if _, err := dev.ReadAt(bpb, int64(partStartLBA)*sectorSize); err != nil {
		t.Fatal(err)
	}
	rsvd := int64(bpb[14]) | int64(bpb[15])<<8
	fatSz := int64(bpb[36]) | int64(bpb[37])<<8 | int64(bpb[38])<<16 | int64(bpb[39])<<24
	fat1 := int64(partStartLBA)*sectorSize + rsvd*sectorSize
	fat2 := fat1 + fatSz*sectorSize
	// 改第二份 FAT 里的一个字节 (挑第一个非零字节, 保证确实写坏)
	buf := make([]byte, 4096)
	if _, err := dev.ReadAt(buf, fat2); err != nil {
		t.Fatal(err)
	}
	pos := -1
	for i, b := range buf {
		if b != 0 {
			pos = i
			break
		}
	}
	if pos < 0 {
		t.Fatal("第二份 FAT 起始处全零? 测试前提不成立")
	}
	if _, err := dev.WriteAt([]byte{buf[pos] ^ 0xFF}, fat2+int64(pos)); err != nil {
		t.Fatal(err)
	}
	lay2, err := VerifyCardLayout(dev, plan, nil)
	if err != nil {
		t.Fatal(err)
	}
	if lay2.OK() {
		t.Fatal("FAT 两份副本不一致时不应通过")
	}
}

// 文件内容被破坏 → 文件级校验必须报错 (证明校验真的在读卡内容)
func TestVerifyCardFilesDetectsCorruption(t *testing.T) {
	a, _, dev, _ := buildCardOnFakeDevice(t)
	off := findMarker(t, dev, marker)
	if off < 0 {
		t.Fatal("未能在设备上找到 marker (测试自身有问题)")
	}
	if _, err := dev.WriteAt([]byte{0xFF}, off); err != nil {
		t.Fatal(err)
	}
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatalf("文件级校验执行失败: %v", err)
	}
	if fv.OK() {
		t.Fatal("内容被破坏后, 文件级校验不应通过")
	}
	if fv.BadCount != 1 {
		t.Errorf("应恰好 1 个文件失败, 实得 %d", fv.BadCount)
	}
	if fv.FirstError() == "" {
		t.Error("应给出失败原因")
	}
}

// 目标盘比计划小 → 直接拒绝, 不写坏盘
func TestBuildCardOnDeviceRejectsSmallDevice(t *testing.T) {
	a, plan := buildTestPkg(t)
	dev := newFileDisk(t, plan.TotalSize-1<<20)
	defer dev.Close()
	if _, err := BuildCardOnDevice(dev, a, plan, nil); err == nil {
		t.Fatal("容量不足时应报错")
	}
}

// devStore.WriteAt 必须做扇区对齐的读-改-写: 改动目标之外的字节一个都不能变
func TestDevStoreWriteAtPreservesNeighbours(t *testing.T) {
	dev := newFileDisk(t, 1<<20)
	defer dev.Close()
	// 铺一层非零底
	base := bytes.Repeat([]byte{0xAA}, 1<<20)
	if _, err := dev.WriteAt(base, 0); err != nil {
		t.Fatal(err)
	}
	st := &devStore{dev: dev}
	// 故意写一个既不对齐开头也不对齐结尾的小块
	payload := []byte{1, 2, 3, 4, 5}
	off := int64(1000)
	if _, err := st.WriteAt(payload, off); err != nil {
		t.Fatal(err)
	}
	got := make([]byte, 1<<20)
	if _, err := dev.ReadAt(got, 0); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got[off:off+int64(len(payload))], payload) {
		t.Error("目标区间内容不对")
	}
	for i := range got {
		if int64(i) >= off && int64(i) < off+int64(len(payload)) {
			continue
		}
		if got[i] != 0xAA {
			t.Fatalf("偏移 %d 的原有内容被改坏了 (0x%02X)", i, got[i])
		}
	}
}

// findMarker 在设备上前若干 MB 内查找 marker 的偏移
func findMarker(t *testing.T, dev DiskDevice, m []byte) int64 {
	t.Helper()
	const blk = 1 << 20
	buf := make([]byte, blk)
	overlap := len(m) - 1
	var carry []byte
	for off := int64(0); off < dev.Size(); off += blk {
		n, _ := dev.ReadAt(buf, off)
		if n <= 0 {
			break
		}
		data := append(append([]byte{}, carry...), buf[:n]...)
		if i := bytes.Index(data, m); i >= 0 {
			return off - int64(len(carry)) + int64(i)
		}
		if len(data) > overlap {
			carry = append([]byte{}, data[len(data)-overlap:]...)
		}
	}
	return -1
}

// 确保 imageFile 辅助仍被使用 (BuildCardImage 的离线路径)
func TestBuildCardImageOfflineStillWorks(t *testing.T) {
	a, plan := buildTestPkg(t)
	dir := t.TempDir()
	img := filepath.Join(dir, "card.img")
	if err := BuildCardImage(a, plan, img, nil); err != nil {
		t.Fatalf("离线建卡失败: %v", err)
	}
	st, err := os.Stat(img)
	if err != nil {
		t.Fatal(err)
	}
	if st.Size() != plan.TotalSize {
		t.Errorf("镜像大小应为 %d, 得 %d", plan.TotalSize, st.Size())
	}
}

// countingDisk 统计真正下发到设备的写入次数与字节数
type countingDisk struct {
	DiskDevice
	writes int
	bytes  int64
}

func (c *countingDisk) WriteAt(p []byte, off int64) (int, error) {
	c.writes++
	c.bytes += int64(len(p))
	return c.DiskDevice.WriteAt(p, off)
}

// 写放大回归: go-diskfs 每分配一次簇都会调 WriteFat。上游实现每次重写整张 FAT
// (两份副本), 大卡上这会把写卡量放大若干倍 —— 本地补丁 5 (只回写脏区间) 修掉了它。
// 这里卡住"物理写入量 ≈ 元数据 + 内容", 而不是"内容 + 若干倍 FAT"。
func TestBuildCardOnDeviceWriteAmplification(t *testing.T) {
	a, plan := buildTestPkg(t)
	dev := newFileDisk(t, plan.TotalSize+1<<20)
	defer dev.Close()

	var content int64
	for _, f := range a.Files {
		content += f.Size
	}
	c := &countingDisk{DiskDevice: dev}
	if _, err := BuildCardOnDevice(c, a, plan, nil); err != nil {
		t.Fatal(err)
	}
	// 允许的额外开销: 卡头 1 MiB + 首次整张 FAT + 对齐
	const slack = 4 << 20
	if c.bytes > content+slack {
		t.Errorf("物理写入 %s 超出 内容 %s + 余量 %s —— FAT 可能又被整张重写了",
			HumanBytes(c.bytes), HumanBytes(content), HumanBytes(slack))
	}
	if c.writes > 2000 {
		t.Errorf("设备写入次数 %d 偏多 (碎写会拖慢写通句柄下的写卡)", c.writes)
	}
}
