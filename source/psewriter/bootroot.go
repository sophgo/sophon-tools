// 刷机包根目录自动定位 (MYS-1062 十五轮)
//
// 需求原文:
//
//	「文件压缩包格式下, 需要自动找到子路径中的刷机包或启动镜像 (通过 fip.bin 等特征文件),
//	  确保写入到 tf 卡的根目下的就是刷机包或启动镜像」
//
// 现场拿到的压缩包常常是"多套了一层目录"的, 例如:
//
//	sdbootrecoveryfiles/boot.scr
//	sdbootrecoveryfiles/fip.bin
//	sdbootrecoveryfiles/sdbootrecovery.itb
//	sdbootrecoveryfiles/recovery-ui/…
//
// 直接按原样写进 FAT32, 卡根目录下就只有 sdbootrecoveryfiles/ 这一层, 设备的
// BootROM/BL2/u-boot 在卡根目录找不到 boot.scr / fip.bin —— 卡做出来了却起不来。
//
// 这里按**特征文件**判断哪一层才是刷机包根目录, 把那层前缀剥掉, 让 fip.bin、boot.scr
// 这些真正落到卡根目录。判定依据必须是内容特征 (文件名), 不能靠"只有一层目录就剥"
// 这种猜测 —— 剥错一层的结果同样是起不来, 而且更难排查。
package main

import (
	"fmt"
	"path"
	"sort"
	"strings"
)

// markerRule 一个特征文件规则
type markerRule struct {
	name   string // 小写 basename; 空 = 用后缀匹配
	suffix string
	weight int
}

// bootMarkers 刷机包/启动镜像的特征文件。
//
// 权重越大越"专有" —— fip.bin 是 BL2/FIP 本体, 见到它基本可以断定这一层就是刷机包根目录;
// boot.scr 与 *.itb 是同一套启动链上的东西, 权重次之。
// 判定只看 basename (不区分大小写), 不看扩展名之外的任何猜测。
var bootMarkers = []markerRule{
	{name: "fip.bin", weight: 4},
	{name: "boot.scr", weight: 3},
	{name: "sdbootrecovery.itb", weight: 3},
	{suffix: ".itb", weight: 2},
}

// bootMarkerDir 目录名也是特征之一: recovery-ui/ 的**父目录**就是刷机包根目录
const bootMarkerDir = "recovery-ui"

// markScore 给一个条目的所在目录打分; 返回 0 表示不是特征
func markScore(base string) int {
	low := strings.ToLower(base)
	for _, r := range bootMarkers {
		if r.name != "" && low == r.name {
			return r.weight
		}
		if r.suffix != "" && strings.HasSuffix(low, r.suffix) {
			return r.weight
		}
	}
	return 0
}

// BootRootInfo 刷机包根目录的判定结果
type BootRootInfo struct {
	Prefix     string   // 选中的前缀 ("" = 文件本来就在根目录 / 没识别出来)
	Stripped   bool     // 是否真的剥掉了前缀
	Score      int      // 选中前缀的得分
	Candidates []string // 并列最高分的其它候选 (非空 = 有歧义, 未做任何调整)
	Outsiders  int      // 剥掉前缀后仍留在原路径的条目数 (不在刷机包内)
	Note       string   // 给界面看的一句话说明
}

// detectBootRoot 按特征文件找出刷机包根目录。
func detectBootRoot(a *Archive) BootRootInfo {
	scores := map[string]int{}
	for _, f := range a.Files {
		if w := markScore(path.Base(f.Name)); w > 0 {
			scores[path.Dir(f.Name)] += w // path.Dir("fip.bin") == "."
		}
	}
	for _, d := range a.Dirs {
		if strings.EqualFold(path.Base(d.Name), bootMarkerDir) {
			scores[path.Dir(d.Name)]++
		}
	}
	// path.Dir 把根目录下的条目给成 ".", 统一成 ""
	for k := range scores {
		if k == "." {
			scores[""] = scores["."]
			delete(scores, ".")
		}
	}
	if len(scores) == 0 {
		return BootRootInfo{Note: "未发现 fip.bin / boot.scr / *.itb 等特征文件, 按压缩包原样写入"}
	}

	best, bestScore := "", -1
	var ties []string
	for dir, sc := range scores {
		switch {
		case sc > bestScore:
			best, bestScore, ties = dir, sc, nil
		case sc == bestScore:
			ties = append(ties, dir)
		}
	}

	if len(ties) > 0 {
		all := append([]string{best}, ties...)
		sort.Strings(all)
		return BootRootInfo{
			Candidates: all,
			Score:      bestScore,
			Note: fmt.Sprintf("发现 %d 个都像刷机包的目录 (%s), 无法确定用哪个 —— 未做调整, 写入后设备可能找不到启动文件",
				len(all), strings.Join(all, ", ")),
		}
	}
	if best == "" {
		return BootRootInfo{Score: bestScore, Note: "特征文件已在根目录, 直接写入卡根目录"}
	}
	return BootRootInfo{Prefix: best, Score: bestScore}
}

// applyBootRoot 把刷机包根目录之外的那层前缀剥掉, 让包内文件落到卡根目录。
//
// 包外的条目 (不在选中前缀下的) 保持原路径不动 —— 宁可多留几个文件, 也不静默丢用户的数据;
// 但它们会与剥出来的名字一起参与重名检查, 撞名就报错而不是互相覆盖。
func applyBootRoot(a *Archive) error {
	info := detectBootRoot(a)
	a.BootRoot = info
	if info.Prefix == "" {
		return nil
	}

	prefix := info.Prefix
	// 写卡时是按**归档里的原始条目名**重新遍历的 (openFiles), 所以要把"原名 → 卡上目标名"
	// 记下来, 否则 buildCardFS/VerifyCardFiles 会拿着带前缀的原名去找文件。
	a.Renames = map[string]string{}
	strip := func(name string) (string, bool) {
		switch {
		case name == prefix:
			return "", false // 前缀目录自身
		case strings.HasPrefix(name, prefix+"/"):
			return strings.TrimPrefix(name, prefix+"/"), true
		default:
			return name, false
		}
	}

	var files, dirs []ArchiveEntry
	outsiders := 0
	for _, f := range a.Files {
		if n, ok := strip(f.Name); ok {
			a.Renames[f.Name] = n
			f.SrcName = f.Name // 目录源读内容仍按磁盘原始路径
			f.Name = n
			files = append(files, f)
		} else {
			outsiders++
			files = append(files, f)
		}
	}
	for _, d := range a.Dirs {
		n, ok := strip(d.Name)
		if !ok {
			if d.Name == prefix {
				continue // 这层目录本身不再需要
			}
			dirs = append(dirs, d) // 包外的目录保持原样
			continue
		}
		if n == "" {
			continue
		}
		d.Name = n
		dirs = append(dirs, d)
	}

	if err := checkStripCollision(files, dirs); err != nil {
		return err
	}
	a.Files, a.Dirs = files, dirs
	a.BootRoot.Stripped = true
	a.BootRoot.Outsiders = outsiders
	if outsiders > 0 {
		a.BootRoot.Note = fmt.Sprintf("已把 %s/ 这一层去掉 (卡根目录即刷机包内容); 另有 %d 个包外文件保持原路径",
			prefix, outsiders)
	} else {
		a.BootRoot.Note = fmt.Sprintf("已把 %s/ 这一层去掉 —— 卡根目录下就是刷机包内容", prefix)
	}
	return nil
}

// checkStripCollision 剥前缀后不允许出现重名 (否则一个会覆盖另一个, 静默出错)
func checkStripCollision(files, dirs []ArchiveEntry) error {
	seen := map[string]string{} // 小写路径 → 原路径
	check := func(name string) error {
		key := strings.ToLower(name)
		if prev, ok := seen[key]; ok {
			return fmt.Errorf("去掉目录前缀后出现重名: %q 与 %q 会写到卡的同一个位置, "+
				"请把压缩包整理成单一的刷机包目录后重试", prev, name)
		}
		seen[key] = name
		return nil
	}
	for _, f := range files {
		if err := check(f.Name); err != nil {
			return err
		}
	}
	for _, d := range dirs {
		if err := check(d.Name); err != nil {
			return err
		}
	}
	return nil
}

// BootRootLines 给界面/命令行用的说明行 (无内容时返回 nil)
func (a *Archive) BootRootLines() [][2]string {
	if a == nil {
		return nil
	}
	b := a.BootRoot
	switch {
	case len(b.Candidates) > 0:
		return [][2]string{{"⚠ 刷机包目录", b.Note}}
	case b.Prefix != "":
		return [][2]string{{"刷机包目录", b.Note}}
	case b.Note != "":
		return [][2]string{{"刷机包目录", b.Note}}
	}
	return nil
}

// TargetName 归档条目名 → 卡上目标路径 (剥过前缀时两者不同)
func (a *Archive) TargetName(entryName string) string {
	if a != nil && a.Renames != nil {
		if to, ok := a.Renames[entryName]; ok {
			return to
		}
	}
	return entryName
}
