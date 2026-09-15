//go:build linux

// Linux 平台层 — 仅供本机自测/联调 (真机目标是 Windows)。
// 枚举 /sys/block 下的块设备, 判定可移动与是否承载根文件系统。
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func enumerateDisks() ([]*DiskInfo, error) {
	rootDev := deviceOfMount("/")
	entries, err := os.ReadDir("/sys/block")
	if err != nil {
		return nil, err
	}
	var out []*DiskInfo
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, "dm-") || strings.HasPrefix(name, "md") ||
			strings.HasPrefix(name, "zram") || strings.HasPrefix(name, "sr") {
			continue
		}
		sysDir := filepath.Join("/sys/block", name)
		dev := "/dev/" + name
		if _, err := os.Stat(dev); err != nil {
			continue
		}
		size := int64(readUint(filepath.Join(sysDir, "size"))) * 512
		if size <= 0 {
			continue
		}
		d := &DiskInfo{Index: len(out), Path: dev, Size: size}
		d.Model = strings.TrimSpace(readStr(filepath.Join(sysDir, "device/model")))
		if d.Model == "" {
			d.Model = "(未知型号)"
		}
		d.Removable = readUint(filepath.Join(sysDir, "removable")) == 1
		d.BusType = linuxBusType(sysDir, d.Removable)
		d.Partitions = linuxPartitions(sysDir, name)
		if rootDev == name {
			d.System = true
		}
		Classify(d)
		out = append(out, d)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("未发现块设备")
	}
	return out, nil
}

func linuxBusType(sysDir string, removable bool) string {
	if b, err := os.ReadFile(filepath.Join(sysDir, "device/uevent")); err == nil {
		s := string(b)
		switch {
		case strings.Contains(s, "usb"):
			return "USB"
		case strings.Contains(s, "mmc"):
			return "MMC"
		case strings.Contains(s, "nvme"):
			return "NVMe"
		case strings.Contains(s, "ata"):
			return "SATA"
		}
	}
	if removable {
		return "USB"
	}
	if strings.HasPrefix(filepath.Base(sysDir), "loop") {
		return "LOOP"
	}
	return "VIRTUAL"
}

func linuxPartitions(sysDir, disk string) []Partition {
	ents, _ := os.ReadDir(sysDir)
	var parts []Partition
	for _, e := range ents {
		if !strings.HasPrefix(e.Name(), disk) || e.Name() == disk {
			continue
		}
		off := int64(readUint(filepath.Join(sysDir, e.Name(), "start"))) * 512
		sz := int64(readUint(filepath.Join(sysDir, e.Name(), "size"))) * 512
		parts = append(parts, Partition{
			Index:  len(parts) + 1,
			Offset: off,
			Size:   sz,
			FSType: "-",
			Label:  e.Name(),
		})
	}
	return parts
}

func deviceOfMount(mp string) string {
	b, err := os.ReadFile("/proc/mounts")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(b), "\n") {
		f := strings.Fields(line)
		if len(f) >= 2 && f[1] == mp {
			base := filepath.Base(f[0])
			// mmcblk0p1 → mmcblk0 ; sda1 → sda
			base = strings.TrimRight(base, "0123456789")
			base = strings.TrimSuffix(base, "p")
			return base
		}
	}
	return ""
}

func readUint(p string) uint64 {
	b, err := os.ReadFile(p)
	if err != nil {
		return 0
	}
	v, _ := strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64)
	return v
}

func readStr(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return string(b)
}

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
	flag := os.O_RDWR
	if ro {
		flag = os.O_RDONLY
	}
	f, err := os.OpenFile(path, flag, 0)
	if err != nil {
		return nil, fmt.Errorf("打开 %s 失败: %w", path, err)
	}
	st, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}
	size := st.Size()
	if b, err := os.ReadFile(filepath.Join("/sys/block", filepath.Base(path), "size")); err == nil {
		if v, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64); err == nil {
			size = v * 512
		}
	}
	return &linuxDisk{path: path, f: f, size: size}, nil
}

type linuxDisk struct {
	path string
	f    *os.File
	size int64
}

func (d *linuxDisk) Path() string                             { return d.path }
func (d *linuxDisk) Size() int64                              { return d.size }
func (d *linuxDisk) WriteAt(p []byte, off int64) (int, error) { return d.f.WriteAt(p, off) }
func (d *linuxDisk) ReadAt(p []byte, off int64) (int, error)  { return d.f.ReadAt(p, off) }
func (d *linuxDisk) Sync() error                              { return d.f.Sync() }
func (d *linuxDisk) Close() error                             { return d.f.Close() }

// lockVolumes Linux 侧为空操作 (自测用)
func lockVolumes(diskNumber int, logf func(string, ...interface{})) (func(), error) {
	return func() {}, nil
}
