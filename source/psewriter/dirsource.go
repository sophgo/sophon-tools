// 目录数据源 (MYS-1062 十八轮④) — 直接把一个**目录**当作写卡来源
//
// 现场常见做法是把要写进卡里的东西先摊在一个目录里 (boot.scr / fip.bin /
// sdbootrecovery.itb / recovery-ui/ …), 以前必须先 tar 成压缩包才让工具吃。
// 这里把目录也接成一种来源: 枚举出来的结果与"文件包压缩包"完全同构
// (同样的 Archive / PackagePlan / 刷机包根目录定位 / 写后逐文件校验),
// 下游一行都不用改。
//
// 与压缩包的两点差异:
//   - 每个文件都是按需从磁盘读 (不存在"整条压缩流只能顺序走一遍"的限制),
//     所以枚举可以顺便给出**准确的字节进度**, 也不存在解压耗时
//   - 目录里可能混着链接/设备文件等 FAT32 放不下的东西 → 跳过并计数,
//     如实报给用户 (不静默吞掉)
package main

import (
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const dirFormat = "dir"

// 目录条目上限 (与归档的 maxEntries 同量级, 防呆)
const maxDirEntries = 100000

// IsDirSource 路径是否应走"目录源"
func IsDirSource(p string) bool {
	if strings.TrimSpace(p) == "" {
		return false
	}
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}

// probeAny 统一入口: 目录走目录源, 其余走归档探测
func probeAny(p string, force *SourceMode, ctl *ProbeCtl) (*Archive, error) {
	if IsDirSource(p) {
		return ProbeDir(p, force, ctl)
	}
	if strings.TrimSpace(p) == "" {
		return nil, fmt.Errorf("未指定来源")
	}
	return ProbeArchive(p, force, ctl)
}

// ProbeDir 枚举目录内容, 得到与压缩包同构的 Archive (文件包模式)。
//
// 符号链接按**目标**处理 (现场目录里常见 .bmodel -> 实体文件的软链);
// 指向目录的链接不递归 (避免环), 其它非普通文件一律跳过并计数。
func ProbeDir(dir string, force *SourceMode, ctl *ProbeCtl) (*Archive, error) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		abs = dir
	}
	a := &Archive{Path: abs, Format: dirFormat, Mode: ModeFilePackage}
	if probeCanceled(ctl) {
		return nil, ErrProbeCanceled
	}

	var total int64
	last := time.Now()
	scan := func() {
		probeReport(ctl, "scan", int64(len(a.Files)+len(a.Dirs)), total)
	}

	walkErr := filepath.WalkDir(abs, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if probeCanceled(ctl) {
			return ErrProbeCanceled
		}
		if p == abs {
			return nil
		}
		rel, rerr := filepath.Rel(abs, p)
		if rerr != nil {
			return nil
		}
		name := filepath.ToSlash(rel)

		switch {
		case d.IsDir():
			a.Dirs = append(a.Dirs, ArchiveEntry{Name: name, IsDir: true})
		case d.Type()&fs.ModeSymlink != 0:
			st, serr := os.Stat(p) // 跟到目标
			switch {
			case serr != nil:
				a.Skipped++
			case st.IsDir():
				a.Skipped++ // 指向目录的链接不递归 (防环)
				return nil
			case st.Mode().IsRegular():
				a.Files = append(a.Files, ArchiveEntry{Name: name, Size: st.Size()})
				total += st.Size()
			default:
				a.Skipped++
			}
		case d.Type().IsRegular():
			info, ierr := d.Info()
			var sz int64
			if ierr == nil {
				sz = info.Size()
			}
			a.Files = append(a.Files, ArchiveEntry{Name: name, Size: sz})
			total += sz
		default:
			a.Skipped++ // 设备/管道/socket 等 FAT32 放不下的
		}

		if len(a.Files)+len(a.Dirs) > maxDirEntries {
			return fmt.Errorf("目录内条目过多 (> %d)", maxDirEntries)
		}
		if now := time.Now(); now.Sub(last) >= 100*time.Millisecond {
			last = now
			scan()
		}
		return nil
	})
	if walkErr != nil {
		if walkErr == ErrProbeCanceled {
			return nil, ErrProbeCanceled
		}
		return nil, fmt.Errorf("读取目录失败: %w", walkErr)
	}

	// 稳定顺序 (WalkDir 本身有序, 这里保一道: 大小写混排时 Windows/Linux 结果一致)
	sort.Slice(a.Files, func(i, j int) bool { return a.Files[i].Name < a.Files[j].Name })
	sort.Slice(a.Dirs, func(i, j int) bool { return a.Dirs[i].Name < a.Dirs[j].Name })

	a.SrcFileSize = total
	a.decideMode()
	if force != nil {
		a.Mode = *force
		a.applyForcedMode()
	}
	if a.Mode == ModeFilePackage {
		if err := applyBootRoot(a); err != nil {
			return nil, err
		}
	}
	scan()
	return a, nil
}

// openDirEntry 打开目录源里的一个文件 (供 openEntryStream 使用)
func (a *Archive) openDirEntry(name string) (io.ReadCloser, error) {
	full := filepath.Join(a.Path, filepath.FromSlash(name))
	// 防越界: 目标必须仍在源目录内
	if rel, err := filepath.Rel(a.Path, full); err != nil || strings.HasPrefix(rel, "..") {
		return nil, fmt.Errorf("目录内路径越界: %s", name)
	}
	return os.Open(full)
}

// dirIter 目录源的顺序迭代器。
//
// 只产出**文件** —— 目录由 PackagePlan.Dirs 在建卡阶段统一创建 (与压缩包模式一致,
// 建卡/校验两处消费方都是"跳过 IsDir, 用条目内容当文件源")。
type dirIter struct {
	a   *Archive
	idx int
}

func (d *dirIter) Next() (*ArchiveEntry, error) {
	if d.idx >= len(d.a.Files) {
		return nil, io.EOF
	}
	e := d.a.Files[d.idx]
	d.idx++
	return &e, nil
}

func (d *dirIter) Open() (io.ReadCloser, error) {
	if d.idx == 0 || d.idx > len(d.a.Files) {
		return nil, fmt.Errorf("目录源: Open 必须在 Next 之后调用")
	}
	// 按磁盘原始路径打开 (剥过刷机包前缀的条目 Name 已是卡上目标名, 见 ArchiveEntry.SrcName)
	return d.a.openDirEntry(d.a.Files[d.idx-1].srcName())
}

func (d *dirIter) Close() error { return nil }
