// SE7 TF 卡烧录工具 — 平台无关核心 (镜像源 / 写入 / 回读校验)
//
// 设计: 磁盘枚举与原始读写由平台层实现 (disk_windows.go / disk_linux.go),
// 本文件只依赖 DiskDevice 抽象, 因此可在 Linux 上用 loop 盘做完整单测。
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const chunkSize = 1 << 20 // 1 MiB — 与 TF 卡扇区/簇对齐

// DiskDevice — 目标块设备 (Windows 物理盘 / Linux 块设备)
type DiskDevice interface {
	Path() string // \\.\PhysicalDriveN / /dev/sdX
	Size() int64  // 容量 (字节)
	WriteAt(p []byte, off int64) (int, error)
	ReadAt(p []byte, off int64) (int, error)
	Sync() error
	Close() error
}

// ImageSource — 烧录源: 外部文件 (.img/.img.gz) / 程序内置镜像 (openFn) / 内存数据 (data, 测试用)
type ImageSource struct {
	Path string // 外部文件路径; 内置镜像为空
	Name string // 展示名 (文件名)
	gzip bool
	raw  int64  // .img: 文件大小; .gz: 已知解压大小时填, 未知为 0
	data []byte // 内存镜像数据 (nil = 从 Path 或 openFn 读)

	openFn   func() (io.ReadCloser, error) // 程序内置镜像 (exe 尾部 payload 区间)
	embedded bool
}

// Display 展示名 (界面/日志用)
func (s *ImageSource) Display() string {
	if s.Name != "" {
		return s.Name
	}
	if s.Path != "" {
		return s.Path
	}
	return "(未命名镜像)"
}

// Embedded 是否为程序内置镜像
func (s *ImageSource) Embedded() bool { return s.embedded || s.data != nil }

// OpenImage 打开镜像; 自动识别 gzip (按扩展名与魔数)
func OpenImage(path string) (*ImageSource, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	src := &ImageSource{Path: path, Name: filepath.Base(path)}
	magic := make([]byte, 2)
	if _, err := io.ReadFull(f, magic); err == nil && magic[0] == 0x1f && magic[1] == 0x8b {
		src.gzip = true
		src.raw = gzipDecodedSize(f, st.Size())
		if src.raw == 0 {
			// GNU gzip 对 ≥4GiB 输入 ISIZE 回绕 (恒为 0) → 读同目录 sidecar
			// (<镜像>.info, 发版包随附) 取解压大小, 保证容量预检与百分比进度可用
			src.raw = sidecarSize(path)
		}
	} else {
		src.raw = st.Size()
	}
	if src.raw == 0 && !src.gzip {
		return nil, errors.New("镜像文件为空")
	}
	return src, nil
}

// gzipDecodedSize 取解压后大小: 尾部 4 字节 ISIZE (单 member 且 <4GiB 时准确)。
// GNU gzip 对 >4GiB 输入写多个 member, ISIZE 会回绕 → 返回 0 表示"未知"。
func gzipDecodedSize(f *os.File, fileSize int64) int64 {
	if fileSize < 18 {
		return 0
	}
	buf := make([]byte, 4)
	if _, err := f.ReadAt(buf, fileSize-4); err != nil {
		return 0
	}
	n := int64(binary.LittleEndian.Uint32(buf))
	if n <= 0 {
		return 0 // 0 或回绕 → 未知 (进度条转为"已写入量"模式)
	}
	return n
}

// Open 返回解压后的顺序读取流 (调用方负责 Close)。内置镜像走文件区间流式读取。
func (s *ImageSource) Open() (io.ReadCloser, error) {
	if s.openFn != nil {
		return s.openFn()
	}
	if s.data != nil {
		br := bytes.NewReader(s.data)
		if !s.gzip {
			return io.NopCloser(br), nil
		}
		zr, err := gzip.NewReader(br)
		if err != nil {
			return nil, fmt.Errorf("内置镜像 gzip 解压失败: %w", err)
		}
		return zr, nil
	}
	f, err := os.Open(s.Path)
	if err != nil {
		return nil, err
	}
	if !s.gzip {
		return f, nil
	}
	zr, err := gzip.NewReader(f)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("gzip 解压失败: %w", err)
	}
	return &gzReadCloser{zr: zr, f: f}, nil
}

type gzReadCloser struct {
	zr *gzip.Reader
	f  *os.File
}

func (g *gzReadCloser) Read(p []byte) (int, error) { return g.zr.Read(p) }
func (g *gzReadCloser) Close() error {
	g.zr.Close()
	return g.f.Close()
}

// Size 返回解压后大小 (0 = 未知)
func (s *ImageSource) Size() int64 { return s.raw }

// Progress 进度回调 (phase: "write" / "verify" / "files" / "check" / "read" / "scan")
type Progress func(phase string, done, total int64, rateBps float64)

// FlashResult 烧录/校验结果
type FlashResult struct {
	ImageBytes   int64
	WrittenBytes int64
	SkippedBytes int64 // 全零且卡上已经是零 → 整块跳过的字节数
	WriteElapsed time.Duration
	VerifyOK     bool
	VerifyBytes  int64
	MismatchOff  int64 // 首个不一致偏移 (-1 = 无)
	MismatchCnt  int64
	SHA256       string // 镜像内容 sha256 (写入时同步计算)
	ReadSHA256   string // 回读内容 sha256
}

// Flash 烧录镜像到设备并回读校验:
//
//	镜像流 → 1MiB 分块顺序写入 (末块补零到扇区对齐)
//	→ Sync 刷盘 → 回读同样字节数逐块比对 (定位首个不一致偏移 + 累计不一致字节)
//	返回 SHA256 (镜像内容) 与 ReadSHA256 (回读内容) 供现场留证核对
func Flash(dev DiskDevice, src *ImageSource, verify bool, cb Progress) (*FlashResult, error) {
	if dev.Size() < src.Size() && src.Size() > 0 {
		return nil, fmt.Errorf("目标容量 %.2f GiB 小于镜像 %.2f GiB",
			float64(dev.Size())/(1<<30), float64(src.Size())/(1<<30))
	}
	rd, err := src.Open()
	if err != nil {
		return nil, err
	}
	defer rd.Close()

	res := &FlashResult{MismatchOff: -1}
	buf := make([]byte, chunkSize)
	imgHash := sha256.New()
	var off int64
	t0 := time.Now()
	last := t0
	var lastBytes int64
	for {
		n, rerr := io.ReadFull(rd, buf)
		if n > 0 {
			blk := buf[:n]
			// 稀疏内容: 源块整块全零时, 先看卡上对应位置是不是本来就是零 —— 是就
			// 一个字节都不写 (恢复镜像九成以上是全零; 卡本身也多半是零)。
			// 反过来, 卡上那块有旧数据时照样会写下去, 结果与逐字节写完全一致。
			if skip, serr := skipZeroBlock(dev, blk, off); serr != nil {
				return res, serr
			} else if skip {
				res.SkippedBytes += int64(n)
			} else {
				// 扇区对齐: Windows 物理盘要求写入长度为扇区整数倍 (512B/4Kn),
				// 末块不足则补零到 4096 对齐 (整盘镜像语义, 尾部补零无副作用)
				if _, werr := dev.WriteAt(padSector(blk), off); werr != nil {
					return res, fmt.Errorf("写入偏移 %d 失败: %w", off, werr)
				}
				res.WrittenBytes += int64(n)
			}
			imgHash.Write(blk)
			off += int64(n)
			if cb != nil {
				now := time.Now()
				if now.Sub(last) >= 200*time.Millisecond {
					rate := float64(res.WrittenBytes-lastBytes) / now.Sub(last).Seconds()
					cb("write", off, src.Size(), rate)
					last, lastBytes = now, res.WrittenBytes
				}
			}
		}
		if rerr == io.EOF || rerr == io.ErrUnexpectedEOF {
			break
		}
		if rerr != nil {
			return res, fmt.Errorf("读取镜像失败 (偏移 %d): %w", off, rerr)
		}
	}
	res.ImageBytes = off
	res.WriteElapsed = time.Since(t0)
	res.SHA256 = fmt.Sprintf("%x", imgHash.Sum(nil))
	if cb != nil {
		cb("write", off, src.Size(), 0)
	}

	if err := dev.Sync(); err != nil {
		return res, fmt.Errorf("刷盘失败 (数据可能仍在缓存): %w", err)
	}
	if !verify {
		return res, nil
	}
	if err := VerifyOnly(dev, src, cb, res); err != nil {
		return res, err
	}
	return res, nil
}

// VerifyOnly 仅回读校验 (不写盘): 把设备前 ImageBytes 字节与镜像逐块比对。
// res 传写入阶段结果 (含 ImageBytes) 或最小 &FlashResult{ImageBytes: N, MismatchOff: -1};
// 校验后填充 VerifyBytes / ReadSHA256 / VerifyOK / MismatchOff / MismatchCnt。
func VerifyOnly(dev DiskDevice, src *ImageSource, cb Progress, res *FlashResult) error {
	if res == nil {
		res = &FlashResult{MismatchOff: -1}
	}
	if res.ImageBytes <= 0 {
		return fmt.Errorf("待校验长度未知 (需先烧录, 或用 --bytes 指定)")
	}
	if res.MismatchOff == 0 {
		res.MismatchOff = -1
	}
	rd, err := src.Open()
	if err != nil {
		return err
	}
	defer rd.Close()
	buf := make([]byte, chunkSize)
	readHash := sha256.New()
	imgHash := sha256.New()
	hashImage := res.SHA256 == ""
	var voff int64
	last := time.Now()
	var lastBytes int64
	for voff < res.ImageBytes {
		want := int64(len(buf))
		if res.ImageBytes-voff < want {
			want = res.ImageBytes - voff
		}
		n, rerr := io.ReadFull(rd, buf[:want])
		if n > 0 {
			got := make([]byte, len(padSector(buf[:n])))
			if _, derr := dev.ReadAt(got, voff); derr != nil {
				return fmt.Errorf("回读偏移 %d 失败: %w", voff, derr)
			}
			readHash.Write(got[:n])
			if hashImage {
				imgHash.Write(buf[:n])
			}
			if !bytes.Equal(got, buf[:n]) {
				for i := 0; i < n; i++ {
					if got[i] != buf[i] {
						if res.MismatchOff < 0 {
							res.MismatchOff = voff + int64(i)
						}
						res.MismatchCnt++
					}
				}
			}
			voff += int64(n)
			if cb != nil {
				now := time.Now()
				if now.Sub(last) >= 200*time.Millisecond {
					cb("verify", voff, res.ImageBytes, float64(voff-lastBytes)/now.Sub(last).Seconds())
					last, lastBytes = now, voff
				}
			}
		}
		if rerr == io.EOF || rerr == io.ErrUnexpectedEOF {
			break
		}
		if rerr != nil {
			return fmt.Errorf("读取镜像失败 (校验, 偏移 %d): %w", voff, rerr)
		}
	}
	res.VerifyBytes = voff
	res.ReadSHA256 = fmt.Sprintf("%x", readHash.Sum(nil))
	if hashImage {
		res.SHA256 = fmt.Sprintf("%x", imgHash.Sum(nil))
	}
	res.VerifyOK = res.MismatchCnt == 0 && voff == res.ImageBytes
	if cb != nil {
		cb("verify", voff, res.ImageBytes, 0)
	}
	return nil
}

// HumanBytes 人类可读容量
func HumanBytes(n int64) string {
	switch {
	case n >= 1<<30:
		return fmt.Sprintf("%.2f GiB", float64(n)/(1<<30))
	case n >= 1<<20:
		return fmt.Sprintf("%.1f MiB", float64(n)/(1<<20))
	case n >= 1<<10:
		return fmt.Sprintf("%.1f KiB", float64(n)/(1<<10))
	}
	return fmt.Sprintf("%d B", n)
}

// HumanRate 速率
func HumanRate(bps float64) string {
	if bps <= 0 {
		return "-"
	}
	return HumanBytes(int64(bps)) + "/s"
}

// ExportImageSHA256 单独计算镜像内容 sha256 (供 --hash 模式/离线核对)
func ExportImageSHA256(path string) (string, int64, error) {
	src, err := OpenImage(path)
	if err != nil {
		return "", 0, err
	}
	return ExportImageSHA256Src(src)
}

// ExportImageSHA256Src 同 ExportImageSHA256, 但直接接受已构造的 ImageSource (含内置镜像)
func ExportImageSHA256Src(src *ImageSource) (string, int64, error) {
	rd, err := src.Open()
	if err != nil {
		return "", 0, err
	}
	defer rd.Close()
	h := sha256.New()
	n, err := io.Copy(h, rd)
	if err != nil {
		return "", 0, err
	}
	return fmt.Sprintf("%x", h.Sum(nil)), n, nil
}

// logDedup 抑制连续重复的日志行 (反复刷新磁盘时不再刷屏)
type logDedup struct{ last string }

// Accept 与上一条相同时返回 false (调用方应跳过该行)
func (d *logDedup) Accept(line string) bool {
	if line == d.last {
		return false
	}
	d.last = line
	return true
}

// Reset 清空去重状态 (新一轮操作开始时调用)
func (d *logDedup) Reset() { d.last = "" }

// displayWidth 等宽环境下的显示宽度: 中日韩全角字符占 2 列, 其余占 1 列。
// 用 ASCII 空格给中文补位必然错位 (「型号」与「目标磁盘」的显示宽度并不等于字符数)。
func displayWidth(s string) int {
	w := 0
	for _, r := range s {
		switch {
		case r >= 0x1100 && r <= 0x115F, // 谚文字母
			r >= 0x2E80 && r <= 0xA4CF, // 中日韩部首 … 彝文
			r >= 0xAC00 && r <= 0xD7A3, // 谚文音节
			r >= 0xF900 && r <= 0xFAFF, // 中日韩兼容表意文字
			r >= 0xFE30 && r <= 0xFE6F, // 中日韩兼容形式
			r >= 0xFF00 && r <= 0xFF60, // 全角 ASCII
			r >= 0xFFE0 && r <= 0xFFE6,
			r >= 0x20000 && r <= 0x3FFFD: // 中日韩扩展区
			w += 2
		default:
			w++
		}
	}
	return w
}

// padRight 右侧补空格到指定显示宽度 (已超宽则原样返回)
func padRight(s string, width int) string {
	if d := width - displayWidth(s); d > 0 {
		return s + strings.Repeat(" ", d)
	}
	return s
}

// ParseDiskArg 允许用户用 "1" / "PhysicalDrive1" / "\\.\PhysicalDrive1" / "/dev/loop0" 指定磁盘
func ParseDiskArg(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	if n, err := parseUint(s); err == nil {
		return fmt.Sprintf("\\\\.\\PhysicalDrive%d", n)
	}
	return s
}

func parseUint(s string) (uint64, error) {
	var v uint64
	if _, err := fmt.Sscanf(s, "%d", &v); err != nil {
		return 0, err
	}
	return v, nil
}

// isAllZero 判断块是否全零
func isAllZero(p []byte) bool {
	for _, b := range p {
		if b != 0 {
			return false
		}
	}
	return true
}

// skipZeroBlock 全零源块可否整块跳过写入。
//
// 只有"卡上同一位置读回来也全是零"才跳 —— 跳过的前提是结果不变, 不是假设卡是空的。
// 读失败 (如末块超出设备容量) 时保守返回 false, 走正常写入路径。
func skipZeroBlock(dev DiskDevice, blk []byte, off int64) (bool, error) {
	if !isAllZero(blk) {
		return false, nil
	}
	cur := make([]byte, len(padSector(blk)))
	if _, err := dev.ReadAt(cur, off); err != nil {
		return false, nil
	}
	return isAllZero(cur[:len(blk)]), nil
}

// padSector 将数据补齐到 4096 字节整数倍 (物理盘读写对齐要求; 512B/4Kn 均安全)
func padSector(p []byte) []byte {
	const align = 4096
	if len(p)%align == 0 {
		return p
	}
	out := make([]byte, (len(p)/align+1)*align)
	copy(out, p)
	return out
}

// sidecarSize 读 <镜像>.info (发版包随附: bytes=/sha256=) 中的解压大小; 无则 0
func sidecarSize(path string) int64 {
	b, err := os.ReadFile(path + ".info")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "bytes=") {
			continue
		}
		var n int64
		if _, err := fmt.Sscanf(strings.TrimPrefix(line, "bytes="), "%d", &n); err == nil && n > 0 {
			return n
		}
	}
	return 0
}
