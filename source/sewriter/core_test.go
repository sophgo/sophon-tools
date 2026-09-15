// 核心逻辑单测 (Linux 可跑): 安全分级 / 镜像源 / 写入+回读校验
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/rand"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fileDisk — 用普通文件模拟块设备 (与真实盘走同一 DiskDevice 接口)
type fileDisk struct {
	f    *os.File
	size int64
}

func (d *fileDisk) Path() string { return d.f.Name() }
func (d *fileDisk) Size() int64  { return d.size }
func (d *fileDisk) WriteAt(p []byte, off int64) (int, error) {
	if off+int64(len(p)) > d.size {
		return 0, os.ErrInvalid
	}
	return d.f.WriteAt(p, off)
}
func (d *fileDisk) ReadAt(p []byte, off int64) (int, error) { return d.f.ReadAt(p, off) }
func (d *fileDisk) Sync() error                             { return d.f.Sync() }
func (d *fileDisk) Close() error                            { return d.f.Close() }

func newFileDisk(t *testing.T, size int64) *fileDisk {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "disk-*.img")
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Truncate(size); err != nil {
		t.Fatal(err)
	}
	return &fileDisk{f: f, size: size}
}

func TestClassifySafety(t *testing.T) {
	cases := []struct {
		name string
		d    DiskInfo
		want Safety
	}{
		{"系统盘", DiskInfo{System: true, BusType: "SATA"}, SafetyDangerous},
		{"USB 读卡器", DiskInfo{BusType: "USB"}, SafetySafe},
		{"SD 总线", DiskInfo{BusType: "SD"}, SafetySafe},
		{"MMC", DiskInfo{BusType: "MMC"}, SafetySafe},
		{"可移动标记", DiskInfo{BusType: "VIRTUAL", Removable: true}, SafetySafe},
		{"内置 NVMe", DiskInfo{BusType: "NVMe"}, SafetyUnknown},
		{"内置 SATA", DiskInfo{BusType: "SATA"}, SafetyUnknown},
	}
	for _, c := range cases {
		d := c.d
		Classify(&d)
		if d.Safety != c.want {
			t.Errorf("%s: 期望 %v, 实得 %v", c.name, c.want, d.Safety)
		}
	}
}

func TestSelectableDisksHidesSystemAndFixed(t *testing.T) {
	sys := &DiskInfo{Index: 0, System: true}
	fixed := &DiskInfo{Index: 1, BusType: "NVMe"}
	usb := &DiskInfo{Index: 2, BusType: "USB"}
	for _, d := range []*DiskInfo{sys, fixed, usb} {
		Classify(d)
	}
	got := SelectableDisks([]*DiskInfo{sys, fixed, usb}, false)
	if len(got) != 1 || got[0].Index != 2 {
		t.Fatalf("默认视图应只含 USB 卡, 实得 %d 项", len(got))
	}
	got = SelectableDisks([]*DiskInfo{sys, fixed, usb}, true)
	if len(got) != 2 {
		t.Fatalf("showAll 应含 USB+固定盘 (系统盘仍排除), 实得 %d 项", len(got))
	}
}

func TestPadSector(t *testing.T) {
	if got := padSector(make([]byte, 4096)); len(got) != 4096 {
		t.Errorf("对齐数据不应扩容, 得 %d", len(got))
	}
	got := padSector([]byte{1, 2, 3})
	if len(got) != 4096 || got[0] != 1 || got[2] != 3 || got[3] != 0 {
		t.Errorf("补零结果错误: len=%d", len(got))
	}
}

func TestOpenImageRawAndGzip(t *testing.T) {
	dir := t.TempDir()
	raw := filepath.Join(dir, "a.img")
	payload := make([]byte, 100000)
	if _, err := rand.Read(payload); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(raw, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	src, err := OpenImage(raw)
	if err != nil || src.Size() != int64(len(payload)) || src.gzip {
		t.Fatalf("raw 镜像解析错误: %+v err=%v", src, err)
	}

	gz := filepath.Join(dir, "a.img.gz")
	f, _ := os.Create(gz)
	zw := gzip.NewWriter(f)
	zw.Write(payload)
	zw.Close()
	f.Close()
	src, err = OpenImage(gz)
	if err != nil || !src.gzip || src.Size() != int64(len(payload)) {
		t.Fatalf("gz 镜像解析错误: size=%d gz=%v err=%v", src.Size(), src.gzip, err)
	}
	rc, err := src.Open()
	if err != nil {
		t.Fatal(err)
	}
	defer rc.Close()
	buf := make([]byte, len(payload))
	if n, err := readFull(rc, buf); err != nil || n != len(payload) {
		t.Fatalf("gz 解压读取失败: n=%d err=%v", n, err)
	}
	if !bytes.Equal(buf, payload) {
		t.Fatal("gz 解压内容不一致")
	}
}

func TestFlashWriteAndVerify(t *testing.T) {
	dir := t.TempDir()
	imgPath := filepath.Join(dir, "img.bin")
	payload := make([]byte, 3*chunkSize+12345) // 非整块: 覆盖末块补零路径
	if _, err := rand.Read(payload); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(imgPath, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	src, err := OpenImage(imgPath)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, 64<<20)
	defer dev.Close()

	res, err := Flash(dev, src, true, nil)
	if err != nil {
		t.Fatalf("烧录失败: %v", err)
	}
	if res.WrittenBytes != int64(len(payload)) {
		t.Errorf("写入字节数错误: %d", res.WrittenBytes)
	}
	if !res.VerifyOK || res.MismatchCnt != 0 {
		t.Errorf("校验应通过: ok=%v mismatch=%d", res.VerifyOK, res.MismatchCnt)
	}
	if res.SHA256 != res.ReadSHA256 {
		t.Errorf("sha256 应一致:\n %s\n %s", res.SHA256, res.ReadSHA256)
	}
	// 盘上内容与镜像一致
	got := make([]byte, len(payload))
	if _, err := dev.ReadAt(got, 0); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatal("盘上内容与镜像不一致")
	}
}

func TestFlashDetectsCorruption(t *testing.T) {
	dir := t.TempDir()
	imgPath := filepath.Join(dir, "img.bin")
	payload := bytes.Repeat([]byte{0xA5}, 2*chunkSize)
	if err := os.WriteFile(imgPath, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	src, _ := OpenImage(imgPath)
	dev := newFileDisk(t, 32<<20)
	defer dev.Close()
	if _, err := Flash(dev, src, true, nil); err != nil {
		t.Fatal(err)
	}
	// 破坏盘上 1MiB+123 处一个字节 → verify 必须发现
	if _, err := dev.WriteAt([]byte{0x00}, int64(chunkSize)+123); err != nil {
		t.Fatal(err)
	}
	res := &FlashResult{ImageBytes: int64(len(payload)), MismatchOff: -1}
	if err := VerifyOnly(dev, src, nil, res); err != nil {
		t.Fatal(err)
	}
	if res.VerifyOK {
		t.Fatal("损坏后校验不应通过")
	}
	if res.MismatchOff != int64(chunkSize)+123 || res.MismatchCnt != 1 {
		t.Fatalf("不一致定位错误: off=%d cnt=%d", res.MismatchOff, res.MismatchCnt)
	}
}

func TestFlashRejectsTooSmallTarget(t *testing.T) {
	dir := t.TempDir()
	imgPath := filepath.Join(dir, "img.bin")
	if err := os.WriteFile(imgPath, make([]byte, 8<<20), 0o644); err != nil {
		t.Fatal(err)
	}
	src, _ := OpenImage(imgPath)
	dev := newFileDisk(t, 1<<20) // 1MiB 盘 vs 8MiB 镜像
	defer dev.Close()
	if _, err := Flash(dev, src, true, nil); err == nil {
		t.Fatal("目标过小应报错")
	}
}

func TestParseDiskArg(t *testing.T) {
	if got := ParseDiskArg("3"); got != `\\.\PhysicalDrive3` {
		t.Errorf("数字应转物理盘路径, 得 %q", got)
	}
	if got := ParseDiskArg("/dev/loop0"); got != "/dev/loop0" {
		t.Errorf("路径应原样保留, 得 %q", got)
	}
}

func readFull(r interface{ Read([]byte) (int, error) }, p []byte) (int, error) {
	done := 0
	for done < len(p) {
		n, err := r.Read(p[done:])
		done += n
		if err != nil {
			if err == io.EOF && done == len(p) {
				return done, nil
			}
			return done, err
		}
	}
	return done, nil
}

// ---- 内置镜像 (MYS-1062 四轮) ----

func TestEmbeddedSource(t *testing.T) {
	meta := EmbeddedImageInfo()
	if !HasEmbeddedImage() {
		// 仓库默认状态: 未内置 → 必须给出可操作的错误
		if _, err := OpenEmbedded(); err == nil {
			t.Fatal("未内置镜像时 OpenEmbedded 应报错")
		}
		t.Log("未内置镜像: 走外部文件路径 (预期)")
		return
	}
	src, err := OpenEmbedded()
	if err != nil {
		t.Fatalf("内置镜像打开失败: %v", err)
	}
	if !src.Embedded() {
		t.Fatal("内置镜像源应标记 Embedded()")
	}
	if meta != nil {
		if src.Size() != meta.Bytes {
			t.Errorf("内置镜像解压大小 %d ≠ meta %d", src.Size(), meta.Bytes)
		}
		if src.Display() != meta.File {
			t.Errorf("展示名 %q ≠ meta %q", src.Display(), meta.File)
		}
		// 内容 sha256 必须与 meta 声明一致 (内置数据完整性)
		h, n, err := ExportImageSHA256Src(src)
		if err != nil {
			t.Fatal(err)
		}
		if meta.SHA256 != "" && h != meta.SHA256 {
			t.Errorf("内置镜像内容 sha256 不符:\n got %s\nwant %s", h, meta.SHA256)
		}
		if meta.Bytes > 0 && n != meta.Bytes {
			t.Errorf("内置镜像字节数 %d ≠ meta %d", n, meta.Bytes)
		}
	}
}

func TestResolveSourceDefaultsToEmbedded(t *testing.T) {
	// 未指定路径 → 内置镜像 (未内置时报错, 不会 panic)
	src, err := resolveSource("")
	if HasEmbeddedImage() {
		if err != nil || src == nil || !src.Embedded() {
			t.Fatalf("应回落到内置镜像: src=%v err=%v", src, err)
		}
	} else if err == nil {
		t.Fatal("未内置镜像且未指定路径时应报错")
	}
}

func TestEmbeddedMetaJSONTags(t *testing.T) {
	// payload meta 字段名契约 (写入程序尾部, 改动即破坏内置信息展示与 repack 兼容)
	var m PayloadMeta
	b := []byte(`{"file":"x.img.gz","bytes":123,"sha256":"ab","stored_bytes":9,"stored_sha256":"cd","compressed":true,"packed_at":"2026-09-14T20:00:00+08:00","source_path":"/p","build_ver":"1.5.1","tool_version":"1.2.0","origin":"repack","skeleton_bytes":4096,"skeleton_sha256":"ef"}`)
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	if m.File != "x.img.gz" || m.Bytes != 123 || m.SHA256 != "ab" || m.StoredBytes != 9 ||
		!m.Compressed || m.PackedAt == "" || m.BuildVer != "1.5.1" || m.ToolVersion != "1.2.0" ||
		m.Origin != "repack" || m.SkeletonBytes != 4096 {
		t.Fatalf("meta 字段解析错误: %+v", m)
	}
}

// ---- 界面/命令行文本格式 (MYS-1062 七轮: 中文对齐与属性行) ----

func TestDisplayWidthCountsCJKAsTwo(t *testing.T) {
	cases := []struct {
		s string
		w int
	}{
		{"", 0},
		{"abc", 3},
		{"型号", 4},
		{"目标磁盘", 8},
		{"内容 sha256", 11},
		{"总线 / 介质", 11}, // 总(2)线(2)+空格+/+空格+介(2)质(2)
	}
	for _, c := range cases {
		if got := displayWidth(c.s); got != c.w {
			t.Errorf("displayWidth(%q) = %d, 期望 %d", c.s, got, c.w)
		}
	}
}

func TestPadRightAlignsMixedWidthLabels(t *testing.T) {
	labels := []string{"型号", "目标磁盘", "内容 sha256", "abc"}
	for _, l := range labels {
		if got := displayWidth(padRight(l, 12)); got != 12 {
			t.Errorf("padRight(%q, 12) 显示宽度 = %d, 期望 12", l, got)
		}
	}
	// 已超宽的原样返回 (不截断)
	if got := padRight("内容 sha256", 4); got != "内容 sha256" {
		t.Errorf("超宽标签不应被修改, 得 %q", got)
	}
}

func TestDetailTextLabelsAligned(t *testing.T) {
	d := &DiskInfo{
		Index: 1, Path: `\\.\PhysicalDrive1`, Model: "ZHITAI TiPlus7100 2TB",
		Size: 1907 << 20, BusType: "NVMe", Removable: false,
		Partitions: []Partition{{Index: 1, Offset: 1 << 20, Size: 100 << 30, FSType: "NTFS", Label: "Data", DriveLetter: "D:"}},
	}
	Classify(d) // NVMe 固定盘 → 需人工确认
	txt := d.DetailText()
	// 属性区每行的冒号必须落在同一显示列 (用空格补位中文会错位, 这里锁死该行为)
	colonCol := -1
	for _, line := range strings.Split(txt, "\n") {
		if line == "" || strings.HasPrefix(line, "分区现状") || strings.HasPrefix(line, "  ") {
			continue
		}
		i := strings.Index(line, ": ")
		if i < 0 {
			t.Fatalf("属性行缺少分隔符: %q", line)
		}
		col := displayWidth(line[:i])
		if colonCol < 0 {
			colonCol = col
		} else if col != colonCol {
			t.Errorf("冒号未对齐: %q 在第 %d 列, 期望 %d 列", line, col, colonCol)
		}
	}
	if colonCol < 0 {
		t.Fatal("未解析到任何属性行")
	}
}

func TestDiskPropertyRows(t *testing.T) {
	d := &DiskInfo{
		Index: 2, Path: "/dev/sdb", Model: "USB Disk", Size: 8 << 30,
		BusType: "USB", Removable: true,
		Partitions: []Partition{{Index: 1, Size: 7 << 30, Offset: 1 << 20, FSType: "FAT32", Label: "BOOT", DriveLetter: "E:"}},
	}
	Classify(d)
	rows := d.PropertyRows()
	if len(rows) == 0 {
		t.Fatal("属性行不应为空")
	}
	for i, r := range rows {
		if r[0] == "" || r[1] == "" {
			t.Errorf("第 %d 行存在空列: %v", i, r)
		}
	}
	joined := ""
	for _, r := range rows {
		joined += r[0] + "=" + r[1] + ";"
	}
	for _, want := range []string{"设备路径=/dev/sdb", "磁盘号=磁盘 2", "容量=8.00 GiB", "安全判定=可安全烧录"} {
		if !strings.Contains(joined, want) {
			t.Errorf("属性行缺少 %q, 实得 %s", want, joined)
		}
	}
	// 型号缺失时用 "-" 占位, 不留空
	blank := &DiskInfo{Index: 0, Path: "x"}
	for _, r := range blank.PropertyRows() {
		if strings.TrimSpace(r[1]) == "" {
			t.Errorf("空字段应显示占位符, 得空值的行: %v", r)
		}
	}
}

func TestPartitionRows(t *testing.T) {
	d := &DiskInfo{Partitions: []Partition{
		{Index: 1, Size: 1 << 30, Offset: 1 << 20, FSType: "FAT32", Label: "BOOT", DriveLetter: "E:"},
		{Index: 2, Size: 2 << 30, Offset: 2 << 30},
	}}
	rows := d.PartitionRows()
	if len(rows) != 2 {
		t.Fatalf("应有两行分区, 得 %d", len(rows))
	}
	for i, r := range rows {
		if len(r) != 6 {
			t.Fatalf("第 %d 行列数应为 6, 得 %d", i, len(r))
		}
	}
	if rows[0][0] != "#1" || rows[0][5] != "E:" {
		t.Errorf("首行内容错误: %v", rows[0])
	}
	if rows[1][4] != "-" || rows[1][5] != "-" {
		t.Errorf("缺省字段应显示 '-': %v", rows[1])
	}
	// 空盘 → 无行 (界面显示空表而不是一行空白)
	if (&DiskInfo{}).PartitionRows() != nil {
		t.Error("空盘不应产生分区行")
	}
}

func TestImagePropertyRowsExternalUnavailable(t *testing.T) {
	rows := ImagePropertyRows(filepath.Join(t.TempDir(), "nope.img"))
	if len(rows) == 0 {
		t.Fatal("外部镜像不可用时应给出说明行")
	}
	found := false
	for _, r := range rows {
		if strings.Contains(r[1], "不可用") {
			found = true
		}
	}
	if !found {
		t.Errorf("应提示镜像不可用, 实得 %v", rows)
	}
}

func TestImagePropertyRowsExternalOK(t *testing.T) {
	dir := t.TempDir()
	raw := filepath.Join(dir, "a.img")
	if err := os.WriteFile(raw, make([]byte, 4096), 0o644); err != nil {
		t.Fatal(err)
	}
	rows := ImagePropertyRows(raw)
	joined := ""
	for _, r := range rows {
		joined += r[0] + "=" + r[1] + ";"
	}
	if !strings.Contains(joined, "来源=外部文件") || !strings.Contains(joined, "格式=未压缩 (.img)") {
		t.Errorf("外部镜像属性行不正确: %s", joined)
	}
}

func TestLogDedupSuppressesRepeats(t *testing.T) {
	var d logDedup
	if !d.Accept("发现 2 个磁盘, 可显示 1 个") {
		t.Fatal("首次应接受")
	}
	if d.Accept("发现 2 个磁盘, 可显示 1 个") {
		t.Error("连续重复应被抑制")
	}
	if !d.Accept("发现 2 个磁盘, 可显示 0 个") {
		t.Error("内容变化应接受")
	}
	if !d.Accept("发现 2 个磁盘, 可显示 1 个") {
		t.Error("非连续重复应接受")
	}
	d.Reset()
	if !d.Accept("发现 2 个磁盘, 可显示 1 个") {
		t.Error("Reset 后应接受")
	}
}

// ---------- 稀疏写入 (MYS-1062 十三轮) ----------

// 造一个"大部分是全零"的整盘镜像 (与真实恢复镜像的形态一致)
func writeSparseImage(t *testing.T, size int64, headBytes int) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "sparse.img")
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := f.Truncate(size); err != nil { // 稀疏文件: 后面全是零
		t.Fatal(err)
	}
	head := make([]byte, headBytes)
	rand.Read(head)
	if _, err := f.WriteAt(head, 0); err != nil {
		t.Fatal(err)
	}
	return p
}

// 卡上本来就是零 → 全零块整块跳过, 实际写入量应远小于镜像。
// 判定粒度是写入分块 (1 MiB): 块内只要有一个非零字节就整块写, 避免退化成
// "一个扇区一次 WriteAt" 的碎写。
func TestFlashSkipsZeroBlocksOnBlankCard(t *testing.T) {
	const n = 8 << 20
	img := writeSparseImage(t, n, int(chunkSize))
	src, err := OpenImage(img)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, n)
	defer dev.Close()

	res, err := Flash(dev, src, true, nil)
	if err != nil {
		t.Fatal(err)
	}
	if res.SkippedBytes <= 0 {
		t.Fatal("全零块应被跳过")
	}
	if res.WrittenBytes > 2*chunkSize {
		t.Errorf("实写 %s 应接近内容大小 (%s), 说明大部分零块没被跳过",
			HumanBytes(res.WrittenBytes), HumanBytes(chunkSize))
	}
	if res.SkippedBytes < n-2*chunkSize {
		t.Errorf("应跳过至少 %s, 实得 %s", HumanBytes(n-2*chunkSize), HumanBytes(res.SkippedBytes))
	}
	if !res.VerifyOK {
		t.Errorf("回读校验应通过: mismatch=%d", res.MismatchCnt)
	}
	if res.ImageBytes != n {
		t.Errorf("镜像长度应为 %d, 得 %d", n, res.ImageBytes)
	}
}

// 卡上有旧数据 → 不能跳, 该写的必须写下去 (结果与逐字节写完全一致)
func TestFlashWritesOverOldData(t *testing.T) {
	const n = 4 << 20
	img := writeSparseImage(t, n, 64<<10)
	src, err := OpenImage(img)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, n)
	defer dev.Close()
	// 铺满 0xFF 模拟"用过的卡"
	old := bytes.Repeat([]byte{0xFF}, n)
	if _, err := dev.WriteAt(old, 0); err != nil {
		t.Fatal(err)
	}

	res, err := Flash(dev, src, true, nil)
	if err != nil {
		t.Fatal(err)
	}
	if res.SkippedBytes != 0 {
		t.Errorf("卡上有旧数据时不应跳过任何块, 实得跳过 %d", res.SkippedBytes)
	}
	if res.WrittenBytes != n {
		t.Errorf("应写入全部 %d 字节, 得 %d", n, res.WrittenBytes)
	}
	if !res.VerifyOK {
		t.Fatalf("回读校验应通过: mismatch=%d @ %d", res.MismatchCnt, res.MismatchOff)
	}
	// 卡上内容必须与镜像逐字节一致
	want, _ := os.ReadFile(img)
	got := make([]byte, n)
	if _, err := dev.ReadAt(got, 0); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(want, got) {
		t.Error("卡上内容与镜像不一致")
	}
}

// 取消/中断后不残留: 稀疏跳过只发生在"读回来确认是零"之后 —— 造一个
// 卡上非零块与源零块错位的场景, 确认该块仍被写零覆盖
func TestFlashZeroesMisalignedOldData(t *testing.T) {
	const n = 2 << 20
	img := writeSparseImage(t, n, 4096) // 只有头 4 KiB 有内容 (在第 0 块内)
	src, err := OpenImage(img)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, n)
	defer dev.Close()
	// 把第 1 个 1 MiB 块 (源里全零) 填成非零, 看它有没有被写零覆盖
	off := int64(chunkSize) + 8192
	if _, err := dev.WriteAt(bytes.Repeat([]byte{0x5A}, 4096), off); err != nil {
		t.Fatal(err)
	}
	if _, err := Flash(dev, src, true, nil); err != nil {
		t.Fatal(err)
	}
	got := make([]byte, 4096)
	if _, err := dev.ReadAt(got, off); err != nil {
		t.Fatal(err)
	}
	if !isAllZero(got) {
		t.Error("源块为零而卡上非零时, 必须写零覆盖掉旧数据")
	}
}
