//go:build windows

// Windows 平台层: 物理盘枚举 (DeviceIoControl) + 原始读写 + 卷锁定/卸载
package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"strings"
	"time"
	"unicode/utf16"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	ioctlDiskGetLengthInfo    = 0x0007405C
	ioctlDiskGetDriveLayoutEx = 0x00070050
	ioctlStorageQueryProperty = 0x002D1400
	ioctlVolumeGetDiskExtents = 0x00560000
	ioctlDiskIsWritable       = 0x00074024
	fsctlLockVolume           = 0x00090018
	fsctlUnlockVolume         = 0x0009001C
	fsctlDismountVolume       = 0x00090020
	ioctlDiskUpdateProperties = 0x000700C0
	storageDeviceProperty     = 0
	propertyStandardQuery     = 0
	maxPhysicalDrives         = 32
)

// ---- Win32 结构 (按文档偏移手工解析, 避免依赖 cgo) ----

type diskExtent struct {
	DiskNumber     uint32
	StartingOffset int64
	ExtentLength   int64
}

// enumerateDisks 枚举全部物理盘并按安全策略分级
func enumerateDisks() ([]*DiskInfo, error) {
	sysDisk, sysParts := systemDiskNumbers()
	var out []*DiskInfo
	for i := 0; i < maxPhysicalDrives; i++ {
		path := fmt.Sprintf(`\\.\PhysicalDrive%d`, i)
		h, err := windows.CreateFile(windows.StringToUTF16Ptr(path),
			windows.GENERIC_READ, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil,
			windows.OPEN_EXISTING, 0, 0)
		if err != nil {
			continue
		}
		size, err := diskLength(h)
		if err != nil || size <= 0 {
			windows.CloseHandle(h)
			continue
		}
		d := &DiskInfo{Index: i, Path: path, Size: size}
		d.Model, d.BusType, d.Removable = diskProperty(h)
		if d.Model == "" {
			d.Model = "(未知型号)"
		}
		d.Partitions = diskPartitions(h, i)
		if sysDisk[i] {
			d.System = true
		}
		// 兜底: 分区起始偏移命中系统卷分区 → 也算系统盘
		if !d.System && len(sysParts) > 0 {
			for _, sp := range sysParts {
				for _, p := range d.Partitions {
					if p.Offset == sp.StartingOffset {
						d.System = true
					}
				}
			}
		}
		Classify(d)
		windows.CloseHandle(h)
		out = append(out, d)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("未发现物理磁盘 (需要管理员权限)")
	}
	return out, nil
}

// openDiskDevice 以读写方式打开物理盘
// openDiskDevice 打开可写设备。
//
// 统一在这里套一层 alignedDevice: 上层 (建卡/go-diskfs/校验) 会按字节精确或
// 512B 扇区去访问设备, 而 Windows 物理盘要求偏移与长度都是扇区 (4096) 整数倍 ——
// 只有这一个入口做对齐, 才不会有人漏掉 (现场那次失败就是漏在"读回对齐头部")。
func openDiskDevice(path string) (DiskDevice, error) {
	d, err := openDisk(path, false)
	if err != nil {
		return nil, err
	}
	return newAlignedDevice(d, nil), nil
}

// openDiskDeviceRO 只读打开 (仅校验用, 不写盘)
func openDiskDeviceRO(path string) (DiskDevice, error) {
	d, err := openDisk(path, true)
	if err != nil {
		return nil, err
	}
	return newAlignedDevice(d, nil), nil
}

func openDisk(path string, ro bool) (DiskDevice, error) {
	access := uint32(windows.GENERIC_READ | windows.GENERIC_WRITE)
	if ro {
		access = windows.GENERIC_READ
	}
	// 写句柄带 FILE_FLAG_WRITE_THROUGH: 写操作直通介质, 不留在系统写缓存里
	// (用户反馈: 部分操作系统有写缓存, 必须确保数据真的落到 TF 卡上)
	flags := uint32(0)
	if !ro {
		flags = windows.FILE_FLAG_WRITE_THROUGH
	}
	h, err := windows.CreateFile(windows.StringToUTF16Ptr(path),
		access,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil, windows.OPEN_EXISTING, flags, 0)
	if err != nil {
		return nil, fmt.Errorf("打开 %s 失败 (需以管理员身份运行): %w", path, err)
	}
	sz, err := diskLength(h)
	if err != nil {
		windows.CloseHandle(h)
		return nil, fmt.Errorf("读取 %s 容量失败: %w", path, err)
	}
	return &winDisk{path: path, h: h, size: sz}, nil
}

type winDisk struct {
	path     string
	h        windows.Handle
	size     int64
	syncNote string
}

func (d *winDisk) Path() string { return d.path }
func (d *winDisk) Size() int64  { return d.size }

func (d *winDisk) WriteAt(p []byte, off int64) (int, error) {
	if _, err := windows.Seek(d.h, off, io.SeekStart); err != nil {
		return 0, err
	}
	var done int
	for done < len(p) {
		var n uint32
		if err := windows.WriteFile(d.h, p[done:], &n, nil); err != nil {
			return done, err
		}
		if n == 0 {
			return done, io.ErrShortWrite
		}
		done += int(n)
	}
	return done, nil
}

func (d *winDisk) ReadAt(p []byte, off int64) (int, error) {
	if _, err := windows.Seek(d.h, off, io.SeekStart); err != nil {
		return 0, err
	}
	var done int
	for done < len(p) {
		var n uint32
		err := windows.ReadFile(d.h, p[done:], &n, nil)
		if err != nil {
			return done, err
		}
		if n == 0 {
			break
		}
		done += int(n)
	}
	return done, nil
}

// Sync 收尾: 冲刷设备缓存 + 让系统重枚举分区表。
//
// 现场 (2026-09-15): USB 读卡器上 `IOCTL_DISK_UPDATE_PROPERTIES` 返回
// ERROR_NOT_SUPPORTED, 把整次写入判成了失败 (日志: "刷盘失败 (数据可能仍在缓存):
// The request is not supported."), 而数据其实已经写完。修正:
//   - FlushFileBuffers 是"真正落盘"的原语, 失败且属于"设备不支持"→ 降级为告警;
//     写句柄本身带 FILE_FLAG_WRITE_THROUGH (写操作直通介质), 且写后还有完整回读校验。
//   - IOCTL_DISK_UPDATE_PROPERTIES 只是为了让资源管理器看到新分区表, 与数据无关 →
//     一律 best-effort, 失败只记一笔。
//
// 两类告警都用 SyncNote() 暴露给上层写进日志, 不静默吞掉。
func (d *winDisk) Sync() error {
	if err := windows.FlushFileBuffers(d.h); err != nil {
		if !deviceUnsupported(err) {
			return err
		}
		d.syncNote = fmt.Sprintf("设备不支持刷新缓存指令 (FlushFileBuffers: %v) — 已按直通写 (FILE_FLAG_WRITE_THROUGH) 处理, 落盘由写后回读校验兜底", err)
	}
	var ret uint32
	if err := windows.DeviceIoControl(d.h, ioctlDiskUpdateProperties, nil, 0, nil, 0, &ret, nil); err != nil {
		if d.syncNote == "" {
			d.syncNote = fmt.Sprintf("设备不支持重新枚举分区表 (IOCTL_DISK_UPDATE_PROPERTIES: %v) — 不影响卡内数据, 重新插拔读卡器即可让系统看到新分区", err)
		}
	}
	return nil
}

// SyncNote 收尾阶段的非致命告警 (空 = 一切正常)
func (d *winDisk) SyncNote() string { return d.syncNote }

func (d *winDisk) Close() error { return windows.CloseHandle(d.h) }

// lockVolumes 让目标盘上的所有卷退出使用, 然后锁定它们 (写原始盘的前置条件);
// 返回解锁函数。
//
// 用户反馈: 直接 FSCTL_LOCK_VOLUME 报 "Access is denied"。原因是卷还被文件系统挂着
// (资源管理器/索引器/杀毒软件都可能持有句柄), 而 LOCK 要求"没人用"。正确顺序是
// **先强制卸载**: FSCTL_DISMOUNT_VOLUME 会把卷的文件系统摘下来 (即使还有打开的句柄
// 也会摘掉), 摘掉之后没有任何文件系统再往这块盘回写, 此时再锁定就稳了。
//
// 另外盘符枚举 (GetLogicalDrives) 漏掉"没有盘符的分区": TF 卡上的分区常常没盘符,
// 但文件系统照样挂着, 不卸载就会在写盘中途被回写 —— 所以这里用 FindFirstVolume
// 枚举**所有**卷, 再按 extent 匹配到目标盘。
func lockVolumes(diskNumber int, logf func(string, ...interface{})) (func(), error) {
	log := func(format string, a ...interface{}) {
		if logf != nil {
			logf(format, a...)
		}
	}
	var handles []windows.Handle
	release := func() {
		for _, h := range handles {
			var ret uint32
			windows.DeviceIoControl(h, fsctlUnlockVolume, nil, 0, nil, 0, &ret, nil)
			windows.CloseHandle(h)
		}
	}

	vols := volumesOnDisk(diskNumber)
	log("目标盘上的卷: %d 个 — 逐个强制卸载后锁定", len(vols))
	for _, v := range vols {
		h, err := openVolumeHandle(v.name)
		if err != nil {
			// 打不开通常是正被别的进程独占; 不致命 (它可能马上释放, 也可能只是只读挂载)
			log("⚠ 卷 %s 打开失败: %v", v.display(), err)
			continue
		}
		// 1) 先强制卸载 —— 这一步不要求"没人用", 是解开 ACCESS_DENIED 的关键
		var ret uint32
		dismounted := windows.DeviceIoControl(h, fsctlDismountVolume, nil, 0, nil, 0, &ret, nil) == nil

		// 2) 再锁定。索引器/杀毒软件释放句柄要一点时间, 所以带重试
		locked := false
		var lerr error
		for attempt := 0; attempt < lockRetries; attempt++ {
			if lerr = windows.DeviceIoControl(h, fsctlLockVolume, nil, 0, nil, 0, &ret, nil); lerr == nil {
				locked = true
				break
			}
			time.Sleep(lockRetryDelay)
		}

		switch {
		case locked && dismounted:
			log("卷 %s: 已卸载并锁定", v.display())
			handles = append(handles, h)
		case locked:
			log("卷 %s: 已锁定", v.display())
			handles = append(handles, h)
		case dismounted:
			// 卸载成功已经达到目的: 文件系统摘掉了, 不会再有回写。锁定失败只是少一道保险。
			log("⚠ 卷 %s 已强制卸载, 但锁定未成功 (%v) — 继续写入", v.display(), lerr)
			handles = append(handles, h)
		default:
			windows.CloseHandle(h)
			release()
			return nil, fmt.Errorf("卷 %s 既无法卸载也无法锁定 (%v)。"+
				"该卷正被占用: 请关闭资源管理器窗口/杀毒软件/同步盘后重试, 或先在系统里弹出该 TF 卡再插入",
				v.display(), lerr)
		}
	}
	return release, nil
}

// lockRetries / lockRetryDelay 锁定重试次数与间隔
const (
	lockRetries    = 20
	lockRetryDelay = 250 * time.Millisecond
)

// volRef 一个卷: 设备名 + 便于阅读的展示名
type volRef struct {
	name    string // \\?\Volume{GUID}
	letters string // "E:" (无盘符时为空)
}

func (v volRef) display() string {
	if v.letters != "" {
		return v.letters + " (" + v.name + ")"
	}
	return v.name
}

// volumesOnDisk 列出某块物理盘上的所有卷 (含没有盘符的)
func volumesOnDisk(diskNumber int) []volRef {
	var out []volRef
	buf := make([]uint16, windows.MAX_PATH+1)
	h, err := windows.FindFirstVolume(&buf[0], uint32(len(buf)))
	if err != nil {
		return out
	}
	defer windows.FindVolumeClose(h)
	for {
		name := strings.TrimSuffix(windows.UTF16ToString(buf), `\`)
		if name != "" {
			if vh, oerr := openVolumeHandle(name); oerr == nil {
				if n, eerr := volumeDiskNumber(vh); eerr == nil && n == uint32(diskNumber) {
					out = append(out, volRef{name: name, letters: volumeLettersOf(name)})
				}
				windows.CloseHandle(vh)
			}
		}
		if err := windows.FindNextVolume(h, &buf[0], uint32(len(buf))); err != nil {
			break
		}
	}
	return out
}

// openVolumeHandle 打开卷设备 (锁/卸载用, 需要读写权限)
func openVolumeHandle(name string) (windows.Handle, error) {
	return windows.CreateFile(windows.StringToUTF16Ptr(name),
		windows.GENERIC_READ|windows.GENERIC_WRITE,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil, windows.OPEN_EXISTING, 0, 0)
}

// volumeLettersOf 取卷的盘符 (可能多个挂载点, 只取第一个 "X:" 形式的)
func volumeLettersOf(name string) string {
	buf := make([]uint16, windows.MAX_PATH+1)
	var ret uint32
	if err := windows.GetVolumePathNamesForVolumeName(windows.StringToUTF16Ptr(name),
		&buf[0], uint32(len(buf)), &ret); err != nil {
		return ""
	}
	for _, p := range strings.Split(windows.UTF16ToString(buf), "\x00") {
		if len(p) >= 2 && p[1] == ':' {
			return p[:2]
		}
	}
	return ""
}

// ---- 内部工具 ----

func diskLength(h windows.Handle) (int64, error) {
	var out int64
	var ret uint32
	if err := windows.DeviceIoControl(h, ioctlDiskGetLengthInfo, nil, 0,
		(*byte)(unsafe.Pointer(&out)), uint32(unsafe.Sizeof(out)), &ret, nil); err != nil {
		return 0, err
	}
	return out, nil
}

func isWritable(h windows.Handle) bool {
	var ret uint32
	return windows.DeviceIoControl(h, ioctlDiskIsWritable, nil, 0, nil, 0, &ret, nil) == nil
}

var busTypeName = map[uint32]string{
	0: "UNKNOWN", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA",
	6: "FIBRE", 7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA",
	12: "SD", 13: "MMC", 14: "VIRTUAL", 15: "FILEBACKED", 16: "SPACEPORT",
	17: "NVMe", 18: "SCM", 19: "UFS",
}

// diskProperty 返回 型号 / 总线类型 / 是否可移动介质
func diskProperty(h windows.Handle) (model, bus string, removable bool) {
	query := make([]byte, 12)
	binary.LittleEndian.PutUint32(query[0:], storageDeviceProperty)
	binary.LittleEndian.PutUint32(query[4:], propertyStandardQuery)
	buf := make([]byte, 1024)
	var ret uint32
	if err := windows.DeviceIoControl(h, ioctlStorageQueryProperty, &query[0], uint32(len(query)),
		&buf[0], uint32(len(buf)), &ret, nil); err != nil {
		return "", "UNKNOWN", false
	}
	if len(buf) < 36 {
		return "", "UNKNOWN", false
	}
	removable = buf[10] != 0
	bt := binary.LittleEndian.Uint32(buf[28:])
	bus = busTypeName[bt]
	if bus == "" {
		bus = fmt.Sprintf("BUS%d", bt)
	}
	// ProductIdOffset / VendorIdOffset 指向 ANSI 字符串
	prodOff := binary.LittleEndian.Uint32(buf[16:])
	vendOff := binary.LittleEndian.Uint32(buf[12:])
	prod := cstr(buf, prodOff)
	vend := cstr(buf, vendOff)
	model = strings.TrimSpace(strings.TrimSpace(vend) + " " + strings.TrimSpace(prod))
	return model, bus, removable
}

func cstr(b []byte, off uint32) string {
	if off == 0 || int(off) >= len(b) {
		return ""
	}
	end := int(off)
	for end < len(b) && b[end] != 0 {
		end++
	}
	return string(b[off:end])
}

// diskPartitions 解析 DRIVE_LAYOUT_INFORMATION_EX
func diskPartitions(h windows.Handle, diskNumber int) []Partition {
	const layoutHdr = 8 // PartitionStyle(4) + PartitionCount(4); union 最大 40 → 分区数组偏移 48
	const entryStride = 144
	buf := make([]byte, layoutHdr+40+entryStride*128)
	var ret uint32
	if err := windows.DeviceIoControl(h, ioctlDiskGetDriveLayoutEx, nil, 0,
		&buf[0], uint32(len(buf)), &ret, nil); err != nil {
		return nil
	}
	style := binary.LittleEndian.Uint32(buf[0:])
	count := int(binary.LittleEndian.Uint32(buf[4:]))
	off := layoutHdr + 40
	var parts []Partition
	for i := 0; i < count && off+entryStride <= len(buf); i++ {
		base := buf[off : off+entryStride]
		p := Partition{
			Index:  int(binary.LittleEndian.Uint32(base[24:])),
			Offset: int64(binary.LittleEndian.Uint64(base[8:])),
			Size:   int64(binary.LittleEndian.Uint64(base[16:])),
		}
		if p.Index == 0 {
			p.Index = i + 1
		}
		if style == 0 { // MBR: union 首字节 = 分区类型
			p.FSType = fmt.Sprintf("MBR:0x%02X", base[32])
		} else { // GPT: union 内 Name 偏移 40 (GUID16+GUID16+Attr8)
			nameOff := 32 + 40
			if nameOff+72 <= len(base) {
				p.Label = utf16ToString(base[nameOff : nameOff+72])
			}
			p.FSType = "GPT"
		}
		parts = append(parts, p)
		off += entryStride
	}
	// 卷标/盘符: 用卷 extent 起始偏移匹配分区
	attachVolumeLabels(diskNumber, parts)
	return parts
}

func attachVolumeLabels(diskNumber int, parts []Partition) {
	for _, l := range volumeLetters() {
		vol := `\\.\` + l + ":"
		h, err := windows.CreateFile(windows.StringToUTF16Ptr(vol), windows.GENERIC_READ,
			windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil, windows.OPEN_EXISTING, 0, 0)
		if err != nil {
			continue
		}
		exts, err := volumeExtents(h)
		windows.CloseHandle(h)
		if err != nil {
			continue
		}
		for _, e := range exts {
			if int(e.DiskNumber) != diskNumber {
				continue
			}
			for i := range parts {
				if parts[i].Offset == e.StartingOffset {
					parts[i].DriveLetter = l + ":"
				}
			}
		}
	}
}

func volumeLetters() []string {
	var out []string
	mask, err := windows.GetLogicalDrives()
	if err != nil {
		return out
	}
	for i := 0; i < 26; i++ {
		if mask&(1<<uint(i)) != 0 {
			out = append(out, string(rune('A'+i)))
		}
	}
	return out
}

func volumeExtents(h windows.Handle) ([]diskExtent, error) {
	buf := make([]byte, 8+24*32)
	var ret uint32
	if err := windows.DeviceIoControl(h, ioctlVolumeGetDiskExtents, nil, 0,
		&buf[0], uint32(len(buf)), &ret, nil); err != nil {
		return nil, err
	}
	n := int(binary.LittleEndian.Uint32(buf[0:]))
	var out []diskExtent
	for i := 0; i < n && 8+24*(i+1) <= len(buf); i++ {
		b := buf[8+24*i:]
		out = append(out, diskExtent{
			DiskNumber:     binary.LittleEndian.Uint32(b[0:]),
			StartingOffset: int64(binary.LittleEndian.Uint64(b[8:])),
			ExtentLength:   int64(binary.LittleEndian.Uint64(b[16:])),
		})
	}
	return out, nil
}

func volumeDiskNumber(h windows.Handle) (uint32, error) {
	exts, err := volumeExtents(h)
	if err != nil || len(exts) == 0 {
		return 0, fmt.Errorf("卷 extent 读取失败")
	}
	return exts[0].DiskNumber, nil
}

// systemDiskNumbers 返回系统盘号 + 系统卷所在分区偏移 (双保险判定)
func systemDiskNumbers() (map[int]bool, []diskExtent) {
	nums := map[int]bool{}
	var parts []diskExtent
	dir, err := windows.GetWindowsDirectory()
	if err != nil || len(dir) < 2 {
		dir, err = windows.GetSystemDirectory()
		if err != nil || len(dir) < 2 {
			return nums, parts
		}
	}
	letter := strings.ToUpper(string(dir[0]))
	vol := `\\.\` + letter + ":"
	h, err := windows.CreateFile(windows.StringToUTF16Ptr(vol), windows.GENERIC_READ,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil, windows.OPEN_EXISTING, 0, 0)
	if err != nil {
		return nums, parts
	}
	defer windows.CloseHandle(h)
	exts, err := volumeExtents(h)
	if err != nil {
		return nums, parts
	}
	for _, e := range exts {
		nums[int(e.DiskNumber)] = true
		parts = append(parts, e)
	}
	return nums, parts
}

// utf16ToString 转换固定长度 UTF-16 缓冲 (遇 NUL 截断)
func utf16ToString(b []byte) string {
	u := make([]uint16, 0, len(b)/2)
	for i := 0; i+1 < len(b); i += 2 {
		c := binary.LittleEndian.Uint16(b[i:])
		if c == 0 {
			break
		}
		u = append(u, c)
	}
	return string(utf16.Decode(u))
}
