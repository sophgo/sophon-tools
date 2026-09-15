// 设备 I/O 对齐 (MYS-1062 二十一轮)
//
// 为什么需要这一层: Windows 物理盘 (\\.\PhysicalDriveN) 要求**偏移与长度都是扇区
// 整数倍**的读写, 否则 ReadFile/WriteFile 直接返回 ERROR_INVALID_PARAMETER
// ("The parameter is incorrect")。而 go-diskfs 是按"字节精确"来读写文件系统的 ——
// 最典型的是写 MBR 分区表: 偏移 446 (partitionEntriesStart)、长度 66。
// Linux 块设备容忍这种未对齐访问 (内核帮你对齐), 所以这个缺陷在 13.24 的环回盘
// 冒烟里永远暴露不出来, 只有 Windows 实机才会炸。
//
// 做法: 把任意 DiskDevice 包一层, 对外只发出 devAlign 对齐的 I/O ——
//
//	写: 读-改-写 (只要边角那两小块, 中间整块被覆盖的部分不读)
//	读: 未对齐时读回覆盖区间再把请求的那段拷出来
//
// 建卡 (devStore)、写后校验 (devBackend)、以及任何其他用到设备的地方都走这一层,
// 保证"设备侧看到的每一次 I/O 都是对齐的"。
package main

import (
	"errors"
	"io"
)

// devAlign 对物理设备读写的最小对齐 (512B/4Kn 扇区都安全)
const devAlign = 4096

// roundUpAlign 向上取整到 devAlign (<=0 → 0)
func roundUpAlign(n int64) int64 {
	if n <= 0 {
		return 0
	}
	if r := n % devAlign; r != 0 {
		return n + devAlign - r
	}
	return n
}

// alignedDevice 把 DiskDevice 包成"只发出对齐 I/O"的设备。
type alignedDevice struct {
	dev   DiskDevice
	track *extentSet // 非 nil 时记录写过的区间 (建卡的"实写字节数"统计)
}

// newAlignedDevice 包装设备; track 可为 nil。
func newAlignedDevice(dev DiskDevice, track *extentSet) *alignedDevice {
	return &alignedDevice{dev: dev, track: track}
}

func (a *alignedDevice) Path() string { return a.dev.Path() }
func (a *alignedDevice) Size() int64  { return a.dev.Size() }
func (a *alignedDevice) Sync() error  { return a.dev.Sync() }
func (a *alignedDevice) Close() error { return a.dev.Close() }

// SyncNote 透传平台层的收尾告警 (Windows 专用; 其他平台没有这个方法)
func (a *alignedDevice) SyncNote() string {
	if n, ok := a.dev.(interface{ SyncNote() string }); ok {
		return n.SyncNote()
	}
	return ""
}

// ReadAt 未对齐时先按 devAlign 读回覆盖区间, 再把请求的那段拷出来。
func (a *alignedDevice) ReadAt(p []byte, off int64) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	if off < 0 {
		return 0, errors.New("负偏移")
	}
	if off%devAlign == 0 && int64(len(p))%devAlign == 0 {
		return a.dev.ReadAt(p, off) // 已对齐 → 直通, 不额外拷贝
	}
	start := off - off%devAlign
	end := roundUpAlign(off + int64(len(p)))
	if size := a.dev.Size(); size > 0 && end > size {
		end = size
	}
	if end <= off {
		return 0, io.EOF
	}
	tmp := make([]byte, end-start)
	n, err := a.dev.ReadAt(tmp, start)
	lo := off - start
	hi := lo + int64(len(p))
	if int64(n) < hi {
		hi = int64(n)
	}
	if hi > lo {
		copy(p[:hi-lo], tmp[lo:hi])
		return int(hi - lo), err
	}
	return 0, err
}

// WriteAt 读-改-写: 把 [off, off+len(p)) 所在的对齐区间整体写回。
// 只有首尾不足一个对齐单元的边角需要先读回来 (中间整块被覆盖的部分不必读),
// 所以写 7 MiB 的 FAT 表时不会额外读 7 MiB。
//
// 头/尾这两次"读回来"同样必须按 devAlign 对齐着读 —— 用字节精确长度去读正是
// 现场那次失败的根因 (读 446 字节 @0 → Windows 报 The parameter is incorrect)。
func (a *alignedDevice) WriteAt(p []byte, off int64) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	if off < 0 {
		return 0, errors.New("负偏移")
	}
	if size := a.dev.Size(); size > 0 && off+int64(len(p)) > size {
		return 0, errors.New("写入越界: 超出设备容量")
	}
	start := off - off%devAlign
	end := roundUpAlign(off + int64(len(p)))
	buf := make([]byte, end-start)
	if head := off - start; head > 0 {
		hLen := roundUpAlign(head) // 从 start (已对齐) 读整数个 devAlign
		if _, err := a.dev.ReadAt(buf[:hLen], start); err != nil {
			return 0, errors.New("读取对齐头部失败: " + err.Error())
		}
	}
	if tail := end - (off + int64(len(p))); tail > 0 {
		tLen := roundUpAlign(tail) // 读到 end (已对齐) 之前的整数个 devAlign
		tStart := end - tLen
		if tStart < start {
			tStart, tLen = start, end-start
		}
		if _, err := a.dev.ReadAt(buf[tStart-start:], tStart); err != nil {
			return 0, errors.New("读取对齐尾部失败: " + err.Error())
		}
	}
	copy(buf[off-start:], p)
	if _, err := a.dev.WriteAt(buf, start); err != nil {
		return 0, err
	}
	if a.track != nil {
		a.track.add(off, int64(len(p)))
	}
	return len(p), nil
}
