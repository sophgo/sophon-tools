// 写入源准备 (MYS-1062 八轮 / 十三轮重构) — CLI 与 GUI 共用
//
// 把「用户选的文件」解析成一份写入计划:
//   - 裸镜像 / 单流压缩镜像 / 含镜像的归档 → 流式解出整盘镜像 (ImageSource)
//   - 文件包                                → 记下"要在卡上建 MBR+FAT32 并写这些文件"
//
// 两条路都不落中间文件: 归档的解析只枚举条目, 真正的解压+写入发生在写卡时。
package main

import (
	"fmt"
	"path/filepath"
	"strings"
)

// PreparedSource 已识别、可直接交给 RunFlash 的写入源。
//
// 这里**不生成任何中间镜像**: 文件包模式只解析出"往卡上建什么", 真正的 FAT32
// 是在写入阶段直接建在目标设备上的 (见 cardbuild.go) —— 否则一张 14 GiB 的卡
// 要先落一个 14 GiB 的临时镜像再整份读回来写, 白占临时盘和系统缓存。
type PreparedSource struct {
	Src     *ImageSource // 整盘镜像模式: 镜像源; 文件包模式为 nil
	Archive *Archive     // 非 nil = 来自归档/压缩包
	Plan    *PackagePlan // 非 nil = 文件包模式 (写入时在卡上建 MBR+FAT32)
}

// IsCard 文件包模式 (在卡上建 FAT32 + 快速格式化语义)
func (p *PreparedSource) IsCard() bool { return p != nil && p.Plan != nil }

// IsFormatOnly 只格式化模式: 只建 MBR+FAT32, 不写任何文件
// (没有文件级校验可做, 写后只回读核对文件系统结构)
func (p *PreparedSource) IsFormatOnly() bool { return p != nil && p.Plan != nil && p.Archive == nil }

// PrepareFormat 只格式化模式: 把整张卡做成 MBR+FAT32, 不写入任何文件。
//
// 现场用途: 卡被别的工具格式化成了 exFAT/NTFS/GPT (SE7 的 BL1 走 FatFs, 认不了),
// 或者 FAT32 被写坏 —— 不必重新下一份发版包, 直接格式化回可用状态。
func PrepareFormat(targetSize int64, label string) (*PreparedSource, error) {
	plan, err := PlanFormatOnly(targetSize, label)
	if err != nil {
		return nil, err
	}
	return &PreparedSource{Plan: plan}, nil
}

// TotalSize 本次写入会占用目标盘的字节数 (0 = 未知)
func (p *PreparedSource) TotalSize() int64 {
	if p == nil {
		return 0
	}
	if p.Plan != nil {
		return p.Plan.TotalSize
	}
	if p.Src != nil {
		return p.Src.Size()
	}
	return 0
}

// PrepareSource 识别来源并算出写入计划 (纯解析, 不落任何中间文件)。
//
//	path       空 = 程序内置镜像
//	forceMode  nil = 按内容自动判定
//	targetSize 目标盘容量 (0 = 未知; 文件包模式用来决定分区大小)
//	fullDisk   文件包模式: true = 按整卡容量建分区, false = 按内容大小
//	overrideMB 文件包模式: >0 时直接指定分区大小 (MiB), 优先于 fullDisk
//	label      卷标覆盖 (空 = 由来源名推导)
//	ctl        探测进度/取消 (nil = 无进度、不可取消)
func PrepareSource(path string, forceMode *SourceMode, targetSize int64, fullDisk bool, overrideMB int64, label string, ctl *ProbeCtl) (*PreparedSource, error) {
	if strings.TrimSpace(path) == "" {
		return prepareEmbedded(forceMode, targetSize, fullDisk, overrideMB, label, ctl)
	}
	a, err := probeAny(path, forceMode, ctl)
	if err != nil {
		return nil, err
	}
	return sourceFromArchive(a, path, targetSize, fullDisk, overrideMB, label)
}

// prepareEmbedded 解析**程序内置数据源**。
//
// 十九轮修正: 内置载荷不一定是整盘镜像 —— 十八轮② 起发版产物是 .txz 文件包,
// 工具必须按载荷**内容**判定, 否则会把压缩包字节当镜像写进卡 (现场事故)。
// 判定为文件包时落一份临时副本, 走与"用户手选文件"完全相同的路径。
func prepareEmbedded(forceMode *SourceMode, targetSize int64, fullDisk bool, overrideMB int64, label string, ctl *ProbeCtl) (*PreparedSource, error) {
	p, err := OpenSelfPayload()
	if err != nil {
		return nil, fmt.Errorf("%w (可用「浏览文件…」选数据源, 或用 repack 生成自带数据源的新程序)", err)
	}
	isPkg, _, kerr := payloadKind(p)
	if kerr == nil && isPkg {
		// 临时副本沿用载荷原名 (放在专属临时目录里), 所以 a.Path 的 basename 就是
		// 用户看到的文件名 —— 展示名与卷标推导都与"手选同一个包"完全一致。
		// 注意: 不能把 a.Path 改成别的展示名 —— 写卡/校验要按它把归档再打开一次。
		tmp, merr := EmbeddedPackageFile()
		if merr != nil {
			return nil, merr
		}
		a, perr := probeAny(tmp, forceMode, ctl)
		if perr != nil {
			return nil, perr
		}
		return sourceFromArchive(a, tmp, targetSize, fullDisk, overrideMB, label)
	}
	src, err := OpenEmbedded()
	if err != nil {
		return nil, err
	}
	return &PreparedSource{Src: src}, nil
}

// sourceFromArchive 把"已探测好的来源"变成写入计划 (手选文件与内置载荷共用)。
// pathForName 只用于推导展示名 (整盘模式下取归档内的镜像条目名)。
func sourceFromArchive(a *Archive, pathForName string, targetSize int64, fullDisk bool, overrideMB int64, label string) (*PreparedSource, error) {
	if a.Mode == ModeRawDisk {
		name := filepath.Base(pathForName)
		if a.Image != "" {
			name = a.Image
		}
		src := &ImageSource{
			Name:   name,
			raw:    a.RawSz,
			openFn: a.ImageOpenFunc(),
		}
		return &PreparedSource{Src: src, Archive: a}, nil
	}

	if len(a.Files) == 0 && len(a.Dirs) == 0 {
		if a.Format == dirFormat {
			return nil, fmt.Errorf("目录内没有任何文件")
		}
		return nil, fmt.Errorf("归档内没有任何文件")
	}
	plan, err := PlanCardImageSized(a, targetSize, fullDisk, overrideMB)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(label) != "" {
		plan.Label = sanitizeLabel(label)
	}
	return &PreparedSource{Archive: a, Plan: plan}, nil
}

// sanitizeLabel 卷标规范化: 大写, 仅 A-Z0-9_-, 最长 11
func sanitizeLabel(s string) string {
	var b strings.Builder
	for _, r := range strings.ToUpper(strings.TrimSpace(s)) {
		switch {
		case r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '_', r == '-':
			b.WriteRune(r)
		case r == ' ' || r == '.':
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

// SourceInfoText 界面用: 当前镜像来源的说明文字。
//
// 这里**不用表格** —— 未选择镜像时表格里只有"未内置镜像/请点浏览…"这类说明，
// 排成"项目|内容"两列反而莫名其妙；直接写两行描述更自然。选中镜像后按行列出
// 关键信息（不做列对齐，避免比例字体下的错位）。
func SourceInfoText(a *Archive, plan *PackagePlan) string {
	if a == nil {
		m := EmbeddedImageInfo()
		if m == nil {
			return "未内置镜像。\r\n请点「浏览…」选择镜像文件或压缩包。"
		}
		return strings.Join([]string{
			"来源：程序内置（" + originText(m.Origin) + "）",
			"文件：" + m.File,
			"大小：" + fmt.Sprintf("%s (%d 字节)", HumanBytes(m.Bytes), m.Bytes),
			"sha256：" + m.SHA256,
			"版本：" + orDashStr(m.BuildVer),
		}, "\r\n")
	}
	srcLabel := "文件："
	if a.Format == dirFormat {
		srcLabel = "目录："
	}
	lines := []string{
		srcLabel + filepath.Base(a.Path),
		"格式：" + formatLabel(a.Format),
		"写入方式：" + a.Mode.String(),
	}
	if a.Skipped > 0 {
		lines = append(lines, fmt.Sprintf("跳过：%d 个条目（FAT32 不支持: 目录链接/设备文件/断链）", a.Skipped))
	}
	if a.Mode == ModeRawDisk {
		img := a.Image
		if img == "" {
			img = "(整个文件即镜像)"
		}
		lines = append(lines, "镜像条目："+img, "解压大小："+HumanBytes(a.RawSz))
		if a.RawSz == 0 {
			lines = append(lines, "提示：解压大小未知，烧录前请自行确认卡容量")
		}
		return strings.Join(lines, "\r\n")
	}
	var content int64
	for _, f := range a.Files {
		content += f.Size
	}
	lines = append(lines, fmt.Sprintf("内容：%d 个文件，合计 %s", len(a.Files), HumanBytes(content)))
	for _, kv := range a.BootRootLines() {
		lines = append(lines, kv[0]+"："+kv[1])
	}
	if plan != nil {
		lines = append(lines, fmt.Sprintf("卡镜像：%s（MBR / 1×FAT32，卷标 %s）",
			HumanBytes(plan.TotalSize), plan.Label))
	}
	return strings.Join(lines, "\r\n")
}

// SourceInfoRows 界面/命令行展示的来源信息 (项目/内容 两列)
func SourceInfoRows(a *Archive, plan *PackagePlan) [][2]string {
	if a == nil {
		return ImagePropertyRows("") // 内置镜像
	}
	srcKey := "文件"
	if a.Format == dirFormat {
		srcKey = "目录"
	}
	rows := [][2]string{
		{srcKey, filepath.Base(a.Path)},
		{"格式", formatLabel(a.Format)},
		{"写入方式", a.Mode.String()},
	}
	if a.Skipped > 0 {
		rows = append(rows, [2]string{"跳过", fmt.Sprintf("%d 个条目 (FAT32 不支持)", a.Skipped)})
	}
	if a.Mode == ModeRawDisk {
		img := a.Image
		if img == "" {
			img = "(整个文件即镜像)"
		}
		rows = append(rows,
			[2]string{"镜像条目", img},
			[2]string{"解压大小", HumanBytes(a.RawSz)},
		)
		if a.RawSz == 0 {
			rows = append(rows, [2]string{"提示", "解压大小未知, 烧录前请自行确认卡容量"})
		}
		return rows
	}
	var content int64
	for _, f := range a.Files {
		content += f.Size
	}
	rows = append(rows,
		[2]string{"文件数", fmt.Sprintf("%d 个文件, %d 个目录", len(a.Files), len(a.Dirs))},
		[2]string{"内容合计", HumanBytes(content)},
	)
	rows = append(rows, a.BootRootLines()...)
	if plan != nil {
		rows = append(rows,
			[2]string{"卡镜像大小", HumanBytes(plan.TotalSize)},
			[2]string{"分区", fmt.Sprintf("MBR / 1×FAT32 (卷标 %s)", plan.Label)},
		)
	}
	for i, f := range a.Files {
		if i >= 8 {
			rows = append(rows, [2]string{"…", fmt.Sprintf("其余 %d 个文件", len(a.Files)-8)})
			break
		}
		rows = append(rows, [2]string{"  " + f.Name, HumanBytes(f.Size)})
	}
	return rows
}

func formatLabel(f string) string {
	switch f {
	case "img", "":
		return "裸磁盘镜像"
	case "dir":
		return "目录"
	case "tar.gz":
		return "tar + gzip"
	case "tar.xz":
		return "tar + xz"
	case "tar.bz2":
		return "tar + bzip2"
	case "tar":
		return "tar"
	}
	return f
}
