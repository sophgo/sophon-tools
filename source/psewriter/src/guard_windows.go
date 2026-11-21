//go:build windows

package main

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"golang.org/x/sys/windows"
)

type diskStamp struct {
	size               int64
	descriptor, layout [32]byte
	media              uint32
	mediaKnown         bool
}

func inspectOperatorDisk(d *winDisk, includeLayout bool) (diskStamp, error) {
	// STORAGE_DEVICE_DESCRIPTOR includes bus, model and serial when available.
	q := make([]byte, 12)
	buf := make([]byte, 4096)
	var n uint32
	if err := windows.DeviceIoControl(d.h, ioctlStorageQueryProperty, &q[0], uint32(len(q)), &buf[0], uint32(len(buf)), &n, nil); err != nil || n < 36 || n > uint32(len(buf)) {
		return diskStamp{}, fmt.Errorf("无法读取设备身份: %v", err)
	}
	st := diskStamp{size: d.Size(), descriptor: sha256.Sum256(buf[:n])}
	// IOCTL_STORAGE_CHECK_VERIFY2: storage media change count, when supported.
	var counter [4]byte
	if err := windows.DeviceIoControl(d.h, 0x002d0800, nil, 0, &counter[0], 4, &n, nil); err == nil && n == 4 {
		st.media, st.mediaKnown = binary.LittleEndian.Uint32(counter[:]), true
	}
	if includeLayout {
		h := sha256.New()
		layout := make([]byte, lenDiskStampRegion)
		aligned := newAlignedDevice(d, nil)
		// Both ends: MBR, primary GPT and backup GPT are typical identity cues.
		for _, off := range []int64{0, d.Size() - lenDiskStampRegion} {
			if off < 0 {
				return diskStamp{}, errors.New("设备容量不足以复核分区布局")
			}
			nr, e := aligned.ReadAt(layout, off)
			if e != nil || nr != len(layout) {
				return diskStamp{}, fmt.Errorf("无法读取设备布局: %w", firstReadError(e))
			}
			h.Write(layout)
		}
		copy(st.layout[:], h.Sum(nil))
	}
	return st, nil
}

const lenDiskStampRegion = 64 << 10

func firstReadError(err error) error {
	if err != nil {
		return err
	}
	return io.ErrUnexpectedEOF
}
func (s diskStamp) sameMedia(other diskStamp) bool {
	return s.size == other.size && s.descriptor == other.descriptor && s.mediaKnown == other.mediaKnown && (!s.mediaKnown || s.media == other.media)
}

func checkOpenedDiskNumber(disk *winDisk, index int) error {
	var buf [12]byte
	var n uint32
	if err := windows.DeviceIoControl(disk.h, 0x002d1080, nil, 0, &buf[0], 12, &n, nil); err != nil || n != 12 {
		return fmt.Errorf("无法核对打开的物理盘编号: %v", err)
	}
	if binary.LittleEndian.Uint32(buf[4:]) != uint32(index) {
		return errors.New("打开的物理盘编号与选择不符")
	}
	return nil
}

func operatorDiskTarget(d *DiskInfo) (diskStamp, error) {
	if err := checkOperatorSystemDisk(d.Index); err != nil {
		return diskStamp{}, err
	}
	disk, err := openDisk(d.Path, true)
	if err != nil {
		return diskStamp{}, err
	}
	defer disk.Close()
	if err := checkOpenedDiskNumber(disk, d.Index); err != nil {
		return diskStamp{}, err
	}
	if disk.size != d.Size {
		return diskStamp{}, errors.New("目标容量已变化，请重新扫描")
	}
	model, bus, removable := diskProperty(disk.h)
	if model == "" {
		model = "(未知型号)"
	}
	if d.Model != model || d.BusType != bus || d.Removable != removable {
		return diskStamp{}, errors.New("目标设备信息已变化，请重新扫描")
	}
	return inspectOperatorDisk(disk, true)
}

func checkOperatorSystemDisk(index int) error {
	nums, _ := systemDiskNumbers()
	if len(nums) == 0 {
		return errors.New("无法确认系统盘，操作未获准")
	}
	if nums[index] {
		return errors.New("目标是系统盘，禁止写入")
	}
	return nil
}

func openVolumeReadMetadata(name string) (windows.Handle, error) {
	return windows.CreateFile(windows.StringToUTF16Ptr(name), 0, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil, windows.OPEN_EXISTING, 0, 0)
}

func operatorSourceVolumeCheck(index int) func(string) error {
	cache := map[string]bool{}
	return func(path string) error {
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		handle := windows.Handle(f.Fd())
		// VOLUME_NAME_GUID | FILE_NAME_OPENED. Resolve mount points and links via
		// the actual file handle; a path drive letter alone can be misleading.
		buf := make([]uint16, 32768)
		n, err := windows.GetFinalPathNameByHandle(handle, &buf[0], uint32(len(buf)), 9)
		s := windows.UTF16ToString(buf)
		if err != nil || n == 0 || int(n) >= len(buf) || !strings.HasPrefix(strings.ToLower(s), `\\?\volume{`) {
			// A UNC path (including localhost shares) is not proof that the
			// file is on another disk. Ask for a verifiable local copy.
			return fmt.Errorf("无法确认来源所在卷：%s。请复制到另一块本地磁盘后重试", path)
		}
		end := strings.Index(s, "}")
		if end < 0 {
			return fmt.Errorf("无法解析来源卷：%s", path)
		}
		name := s[:end+1]
		hit, cached := cache[name]
		if !cached {
			h, e := openVolumeReadMetadata(name)
			if e != nil {
				return fmt.Errorf("无法确认来源所在卷 %s: %w", path, e)
			}
			ext, e := volumeExtents(h)
			windows.CloseHandle(h)
			if e != nil || len(ext) == 0 {
				return fmt.Errorf("无法确认来源卷所在磁盘：%s", path)
			}
			for _, x := range ext {
				if x.DiskNumber == uint32(index) {
					hit = true
				}
			}
			cache[name] = hit
		}
		if hit {
			return fmt.Errorf("数据源位于目标盘，不能边读取边覆盖：%s。请先复制到另一块盘", path)
		}
		return nil
	}
}

func operatorFlashAccess(d *DiskInfo, expected diskStamp, sources []sourceFileStamp, begin func()) flashAccess {
	check := func() error {
		if err := checkOperatorSystemDisk(d.Index); err != nil {
			return err
		}
		return operatorStampsCurrent(sources, operatorSourceVolumeCheck(d.Index))
	}
	changed := errors.New("目标设备与确认时不同，请刷新并重新选择")
	return flashAccess{
		lock: func(log func(string, ...interface{})) (func(), error) {
			if err := check(); err != nil {
				return nil, err
			}
			actual, err := operatorDiskTarget(d)
			if err != nil {
				return nil, err
			}
			if expected != actual {
				return nil, changed
			}
			return lockWindowsVolumes(d.Index, true, d.Partitions, log)
		},
		write: func() (DiskDevice, error) {
			if err := check(); err != nil {
				return nil, err
			}
			actual, err := openDisk(d.Path, false)
			if err != nil {
				return nil, err
			}
			if err := checkOpenedDiskNumber(actual, d.Index); err != nil {
				actual.Close()
				return nil, err
			}
			s, err := inspectOperatorDisk(actual, true)
			if err != nil || s != expected {
				actual.Close()
				if err != nil {
					return nil, err
				}
				return nil, changed
			}
			// The handle that was just inspected is the same handle that gets written.
			return newAlignedDevice(actual, nil), nil
		},
		read: func() (DiskDevice, error) {
			actual, err := openDisk(d.Path, true)
			if err != nil {
				return nil, err
			}
			if err := checkOpenedDiskNumber(actual, d.Index); err != nil {
				actual.Close()
				return nil, err
			}
			s, err := inspectOperatorDisk(actual, false)
			if err != nil || !expected.sameMedia(s) {
				actual.Close()
				if err != nil {
					return nil, err
				}
				return nil, changed
			}
			return newAlignedDevice(actual, nil), nil
		},
		beforeWrite: begin,
	}
}
