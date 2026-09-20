// 内置数据源 — 「骨架程序 + 追加 payload」自包含结构 (MYS-1062 五轮)
//
// 布局 (exe/ELF 尾部附加数据, 加载器按 PE section / ELF program header 加载, 尾部被忽略):
//
//	[骨架二进制][payload 数据][metaJSON][uint32 jsonLen][16B magic]
//
// 由此程序可以在运行期:
//   - 从自身尾部定位并读取内置镜像 (无需整块载入内存, 用 SectionReader 流式读)
//   - 剥离已有 payload 得到**纯净骨架**, 再追加新镜像 → 产出第二个自带镜像的程序
//     (即「独自更换默认镜像、重新生成新程序」, 不需要构建机、不需要 Go 环境)
//
// 结构自描述: 末尾 20 字节 = jsonLen(4, LE) + magic(16); metaJSON 里记 skeleton_bytes,
// 读取时与推导出的偏移交叉校验, 随机文件被误判的概率可忽略。
package main

import (
	"compress/gzip"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	payloadMagic = "SE7FLASH-PAYLOAD" // 16 字节
	footerTail   = len(payloadMagic) + 4
	maxMetaJSON  = 1 << 20
)

// ErrNoPayload — 该文件不带内置数据源 (纯骨架程序)
var ErrNoPayload = errors.New("本程序未内置数据源")

// PayloadMeta 内置数据源的版本信息 (界面/CLI 展示, 亦写入新程序尾部)
type PayloadMeta struct {
	File          string `json:"file"`            // 原始镜像文件名
	Bytes         int64  `json:"bytes"`           // 解压后大小
	SHA256        string `json:"sha256"`          // 解压后内容 sha256
	StoredBytes   int64  `json:"stored_bytes"`    // 内置数据字节数
	StoredSHA256  string `json:"stored_sha256"`   // 内置数据 sha256
	Compressed    bool   `json:"compressed"`      // 内置数据是否为 gzip
	PackedAt      string `json:"packed_at"`       // 打包时间 (RFC3339)
	SourcePath    string `json:"source_path"`     // 打包时的源路径 (留证)
	BuildVer      string `json:"build_ver"`       // 镜像版本号 (若有)
	ToolVersion   string `json:"tool_version"`    // 打包它的烧录工具版本
	Origin        string `json:"origin"`          // build = 构建机打包 / repack = 程序内生成
	SkeletonBytes int64  `json:"skeleton_bytes"`  // 骨架大小 (= payload 起始偏移)
	SkeletonSHA   string `json:"skeleton_sha256"` // 骨架 sha256 (校验用)
}

// Payload 已定位的内置镜像 (不含数据本体)
type Payload struct {
	Meta          PayloadMeta
	Offset        int64 // payload 起始偏移 = SkeletonBytes
	Size          int64 // payload 字节数
	SelfPath      string
	HasSkeleton   bool // 是否成功定位骨架 (始终为真; 保留语义位)
	skeletonBytes int64
}

// ReadPayloadFrom 从文件尾部解析内置镜像; 无 payload → ErrNoPayload
func ReadPayloadFrom(r io.ReaderAt, size int64) (*Payload, error) {
	if size < int64(footerTail)+2 {
		return nil, ErrNoPayload
	}
	tail := make([]byte, footerTail)
	if _, err := r.ReadAt(tail, size-int64(footerTail)); err != nil {
		return nil, err
	}
	if string(tail[4:]) != payloadMagic {
		return nil, ErrNoPayload
	}
	jl := int64(binary.LittleEndian.Uint32(tail[:4]))
	if jl <= 0 || jl > maxMetaJSON || size-int64(footerTail)-jl < 0 {
		return nil, ErrNoPayload
	}
	jb := make([]byte, jl)
	if _, err := r.ReadAt(jb, size-int64(footerTail)-jl); err != nil {
		return nil, err
	}
	var m PayloadMeta
	if err := json.Unmarshal(jb, &m); err != nil {
		return nil, ErrNoPayload
	}
	off := size - int64(footerTail) - jl - m.StoredBytes
	if m.StoredBytes <= 0 || off <= 0 || off != m.SkeletonBytes {
		return nil, ErrNoPayload
	}
	return &Payload{Meta: m, Offset: off, Size: m.StoredBytes, HasSkeleton: true, skeletonBytes: off}, nil
}

// SelfExePath 当前可执行文件路径 (解析符号链接)
func SelfExePath() string {
	p, err := os.Executable()
	if err != nil {
		return ""
	}
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return p
}

// OpenSelfPayload 打开当前程序的内置镜像 (无则 ErrNoPayload)
func OpenSelfPayload() (*Payload, error) {
	self := SelfExePath()
	if self == "" {
		return nil, ErrNoPayload
	}
	return OpenPayloadFile(self)
}

// OpenPayloadFile 打开任意文件的内置镜像 (用于校验生成的新程序)
func OpenPayloadFile(path string) (*Payload, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	p, err := ReadPayloadFrom(f, st.Size())
	if err != nil {
		return nil, err
	}
	p.SelfPath = path
	return p, nil
}

// Skeleton 返回不含 payload 的纯净骨架读取器 (调用方 Close)
func (p *Payload) Skeleton() (io.ReadCloser, error) {
	f, err := os.Open(p.SelfPath)
	if err != nil {
		return nil, err
	}
	return &sectionReadCloser{SectionReader: io.NewSectionReader(f, 0, p.Offset), f: f}, nil
}

// open 返回解压后的镜像流 (调用方 Close)
func (p *Payload) open() (io.ReadCloser, error) {
	f, err := os.Open(p.SelfPath)
	if err != nil {
		return nil, err
	}
	sr := io.NewSectionReader(f, p.Offset, p.Size)
	if !p.Meta.Compressed {
		return &sectionReadCloser{SectionReader: sr, f: f}, nil
	}
	zr, err := gzip.NewReader(sr)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("内置镜像 gzip 解压失败: %w", err)
	}
	return &gzSectionReadCloser{zr: zr, f: f}, nil
}

type sectionReadCloser struct {
	*io.SectionReader
	f *os.File
}

func (s *sectionReadCloser) Close() error { return s.f.Close() }

type gzSectionReadCloser struct {
	zr *gzip.Reader
	f  *os.File
}

func (g *gzSectionReadCloser) Read(p []byte) (int, error) { return g.zr.Read(p) }
func (g *gzSectionReadCloser) Close() error {
	g.zr.Close()
	return g.f.Close()
}

// ---- 展示 (界面 / CLI) ----

// HasEmbeddedImage 当前程序是否内置镜像
func HasEmbeddedImage() bool {
	_, err := OpenSelfPayload()
	return err == nil
}

// EmbeddedImageInfo 当前程序内置镜像的元信息 (未内置 → nil)
func EmbeddedImageInfo() *PayloadMeta {
	p, err := OpenSelfPayload()
	if err != nil {
		return nil
	}
	return &p.Meta
}

// OpenEmbedded 把内置数据源作为写入源 (未内置则报错)
func OpenEmbedded() (*ImageSource, error) {
	p, err := OpenSelfPayload()
	if err != nil {
		return nil, fmt.Errorf("%w (可用「浏览…」选镜像文件, 或用 repack 生成自带镜像的新程序)", err)
	}
	return &ImageSource{
		Name:     p.Meta.File,
		raw:      p.Meta.Bytes,
		gzip:     p.Meta.Compressed,
		openFn:   p.open,
		embedded: true,
	}, nil
}

// EmbeddedSummary 一行摘要
func EmbeddedSummary() string {
	m := EmbeddedImageInfo()
	if m == nil {
		return "未内置数据源 (需选择镜像/文件包/目录, 或生成自带数据源的新程序)"
	}
	return fmt.Sprintf("%s  内容 %s  sha256 %s  内置体积 %s  %s",
		m.File, HumanBytes(m.Bytes), shortHash(m.SHA256), HumanBytes(m.StoredBytes), originText(m.Origin))
}

// EmbeddedLines 命令行 (se7flash info) 用多行版本信息; 标签按显示宽度对齐
func EmbeddedLines() []string {
	const lw = 12
	m := EmbeddedImageInfo()
	if m == nil {
		return []string{
			padRight("状态", lw) + ": " + "未内置数据源",
			padRight("可选", lw) + ": " + "用「浏览文件…」/「浏览目录…」选择来源",
			padRight("或", lw) + ": " + "用 repack / 界面按钮生成自带数据源的新程序",
		}
	}
	return []string{
		padRight("写卡工具", lw) + ": v" + orDashStr(m.ToolVersion),
		padRight("数据源", lw) + ": " + originText(m.Origin),
		padRight("文件名", lw) + ": " + m.File,
		padRight("内容大小", lw) + ": " + fmt.Sprintf("%s (%d 字节)", HumanBytes(m.Bytes), m.Bytes),
		padRight("内容 sha256", lw) + ": " + m.SHA256,
		padRight("内置体积", lw) + ": " + HumanBytes(m.StoredBytes),
		padRight("打包时间", lw) + ": " + fmtTime(m.PackedAt),
		padRight("固件版本", lw) + ": " + orDashStr(m.BuildVer),
		padRight("程序骨架", lw) + ": " + HumanBytes(m.SkeletonBytes),
	}
}

// ImagePropertyRows 界面用「项目/内容」两列展示当前镜像信息。
// imgPath 为空 = 程序内置镜像; 否则为外部镜像文件。用真表格取代空格对齐, 中文不会错位。
func ImagePropertyRows(imgPath string) [][2]string {
	if strings.TrimSpace(imgPath) == "" {
		p, err := OpenSelfPayload()
		if err != nil {
			return [][2]string{
				{"状态", "本程序未内置数据源"},
				{"下一步", "点「浏览文件…」/「浏览目录…」选择来源"},
			}
		}
		m := p.Meta
		rows := [][2]string{
			{"来源", originText(m.Origin)},
			{"文件名", m.File},
			{"内容大小", fmt.Sprintf("%s (%d 字节)", HumanBytes(m.Bytes), m.Bytes)},
			{"内容 sha256", m.SHA256},
			{"内置体积", HumanBytes(m.StoredBytes)},
			{"打包时间", fmtTime(m.PackedAt)},
			{"固件版本", orDashStr(m.BuildVer)},
			{"写卡工具", "v" + orDashStr(m.ToolVersion)},
			{"程序骨架", HumanBytes(m.SkeletonBytes) + " (换镜像时复用)"},
		}
		return rows
	}
	src, err := OpenImage(imgPath)
	if err != nil {
		return [][2]string{
			{"来源", "外部文件"},
			{"路径", imgPath},
			{"当前状态", "不可用: " + err.Error()},
		}
	}
	kind := "gzip 压缩"
	if !src.gzip {
		kind = "未压缩 (.img)"
	}
	rows := [][2]string{
		{"来源", "外部文件"},
		{"路径", imgPath},
		{"文件名", src.Display()},
		{"大小", HumanBytes(src.Size())},
		{"格式", kind},
	}
	if src.Size() == 0 {
		rows = append(rows, [2]string{"提示", "大小未知, 写卡前请自行确认卡容量"})
	}
	return rows
}

func originText(o string) string {
	switch o {
	case "repack":
		return "本程序生成"
	case "build":
		return "构建机内置"
	case "":
		return "-"
	}
	return o
}

func fmtTime(s string) string {
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t.Format("2006-01-02 15:04:05")
	}
	return orDashStr(s)
}

func orDashStr(s string) string {
	if s == "" {
		return "-"
	}
	return s
}

func shortHash(h string) string {
	if len(h) <= 12 {
		return h
	}
	return h[:12] + "…"
}

// writeFooter 追加 metaJSON + jsonLen + magic
func writeFooter(w io.Writer, m PayloadMeta) error {
	b, err := json.Marshal(m)
	if err != nil {
		return err
	}
	if len(b) > maxMetaJSON {
		return errors.New("meta 过大")
	}
	var l [4]byte
	binary.LittleEndian.PutUint32(l[:], uint32(len(b)))
	if _, err := w.Write(b); err != nil {
		return err
	}
	if _, err := w.Write(l[:]); err != nil {
		return err
	}
	_, err = io.WriteString(w, payloadMagic)
	return err
}
