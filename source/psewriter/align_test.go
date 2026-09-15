// 设备 I/O 对齐 单测 (MYS-1062 二十一轮, Linux 可跑)
//
// 现场 (Windows): 写文件包到卡时第一步就失败
//
//	✗ 写分区表失败: failed to write partition table: error writing partition table to
//	  disk: 读取对齐头部失败: The parameter is incorrect.
//
// 根因: go-diskfs 写 MBR 分区表用的是偏移 446 (partitionEntriesStart), 长度 66。
// devStore.WriteAt 会把**写入**补齐到 devAlign(4096), 但"读回对齐头部/尾部"用的是
// 字节精确长度 (446 字节 @0) —— Linux 块设备容忍任意偏移/长度的缓冲读, Windows
// 物理盘 (\\\\.\\PhysicalDriveN) 则要求偏移与长度都是扇区整数倍, 否则返回
// ERROR_INVALID_PARAMETER ("The parameter is incorrect")。
//
// 这个缺陷在 Linux 的环回盘冒烟里**永远测不出来** (Linux 不挑对齐), 所以这里造一个
// "只接受对齐读写"的假设备来复现 Windows 行为 —— 它拒绝任何未对齐的 I/O, 正是现场
// 那台机器做的事。
package main

import (
	"fmt"
	"io"
	"os"
	"testing"
)

// alignedOnlyDisk 包一层 fileDisk, 拒绝一切"偏移或长度不是 devAlign 整数倍"的读写。
// 错误文案与 Windows 一致, 便于对照现场日志。
type alignedOnlyDisk struct {
	*fileDisk
	readsBad  int
	writesBad int
}

var errUnaligned = fmt.Errorf("The parameter is incorrect")

func (d *alignedOnlyDisk) check(op string, n int, off int64) error {
	if off%devAlign != 0 || int64(n)%devAlign != 0 {
		if op == "read" {
			d.readsBad++
		} else {
			d.writesBad++
		}
		return errUnaligned
	}
	return nil
}

func (d *alignedOnlyDisk) ReadAt(p []byte, off int64) (int, error) {
	if err := d.check("read", len(p), off); err != nil {
		return 0, err
	}
	return d.fileDisk.ReadAt(p, off)
}

func (d *alignedOnlyDisk) WriteAt(p []byte, off int64) (int, error) {
	if err := d.check("write", len(p), off); err != nil {
		return 0, err
	}
	return d.fileDisk.WriteAt(p, off)
}

// 回归: 在"只接受对齐 I/O"的设备上建卡必须完整跑通。
// 修复前: 第一步写分区表就读 446 字节 @0 → 直接失败 (与现场日志逐字一致)。
func TestBuildCardOnAlignedOnlyDevice(t *testing.T) {
	a, plan := buildTestPkg(t)
	dev := &alignedOnlyDisk{fileDisk: newFileDisk(t, plan.TotalSize+1<<20)}
	defer dev.Close()

	if _, err := BuildCardOnDevice(dev, a, plan, nil); err != nil {
		t.Fatalf("在只接受对齐 I/O 的设备上建卡失败 (Windows 就是这么报的): %v", err)
	}
	if dev.writesBad > 0 {
		t.Errorf("向设备发出了 %d 次未对齐写入", dev.writesBad)
	}
	if dev.readsBad > 0 {
		t.Errorf("向设备发出了 %d 次未对齐读取", dev.readsBad)
	}
	// 卡上文件级校验同样要能在该设备上跑通 (校验会大量读 FAT/目录/文件)
	fv, err := VerifyCardFiles(dev, a, 1, nil)
	if err != nil {
		t.Fatalf("在只接受对齐 I/O 的设备上做文件级校验失败: %v", err)
	}
	if !fv.OK() {
		t.Fatalf("文件级校验未通过: %s / %s", fv.Summary(), fv.FirstError())
	}
}

// 定点: 模拟 go-diskfs 写 MBR 分区表的那一次写 (偏移 446 / 长度 66)
func TestDevStoreRMWAlignsEdges(t *testing.T) {
	base := newFileDisk(t, 1<<20)
	defer base.Close()
	// 预置一点内容, 验证"读-改-写"没有破坏边角数据
	pre := make([]byte, devAlign)
	for i := range pre {
		pre[i] = 0xA5
	}
	if _, err := base.WriteAt(pre, 0); err != nil {
		t.Fatal(err)
	}
	pre2 := make([]byte, devAlign)
	for i := range pre2 {
		pre2[i] = 0x5A
	}
	if _, err := base.WriteAt(pre2, devAlign); err != nil {
		t.Fatal(err)
	}

	dev := &alignedOnlyDisk{fileDisk: base}
	st := newDevStore(dev, nil) // 走真实构造路径 (内部套对齐层)

	// 就是 MBR 分区表那一笔
	payload := make([]byte, 66)
	for i := range payload {
		payload[i] = byte(i)
	}
	if _, err := st.WriteAt(payload, 446); err != nil {
		t.Fatalf("写偏移 446 (MBR 分区表) 失败: %v", err)
	}
	if dev.readsBad > 0 || dev.writesBad > 0 {
		t.Fatalf("发出了未对齐 I/O: 读 %d 次 / 写 %d 次", dev.readsBad, dev.writesBad)
	}

	// 请求区间被正确写入
	got := make([]byte, 66)
	if _, err := base.ReadAt(got, 446); err != nil {
		t.Fatal(err)
	}
	for i := range got {
		if got[i] != byte(i) {
			t.Fatalf("偏移 446 处内容不对: got[%d]=%#x", i, got[i])
		}
	}
	// 边角 (0..446 与 512..4096) 必须保持原值
	edge := make([]byte, 446)
	if _, err := base.ReadAt(edge, 0); err != nil {
		t.Fatal(err)
	}
	for i, b := range edge {
		if b != 0xA5 {
			t.Fatalf("头部边角被破坏: [%d]=%#x (应为 0xA5)", i, b)
		}
	}
	tail := make([]byte, devAlign-512)
	if _, err := base.ReadAt(tail, 512); err != nil {
		t.Fatal(err)
	}
	for i, b := range tail {
		if b != 0xA5 {
			t.Fatalf("尾部边角被破坏: [%d]=%#x (应为 0xA5)", i, b)
		}
	}
	// 下一块 (4096 起) 不该被动过
	nxt := make([]byte, 64)
	if _, err := base.ReadAt(nxt, devAlign); err != nil {
		t.Fatal(err)
	}
	for i, b := range nxt {
		if b != 0x5A {
			t.Fatalf("越界写到下一块了: [%d]=%#x (应为 0x5A)", i, b)
		}
	}
}

// devStore.ReadAt 对未对齐请求也要能读 (Windows 上 512 对齐的 FAT 读会被拒)
func TestDevStoreReadUnaligned(t *testing.T) {
	base := newFileDisk(t, 1<<20)
	defer base.Close()
	blk := make([]byte, devAlign)
	for i := range blk {
		blk[i] = byte(i % 251)
	}
	if _, err := base.WriteAt(blk, devAlign); err != nil {
		t.Fatal(err)
	}
	dev := &alignedOnlyDisk{fileDisk: base}
	st := newDevStore(dev, nil)

	// 512 对齐但非 4096 对齐、长度 512 (go-diskfs 读扇区的典型形态)
	buf := make([]byte, 512)
	n, err := st.ReadAt(buf, devAlign+512)
	if err != nil && err != io.EOF {
		t.Fatalf("未对齐读取失败: %v", err)
	}
	if n != 512 {
		t.Fatalf("读了 %d 字节, 期望 512", n)
	}
	for i := range buf {
		if buf[i] != byte((512+i)%251) {
			t.Fatalf("内容不对: buf[%d]=%#x", i, buf[i])
		}
	}
	if dev.readsBad > 0 {
		t.Fatalf("发出了 %d 次未对齐读取", dev.readsBad)
	}
	// 设备本身确实会拒绝未对齐读 (证明这个假设备真的在模拟 Windows)
	if _, err := dev.fileDisk.ReadAt(make([]byte, 446), 0); err != nil {
		t.Fatal(err)
	}
	if _, err := (&alignedOnlyDisk{fileDisk: base}).ReadAt(make([]byte, 446), 0); err == nil {
		t.Fatal("假设备没有拒绝未对齐读, 测试前提不成立")
	}
	_ = os.ErrNotExist
}
