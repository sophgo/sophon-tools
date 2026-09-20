// 直接在目标设备上建 MBR+FAT32 卡 (MYS-1062 十三轮)
//
// 背景 (用户反馈):
//
//	「对于已经压缩后的镜像/文件, 需要流式解压、写入, 防止大镜像文件将内存/缓存区吃满」
//	「对于稀疏文件的压缩镜像文件, 必须要流式解压, 或者缓存区需要支持稀疏模式」
//
// 旧做法是"先在临时文件里离线建好整张卡镜像, 再整份读回来写进卡"。一张 14 GiB 的卡
// 就要: 落一个 14 GiB 的临时镜像 → 整份读一遍 (约 15.8 GB 过一遍系统文件缓存) → 写卡。
// 实测这类文件包里真正的数据只有几百 MB, 其余全是空洞, 白占临时盘也白占缓存。
//
// 新做法 (本文件): 把 go-diskfs 的**可写 backend 直接架在目标设备上**, 归档流式解压
// 出来的字节直接落到卡上 —— 中间不产生任何整卡尺寸的中间物。附带好处:
//   - 天然就是"快速格式化": 只写文件系统元数据和真实文件数据, 未用空间一个字节都不碰
//   - 少一遍整卡读 + 一遍整卡写
//
// Windows 物理盘句柄只接受**扇区对齐**的读写, 而 go-diskfs 按文件语义任意偏移写
// (目录项更新常落在扇区中间), 所以 devStore.WriteAt 做读-改-写 (见下)。
package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"sort"
	"time"

	"github.com/diskfs/go-diskfs"
	"github.com/diskfs/go-diskfs/backend"
	filebackend "github.com/diskfs/go-diskfs/backend/file"
	"github.com/diskfs/go-diskfs/disk"
	"github.com/diskfs/go-diskfs/filesystem"
	"github.com/diskfs/go-diskfs/partition/mbr"
)

// 设备 I/O 的对齐处理统一放在 align.go 的 alignedDevice 里 (建卡/校验共用同一层):
// 见那里的说明 —— Windows 物理盘拒绝未对齐读写, 而 go-diskfs 是按字节精确访问的。

// ByteRange 目标设备上一段被写过的区间
type ByteRange struct {
	Off int64
	Len int64
}

// extentSet 记录"到底写了卡上哪些字节"。
//
// 用途有两个: 汇报真实写入量 (快速格式化省掉多少), 以及校验阶段知道该回读哪儿。
// 只存区间不存数据 —— 几百个区间的开销可以忽略, 存内容才会把内存吃满。
type extentSet struct {
	ranges []ByteRange
}

func (e *extentSet) add(off, n int64) {
	if n <= 0 {
		return
	}
	e.ranges = append(e.ranges, ByteRange{off, n})
	// 区间数量很少 (每个文件/FAT 各一段), 直接排序合并
	sort.Slice(e.ranges, func(i, j int) bool { return e.ranges[i].Off < e.ranges[j].Off })
	merged := e.ranges[:0]
	for _, r := range e.ranges {
		if len(merged) > 0 {
			last := &merged[len(merged)-1]
			if r.Off <= last.Off+last.Len { // 相邻或重叠
				if end := r.Off + r.Len; end > last.Off+last.Len {
					last.Len = end - last.Off
				}
				continue
			}
		}
		merged = append(merged, r)
	}
	e.ranges = merged
}

func (e *extentSet) Total() int64 {
	var n int64
	for _, r := range e.ranges {
		n += r.Len
	}
	return n
}

// ---------- 可写设备 backend ----------

// devStore 把 DiskDevice 适配成 go-diskfs 的 backend.Storage。
type devStore struct {
	dev   DiskDevice
	pos   int64
	ro    bool
	track *extentSet
}

func (b *devStore) Stat() (fs.FileInfo, error) { return devFileInfo{b.dev.Size()}, nil }

func (b *devStore) Read(p []byte) (int, error) {
	if b.pos >= b.dev.Size() {
		return 0, io.EOF
	}
	if int64(len(p)) > b.dev.Size()-b.pos {
		p = p[:b.dev.Size()-b.pos]
	}
	n, err := b.ReadAt(p, b.pos)
	b.pos += int64(n)
	if err == nil && n == 0 {
		err = io.EOF
	}
	return n, err
}

func (b *devStore) ReadAt(p []byte, off int64) (int, error) { return b.dev.ReadAt(p, off) }

// WriteAt 交给对齐层 (alignedDevice) 做读-改-写; 这里只补越界检查与"实写区间"统计。
func (b *devStore) WriteAt(p []byte, off int64) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	if off < 0 {
		return 0, errors.New("负偏移")
	}
	size := b.dev.Size()
	if size > 0 && off+int64(len(p)) > size {
		return 0, fmt.Errorf("写入越界: 偏移 %d + %d 字节 超出设备容量 %d", off, len(p), size)
	}
	if _, err := b.dev.WriteAt(p, off); err != nil {
		return 0, err
	}
	if b.track != nil {
		b.track.add(off, int64(len(p)))
	}
	return len(p), nil
}

func (b *devStore) Seek(offset int64, whence int) (int64, error) {
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

func (b *devStore) Close() error { return nil }

// Sys go-diskfs 用它做块设备 ioctl; 物理盘由平台层自己管, 这里不给
func (b *devStore) Sys() (*os.File, error) {
	return nil, errors.New("设备 backend 不支持 Sys()")
}

func (b *devStore) Writable() (backend.WritableFile, error) {
	if b.ro {
		return nil, backend.ErrIncorrectOpenMode
	}
	return b, nil
}

func (b *devStore) Path() string { return b.dev.Path() }

// newDevStore 建卡的 backend: 设备先套上"只发对齐 I/O"的一层
func newDevStore(dev DiskDevice, track *extentSet) *devStore {
	// track 只挂在这一层: 对齐层会把写入补到 4096, 统计要的是"逻辑上写了哪几段"
	return &devStore{dev: newAlignedDevice(dev, nil), track: track}
}

func (b *devStore) Write(p []byte) (int, error) {
	n, err := b.WriteAt(p, b.pos)
	b.pos += int64(n)
	return n, err
}

// ---------- 建卡 ----------

// buildCardFS 在任意 backend 上建 MBR + FAT32 并把文件包写进去。
// 目标可以是一个镜像文件 (BuildCardImage), 也可以是物理设备 (BuildCardOnDevice)。
//
// plan 里没有文件时 (= 只格式化模式, 见 PlanFormatOnly) 建完文件系统就结束 ——
// 卡上留下的是一个空的、格式正确的 FAT32, 文件由用户自己往里拷。
// pkg 只在这一步才用到, 所以只格式化时传 nil 是安全的。
func buildCardFS(store backend.Storage, pkg *Archive, plan *PackagePlan, cb Progress) error {
	if err := preflightNames(plan); err != nil {
		return err
	}
	d, err := diskfs.OpenBackend(store, diskfs.WithSectorSize(diskfs.SectorSize512))
	if err != nil {
		return fmt.Errorf("打开目标失败: %w", err)
	}
	defer d.Close()

	// 0) 先把分区表之前那 1 MiB 抹成零。
	//
	// go-diskfs 写 MBR 时只写偏移 446 起的分区项与 0x55AA 签名, 前 446 字节的引导代码
	// 它不碰。卡如果是"用过的", 那半截旧引导代码/旧引导器残片就会留在卡头 —— 抹掉它
	// 既让结果确定, 也避免卡上残留上一任的分区/引导器痕迹。
	w, err := store.Writable()
	if err != nil {
		return fmt.Errorf("目标不可写: %w", err)
	}
	if _, err := w.WriteAt(make([]byte, partStartLBA*sectorSize), 0); err != nil {
		return fmt.Errorf("清空卡头失败: %w", err)
	}

	// 1) MBR 分区表: 一个 FAT32 LBA 分区
	tbl := &mbr.Table{Partitions: []*mbr.Partition{{
		Index:    1,
		Bootable: false,
		Type:     mbr.Fat32LBA,
		Start:    partStartLBA,
		Size:     uint32(plan.PartSize / sectorSize),
	}}}
	if err := d.Partition(tbl); err != nil {
		return fmt.Errorf("写分区表失败: %w", err)
	}

	// 2) FAT32 文件系统
	fsys, err := d.CreateFilesystem(disk.FilesystemSpec{
		Partition:   1,
		FSType:      filesystem.TypeFat32,
		VolumeLabel: plan.Label,
	})
	if err != nil {
		return fmt.Errorf("建立 FAT32 失败: %w", err)
	}

	// 3) 目录
	for _, dir := range plan.Dirs {
		if err := fsys.Mkdir(fatPath(dir.Name)); err != nil {
			return fmt.Errorf("建目录 %s 失败: %w", dir.Name, err)
		}
	}

	// 4) 文件 (逐个从归档流式解出, 不经内存整份缓存)
	//    只格式化模式: 计划里没有文件, 到这儿就收工
	if len(plan.Files) == 0 {
		return nil
	}
	it, err := pkg.openFiles()
	if err != nil {
		return err
	}
	defer it.Close()

	var total int64
	for _, e := range plan.Files {
		total += e.Size
	}
	var written int64
	for {
		ent, err := it.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("读取归档失败: %w", err)
		}
		if ent == nil || ent.IsDir {
			continue
		}
		rc, err := it.Open()
		if err != nil {
			return fmt.Errorf("打开归档内 %s 失败: %w", ent.Name, err)
		}
		target := pkg.TargetName(ent.Name)
		if err := writeOneFile(fsys, target, rc, func(n int64) {
			written += n
			if cb != nil {
				cb("files", written, total, 0)
			}
		}); err != nil {
			rc.Close()
			return err
		}
		rc.Close()
	}
	if cb != nil {
		cb("files", written, total, 0)
	}
	return nil
}

// BuildCardImage 把文件包离线构建成一张卡镜像文件 (测试与离线检查用)。
//
// 正式写入走 BuildCardOnDevice, 不落这个中间文件。
func BuildCardImage(pkg *Archive, plan *PackagePlan, tmpPath string, cb Progress) error {
	f, err := os.Create(tmpPath)
	if err != nil {
		return err
	}
	if err := f.Truncate(plan.TotalSize); err != nil {
		f.Close()
		return fmt.Errorf("创建临时镜像失败 (磁盘空间不足?): %w", err)
	}
	f.Close()
	store, err := diskfileStore(tmpPath)
	if err != nil {
		return err
	}
	return buildCardFS(store, pkg, plan, cb)
}

// BuildCardOnDevice 直接在目标设备上建卡, 并把"写了哪些区间"记进结果。
// pkg 为 nil = 只格式化 (plan 里没有文件)。
func BuildCardOnDevice(dev DiskDevice, pkg *Archive, plan *PackagePlan, cb Progress) (*CardWriteResult, error) {
	if dev.Size() <= 0 {
		return nil, fmt.Errorf("无法确定目标设备容量")
	}
	if dev.Size() < plan.TotalSize {
		return nil, fmt.Errorf("目标容量 %s 小于卡镜像 %s",
			HumanBytes(dev.Size()), HumanBytes(plan.TotalSize))
	}
	track := &extentSet{}
	t0 := time.Now()
	if err := buildCardFS(newDevStore(dev, track), pkg, plan, cb); err != nil {
		return nil, err
	}
	written := track.Total()
	return &CardWriteResult{
		TotalSize:    plan.TotalSize,
		WrittenBytes: written,
		SkippedBytes: plan.TotalSize - written,
		Extents:      track.ranges,
		Elapsed:      time.Since(t0),
		MismatchOff:  -1,
	}, nil
}

// CardWriteResult 卡上建 FAT32 的写入结果
type CardWriteResult struct {
	TotalSize    int64 // 卡镜像总容量 (分区表声明的)
	WrittenBytes int64 // 真正落到卡上的字节数
	SkippedBytes int64 // 未触碰的字节数 (快速格式化语义省掉的)
	Elapsed      time.Duration
	Extents      []ByteRange // 写过的区间 (校验阶段回读这些地方)

	VerifyOK    bool
	VerifyBytes int64
	MismatchOff int64
	MismatchCnt int64
}

// diskfileStore 把一个已存在的镜像文件包成 go-diskfs backend (可写)
func diskfileStore(path string) (backend.Storage, error) {
	return filebackend.OpenFromPathWithExclusive(path, false, false)
}
