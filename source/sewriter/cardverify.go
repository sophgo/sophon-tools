// 卡上 FAT32 文件级校验 (MYS-1062 九轮)
//
// 需求: 「文件压缩包模式写入后需要二次校验文件完整性」
//
// 做法: 把目标设备包一层只读 backend 交给 go-diskfs, **直接从卡上**挂载 FAT32,
// 逐个文件读回、算 sha256, 与源压缩包里的对应条目比对。
//
// 这是比"逐字节回读比对"更强的验证 —— 它证明的是:
//   - 卡上的分区表/引导扇区/FAT 表确实构成一个能被解析的 FAT32
//   - 每个文件都能按路径找到、长度正确、内容与源压缩包逐位一致
//
// 而且读的是**卡**而不是本地镜像, 因此也能暴露"写缓存没落盘"这类问题。
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"strings"
	"time"

	"github.com/diskfs/go-diskfs"
	"github.com/diskfs/go-diskfs/backend"
)

// FileCheckResult 单个文件的校验结果
type FileCheckResult struct {
	Name    string
	Size    int64
	WantSHA string
	GotSHA  string
	OK      bool
	Err     string
	Elapsed time.Duration
}

// CardVerifyResult 卡上文件级校验汇总
type CardVerifyResult struct {
	Files    []FileCheckResult
	OKCount  int
	BadCount int
	Bytes    int64
	Elapsed  time.Duration
	// BL1Err 非空 = 卡根 fip.bin 的 8.3 短名不对, BM1684X 的 BL1 认不出来
	// (BL1 的 FatFs 编的是 FF_USE_LFN=0, 只认短名; 详见 bl1check.go)
	BL1Err string
	// BL1Note 卡根短名核对结论 (无论对错都给一行, 便于日志留痕)
	BL1Note string
}

// OK 全部通过
func (r *CardVerifyResult) OK() bool { return r.BadCount == 0 && r.OKCount > 0 }

// Summary 一行摘要
func (r *CardVerifyResult) Summary() string {
	s := fmt.Sprintf("%d 个文件校验失败 (通过 %d)", r.BadCount, r.OKCount)
	if r.OK() {
		s = fmt.Sprintf("%d 个文件全部校验通过 (%s, 耗时 %s)",
			r.OKCount, HumanBytes(r.Bytes), r.Elapsed.Round(time.Millisecond))
	}
	if r.BL1Note != "" {
		s += " ｜ BL1: " + r.BL1Note
	}
	return s
}

// FirstError 第一条失败原因 (无失败返回 "")
func (r *CardVerifyResult) FirstError() string {
	if r.BL1Err != "" {
		return r.BL1Err
	}
	for _, f := range r.Files {
		if !f.OK {
			if f.Err != "" {
				return fmt.Sprintf("%s: %s", f.Name, f.Err)
			}
			return fmt.Sprintf("%s: 内容不一致 (期望 sha256 %s, 实得 %s)", f.Name, shortHash(f.WantSHA), shortHash(f.GotSHA))
		}
	}
	return ""
}

// ---------- 只读 backend: 让 go-diskfs 直接读物理盘 ----------

// devBackend 把 DiskDevice 适配成 go-diskfs 的 backend.Storage (只读)。
// 设备先套一层 alignedDevice: 校验时会按 512B 扇区读 FAT/目录, 那是 512 对齐但
// 不是 4096 对齐 —— Windows 物理盘会直接拒绝 (Linux 容忍, 所以只有实机会炸)。
type devBackend struct {
	dev DiskDevice
	pos int64
}

// newDevBackend 只读 backend (套对齐层)
func newDevBackend(dev DiskDevice) *devBackend {
	return &devBackend{dev: newAlignedDevice(dev, nil)}
}

func (b *devBackend) Stat() (fs.FileInfo, error) { return devFileInfo{b.dev.Size()}, nil }

func (b *devBackend) Read(p []byte) (int, error) {
	if b.pos >= b.dev.Size() {
		return 0, io.EOF
	}
	if int64(len(p)) > b.dev.Size()-b.pos {
		p = p[:b.dev.Size()-b.pos]
	}
	n, err := b.dev.ReadAt(p, b.pos)
	b.pos += int64(n)
	if err == nil && n == 0 {
		err = io.EOF
	}
	return n, err
}

func (b *devBackend) ReadAt(p []byte, off int64) (int, error) { return b.dev.ReadAt(p, off) }

func (b *devBackend) Seek(offset int64, whence int) (int64, error) {
	var abs int64
	switch whence {
	case io.SeekStart:
		abs = offset
	case io.SeekCurrent:
		abs = b.pos + offset
	case io.SeekEnd:
		abs = b.dev.Size() + offset
	default:
		return 0, errors.New("无效的 whence")
	}
	if abs < 0 {
		return 0, errors.New("负偏移")
	}
	b.pos = abs
	return abs, nil
}

func (b *devBackend) Close() error { return nil }

// Sys go-diskfs 用它做 ioctl; 只读校验路径不需要
func (b *devBackend) Sys() (*os.File, error) {
	return nil, errors.New("设备 backend 不支持 Sys()")
}

// Writable 校验路径全程只读
func (b *devBackend) Writable() (backend.WritableFile, error) {
	return nil, backend.ErrIncorrectOpenMode
}

func (b *devBackend) Path() string { return b.dev.Path() }

type devFileInfo struct{ size int64 }

func (d devFileInfo) Name() string       { return "device" }
func (d devFileInfo) Size() int64        { return d.size }
func (d devFileInfo) Mode() fs.FileMode  { return 0 }
func (d devFileInfo) ModTime() time.Time { return time.Time{} }
func (d devFileInfo) IsDir() bool        { return false }
func (d devFileInfo) Sys() interface{}   { return nil }

// ---------- 卡上文件系统结构的回读核对 ----------

// LayoutVerifyResult 卡上文件系统结构回读核对结果
type LayoutVerifyResult struct {
	Bytes    int64 // 回读并核对的元数据字节数
	FATBytes int64 // 其中 FAT 表字节数 (两份)
	MetaEnd  int64 // 文件系统元数据区右边界
	Label    string
	Elapsed  time.Duration
	Problems []string
}

// OK 结构全部核对通过
func (r *LayoutVerifyResult) OK() bool { return len(r.Problems) == 0 }

// Summary 一行摘要
func (r *LayoutVerifyResult) Summary() string {
	if r.OK() {
		return fmt.Sprintf("元数据区 %s 回读一致 (含 FAT 两份副本 %s, 卷标 %s)",
			HumanBytes(r.Bytes), HumanBytes(r.FATBytes), r.Label)
	}
	return fmt.Sprintf("卡上文件系统结构有 %d 处不符", len(r.Problems))
}

// VerifyCardLayout 回读卡上的分区表与 FAT32 结构并逐项核对。
//
// 卡是直接在设备上建出来的, 没有"中间镜像"可以逐字节比对, 所以这里核对的是
// **结构化的事实**:
//   - MBR: 引导签名 + 恰好一个 FAT32 LBA 分区, 起始/长度与写入计划一致
//   - BPB: FAT32 标记 / 每扇区字节 / FAT 份数 / 总扇区 / 卷标
//   - FAT 两份副本逐字节一致 (写全了且互为镜像 —— 单份写坏必被发现)
//
// 文件内容的逐字节保证由 VerifyCardFiles (从卡上挂 FAT32 逐文件比 sha256) 负责。
func VerifyCardLayout(dev DiskDevice, plan *PackagePlan, cb Progress) (*LayoutVerifyResult, error) {
	res := &LayoutVerifyResult{Label: plan.Label}
	t0 := time.Now()
	partStart := int64(partStartLBA) * sectorSize
	partSectors := uint32(plan.PartSize / sectorSize)

	// ---- MBR ----
	mbrBuf := make([]byte, sectorSize)
	if _, err := dev.ReadAt(mbrBuf, 0); err != nil {
		return nil, fmt.Errorf("回读分区表失败: %w", err)
	}
	if mbrBuf[510] != 0x55 || mbrBuf[511] != 0xAA {
		res.Problems = append(res.Problems, "MBR 引导签名 55AA 缺失")
	}
	entry := mbrBuf[446 : 446+16]
	etype := entry[4]
	estart := uint32(entry[8]) | uint32(entry[9])<<8 | uint32(entry[10])<<16 | uint32(entry[11])<<24
	esize := uint32(entry[12]) | uint32(entry[13])<<8 | uint32(entry[14])<<16 | uint32(entry[15])<<24
	if etype != 0x0C {
		res.Problems = append(res.Problems, fmt.Sprintf("分区 1 类型为 0x%02X, 期望 0x0C (FAT32 LBA)", etype))
	}
	if estart != partStartLBA {
		res.Problems = append(res.Problems, fmt.Sprintf("分区 1 起始 LBA 为 %d, 期望 %d", estart, partStartLBA))
	}
	// 计划里的分区大小 (调用方按同一套参数算出来的) —— 不一致说明写进去的和打算写的不是一回事
	if esize != partSectors {
		res.Problems = append(res.Problems, fmt.Sprintf("分区 1 扇区数为 %d, 期望 %d", esize, partSectors))
	}
	if esize == 0 {
		res.Problems = append(res.Problems, "分区 1 扇区数为 0")
	}

	// ---- BPB ----
	bpb := make([]byte, sectorSize)
	if _, err := dev.ReadAt(bpb, partStart); err != nil {
		return nil, fmt.Errorf("回读引导扇区失败: %w", err)
	}
	if !bytes.Equal(bpb[82:87], []byte("FAT32")) {
		res.Problems = append(res.Problems, "引导扇区偏移 82 处不是 \"FAT32\" 标记")
	}
	bytesPerSec := int64(binary.LittleEndian.Uint16(bpb[11:]))
	secPerClus := int64(bpb[13])
	rsvdSec := int64(binary.LittleEndian.Uint16(bpb[14:]))
	numFATs := int64(bpb[16])
	fatSz := int64(binary.LittleEndian.Uint32(bpb[36:]))
	totalSec := int64(binary.LittleEndian.Uint32(bpb[32:]))
	if bytesPerSec != sectorSize {
		res.Problems = append(res.Problems, fmt.Sprintf("每扇区字节数为 %d, 期望 %d", bytesPerSec, sectorSize))
	}
	if numFATs != 2 {
		res.Problems = append(res.Problems, fmt.Sprintf("FAT 份数为 %d, 期望 2", numFATs))
	}
	// MBR 与 BPB 必须自洽 —— 这条不依赖外部计划, 任何情况下都成立
	if totalSec != int64(esize) {
		res.Problems = append(res.Problems,
			fmt.Sprintf("MBR 分区扇区数 %d 与 BPB 总扇区数 %d 不一致", esize, totalSec))
	}
	if label := strings.TrimRight(string(bpb[71:82]), " \x00"); label != plan.Label {
		res.Problems = append(res.Problems, fmt.Sprintf("卷标为 %q, 期望 %q", label, plan.Label))
	}
	if bytesPerSec <= 0 || secPerClus <= 0 || numFATs <= 0 || fatSz <= 0 {
		res.Problems = append(res.Problems, "BPB 关键字段为零, 无法继续核对 FAT")
		res.Elapsed = time.Since(t0)
		return res, nil
	}

	// ---- FAT 两份副本逐字节一致 ----
	fatBytes := fatSz * bytesPerSec
	fat1 := partStart + rsvdSec*bytesPerSec
	fat2 := fat1 + fatBytes
	bufA := make([]byte, 1<<20)
	bufB := make([]byte, 1<<20)
	for off := int64(0); off < fatBytes; off += int64(len(bufA)) {
		n := int64(len(bufA))
		if fatBytes-off < n {
			n = fatBytes - off
		}
		if _, err := dev.ReadAt(bufA[:n], fat1+off); err != nil {
			return nil, fmt.Errorf("回读 FAT 副本 1 失败: %w", err)
		}
		if _, err := dev.ReadAt(bufB[:n], fat2+off); err != nil {
			return nil, fmt.Errorf("回读 FAT 副本 2 失败: %w", err)
		}
		if !bytes.Equal(bufA[:n], bufB[:n]) {
			res.Problems = append(res.Problems, fmt.Sprintf("FAT 两份副本在偏移 %d 处不一致", off))
			break
		}
		if cb != nil {
			cb("verify", off+n, fatBytes, 0)
		}
	}
	res.FATBytes = fatBytes * 2
	res.MetaEnd = partStart + (rsvdSec+numFATs*fatSz)*bytesPerSec + secPerClus*bytesPerSec
	res.Bytes = res.MetaEnd
	res.Elapsed = time.Since(t0)
	return res, nil
}

// ---------- 文件级校验 ----------

// VerifyCardFiles 从卡上挂载 FAT32, 逐个文件读回并与源压缩包比对 sha256。
//
// partition: 分区号 (本工具的卡镜像恒为 1)
func VerifyCardFiles(dev DiskDevice, pkg *Archive, partition int, cb Progress) (*CardVerifyResult, error) {
	res := &CardVerifyResult{}
	t0 := time.Now()

	// 1) 挂载卡上的 FAT32
	d, err := diskfs.OpenBackend(newDevBackend(dev), diskfs.WithSectorSize(diskfs.SectorSize512))
	if err != nil {
		return nil, fmt.Errorf("从卡上解析分区表失败: %w", err)
	}
	defer d.Close()
	cfs, err := d.GetFilesystem(partition)
	if err != nil {
		return nil, fmt.Errorf("从卡上挂载 FAT32 失败: %w", err)
	}

	// 2) 逐个文件读回比对
	it, err := pkg.openFiles()
	if err != nil {
		return nil, err
	}
	defer it.Close()

	var idx, total int
	for _, f := range pkg.Files {
		total++
		_ = f
	}
	for {
		ent, err := it.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return res, fmt.Errorf("读取源压缩包失败: %w", err)
		}
		if ent == nil || ent.IsDir {
			continue
		}
		idx++
		target := pkg.TargetName(ent.Name)
		fr := FileCheckResult{Name: target, Size: ent.Size}
		ft0 := time.Now()

		// 源内容 sha256
		rc, err := it.Open()
		if err != nil {
			fr.Err = "读取源压缩包条目失败: " + err.Error()
			res.Files = append(res.Files, fr)
			res.BadCount++
			continue
		}
		wantH := sha256.New()
		wantN, err := io.Copy(wantH, rc)
		rc.Close()
		if err != nil {
			fr.Err = "读取源压缩包条目失败: " + err.Error()
			res.Files = append(res.Files, fr)
			res.BadCount++
			continue
		}
		fr.WantSHA = fmt.Sprintf("%x", wantH.Sum(nil))

		// 卡上内容 sha256
		cf, err := cfs.OpenFile(devFatPath(target), os.O_RDONLY)
		if err != nil {
			fr.Err = "卡上找不到该文件: " + err.Error()
			fr.Elapsed = time.Since(ft0)
			res.Files = append(res.Files, fr)
			res.BadCount++
			continue
		}
		gotH := sha256.New()
		gotN, err := io.Copy(gotH, cf)
		cf.Close()
		if err != nil {
			fr.Err = "读卡上文件失败: " + err.Error()
			fr.Elapsed = time.Since(ft0)
			res.Files = append(res.Files, fr)
			res.BadCount++
			continue
		}
		fr.GotSHA = fmt.Sprintf("%x", gotH.Sum(nil))
		fr.Size = gotN
		fr.Elapsed = time.Since(ft0)

		switch {
		case gotN != wantN:
			fr.Err = fmt.Sprintf("长度不符 (期望 %d 字节, 实得 %d)", wantN, gotN)
		case fr.GotSHA != fr.WantSHA:
			fr.Err = "内容 sha256 不一致"
		default:
			fr.OK = true
			res.OKCount++
			res.Bytes += gotN
		}
		if !fr.OK {
			res.BadCount++
		}
		res.Files = append(res.Files, fr)
		if cb != nil {
			cb("check", int64(idx), int64(total), 0)
		}
	}

	// 3) BL1 可读性: 核对卡根 fip.bin 的 8.3 短名 (BL1 的 FatFs 不解析长名)。
	// 直接读卡上的原始目录项, 不经过文件系统库 —— 短名写坏正是"库自认为没问题、
	// 设备却起不来"的那类缺陷, 必须拿落地字节核对。
	if bl1, berr := CheckCardBL1(dev); berr != nil {
		res.BL1Err = "核对卡根短名失败: " + berr.Error()
		res.BadCount++
	} else {
		res.BL1Note = bl1.Note()
		if !bl1.OK() {
			res.BL1Err = bl1.Note()
			res.BadCount++
		}
	}
	res.Elapsed = time.Since(t0)
	return res, nil
}

// devFatPath 归档内路径 → FAT32 绝对路径
func devFatPath(name string) string {
	p := "/" + strings.TrimPrefix(path.Clean("/"+name), "/")
	return p
}
