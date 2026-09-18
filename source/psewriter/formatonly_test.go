// 只格式化模式 (MYS-1237) + 大卡 FAT32 几何回归 单测 (Linux 可跑)
//
// 只格式化与"写文件包"走的是同一个 buildCardFS, 差别只在计划里有没有文件;
// 这里卡住的是它真正的承诺: 卡上留下一个**空的、能被解析、能继续放文件**的 FAT32。
package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"testing"

	"github.com/diskfs/go-diskfs"
)

// ---------- 分区计划 ----------

func TestPlanFormatOnly(t *testing.T) {
	t.Run("整卡一个 FAT32 分区", func(t *testing.T) {
		const size = 8 << 30
		plan, err := PlanFormatOnly(size, "")
		if err != nil {
			t.Fatal(err)
		}
		if plan.TotalSize != size {
			t.Errorf("卡容量应为整卡 %d, 得 %d", size, plan.TotalSize)
		}
		if plan.PartSize != size-partStartLBA*sectorSize {
			t.Errorf("分区大小应为 %d, 得 %d", size-partStartLBA*sectorSize, plan.PartSize)
		}
		if len(plan.Files) != 0 || len(plan.Dirs) != 0 {
			t.Errorf("只格式化不该带任何文件/目录, 得 %d/%d", len(plan.Files), len(plan.Dirs))
		}
		if plan.Label != "SE" {
			t.Errorf("默认卷标应为 SE, 得 %q", plan.Label)
		}
	})

	t.Run("卷标规范化", func(t *testing.T) {
		plan, err := PlanFormatOnly(8<<30, "se7 boot!")
		if err != nil {
			t.Fatal(err)
		}
		if plan.Label != "SE7-BOOT" {
			t.Errorf("卷标应规范化为 SE7-BOOT, 得 %q", plan.Label)
		}
	})

	t.Run("太小报错", func(t *testing.T) {
		if _, err := PlanFormatOnly(minFAT32Size-1, ""); err == nil {
			t.Error("小于 FAT32 下限应报错")
		}
	})

	t.Run("容量未知报错", func(t *testing.T) {
		if _, err := PlanFormatOnly(0, ""); err == nil {
			t.Error("容量为 0 应报错")
		}
	})

	t.Run("超过 FAT32 上限按上限建", func(t *testing.T) {
		plan, err := PlanFormatOnly(fat32MaxSize*2, "")
		if err != nil {
			t.Fatal(err)
		}
		if plan.TotalSize != fat32MaxSize {
			t.Errorf("应被截到 FAT32 上限 %d, 得 %d", fat32MaxSize, plan.TotalSize)
		}
	})
}

func TestPrepareFormat(t *testing.T) {
	prep, err := PrepareFormat(8<<30, "")
	if err != nil {
		t.Fatal(err)
	}
	if !prep.IsCard() {
		t.Error("只格式化也算建卡路径 (写后要核对文件系统结构)")
	}
	if !prep.IsFormatOnly() {
		t.Error("应判定为只格式化")
	}
	if prep.Archive != nil || prep.Src != nil {
		t.Error("只格式化不该有数据源")
	}
	if prep.TotalSize() != 8<<30 {
		t.Errorf("占用容量应为整卡, 得 %d", prep.TotalSize())
	}
}

// 文件包模式不能被误判成只格式化
func TestPreparedSourceNotFormatOnlyForPackage(t *testing.T) {
	_, plan := buildTestPkg(t)
	prep := &PreparedSource{Archive: &Archive{}, Plan: plan}
	if prep.IsFormatOnly() {
		t.Error("带归档的来源不该判为只格式化")
	}
}

// ---------- 卡上落地 ----------

// formatFakeDevice 在模拟设备上只格式化, 返回设备与计划
func formatFakeDevice(t *testing.T, size int64, label string) (*fileDisk, *PackagePlan) {
	t.Helper()
	plan, err := PlanFormatOnly(size, label)
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize)
	t.Cleanup(func() { dev.Close() })
	if _, err := BuildCardOnDevice(dev, nil, plan, nil); err != nil {
		t.Fatalf("只格式化失败: %v", err)
	}
	return dev, plan
}

// 只格式化的核心承诺: 卡上是空的 (没有任何文件), 但格式本身完全正确
func TestFormatCardOnDeviceLeavesEmptyValidFAT32(t *testing.T) {
	dev, plan := formatFakeDevice(t, 8<<30, "")

	lay, err := VerifyCardLayout(dev, plan, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !lay.OK() {
		t.Fatalf("文件系统结构核对未通过: %v", lay.Problems)
	}

	// 挂上卡上的 FAT32, 根目录必须是空的
	d, err := diskfs.OpenBackend(newDevBackend(dev), diskfs.WithSectorSize(diskfs.SectorSize512))
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	cfs, err := d.GetFilesystem(1)
	if err != nil {
		t.Fatalf("挂载卡上 FAT32 失败: %v", err)
	}
	// go-diskfs 的根目录写作 "." (io/fs 的路径规范: 不接受前导斜杠)
	ents, err := cfs.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	if len(ents) != 0 {
		names := make([]string, 0, len(ents))
		for _, e := range ents {
			names = append(names, e.Name())
		}
		t.Fatalf("只格式化后卡根应为空, 实得 %d 项: %v", len(ents), names)
	}
}

// 格式化出来的卡必须能继续放文件 —— 这才证明 FAT 表真的建对了
// (FAT 比卷所需簇数还小时, 建的时候看不出来, 一分配簇就越界)
func TestFormattedCardAcceptsFiles(t *testing.T) {
	dev, _ := formatFakeDevice(t, 8<<30, "")

	// 用可写 backend 挂同一张卡
	d, err := diskfs.OpenBackend(newDevStore(dev, nil), diskfs.WithSectorSize(diskfs.SectorSize512))
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	cfs, err := d.GetFilesystem(1)
	if err != nil {
		t.Fatal(err)
	}
	want := bytes.Repeat([]byte("SE7\n"), 100000) // 400 KB, 跨多个簇
	w, err := cfs.OpenFile("/fip.bin", os.O_CREATE|os.O_RDWR)
	if err != nil {
		t.Fatalf("格式化后的卡上建文件失败: %v", err)
	}
	if _, err := w.Write(want); err != nil {
		t.Fatalf("写文件失败: %v", err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}

	rc, err := cfs.OpenFile("/fip.bin", os.O_RDONLY)
	if err != nil {
		t.Fatalf("读回文件失败: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Errorf("读回内容不一致 (%d vs %d 字节)", len(got), len(want))
	}
}

// 只格式化 + 写后回读校验的完整流程 (RunFlash)
func TestRunFlashFormatOnly(t *testing.T) {
	plan, err := PlanFormatOnly(8<<30, "")
	if err != nil {
		t.Fatal(err)
	}
	dev := newFileDisk(t, plan.TotalSize)
	defer dev.Close()

	prep, err := PrepareFormat(plan.TotalSize, "")
	if err != nil {
		t.Fatal(err)
	}
	out, err := RunFlash(&DiskInfo{Path: dev.Path()}, prep, true, nil, nil)
	if err != nil {
		t.Fatalf("只格式化流程失败: %v", err)
	}
	if !out.IsCard || !out.FormatOnly {
		t.Fatalf("应判为只格式化, 得 IsCard=%v FormatOnly=%v", out.IsCard, out.FormatOnly)
	}
	if out.Layout == nil || !out.Layout.OK() {
		t.Fatalf("回读结构核对未通过: %+v", out.Layout)
	}
	if out.FileVerify != nil {
		t.Error("只格式化没有文件可做文件级校验")
	}
	if !out.OK() {
		t.Error("整体结果应为成功")
	}
	if out.Card.SkippedBytes <= 0 {
		t.Error("只格式化只该写元数据, 未触碰空间应远大于零")
	}
}

// ---------- 大卡 FAT32 几何回归 (third_party 补丁 7) ----------

// checkFAT32Geometry 格式化一张 size 字节的卡, 核对 BPB 里的 FAT 表放得下卷里每一个数据簇。
//
// 不变量 (与 mkfs.fat 的检查一致): (total - rsvd - nfat*fatSz) / spc + 2 <= fatSz * bps / 4
// 左边是卷实际需要的簇数 (+2 是 FAT 保留的头两个表项), 右边是 FAT 表能表示的表项数。
// 上游 v1.9.4 三处出错: 4*total 溢出 uint32 (≥512 GiB 直接 panic)、结果窄化成 uint16
// (≥256 GiB 被截断)、分子漏 +8*spc (14/15/30/60 GB 等少算 1~2 个表项)。
// 症状都是"卡格式化完了却挂不上/一写就坏", 只在特定容量上出现, 现场很难查。
func checkFAT32Geometry(t *testing.T, size int64) {
	t.Helper()
	dev, _ := formatFakeDevice(t, size, "")
	bpb := make([]byte, 512)
	if _, err := dev.ReadAt(bpb, partStartLBA*sectorSize); err != nil {
		t.Fatal(err)
	}
	bps := int64(binary.LittleEndian.Uint16(bpb[11:13]))
	spc := int64(bpb[13])
	rsvd := int64(binary.LittleEndian.Uint16(bpb[14:16]))
	nfat := int64(bpb[16])
	fatSz := int64(binary.LittleEndian.Uint32(bpb[36:40]))
	total := int64(binary.LittleEndian.Uint32(bpb[32:36]))
	if bps <= 0 || spc <= 0 || fatSz <= 0 {
		t.Fatalf("BPB 关键字段为零: bps=%d spc=%d fatSz=%d", bps, spc, fatSz)
	}
	clusters := (total - rsvd - nfat*fatSz) / spc
	entries := fatSz * bps / 4 // FAT 表能表示多少个簇
	if clusters+2 > entries {
		t.Errorf("FAT 表太小: 卷有 %d 个簇, 表只放得下 %d 个 (fatSz=%d) —— 这个容量上会挂载失败/写坏数据",
			clusters, entries, fatSz)
	}
	// 数据区起点不能超出 FAT32 的 32 位寻址能力
	if dataStart := (rsvd + nfat*fatSz) * bps; dataStart >= 1<<32 {
		t.Errorf("数据区起点 %d 超出 32 位寻址范围", dataStart)
	}
}

// 逐个容量扫一遍。**必须扫**而不是挑几个"大卡"当代表: 漏掉 +8*spc 那一项时,
// 出问题的恰恰是 14/15/30/60 GB 这些不起眼的容量, 而 256/384/512/1024 GB 全是好的。
func TestFAT32GeometryOnLargeCards(t *testing.T) {
	if testing.Short() {
		t.Skip("几何扫描要建稀疏文件")
	}
	// 8~48 GB 逐 GB (覆盖 uint16 截断之前的全部簇大小档位与 +8*spc 的缺口)
	for gb := int64(8); gb <= 48; gb++ {
		t.Run(fmt.Sprintf("%dGB", gb), func(t *testing.T) { checkFAT32Geometry(t, gb<<30) })
	}
	// 大卡: uint16 截断 (≥256 GiB) 与 uint32 溢出 (≥512 GiB) 的分界
	for _, gb := range []int64{256, 384, 512, 1024} {
		t.Run(fmt.Sprintf("%dGB", gb), func(t *testing.T) { checkFAT32Geometry(t, gb<<30) })
	}
}

// 只格式化的卡与"写文件包"建出来的卡必须是同一种格式 —— 现场两边的卡可以互换
func TestFormatOnlyMatchesPackageCardLayout(t *testing.T) {
	const size = 8 << 30
	dev, plan := formatFakeDevice(t, size, "")

	a, pkgPlan := buildTestPkg(t)
	pkgPlan.TotalSize = size
	pkgPlan.PartSize = size - partStartLBA*sectorSize
	devPkg := newFileDisk(t, size)
	defer devPkg.Close()
	if _, err := BuildCardOnDevice(devPkg, a, pkgPlan, nil); err != nil {
		t.Fatal(err)
	}

	read := func(d DiskDevice) (spc byte, fatSz uint32, total uint32) {
		b := make([]byte, 512)
		if _, err := d.ReadAt(b, partStartLBA*sectorSize); err != nil {
			t.Fatal(err)
		}
		return b[13], binary.LittleEndian.Uint32(b[36:40]), binary.LittleEndian.Uint32(b[32:36])
	}
	spcA, fatA, totA := read(dev)
	spcB, fatB, totB := read(devPkg)
	if spcA != spcB || fatA != fatB || totA != totB {
		t.Errorf("只格式化 (spc=%d fatSz=%d total=%d) 与文件包模式 (spc=%d fatSz=%d total=%d) 的 FAT32 布局不一致",
			spcA, fatA, totA, spcB, fatB, totB)
	}
	if plan.Label != pkgPlan.Label && pkgPlan.Label != "SE" {
		t.Logf("卷标不同 (只格式化 %q / 文件包 %q) —— 由来源名推导, 属预期", plan.Label, pkgPlan.Label)
	}
}
