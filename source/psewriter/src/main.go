// SE写卡工具 — CLI 入口 (Windows 下无参数则启动图形界面)
//
// 用法:
//
//	sewriter.exe                          图形界面 (Windows; 需以管理员身份运行)
//	sewriter.exe list [--all]             列出磁盘 (--all 含未确认的固定盘)
//	sewriter.exe write --disk 3 --image X.img[.gz] [--yes] [--no-verify] [--force]
//	sewriter.exe verify --disk 3 --image X.img[.gz] [--bytes N]
//	sewriter.exe hash --image X.img[.gz]
//
// 安全: 系统盘恒不可选; 固定盘需 --force; CLI 写盘需 --yes (或交互确认)。
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	code := run()
	// 内置数据源若是文件包, 分析时会落一份临时副本 —— 退出前清掉
	CleanupEmbeddedTemp()
	os.Exit(code)
}

func run() int {
	args := os.Args[1:]
	if len(args) == 0 {
		return runGUI()
	}
	switch args[0] {
	case "list", "ls":
		return cmdList(args[1:])
	case "write", "flash":
		return cmdWrite(args[1:])
	case "format", "fmt":
		return cmdFormat(args[1:])
	case "verify":
		return cmdVerify(args[1:])
	case "hash":
		return cmdHash(args[1:])
	case "info", "embedded":
		return cmdInfo(args[1:])
	case "repack", "retarget":
		return cmdRepack(args[1:])
	case "-h", "--help", "help":
		usage()
		return 0
	default:
		fmt.Fprintf(os.Stderr, "未知命令: %s\n\n", args[0])
		usage()
		return 2
	}
}

func usage() {
	fmt.Print(`SE写卡工具

  sewriter.exe                              图形界面 (需管理员权限)
  sewriter.exe list [--all]                 列出磁盘
  sewriter.exe info                         查看内置数据源版本信息 (文件名/大小/sha256/打包时间)
  sewriter.exe repack --image <img> [--out <新程序>] [--skeleton <模板程序>] [--force]
                                        换镜像生成第二个自带镜像的程序
  sewriter.exe write --disk N [--image <镜像> | --dir <目录>] [--as raw|files]
                [--fs-size max|auto|<MB>] [--label <卷标>] [--yes] [--no-verify] [--force]
  sewriter.exe format --disk N [--label <卷标>] [--yes] [--no-verify] [--force]
                                        只格式化: 在卡上建 MBR+FAT32, 不写入任何文件
  sewriter.exe verify --disk N [--image <镜像> | --dir <目录>] [--bytes N]
  sewriter.exe hash [--image <镜像>]

数据源 (按内容识别, 扩展名只作提示):
  * 不指定 --image/--dir 时使用**程序内置数据源** (随 exe 打包)
  * 整盘镜像:  .img / .raw 等裸镜像, 或经 gz/xz/bz2/zst/zip/7z/rar/tar/tar.gz/tar.xz 压缩
  * 文件包:    压缩包内是一批文件 (boot.scr、fip.bin、*.itb、recovery-ui/ …)
               → 目标卡格式化为 MBR + FAT32, 再把文件写进去 (做 SE5/SE7/SE9 刷机卡)
  * 目录:      --dir <目录> 直接拿目录当来源 (等价于把该目录打成文件包, 但不用先打包);
               目录里的软链按目标文件处理, FAT32 放不下的条目 (设备文件/断链) 跳过并计数
  * --as raw|files 可强制指定; 默认自动判定 (只有一个镜像文件 → 整盘; 否则 → 文件包)
  * --fs-size: 默认整卡格式化; auto = 只按内容大小建分区 (更快, 卡上剩余空间不参与)

format 模式 (只格式化 TF 卡):
  * 整张卡格式化为 MBR + 1×FAT32 (与写卡时先建的那种格式完全一样)
  * 不写入任何文件 —— 用于卡被格成 exFAT/NTFS/GPT、或 FAT32 被写坏时快速恢复
  * 卡比 FAT32 上限 (2 TiB) 还大时按上限建分区; 小于 64 MiB 时报错
  * 写后同样回读核对分区表 / BPB / FAT 两份副本 (没有文件, 故无文件级校验)

安全约定:
  * 系统盘永不出现在可选列表 (list --all 也只标注, 不允许写)
  * 固定盘 (SATA/NVMe/RAID) 判定为"需人工确认", 默认隐藏, 需 --all 查看 + --force 才可写
  * 写盘前打印目标磁盘的型号/容量/分区表, 需 --yes 或交互确认
  * 默认写后回读校验 (--no-verify 关闭)
  * repack 不会改动本程序自身, 只输出到新文件
`)
}

// parseModeFlag 解析 --as 参数
func parseModeFlag(s string) *SourceMode {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "raw", "disk", "image", "整盘":
		m := ModeRawDisk
		return &m
	case "files", "file", "package", "fat32", "文件包":
		m := ModeFilePackage
		return &m
	}
	return nil
}

// parseFSSize --fs-size: "max"/"" = 整卡; "auto" = 按内容; "<MB>" = 指定 MB
func parseFSSize(s string, targetSize int64) (fullDisk bool, overrideMB int64) {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "", "max", "full":
		return true, 0
	case "auto":
		return false, 0
	}
	var mb int64
	if _, err := fmt.Sscanf(strings.TrimSpace(s), "%d", &mb); err == nil && mb > 0 {
		return false, mb
	}
	return true, 0
}

func cmdList(args []string) int {
	fs := flag.NewFlagSet("list", flag.ExitOnError)
	all := fs.Bool("all", false, "包含需人工确认的固定盘")
	_ = fs.Parse(args)
	disks, err := enumerateDisks()
	if err != nil {
		fmt.Fprintln(os.Stderr, "枚举磁盘失败:", err)
		return 1
	}
	shown := SelectableDisks(disks, *all)
	if len(shown) == 0 {
		fmt.Println("没有可安全烧录的磁盘 (请插入 TF 卡读卡器; --all 可查看全部磁盘)")
		return 1
	}
	fmt.Printf("共 %d 个磁盘 (显示 %d 个):\n\n", len(disks), len(shown))
	for _, d := range shown {
		fmt.Println("  " + d.DescribeLine())
	}
	fmt.Println("\n提示: 若目标卡未出现, 用 --all 查看是否被判为固定盘 (需人工确认)。")
	return 0
}

func cmdInfo(args []string) int {
	fmt.Println("== 内置数据源 (随程序打包, 默认写入源) ==")
	for _, l := range EmbeddedLines() {
		fmt.Println("  " + l)
	}
	if HasEmbeddedImage() {
		fmt.Println("\n换掉默认镜像 (程序自己就能做, 无需构建机):")
		fmt.Println("  sewriter.exe repack --image <新的 se7-recovery-*.img[.gz]>")
	} else {
		fmt.Println("\n本程序未内置数据源。可生成一个自带数据源的新程序:")
		fmt.Println("  sewriter.exe repack --image <se7-recovery-*.img[.gz]>")
	}
	fmt.Println("\n== 本机磁盘 ==")
	disks, err := enumerateDisks()
	if err != nil {
		fmt.Fprintln(os.Stderr, "  枚举磁盘失败:", err)
		return 1
	}
	shown := SelectableDisks(disks, false)
	if len(shown) == 0 {
		fmt.Println("  没有可安全烧录的磁盘 (插入 TF 卡读卡器; --all 见全部)")
		return 0
	}
	for _, d := range shown {
		fmt.Println("  " + d.DescribeLine())
	}
	return 0
}

// cmdRepack 换镜像生成第二个自带镜像的程序 (剥离自身骨架 → 追加新镜像)
func cmdRepack(args []string) int {
	fs := flag.NewFlagSet("repack", flag.ExitOnError)
	img := fs.String("image", "", "要内置的镜像文件 (.img / .img.gz)")
	out := fs.String("out", "", "新程序输出路径 (省略 = 按镜像版本自动命名)")
	skel := fs.String("skeleton", "", "骨架模板程序 (省略 = 本程序自身)")
	force := fs.Bool("force", false, "覆盖已存在的输出文件")
	_ = fs.Parse(args)
	if *img == "" {
		fmt.Fprintln(os.Stderr, "缺少 --image (要内置的镜像文件)")
		return 2
	}
	self := SelfExePath()
	if *skel == "" {
		*skel = self
	}
	fmt.Printf("骨架: %s\n", *skel)
	if *skel == self {
		if p, err := OpenSelfPayload(); err == nil {
			fmt.Printf("      (本程序已内置 %s, 生成时将先剥离该镜像再换入新镜像)\n", p.Meta.File)
		} else {
			fmt.Println("      (本程序未内置数据源, 直接作为骨架)")
		}
	}
	fmt.Printf("镜像: %s\n\n", *img)

	res, err := Repack(*img, *out, *skel, *force, func(phase string, done, total int64, rate float64) {})
	if err != nil {
		fmt.Fprintln(os.Stderr, "× 生成失败:", err)
		return 1
	}
	fmt.Printf("✓ 已生成新程序: %s\n", res.OutPath)
	fmt.Printf("  程序大小  : %s (%d 字节)\n", HumanBytes(res.OutBytes), res.OutBytes)
	fmt.Printf("  程序 sha256: %s\n", res.OutSHA256)
	fmt.Printf("  骨架      : %s  sha256 %s\n", HumanBytes(res.SkeletonBytes), shortHash(res.SkeletonSHA))
	fmt.Printf("  内置数据源: %s\n", res.Image.File)
	fmt.Printf("    内容大小: %s (%d 字节)\n", HumanBytes(res.Image.Bytes), res.Image.Bytes)
	fmt.Printf("    内容 sha256: %s\n", res.Image.SHA256)
	fmt.Printf("    内置体积: %s (压缩: %v)\n", HumanBytes(res.Image.StoredBytes), res.Image.Compressed)
	if res.Image.BuildVer != "" {
		fmt.Printf("    镜像版本: %s\n", res.Image.BuildVer)
	}
	fmt.Printf("  回读自检  : %v (骨架一致 + 内置数据 sha256 一致)\n", res.Verified)
	fmt.Printf("\n新程序已自带该镜像, 双击/命令行均可直接用 (无需再带镜像文件)。\n")
	return 0
}

func cmdHash(args []string) int {
	fs := flag.NewFlagSet("hash", flag.ExitOnError)
	img := fs.String("image", "", "镜像文件/压缩包/目录; 省略 = 内置数据源")
	_ = fs.Parse(args)
	src, err := resolveSource(*img)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	h, n, err := ExportImageSHA256Src(src)
	if err != nil {
		fmt.Fprintln(os.Stderr, "计算失败:", err)
		return 1
	}
	fmt.Printf("镜像  : %s%s\n大小  : %s (%d 字节)\nsha256: %s\n",
		src.Display(), map[bool]string{true: "  [内置]", false: ""}[src.Embedded()], HumanBytes(n), n, h)
	return 0
}

func cmdWrite(args []string) int {
	fs := flag.NewFlagSet("write", flag.ExitOnError)
	disk := fs.String("disk", "", "目标磁盘号 (如 3) 或设备路径")
	img := fs.String("image", "", "镜像文件/压缩包/目录; 省略 = 内置数据源")
	dir := fs.String("dir", "", "目录数据源 (与 --image 二选一)")
	yes := fs.Bool("yes", false, "跳过交互确认 (自动化; 仍需通过安全判定)")
	noVerify := fs.Bool("no-verify", false, "关闭写后回读校验")
	force := fs.Bool("force", false, "允许写被判为'需人工确认'的固定盘 (系统盘仍禁止)")
	as := fs.String("as", "", "强制写入方式: raw=整盘镜像 / files=文件包(格式化 MBR+FAT32)")
	fsSize := fs.String("fs-size", "", "文件包模式分区大小: 默认整卡 / auto 按内容 / <MB>")
	label := fs.String("label", "", "文件包模式卷标 (默认由文件名推导)")
	_ = fs.Parse(args)
	if *disk == "" {
		fmt.Fprintln(os.Stderr, "缺少 --disk")
		return 2
	}
	if *dir != "" {
		if *img != "" {
			fmt.Fprintln(os.Stderr, "--image 与 --dir 只能给一个")
			return 2
		}
		*img = *dir
	}
	target, err := findDisk(*disk)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if code := guardTarget(target, *force, *yes); code != 0 {
		return code
	}
	full, overrideMB := parseFSSize(*fsSize, target.Size)
	if overrideMB > 0 {
		full = false
	}
	if overrideMB > 0 {
		fmt.Printf("分区大小: 指定 %d MiB\n", overrideMB)
	}
	prep, err := PrepareSource(*img, parseModeFlag(*as), target.Size, full, overrideMB, *label, cliProbeCtl())
	clearLine()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	name, embedded := "文件包 (MBR+FAT32)", ""
	if prep.Src != nil {
		name = prep.Src.Display()
		if prep.Src.Embedded() {
			embedded = "  [内置]"
		}
	}
	if n := prep.TotalSize(); n > 0 && target.Size < n {
		fmt.Fprintf(os.Stderr, "× 目标容量 %s 小于镜像 %s\n", HumanBytes(target.Size), HumanBytes(n))
		return 1
	}
	fmt.Printf("目标: %s\n%s\n镜像: %s%s (%s)\n", target.Path, target.DetailText(),
		name, embedded, HumanBytes(prep.TotalSize()))
	for _, kv := range SourceInfoRows(prep.Archive, prep.Plan) {
		fmt.Printf("  %s: %s\n", padRight(kv[0], 12), kv[1])
	}
	fmt.Println()

	return flashToDisk(target, prep, !*noVerify, cliProgress)
}

// cmdFormat 只格式化: 在卡上建 MBR+FAT32, 不写入任何文件
func cmdFormat(args []string) int {
	fs := flag.NewFlagSet("format", flag.ExitOnError)
	disk := fs.String("disk", "", "目标磁盘号 (如 3) 或设备路径")
	label := fs.String("label", "", "卷标 (默认 SE)")
	yes := fs.Bool("yes", false, "跳过交互确认 (自动化; 仍需通过安全判定)")
	noVerify := fs.Bool("no-verify", false, "关闭写后回读校验")
	force := fs.Bool("force", false, "允许写被判为'需人工确认'的固定盘 (系统盘仍禁止)")
	_ = fs.Parse(args)
	if *disk == "" {
		fmt.Fprintln(os.Stderr, "缺少 --disk")
		return 2
	}
	target, err := findDisk(*disk)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if code := guardTarget(target, *force, *yes); code != 0 {
		return code
	}
	prep, err := PrepareFormat(target.Size, *label)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	fmt.Printf("目标: %s\n%s\n操作: 只格式化 — 建 MBR + FAT32, 不写入任何文件\n",
		target.Path, target.DetailText())
	fmt.Printf("  %s: %s\n", padRight("卡容量", 12), HumanBytes(target.Size))
	fmt.Printf("  %s: MBR / 1×FAT32 (卷标 %s)\n", padRight("分区", 12), prep.Plan.Label)
	fmt.Println()

	return flashToDisk(target, prep, !*noVerify, cliProgress)
}

// cliProgress 命令行下的写入/校验进度 (文件级校验的单位是"文件个数", 不是字节)
func cliProgress(phase string, done, total int64, rate float64) {
	switch {
	case phase == "check":
		fmt.Printf("\r  [校验文件] %d / %d 个   ", done, total)
	case total > 0:
		fmt.Printf("\r  [%s] %5.1f%%  %s / %s  %s   ", phaseName(phase), float64(done)*100/float64(total),
			HumanBytes(done), HumanBytes(total), HumanRate(rate))
	default:
		fmt.Printf("\r  [%s] 已处理 %s  %s   ", phaseName(phase), HumanBytes(done), HumanRate(rate))
	}
}

func cmdVerify(args []string) int {
	fs := flag.NewFlagSet("verify", flag.ExitOnError)
	disk := fs.String("disk", "", "目标磁盘号或设备路径")
	img := fs.String("image", "", "镜像文件/压缩包/目录; 省略 = 内置数据源")
	dir := fs.String("dir", "", "目录数据源 (与 --image 二选一)")
	nbytes := fs.Int64("bytes", 0, "待校验字节数 (解压大小未知时使用)")
	fsSize := fs.String("fs-size", "full", "文件包模式的分区大小: full|auto|<MiB> (需与写入时一致)")
	_ = fs.Parse(args)
	if *disk == "" {
		fmt.Fprintln(os.Stderr, "缺少 --disk")
		return 2
	}
	if *dir != "" {
		if *img != "" {
			fmt.Fprintln(os.Stderr, "--image 与 --dir 只能给一个")
			return 2
		}
		*img = *dir
	}
	target, err := findDisk(*disk)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	full, overrideMB := parseFSSize(*fsSize, target.Size)
	if overrideMB > 0 {
		full = false
	}
	prep, err := PrepareSource(*img, nil, target.Size, full, overrideMB, "", cliProbeCtl())
	clearLine()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	dev, err := openDiskDeviceRO(target.Path)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	defer dev.Close()

	// 文件包: 卡上是 FAT32 文件系统, 校验"结构 + 每个文件的 sha256"
	if prep.IsCard() {
		fmt.Printf("只读校验: %s 上的 FAT32 vs %s\n", target.Path, filepath.Base(prep.Archive.Path))
		lay, lerr := VerifyCardLayout(dev, prep.Plan, nil)
		if lerr != nil {
			fmt.Fprintln(os.Stderr, "校验失败:", lerr)
			return 1
		}
		if !lay.OK() {
			fmt.Fprintln(os.Stderr, "× 文件系统结构不符:", lay.Problems)
			return 1
		}
		fmt.Println("✓", lay.Summary())
		fv, ferr := VerifyCardFiles(dev, prep.Archive, 1, nil)
		if ferr != nil {
			fmt.Fprintln(os.Stderr, "文件级校验失败:", ferr)
			return 1
		}
		fmt.Println("✓", fv.Summary())
		if !fv.OK() {
			fmt.Fprintln(os.Stderr, "×", fv.FirstError())
			return 1
		}
		return 0
	}

	src := prep.Src
	n := src.Size()
	if n <= 0 {
		n = *nbytes
	}
	if n <= 0 {
		fmt.Fprintln(os.Stderr, "解压大小未知, 请用 --bytes 指定待校验字节数")
		return 2
	}
	fmt.Printf("只读校验: %s 前 %s vs %s%s\n", target.Path, HumanBytes(n),
		src.Display(), map[bool]string{true: "  [内置]", false: ""}[src.Embedded()])
	res := &FlashResult{ImageBytes: n, MismatchOff: -1}
	if err := VerifyOnly(dev, src, func(phase string, done, total int64, rate float64) {
		fmt.Printf("\r  [校验] %s / %s  %s   ", HumanBytes(done), HumanBytes(total), HumanRate(rate))
	}, res); err != nil {
		fmt.Fprintln(os.Stderr, "\n校验失败:", err)
		return 1
	}
	fmt.Println()
	return reportResult(res)
}

// cliProbeCtl 命令行下的探测进度 (分析大压缩包时能看到进展, 不再是黑屏干等)
func cliProbeCtl() *ProbeCtl {
	return &ProbeCtl{
		Progress: func(phase string, done, total int64) {
			if total > 0 {
				fmt.Printf("\r  [分析] %5.1f%%  %s / %s   ",
					float64(done)*100/float64(total), HumanBytes(done), HumanBytes(total))
			} else {
				fmt.Printf("\r  [分析] 已解析 %d 个条目   ", done)
			}
		},
	}
}

// clearLine 清掉进度行
func clearLine() { fmt.Print("\r\x1b[K") }

// resolveSource 解析数据源: 显式路径优先, 否则用程序内置数据源
func resolveSource(path string) (*ImageSource, error) {
	if strings.TrimSpace(path) != "" {
		return OpenImage(path)
	}
	return OpenEmbedded()
}

// findDisk 按磁盘号/路径定位磁盘并做安全分级
func findDisk(spec string) (*DiskInfo, error) {
	disks, err := enumerateDisks()
	if err != nil {
		return nil, err
	}
	want := ParseDiskArg(spec)
	for _, d := range disks {
		if d.Path == want || fmt.Sprint(d.Index) == strings.TrimSpace(spec) {
			return d, nil
		}
	}
	// Linux: 允许直接用设备路径 (/dev/loop0 等不在枚举结果时)
	for _, d := range disks {
		if strings.EqualFold(d.Path, spec) {
			return d, nil
		}
	}
	return nil, fmt.Errorf("未找到磁盘 %q (用 list 查看可用磁盘)", spec)
}

// guardTarget 安全闸门: 系统盘/固定盘/交互确认
func guardTarget(d *DiskInfo, force, yes bool) int {
	fmt.Println(d.DetailText())
	switch d.Safety {
	case SafetyDangerous:
		fmt.Fprintf(os.Stderr, "× 拒绝: 磁盘 %d 是系统盘 (%s) — 禁止烧录\n", d.Index, d.Reason)
		return 1
	case SafetyUnknown:
		if !force {
			fmt.Fprintf(os.Stderr, "× 拒绝: 磁盘 %d 判定为「%s」(%s)。确认无误请加 --force\n", d.Index, d.Safety, d.Reason)
			return 1
		}
		fmt.Printf("⚠ 已用 --force 放开「%s」判定: %s\n", d.Safety, d.Reason)
	}
	if yes {
		return 0
	}
	fmt.Printf("\n⚠ 以上磁盘 (%s, %s) 的**全部分区**将被覆盖, 数据不可恢复。\n请输入大写 YES 确认: ", d.Path, HumanBytes(d.Size))
	var ans string
	if _, err := fmt.Scanln(&ans); err != nil || strings.TrimSpace(ans) != "YES" {
		fmt.Fprintln(os.Stderr, "未确认, 已取消")
		return 1
	}
	return 0
}

// flashToDisk 统一写入入口: 锁卷 → 写(快速格式化/整盘) → 落盘 → 换新句柄回读 → 文件级校验
func flashToDisk(d *DiskInfo, prep *PreparedSource, verify bool, cb Progress) int {
	out, err := RunFlash(d, prep, verify, cb, func(format string, a ...interface{}) {
		fmt.Printf("  "+format+"\n", a...)
	})
	fmt.Println()
	if err != nil {
		fmt.Fprintln(os.Stderr, "× 写入失败:", err)
		return 1
	}
	return reportOutcome(out)
}

// reportOutcome 汇总报告 (CLI)
func reportOutcome(out *FlashOutcome) int {
	if out.IsCard {
		res := out.Card
		if out.FormatOnly {
			fmt.Printf("格式化完成: 实写 %s / 耗时 %s (%.1f MiB/s)\n", HumanBytes(res.WrittenBytes),
				res.Elapsed.Round(time.Millisecond), mibPerSec(res.WrittenBytes, res.Elapsed))
			fmt.Printf("快速格式化: 卡容量 %s, 实写 %s, 未触碰 %s (剩余空间不擦除, 卡上没有写入任何文件)\n",
				HumanBytes(res.TotalSize), HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes))
		} else {
			fmt.Printf("写入完成: %s / 耗时 %s (%.1f MiB/s)\n", HumanBytes(res.WrittenBytes),
				res.Elapsed.Round(time.Millisecond), mibPerSec(res.WrittenBytes, res.Elapsed))
			fmt.Printf("快速格式化: 卡容量 %s, 实写 %s, 未触碰 %s (剩余空间不擦除)\n",
				HumanBytes(res.TotalSize), HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes))
		}
		if out.Layout == nil {
			fmt.Println("（未执行回读校验）")
			return 0
		}
		if !out.Layout.OK() {
			fmt.Fprintf(os.Stderr, "× 文件系统结构核对失败: %v\n", out.Layout.Problems)
			return 1
		}
		fmt.Printf("✓ 回读校验: %s\n", out.Layout.Summary())
		fv := out.FileVerify
		if fv == nil {
			return 0
		}
		fmt.Printf("文件级校验 (%s):\n", fv.Summary())
		for _, f := range fv.Files {
			mark := "✓"
			note := ""
			if !f.OK {
				mark = "×"
				note = "  " + f.Err
			}
			fmt.Printf("  %s %-40s %10s  sha256 %s%s\n", mark, f.Name, HumanBytes(f.Size), shortHash(f.GotSHA), note)
		}
		if !fv.OK() {
			fmt.Fprintf(os.Stderr, "× 文件级校验失败: %s\n", fv.FirstError())
			return 1
		}
		fmt.Printf("✓ 文件级校验通过: 卡上 %d 个文件与源压缩包完全一致\n", fv.OKCount)
		return 0
	}

	res := out.Image
	fmt.Printf("写入完成: 实写 %s / 耗时 %s (%.1f MiB/s)\n", HumanBytes(res.WrittenBytes),
		res.WriteElapsed.Round(time.Millisecond), mibPerSec(res.WrittenBytes, res.WriteElapsed))
	if res.SkippedBytes > 0 {
		fmt.Printf("稀疏写入: 镜像共 %s, 其中 %s 全零且卡上本就是零 → 未写\n",
			HumanBytes(res.ImageBytes), HumanBytes(res.SkippedBytes))
	}
	return reportResult(res)
}

func reportResult(res *FlashResult) int {
	if res.ReadSHA256 == "" && !res.VerifyOK {
		fmt.Println("（未执行回读校验）")
		return 0
	}
	fmt.Printf("镜像 sha256: %s\n回读 sha256: %s\n", res.SHA256, res.ReadSHA256)
	if res.VerifyOK {
		fmt.Printf("✓ 校验通过: %s 回读一致\n", HumanBytes(res.VerifyBytes))
		return 0
	}
	fmt.Fprintf(os.Stderr, "× 校验失败: 首个不一致偏移 %d, 不一致字节 %d\n", res.MismatchOff, res.MismatchCnt)
	return 1
}

func mibPerSec(n int64, d time.Duration) float64 {
	if d <= 0 {
		return 0
	}
	return float64(n) / (1 << 20) / d.Seconds()
}
