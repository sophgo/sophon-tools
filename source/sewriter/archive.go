// 归档识别与解压 (MYS-1062 八轮)
//
// 支持的镜像来源 (按魔数识别, 扩展名只作提示):
//
//	裸镜像      .img / .bin / .raw            → 整盘写入
//	单流压缩    .gz / .xz / .bz2 / .zst       → 解压后是整盘镜像
//	归档容器    .zip / .7z / .rar             → 内含单个镜像文件(整盘) 或一批文件(文件包)
//	tar 家族    .tar / .tar.gz / .tar.xz / .tar.bz2 → 同上
//
// 两种写入模式:
//
//	ModeRawDisk     整盘镜像 → 逐字节写入目标盘 (原有路径)
//	ModeFilePackage 文件包   → 目标盘格式化为 MBR + FAT32, 再把文件写进去 (做 SE5/SE7/SE9 刷机卡)
//
// 所有格式都归一到同一个顺序迭代接口, 上层不需要关心容器差异。
package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/bzip2"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/bodgit/sevenzip"
	"github.com/klauspost/compress/zstd"
	"github.com/nwaples/rardecode/v2"
	"github.com/ulikunitz/xz"
	"golang.org/x/text/encoding/simplifiedchinese"
)

// SourceMode 写入模式
type SourceMode int

const (
	ModeRawDisk     SourceMode = iota // 整盘镜像: 覆盖写入目标盘
	ModeFilePackage                   // 文件包: 格式化为 MBR+FAT32 后写入文件
)

func (m SourceMode) String() string {
	if m == ModeFilePackage {
		return "文件包 (MBR+FAT32)"
	}
	return "整盘镜像"
}

// ArchiveEntry 归档内的一个条目
type ArchiveEntry struct {
	Name  string // 归一化后的相对路径 (以 / 分隔, 无前导 /)
	Size  int64
	IsDir bool
}

// Archive 已识别的镜像来源
type Archive struct {
	Path   string
	Format string         // gz/xz/zip/7z/rar/tar/tar.gz/... 或 "img"(裸镜像)
	Mode   SourceMode     // 自动判定的写入模式
	Image  string         // ModeRawDisk: 归档内的镜像条目名 (空 = 整个文件就是镜像)
	RawSz  int64          // ModeRawDisk: 解压后大小 (0 = 未知)
	Files  []ArchiveEntry // ModeFilePackage: 待写入 FAT32 的文件清单
	Dirs   []ArchiveEntry // ModeFilePackage: 目录清单

	ImageCompressed bool // ModeRawDisk: 镜像是否被压缩 (影响 sidecar 回退)
	SrcFileSize     int64

	// BootRoot 文件包模式: 刷机包根目录的判定结果 (见 bootroot.go)。
	// 现场拿到的压缩包常常多套了一层目录, 直接原样写进卡会让设备在卡根目录找不到
	// boot.scr / fip.bin —— 这里把它识别出来并剥掉。
	BootRoot BootRootInfo

	// Renames 归档原始条目名 → 卡上目标路径 (剥掉刷机包目录前缀时两者不同)。
	// 写卡与校验都要走 TargetName(), 否则会拿着带前缀的原名去找文件。
	Renames map[string]string

	// Skipped 目录源专用: 因 FAT32 放不下而被跳过的条目数
	// (符号链接指向目录 / 设备文件 / 断链)。如实报出来, 不静默吞掉。
	Skipped int
}

// 判定"这个归档里的单个文件是不是磁盘镜像"
// 注意: 不含 .bin —— 本项目里 fip.bin 等是"放进 FAT32 的文件", 不是整盘镜像;
// 单个 .bin 归档如需整盘写入, 用 --as raw / 界面里手动选"整盘镜像"。
var diskImageExts = []string{".img", ".raw", ".dd", ".iso", ".wic", ".hddimg"}

// archiveImpl 各格式统一的顺序迭代接口
type archiveImpl interface {
	// Next 前进到下一个条目; 迭代结束返回 io.EOF
	Next() (*ArchiveEntry, error)
	// Open 打开当前条目内容 (必须在 Next 之后调用)
	Open() (io.ReadCloser, error)
	Close() error
}

// ---------- 格式识别 ----------

type magicSig struct {
	format string
	bytes  []byte
	off    int
}

var magics = []magicSig{
	{"gz", []byte{0x1f, 0x8b}, 0},
	{"xz", []byte{0xfd, '7', 'z', 'X', 'Z', 0x00}, 0},
	{"bz2", []byte{'B', 'Z', 'h'}, 0},
	{"zst", []byte{0x28, 0xb5, 0x2f, 0xfd}, 0},
	{"zip", []byte{'P', 'K', 0x03, 0x04}, 0},
	{"zip", []byte{'P', 'K', 0x05, 0x06}, 0}, // 空归档
	{"7z", []byte{'7', 'z', 0xbc, 0xaf, 0x27, 0x1c}, 0},
	{"rar", []byte{'R', 'a', 'r', '!', 0x1a, 0x07, 0x00}, 0}, // RAR4
	{"rar", []byte{'R', 'a', 'r', '!', 0x1a, 0x07, 0x01, 0x00}, 0},
	{"tar", []byte("ustar"), 257},
}

// detectFormat 按魔数识别格式; 识别不出按裸镜像处理
func detectFormat(head []byte) string {
	for _, m := range magics {
		if len(head) < m.off+len(m.bytes) {
			continue
		}
		if bytes.Equal(head[m.off:m.off+len(m.bytes)], m.bytes) {
			return m.format
		}
	}
	return "img"
}

// streamFormats 单流压缩 (解压后可能是镜像, 也可能是 tar)
var streamFormats = map[string]bool{"gz": true, "xz": true, "bz2": true, "zst": true}

// containerFormats 归档容器 (可枚举条目)
var containerFormats = map[string]bool{"zip": true, "7z": true, "rar": true}

// ProbeCtl 探测 (识别格式 / 枚举归档条目) 的进度反馈与取消。
//
// 大压缩包 (如 14 GiB 的 .txz 文件包) 必须把整条压缩流解一遍才能枚举出条目,
// 这个过程可能要几十秒到几分钟。GUI 不能因此卡死, 所以探测过程要:
//   - 能报告进度 (phase="read": 已消费的**源文件字节数**; phase="scan": 已扫到的条目数)
//   - 能被取消 (Canceled 返回 true → 返回 ErrProbeCanceled)
//
// nil 表示不要进度、不响应取消 (命令行与单测用)。
type ProbeCtl struct {
	Progress func(phase string, done, total int64)
	Canceled func() bool
}

// ErrProbeCanceled 用户中止了探测
var ErrProbeCanceled = errors.New("已取消分析")

func probeCanceled(ctl *ProbeCtl) bool {
	return ctl != nil && ctl.Canceled != nil && ctl.Canceled()
}

func probeReport(ctl *ProbeCtl, phase string, done, total int64) {
	if ctl != nil && ctl.Progress != nil {
		ctl.Progress(phase, done, total)
	}
}

// probeReader 统计从源文件读了多少字节 (压缩字节数, 与源文件大小同量纲),
// 顺便响应取消 —— 这是 tar.xz 探测期间唯一能给出真实百分比的量。
type probeReader struct {
	r     io.Reader
	ctl   *ProbeCtl
	total int64
	done  int64
	last  time.Time
}

func (p *probeReader) Read(b []byte) (int, error) {
	if probeCanceled(p.ctl) {
		return 0, ErrProbeCanceled
	}
	n, err := p.r.Read(b)
	if n > 0 {
		p.done += int64(n)
		now := time.Now()
		if p.done >= p.total || now.Sub(p.last) >= 100*time.Millisecond {
			p.last = now
			probeReport(p.ctl, "read", p.done, p.total)
		}
	}
	return n, err
}

// ProbeArchive 识别来源并判定写入模式; force 非 nil 时强制指定模式。
// ctl 可为 nil (无进度、不可取消)。
func ProbeArchive(p string, force *SourceMode, ctl *ProbeCtl) (*Archive, error) {
	if probeCanceled(ctl) {
		return nil, ErrProbeCanceled
	}
	f, err := os.Open(p)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	head := make([]byte, 512)
	n, _ := io.ReadFull(f, head)
	head = head[:n]
	format := detectFormat(head)

	a := &Archive{Path: p, Format: format, SrcFileSize: st.Size()}

	switch {
	case containerFormats[format]:
		if err := a.probeContainer(ctl); err != nil {
			return nil, err
		}
	case streamFormats[format] || format == "tar":
		// 单流: 解压(如需)后看是不是 tar
		inner, closer, err := a.openStreamCtl(ctl)
		if err != nil {
			return nil, err
		}
		kind := peekStreamKind(inner)
		cerr := closer.Close() // 只用于探测, 关闭后按最终格式重新打开
		if cerr != nil {
			return nil, cerr
		}
		switch {
		case kind == "tar":
			if format != "tar" {
				a.Format = "tar." + format
			}
			if err := a.probeTar(ctl); err != nil {
				return nil, err
			}
		default:
			// 单流压缩 → 内容就是整盘镜像
			a.Format = format
			a.Mode = ModeRawDisk
			a.RawSz = a.streamRawSize(f, st.Size(), format)
			probeReport(ctl, "read", st.Size(), st.Size())
		}
	default:
		// 裸镜像
		a.Mode = ModeRawDisk
		a.RawSz = st.Size()
	}
	if force != nil {
		a.Mode = *force
		a.applyForcedMode()
	}
	// 文件包: 定位刷机包根目录, 把多套的那层去掉 (写入卡根目录的就是刷机包本身)
	if a.Mode == ModeFilePackage {
		if err := applyBootRoot(a); err != nil {
			return nil, err
		}
	}
	return a, nil
}

// applyForcedMode 用户强制指定模式时补齐必要信息
func (a *Archive) applyForcedMode() {
	if a.Mode == ModeRawDisk && a.Image == "" && a.Format != "img" {
		// 容器里强制当整盘镜像用: 取其中最大的文件
		if best := a.largestFile(); best != "" {
			a.Image = best
			a.RawSz = a.entrySize(best)
			a.ImageCompressed = false
		}
	}
}

// probeContainer 枚举 zip/7z/rar 条目
func (a *Archive) probeContainer(ctl *ProbeCtl) error {
	it, err := a.openContainer()
	if err != nil {
		return err
	}
	defer it.Close()
	if err := collectEntries(a, it, ctl); err != nil {
		return err
	}
	a.decideMode()
	return nil
}

// probeTar 枚举 tar / tar.* 条目
func (a *Archive) probeTar(ctl *ProbeCtl) error {
	it, err := a.openTarCtl(ctl)
	if err != nil {
		return err
	}
	defer it.Close()
	if err := collectEntries(a, it, ctl); err != nil {
		return err
	}
	a.decideMode()
	return nil
}

func collectEntries(a *Archive, it archiveImpl, ctl *ProbeCtl) error {
	const maxEntries = 100000
	last := time.Now()
	for {
		if probeCanceled(ctl) {
			return ErrProbeCanceled
		}
		e, err := it.Next()
		if err == io.EOF {
			// 收尾再报一次: 条目少时可能一次都没触发节流上报, 界面要有个"解析完了"
			probeReport(ctl, "scan", int64(len(a.Files)+len(a.Dirs)), 0)
			return nil
		}
		if err != nil {
			return fmt.Errorf("读取归档内容失败: %w", err)
		}
		if e == nil {
			continue
		}
		if e.IsDir {
			a.Dirs = append(a.Dirs, *e)
		} else {
			a.Files = append(a.Files, *e)
		}
		// 容器格式走随机访问, 没有"已读压缩字节"可报, 用条目数当进度 (total=0 → 界面转圈)
		if now := time.Now(); now.Sub(last) >= 100*time.Millisecond {
			last = now
			probeReport(ctl, "scan", int64(len(a.Files)+len(a.Dirs)), 0)
		}
		if len(a.Files)+len(a.Dirs) > maxEntries {
			return fmt.Errorf("归档内条目过多 (> %d)", maxEntries)
		}
	}
}

// decideMode 自动判定: 归档里只有一个"像磁盘镜像"的文件 → 整盘写入, 否则按文件包处理
func (a *Archive) decideMode() {
	if len(a.Files) == 1 && len(a.Dirs) == 0 && looksLikeDiskImage(a.Files[0].Name) {
		a.Mode = ModeRawDisk
		a.Image = a.Files[0].Name
		a.RawSz = a.Files[0].Size
		a.ImageCompressed = false
		return
	}
	a.Mode = ModeFilePackage
}

// looksLikeDiskImage 去掉压缩/光盘扩展名后, 判断是否像磁盘镜像
func looksLikeDiskImage(name string) bool {
	low := strings.ToLower(path.Base(name))
	for _, ext := range []string{".gz", ".xz", ".bz2", ".zst", ".zip", ".7z", ".rar"} {
		low = strings.TrimSuffix(low, ext)
	}
	for _, ext := range diskImageExts {
		if strings.HasSuffix(low, ext) {
			return true
		}
	}
	return false
}

func (a *Archive) entrySize(name string) int64 {
	for _, e := range a.Files {
		if e.Name == name {
			return e.Size
		}
	}
	return 0
}

func (a *Archive) largestFile() string {
	best, bestSz := "", int64(-1)
	for _, e := range a.Files {
		if e.Size > bestSz {
			best, bestSz = e.Name, e.Size
		}
	}
	return best
}

// ---------- 打开具体格式 ----------

// openStream 打开单流压缩 (gz/xz/bz2/zst); 未压缩时返回裸文件
func (a *Archive) openStream() (io.Reader, io.Closer, error) { return a.openStreamCtl(nil) }

// openStreamCtl 同上, 但把源文件的读取接上进度/取消 (ctl 可为 nil)
func (a *Archive) openStreamCtl(ctl *ProbeCtl) (io.Reader, io.Closer, error) {
	f, err := os.Open(a.Path)
	if err != nil {
		return nil, nil, err
	}
	var src io.Reader = f
	if ctl != nil {
		st, serr := f.Stat()
		if serr != nil {
			f.Close()
			return nil, nil, serr
		}
		src = &probeReader{r: f, ctl: ctl, total: st.Size()}
	}
	switch a.Format {
	case "gz", "tar.gz":
		zr, err := gzip.NewReader(src)
		if err != nil {
			f.Close()
			return nil, nil, err
		}
		return zr, &multiCloser{inner: zr, f: f}, nil
	case "xz", "tar.xz":
		xr, err := xz.NewReader(src)
		if err != nil {
			f.Close()
			return nil, nil, err
		}
		return xr, f, nil
	case "bz2", "tar.bz2":
		return bzip2.NewReader(src), f, nil
	case "zst":
		zr, err := zstd.NewReader(src)
		if err != nil {
			f.Close()
			return nil, nil, err
		}
		return zr, &multiCloser{inner: zr.IOReadCloser(), f: f}, nil
	}
	return src, f, nil
}

// multiCloser 同时关闭解压器与底层文件 (gzip/zstd 的 Close 不管底层 fd)
type multiCloser struct {
	inner io.Closer
	f     *os.File
}

func (m *multiCloser) Close() error {
	err := m.inner.Close()
	if cerr := m.f.Close(); err == nil {
		err = cerr
	}
	return err
}

// peekStreamKind 探测解压流的内容类型 (tar / 其它)
func peekStreamKind(r io.Reader) string {
	head := make([]byte, 512)
	n, _ := io.ReadFull(r, head)
	if n >= 262 && bytes.Equal(head[257:262], []byte("ustar")) {
		return "tar"
	}
	return "raw"
}

func (a *Archive) openContainer() (archiveImpl, error) {
	switch a.Format {
	case "zip":
		zr, err := zip.OpenReader(a.Path)
		if err != nil {
			return nil, err
		}
		return &zipIter{zr: zr}, nil
	case "7z":
		zr, err := sevenzip.OpenReader(a.Path)
		if err != nil {
			return nil, err
		}
		return &sevenZipIter{zr: zr}, nil
	case "rar":
		rr, err := rardecode.OpenReader(a.Path)
		if err != nil {
			return nil, err
		}
		return &rarIter{rr: rr}, nil
	}
	return nil, fmt.Errorf("不支持的归档格式: %s", a.Format)
}

func (a *Archive) openTar() (archiveImpl, error) { return a.openTarCtl(nil) }

func (a *Archive) openTarCtl(ctl *ProbeCtl) (archiveImpl, error) {
	var r io.Reader
	var closer io.Closer
	if a.Format == "tar" {
		f, err := os.Open(a.Path)
		if err != nil {
			return nil, err
		}
		if ctl != nil {
			st, serr := f.Stat()
			if serr != nil {
				f.Close()
				return nil, serr
			}
			r = &probeReader{r: f, ctl: ctl, total: st.Size()}
		} else {
			r = f
		}
		closer = f
	} else {
		var err error
		r, closer, err = a.openStreamCtl(ctl)
		if err != nil {
			return nil, err
		}
	}
	return &tarIter{tr: tar.NewReader(r), closer: closer}, nil
}

// openEntryStream 打开归档内某个文件的内容 (整盘镜像模式用)
func (a *Archive) openEntryStream(name string) (io.ReadCloser, error) {
	if a.Format == dirFormat {
		return a.openDirEntry(name)
	}
	switch {
	case containerFormats[a.Format]:
		it, err := a.openContainer()
		if err != nil {
			return nil, err
		}
		for {
			e, err := it.Next()
			if err == io.EOF {
				it.Close()
				return nil, fmt.Errorf("归档内未找到 %q", name)
			}
			if err != nil {
				it.Close()
				return nil, err
			}
			if e.IsDir || e.Name != name {
				continue
			}
			rc, err := it.Open()
			if err != nil {
				it.Close()
				return nil, err
			}
			return &entryReadCloser{rc: rc, it: it}, nil
		}
	default: // tar 家族: 顺序走到目标条目
		it, err := a.openTar()
		if err != nil {
			return nil, err
		}
		for {
			e, err := it.Next()
			if err == io.EOF {
				it.Close()
				return nil, fmt.Errorf("归档内未找到 %q", name)
			}
			if err != nil {
				it.Close()
				return nil, err
			}
			if e.IsDir || e.Name != name {
				continue
			}
			rc, err := it.Open()
			if err != nil {
				it.Close()
				return nil, err
			}
			return &entryReadCloser{rc: rc, it: it}, nil
		}
	}
}

type entryReadCloser struct {
	rc io.ReadCloser
	it archiveImpl
}

func (e *entryReadCloser) Read(p []byte) (int, error) { return e.rc.Read(p) }
func (e *entryReadCloser) Close() error {
	e.rc.Close()
	return e.it.Close()
}

// streamRawSize 估算单流压缩镜像的解压大小 (未知返回 0)
func (a *Archive) streamRawSize(f *os.File, fileSize int64, format string) int64 {
	if format != "gz" {
		return 0
	}
	if n := gzipDecodedSize(f, fileSize); n > 0 {
		return n
	}
	return sidecarSize(a.Path) // ≥4GiB 时 ISIZE 回绕, 靠发版包 sidecar
}

// ---------- 各格式迭代器 ----------

type zipIter struct {
	zr  *zip.ReadCloser
	idx int
	cur *zip.File
}

func (z *zipIter) Next() (*ArchiveEntry, error) {
	if z.idx >= len(z.zr.File) {
		return nil, io.EOF
	}
	z.cur = z.zr.File[z.idx]
	z.idx++
	return entryFrom(decodeZipName(z.cur), z.cur.FileInfo().IsDir(), int64(z.cur.UncompressedSize64))
}

// decodeZipName 处理"文件名不是 UTF-8"的 zip。
//
// zip 规范里有个 UTF-8 标志位; 没置位时名字按"创建者本地代码页"编码 —— 中文 Windows
// 上打出来的包多半是 GBK。Go 的 archive/zip 这时给出原始字节 (NonUTF8=true), 直接当
// UTF-8 用会变乱码, 于是卡上出现一堆问号/乱码文件名。这里按 GBK 兜底解一次。
func decodeZipName(f *zip.File) string {
	name := f.Name
	if !f.NonUTF8 || utf8.ValidString(name) {
		return name
	}
	if dec, err := simplifiedchinese.GBK.NewDecoder().String(name); err == nil && utf8.ValidString(dec) {
		return dec
	}
	return name
}

func (z *zipIter) Open() (io.ReadCloser, error) { return z.cur.Open() }
func (z *zipIter) Close() error                 { return z.zr.Close() }

type sevenZipIter struct {
	zr  *sevenzip.ReadCloser
	idx int
	cur *sevenzip.File
}

func (s *sevenZipIter) Next() (*ArchiveEntry, error) {
	if s.idx >= len(s.zr.File) {
		return nil, io.EOF
	}
	s.cur = s.zr.File[s.idx]
	s.idx++
	return entryFrom(s.cur.Name, s.cur.FileInfo().IsDir(), int64(s.cur.FileInfo().Size()))
}

func (s *sevenZipIter) Open() (io.ReadCloser, error) { return s.cur.Open() }
func (s *sevenZipIter) Close() error                 { return s.zr.Close() }

type rarIter struct {
	rr  *rardecode.ReadCloser
	cur *rardecode.FileHeader
}

func (r *rarIter) Next() (*ArchiveEntry, error) {
	h, err := r.rr.Next()
	if err != nil {
		return nil, err // io.EOF 由调用方识别
	}
	r.cur = h
	return entryFrom(h.Name, h.IsDir, h.UnPackedSize)
}

func (r *rarIter) Open() (io.ReadCloser, error) { return io.NopCloser(r.rr), nil }
func (r *rarIter) Close() error                 { return r.rr.Close() }

type tarIter struct {
	tr     *tar.Reader
	closer io.Closer
}

func (t *tarIter) Next() (*ArchiveEntry, error) {
	for {
		h, err := t.tr.Next()
		if err != nil {
			return nil, err
		}
		switch h.Typeflag {
		case tar.TypeReg:
			return entryFrom(h.Name, false, h.Size)
		case tar.TypeDir:
			return entryFrom(h.Name, true, 0)
		}
		// 链接/设备等条目跳过
	}
}

func (t *tarIter) Open() (io.ReadCloser, error) { return io.NopCloser(t.tr), nil }
func (t *tarIter) Close() error {
	if t.closer != nil {
		return t.closer.Close()
	}
	return nil
}

// entryFrom 归一化归档条目路径, 拒绝越界路径
func entryFrom(raw string, isDir bool, size int64) (*ArchiveEntry, error) {
	name := normalizeEntryName(raw)
	if name == "" {
		return nil, nil // 根目录 / 越界路径 → 跳过
	}
	return &ArchiveEntry{Name: name, IsDir: isDir, Size: size}, nil
}

// normalizeEntryName 统一分隔符, 去掉前导 / 与盘符, 拒绝 ..
func normalizeEntryName(raw string) string {
	s := strings.ReplaceAll(raw, "\\", "/")
	s = strings.TrimPrefix(s, "/")
	if i := strings.Index(s, ":"); i == 1 { // "C:/x"
		s = s[2:]
	}
	s = path.Clean(s)
	if s == "." || s == "/" {
		return ""
	}
	s = strings.TrimPrefix(s, "/")
	// 拒绝越界
	for _, part := range strings.Split(s, "/") {
		if part == ".." {
			return ""
		}
	}
	if s == "" || strings.HasPrefix(s, "../") {
		return ""
	}
	return s
}

// ErrNoImageInArchive 归档里没有可用的镜像
var ErrNoImageInArchive = errors.New("归档内没有可用于整盘写入的镜像文件")
