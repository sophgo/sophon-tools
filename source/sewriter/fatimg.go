// 文件包 → MBR + FAT32 卡镜像 (MYS-1062 八轮)
//
// 做 SE5/SE7/SE9 的 TF 刷机卡: 把压缩包里的一批文件写进一张按 MBR+FAT32 格式化过的卡。
//
// 实现分两块:
//   - 本文件: 分区/卷标规划, 以及把归档里的文件写进 FAT32
//   - cardbuild.go: 把 go-diskfs 直接架在目标设备上 (卡上直接建, 不落中间镜像)
package main

import (
	"fmt"
	"io"
	"os"
	"path"
	"strings"

	"github.com/diskfs/go-diskfs/filesystem"
)

const (
	// 分区起始扇区 (1 MiB 对齐, 与常规卡布局一致)
	partStartLBA = 2048
	sectorSize   = 512
	// FAT32 最小可用尺寸 (再小 go-diskfs 会拒绝建卷)
	minFAT32Size = 64 << 20
	// 内容之外的余量 (目录/FAT 表 + 后续手工放文件的空档)
	slackRatio = 0.25
	slackMin   = 16 << 20
)

// PackagePlan 文件包写入计划
type PackagePlan struct {
	TotalSize int64  // 卡镜像总大小 (= 分区大小 + 1MiB 对齐头)
	PartSize  int64  // 分区大小
	Label     string // 卷标 (≤11 字符)
	Files     []ArchiveEntry
	Dirs      []ArchiveEntry
}

// PlanCardImage 计算卡镜像尺寸与卷标
//
// totalTarget: 目标盘容量; 0 = 未知。requireFullDisk=true 表示整卡格式化。
func PlanCardImage(pkg *Archive, totalTarget int64, requireFullDisk bool) (*PackagePlan, error) {
	return PlanCardImageSized(pkg, totalTarget, requireFullDisk, 0)
}

// PlanCardImageSized 同 PlanCardImage, 但可用 overrideMB 指定分区大小 (MiB)
func PlanCardImageSized(pkg *Archive, totalTarget int64, requireFullDisk bool, overrideMB int64) (*PackagePlan, error) {
	var content int64
	for _, f := range pkg.Files {
		content += f.Size
	}
	plan := &PackagePlan{Files: pkg.Files, Dirs: pkg.Dirs}

	switch {
	case overrideMB > 0:
		plan.TotalSize = roundUp(overrideMB<<20, 1<<20) + partStartLBA*sectorSize
	case requireFullDisk && totalTarget > 0:
		plan.TotalSize = totalTarget
	default:
		// 内容 + 余量, 向上取整到 1MiB
		need := content + content/4
		if need < content+slackMin {
			need = content + slackMin
		}
		if need < minFAT32Size {
			need = minFAT32Size
		}
		plan.TotalSize = roundUp(need, 1<<20)
		if totalTarget > 0 && plan.TotalSize > totalTarget {
			plan.TotalSize = totalTarget
		}
	}
	if plan.TotalSize > fat32MaxSize {
		plan.TotalSize = fat32MaxSize
	}
	if plan.TotalSize < minFAT32Size {
		return nil, fmt.Errorf("目标盘 %s 太小, 无法建立 FAT32 (至少需要 %s)",
			HumanBytes(plan.TotalSize), HumanBytes(minFAT32Size))
	}
	plan.PartSize = plan.TotalSize - partStartLBA*sectorSize
	plan.Label = volumeLabel(pkg)
	return plan, nil
}

// fat32MaxSize FAT32 规范上限 (2 TiB 量级)
const fat32MaxSize int64 = 2198754099200

func roundUp(v, align int64) int64 {
	if v%align == 0 {
		return v
	}
	return (v/align + 1) * align
}

// volumeLabel 由来源名推导卷标: 大写, 仅 A-Z0-9_- , 最长 11 字符
func volumeLabel(pkg *Archive) string {
	base := strings.ToUpper(strings.TrimSuffix(path.Base(pkg.Path), path.Ext(pkg.Path)))
	var b strings.Builder
	for _, r := range base {
		switch {
		case r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '_', r == '-':
			b.WriteRune(r)
		case r == '.' || r == ' ':
			b.WriteRune('-')
		}
		if b.Len() >= 11 {
			break
		}
	}
	out := strings.Trim(b.String(), "-")
	if out == "" {
		return "SE"
	}
	return out
}

// writeOneFile 把 rc 写入 FAT32 的指定路径 (自动补建父目录)
func writeOneFile(fs filesystem.FileSystem, name string, rc io.Reader, onProgress func(int64)) error {
	p := fatPath(name)
	if dir := path.Dir(p); dir != "/" && dir != "." {
		if err := fs.Mkdir(dir); err != nil && !os.IsExist(err) {
			// Mkdir 在部分实现下父目录已存在会报错, 这里继续尝试写文件
			_ = err
		}
	}
	w, err := fs.OpenFile(p, os.O_CREATE|os.O_RDWR|os.O_TRUNC)
	if err != nil {
		return fmt.Errorf("建文件 %s 失败: %w", name, err)
	}
	defer w.Close()
	buf := make([]byte, 1<<20)
	var n int64
	for {
		rn, rerr := rc.Read(buf)
		if rn > 0 {
			if _, werr := w.Write(buf[:rn]); werr != nil {
				return fmt.Errorf("写文件 %s 失败: %w", name, werr)
			}
			n += int64(rn)
			if onProgress != nil {
				onProgress(int64(rn))
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return fmt.Errorf("读归档内 %s 失败: %w", name, rerr)
		}
	}
	return nil
}

func fatPath(name string) string {
	return "/" + strings.TrimPrefix(name, "/")
}

// preflightNames 检查文件包里的名字能不能放进 FAT32。
//
// 长文件名 (LFN) 以 **UCS-2** 存储, 所以中日韩等 BMP 字符是支持的
// (上游 go-diskfs 曾因短名生成的 rune→byte 截断 bug 写不进中文名, 已在
// third_party/go-diskfs 打补丁修复)。真正存不下/非法的只有:
//   - BMP 之外的字符 (码点 > 0xFFFF, 如 emoji) —— UCS-2 表示不了
//   - FAT 规定的非法字符  < > : " / \ | ? *  与控制字符
func preflightNames(plan *PackagePlan) error {
	var bad []string
	check := func(name string) {
		for _, part := range strings.Split(name, "/") {
			if part == "" {
				continue
			}
			for _, r := range part {
				if r > 0xFFFF || r < 0x20 || strings.ContainsRune(`<>:"/\|?*`, r) {
					bad = append(bad, name)
					return
				}
			}
		}
	}
	for _, f := range plan.Files {
		check(f.Name)
	}
	for _, d := range plan.Dirs {
		check(d.Name)
	}
	if len(bad) > 0 {
		show := bad
		if len(show) > 5 {
			show = show[:5]
		}
		return fmt.Errorf("文件包内有 FAT32 无法表示的名字: %s%s\n"+
			"FAT32 不支持: BMP 之外的字符(如 emoji)、以及 < > : \" / \\ | ? * 与控制字符。\n"+
			"中文/日文/韩文等常规字符是支持的, 请检查上面这些条目。",
			strings.Join(show, ", "), map[bool]string{true: " …", false: ""}[len(bad) > 5])
	}
	return nil
}

// openFiles 打开文件包的顺序迭代器 (调用方负责 Close)
func (a *Archive) openFiles() (archiveImpl, error) {
	if a.Format == dirFormat {
		return &dirIter{a: a}, nil // 目录源: 逐文件直接从磁盘读
	}
	if containerFormats[a.Format] {
		return a.openContainer()
	}
	return a.openTar()
}

// ImageOpenFunc 整盘模式下打开镜像数据流
func (a *Archive) ImageOpenFunc() func() (io.ReadCloser, error) {
	return func() (io.ReadCloser, error) {
		if a.Image == "" {
			// 整个文件就是镜像 (裸镜像或单流压缩)
			return a.openWholeImage()
		}
		return a.openEntryStream(a.Image)
	}
}

// openWholeImage 裸镜像 / 单流压缩镜像
func (a *Archive) openWholeImage() (io.ReadCloser, error) {
	switch a.Format {
	case "img", "":
		return os.Open(a.Path)
	default:
		r, closer, err := a.openStream()
		if err != nil {
			return nil, err
		}
		if rc, ok := r.(io.ReadCloser); ok {
			return rc, nil
		}
		return &nopReadCloser{r: r, c: closer}, nil
	}
}

type nopReadCloser struct {
	r io.Reader
	c io.Closer
}

func (n *nopReadCloser) Read(p []byte) (int, error) { return n.r.Read(p) }
func (n *nopReadCloser) Close() error {
	if n.c != nil {
		return n.c.Close()
	}
	return nil
}
