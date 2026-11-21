package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// The Windows operator's selected task is an execution contract, not a hint
// to the auto-detecting CLI.
type taskMode int

const (
	modeMakeCard taskMode = iota
	modeWriteImage
	modeFormatOnly
)

func prepareOperatorSource(mode taskMode, path string, target int64, full bool, label string, ctl *ProbeCtl) (*PreparedSource, error) {
	if target <= 0 {
		return nil, errors.New("请先选择并核对目标设备")
	}
	if mode == modeFormatOnly {
		return PrepareFormat(target, label)
	}
	if mode == modeWriteImage && path != "" && IsDirSource(path) {
		return nil, errors.New("整盘镜像模式不接受目录，请选择镜像文件")
	}
	p, err := PrepareSource(path, nil, target, full, 0, "", ctl)
	if err != nil {
		return nil, err
	}
	switch mode {
	case modeMakeCard:
		if !p.IsCard() {
			return nil, errors.New("检测到整盘镜像。请重新选刷机包，或手动切换到「写入整盘镜像」")
		}
		if a := p.Archive; a == nil || !hasRootBootFile(a) || len(a.BootRoot.Candidates) > 0 {
			return nil, errors.New("无法明确识别刷机包根目录。请选择含 fip.bin、boot.scr 或 .itb 的刷机包或目录")
		}
		if err := validatePackageCapacity(p); err != nil {
			return nil, err
		}
	case modeWriteImage:
		if p.IsCard() {
			return nil, errors.New("检测到文件包。请重新选择镜像，或手动切换到「制作刷机卡」")
		}
		image := path
		if p.Archive != nil && p.Archive.Image != "" {
			image = p.Archive.Image
		}
		if image == "" && p.Src != nil {
			image = p.Src.Name
		}
		if !looksLikeDiskImage(image) || (p.Archive != nil && p.Archive.Format == "img" && !bareImageName(image)) {
			return nil, errors.New("不能确认这是整盘镜像。请选择 .img、.raw、.iso 或其受支持的压缩体")
		}
		if p.Archive != nil && p.Archive.Image != "" && !bareImageName(p.Archive.Image) {
			return nil, errors.New("包内镜像还带独立压缩层，请解压后直接选择镜像")
		}
		if p.Archive == nil || p.Archive.Format != "img" {
			size, err := operatorImageSize(p.Src, target, ctl)
			if err != nil {
				return nil, err
			}
			p.Src.raw = size
			if p.Archive != nil {
				p.Archive.RawSz = size
			}
		}
		if p.TotalSize() <= 0 {
			return nil, errors.New("镜像内容为空，不能写入")
		}
	default:
		return nil, errors.New("请明确选择操作")
	}
	if p.TotalSize() > target {
		return nil, fmt.Errorf("目标容量 %s 小于所需 %s", HumanBytes(target), HumanBytes(p.TotalSize()))
	}
	return p, nil
}

func hasRootBootFile(a *Archive) bool {
	for _, f := range a.Files {
		if path.Dir(f.Name) == "." && markScore(path.Base(f.Name)) > 0 {
			return true
		}
	}
	return false
}

func bareImageName(name string) bool {
	ext := strings.ToLower(filepath.Ext(name))
	for _, want := range diskImageExts {
		if ext == want {
			return true
		}
	}
	return false
}

// Gzip footer lengths wrap at 4 GiB, and many streams have no reliable
// length in their metadata. Count decoded bytes before reporting a plan.
func operatorImageSize(src *ImageSource, target int64, ctl *ProbeCtl) (int64, error) {
	r, err := src.Open()
	if err != nil {
		return 0, err
	}
	defer r.Close()
	buf := make([]byte, 1<<20)
	var n int64
	for {
		if probeCanceled(ctl) {
			return 0, ErrProbeCanceled
		}
		nr, err := r.Read(buf)
		if int64(nr) > target-n {
			return 0, fmt.Errorf("镜像解压后超过目标容量 %s", HumanBytes(target))
		}
		n += int64(nr)
		if nr > 0 {
			probeReport(ctl, "read", n, 0)
		}
		if err == io.EOF {
			return n, nil
		}
		if err != nil {
			return 0, fmt.Errorf("预检解压失败: %w", err)
		}
	}
}

func validatePackageCapacity(p *PreparedSource) error {
	// At least fit each file and their logical bytes before any destructive
	// operation. Existing FAT32 layout validation also applies when writing.
	size := p.Plan.PartSize
	cluster := int64(512)
	switch {
	case size > 32<<30:
		cluster = 32 << 10
	case size > 16<<30:
		cluster = 16 << 10
	case size > 8<<30:
		cluster = 8 << 10
	case size > 260<<20:
		cluster = 4 << 10
	}
	// Conservative allowance for both allocation tables, long-name entries
	// and directory clusters. A plan rejected here never reaches disk I/O.
	entries := int64(len(p.Plan.Files) + len(p.Plan.Dirs))
	content := int64(32*512) + 2*((size/cluster+2)*4+511)/512*512
	content += (int64(len(p.Plan.Dirs))+1)*cluster + entries*(21*32+cluster)
	for _, entry := range p.Plan.Files {
		if entry.Size < 0 || entry.Size > 0xffffffff {
			return fmt.Errorf("文件 %s 超过 FAT32 单文件限制", entry.Name)
		}
		if entry.Size > p.Plan.PartSize-content {
			return errors.New("所选分区放不下刷机包文件")
		}
		content += entry.Size
	}
	return nil
}

type sourceFileStamp struct {
	path string
	info os.FileInfo
}

func readSourceStamp(path string) (sourceFileStamp, error) {
	f, err := os.Open(path)
	if err != nil {
		return sourceFileStamp{}, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return sourceFileStamp{}, err
	}
	return sourceFileStamp{path, st}, nil
}
func (s sourceFileStamp) current() bool {
	other, err := readSourceStamp(s.path)
	if err != nil {
		return false
	}
	st := other.info
	return os.SameFile(s.info, st) && s.info.Size() == st.Size() && s.info.Mode() == st.Mode() && s.info.ModTime().Equal(st.ModTime())
}

// The archive may be re-opened by the writer. Check the selected path and,
// for directory sources, every actual source file (including link targets).
func operatorSourceStamps(path string, p *PreparedSource, check func(string) error, ctl *ProbeCtl) ([]sourceFileStamp, error) {
	if p.IsFormatOnly() {
		return nil, nil
	}
	if path == "" {
		path = SelfExePath()
	}
	paths := []string{path}
	if a := p.Archive; a != nil {
		if a.Path != path {
			paths = append(paths, a.Path)
		}
		if a.Format == dirFormat {
			for _, d := range a.Dirs {
				paths = append(paths, filepath.Join(a.Path, filepath.FromSlash(d.srcName())))
			}
			for _, f := range a.Files {
				paths = append(paths, filepath.Join(a.Path, filepath.FromSlash(f.srcName())))
			}
		}
	}
	stamps := make([]sourceFileStamp, 0, len(paths))
	for _, name := range paths {
		if probeCanceled(ctl) {
			return nil, ErrProbeCanceled
		}
		if err := check(name); err != nil {
			return nil, err
		}
		st, err := readSourceStamp(name)
		if err != nil {
			return nil, fmt.Errorf("读取来源 %s: %w", name, err)
		}
		stamps = append(stamps, st)
	}
	return stamps, nil
}

func operatorStampsCurrent(stamps []sourceFileStamp, check func(string) error) error {
	for _, s := range stamps {
		if !s.current() {
			return fmt.Errorf("来源已变化，请重新分析：%s", s.path)
		}
		if err := check(s.path); err != nil {
			return err
		}
	}
	return nil
}

func operatorPlanText(d *DiskInfo, p *PreparedSource) string {
	if d == nil || p == nil {
		return ""
	}
	if !p.IsCard() {
		return fmt.Sprintf("磁盘 %d · 从盘首写入 %s；镜像范围外不作校验", d.Index, HumanBytes(p.TotalSize()))
	}
	action := "制作刷机卡"
	if p.IsFormatOnly() {
		action = "只格式化（不写入文件）"
	}
	part := p.Plan.PartSize / sectorSize * sectorSize
	left := d.Size - part - partStartLBA*sectorSize
	if left < 0 {
		left = 0
	}
	return fmt.Sprintf("磁盘 %d · %s · FAT32 %s · 卷标 %s · 尾部未分配 %s", d.Index, action, HumanBytes(part), p.Plan.Label, HumanBytes(left))
}

func operatorPlanDetails(d *DiskInfo, p *PreparedSource, src string) string {
	text := operatorPlanText(d, p)
	if p.IsFormatOnly() {
		return text
	}
	if p.IsCard() {
		return fmt.Sprintf("%s\r\n来源：%s · %d 个文件", text, src, len(p.Plan.Files))
	}
	if p.Archive != nil && p.Archive.Image != "" {
		src += " → " + p.Archive.Image
	}
	return strings.Join([]string{text, "来源：" + src}, "\r\n")
}
