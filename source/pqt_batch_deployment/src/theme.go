//go:build !headless

package main

// 界面主题与视觉规范。
//
// 与 Web UI（webui/index.html 的 :root 变量）共用同一套设计 token，
// 两个界面观感一致；视觉决策集中在这里，gui.go 只负责布局。
//
//   - 主色取自 SOPHGO logo 的蓝（#3080E8），压暗到 #1D6BD6 以保证白字对比度；
//     红色只留给「删除 / 中止」这类破坏性操作，不再和主按钮抢视线。
//   - 灰底（background）+ 白色卡片（surface）分区，替代满屏分割线。
//   - 状态一律「色块 + 文字」双编码，不只靠颜色区分。
//
// 约束（见 BUILD.md）：全部通过 go:embed 内嵌，不引入任何运行时外部文件，
// 保证 Linux / Windows 都是单个可执行文件。

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/theme"
)

var (
	colorBrand      = color.NRGBA{R: 0x1D, G: 0x6B, B: 0xD6, A: 0xFF}
	colorBrandHover = color.NRGBA{R: 0x17, G: 0x58, B: 0xB4, A: 0xFF}
	colorBrandSoft  = color.NRGBA{R: 0xEA, G: 0xF2, B: 0xFD, A: 0xFF}

	// 语义色（文字）与对应的浅底（色块背景）。
	colorSuccess     = color.NRGBA{R: 0x18, G: 0x86, B: 0x4B, A: 0xFF}
	colorSuccessSoft = color.NRGBA{R: 0xE7, G: 0xF5, B: 0xED, A: 0xFF}
	colorWarning     = color.NRGBA{R: 0xB2, G: 0x6B, B: 0x00, A: 0xFF}
	colorWarningSoft = color.NRGBA{R: 0xFD, G: 0xF3, B: 0xE1, A: 0xFF}
	colorDanger      = color.NRGBA{R: 0xD9, G: 0x30, B: 0x26, A: 0xFF}
	colorDangerSoft  = color.NRGBA{R: 0xFD, G: 0xEC, B: 0xEA, A: 0xFF}
	colorRunning     = colorBrand
	colorRunningSoft = color.NRGBA{R: 0xD8, G: 0xE7, B: 0xFB, A: 0xFF} // 比选中行底色深一档，选中行上仍可见

	// 操作类型标签色：命令 / 上传 / 下载。
	colorTypeFg = [3]color.NRGBA{
		{R: 0x6B, G: 0x3F, B: 0xD4, A: 0xFF},
		{R: 0x0B, G: 0x7A, B: 0x75, A: 0xFF},
		{R: 0xA4, G: 0x5A, B: 0x00, A: 0xFF},
	}
	colorTypeBg = [3]color.NRGBA{
		{R: 0xF1, G: 0xEC, B: 0xFD, A: 0xFF},
		{R: 0xE3, G: 0xF5, B: 0xF4, A: 0xFF},
		{R: 0xFD, G: 0xF1, B: 0xE2, A: 0xFF},
	}

	// 中性色
	colorText       = color.NRGBA{R: 0x1F, G: 0x23, B: 0x29, A: 0xFF}
	colorText2      = color.NRGBA{R: 0x4B, G: 0x52, B: 0x60, A: 0xFF}
	colorTextMuted  = color.NRGBA{R: 0x8A, G: 0x90, B: 0x9C, A: 0xFF}
	colorBackground = color.NRGBA{R: 0xF3, G: 0xF5, B: 0xF8, A: 0xFF}
	colorSurface    = color.NRGBA{R: 0xFF, G: 0xFF, B: 0xFF, A: 0xFF}
	colorSurfaceAlt = color.NRGBA{R: 0xF7, G: 0xF8, B: 0xFA, A: 0xFF}
	colorBorder     = color.NRGBA{R: 0xE1, G: 0xE5, B: 0xEB, A: 0xFF}
	colorBorderDark = color.NRGBA{R: 0xCF, G: 0xD5, B: 0xDD, A: 0xFF}
	colorButton     = color.NRGBA{R: 0xED, G: 0xF0, B: 0xF4, A: 0xFF}

	// 日志终端区
	colorTermBg  = color.NRGBA{R: 0x1B, G: 0x1F, B: 0x27, A: 0xFF}
	colorTermFg  = color.NRGBA{R: 0xD6, G: 0xDD, B: 0xE8, A: 0xFF}
	colorTermErr = color.NRGBA{R: 0xFF, G: 0x8A, B: 0x80, A: 0xFF}
	colorTermOK  = color.NRGBA{R: 0x8B, G: 0xE2, B: 0xA8, A: 0xFF}
	colorTermDim = color.NRGBA{R: 0x7D, G: 0x86, B: 0x96, A: 0xFF}
)

// 自定义颜色名：供 RichText 段落按名字取色（日志区按行着色）。
const (
	colorNameTermFg  fyne.ThemeColorName = "bdTermFg"
	colorNameTermErr fyne.ThemeColorName = "bdTermErr"
	colorNameTermOK  fyne.ThemeColorName = "bdTermOK"
	colorNameTermDim fyne.ThemeColorName = "bdTermDim"
	colorNameMuted   fyne.ThemeColorName = "bdMuted"
)

// appTheme 在 Fyne 内置浅色主题上覆写配色、尺寸与字体。
type appTheme struct {
	fyne.Theme

	font fyne.Resource
}

func newAppTheme() fyne.Theme {
	return &appTheme{
		// 用 LightTheme 而不是 DefaultTheme：后者跟随系统，Linux 桌面常常是深色，
		// 会让本文件定义的一套浅色中性色失去意义。
		Theme: theme.LightTheme(),
		font:  cjkFontResource(),
	}
}

func (t *appTheme) Color(name fyne.ThemeColorName, v fyne.ThemeVariant) color.Color {
	switch name {
	case theme.ColorNamePrimary, theme.ColorNameHyperlink:
		return colorBrand
	case theme.ColorNameFocus:
		// 注意：Fyne 的下拉菜单项选中态也用这个颜色画**整行背景**。
		// 直接给品牌蓝会变成一大块高饱和色块，与整体浅色卡片风格割裂；
		// 这里给浅色选中底，输入框的焦点框由 InputBorder+Primary 负责，不受影响。
		return colorBrandSoft
	case theme.ColorNameForeground:
		return colorText
	case theme.ColorNameBackground:
		return colorBackground
	case theme.ColorNameButton:
		// 次要按钮用浅灰底：白色卡片上仍能看出按钮轮廓。
		return colorButton
	case theme.ColorNameHover:
		return color.NRGBA{R: 0x1F, G: 0x23, B: 0x29, A: 0x0D}
	case theme.ColorNamePressed:
		return color.NRGBA{R: 0x1F, G: 0x23, B: 0x29, A: 0x1A}
	case theme.ColorNameInputBackground, theme.ColorNameMenuBackground, theme.ColorNameOverlayBackground:
		return colorSurface
	case theme.ColorNameInputBorder:
		return colorBorderDark
	case theme.ColorNameHeaderBackground:
		return colorSurfaceAlt
	case theme.ColorNameSeparator:
		return colorBorder
	case theme.ColorNamePlaceHolder:
		return color.NRGBA{R: 0xA8, G: 0xAE, B: 0xB8, A: 0xFF}
	case theme.ColorNameSelection:
		return color.NRGBA{R: 0x1D, G: 0x6B, B: 0xD6, A: 0x33}
	case theme.ColorNameError:
		return colorDanger
	case theme.ColorNameSuccess:
		return colorSuccess
	case theme.ColorNameWarning:
		return colorWarning
	case theme.ColorNameScrollBar:
		return color.NRGBA{R: 0x1F, G: 0x23, B: 0x29, A: 0x40}
	case theme.ColorNameShadow:
		return color.NRGBA{R: 0x10, G: 0x18, B: 0x28, A: 0x2A}
	case colorNameTermFg:
		return colorTermFg
	case colorNameTermErr:
		return colorTermErr
	case colorNameTermOK:
		return colorTermOK
	case colorNameTermDim:
		return colorTermDim
	case colorNameMuted:
		return colorTextMuted
	}
	return t.Theme.Color(name, v)
}

func (t *appTheme) Size(name fyne.ThemeSizeName) float32 {
	switch name {
	case theme.SizeNamePadding:
		return 6
	case theme.SizeNameInnerPadding:
		return 9
	case theme.SizeNameText:
		return 14
	case theme.SizeNameCaptionText:
		return 12
	case theme.SizeNameHeadingText:
		return 18
	case theme.SizeNameSubHeadingText:
		return 15
	case theme.SizeNameInputRadius, theme.SizeNameButtonRadius, theme.SizeNameSelectionRadius:
		return 6
	case theme.SizeNameCardRadius, theme.SizeNameDialogRadius,
		theme.SizeNamePopupRadius, theme.SizeNameMenuRadius:
		return 10
	case theme.SizeNameInputBorder:
		return 1
	case theme.SizeNameSeparatorThickness:
		return 1
	}
	return t.Theme.Size(name)
}

func (t *appTheme) Font(style fyne.TextStyle) fyne.Resource {
	// 只替换常规/粗体正文；等宽与符号图标仍走默认资源，
	// 否则代码块与内置图标会因思源黑体缺字形而显示成方块。
	if !style.Monospace && !style.Symbol && t.font != nil {
		return t.font
	}
	return t.Theme.Font(style)
}

// cjkFontResource 内嵌思源黑体（与旧版 Qt 版同一份字体，原先已随仓库提供但从未被使用）。
func cjkFontResource() fyne.Resource {
	data, err := ReadAsset("SourceHanSansCN-Medium.otf")
	if err != nil {
		return nil // 退回默认字体，不因缺字体拒绝启动
	}
	return fyne.NewStaticResource("SourceHanSansCN-Medium.otf", data)
}

// statusKind 设备状态分类，供配色与统计共用。
type statusKind int

const (
	statusNone statusKind = iota
	statusOK
	statusFail
	statusWait
	statusRun
)

func classifyStatus(status string) statusKind {
	switch {
	case status == "":
		return statusNone
	case hasAnyPrefix(status, "成功"):
		return statusOK
	case hasAnyPrefix(status, "失败"):
		return statusFail
	case hasAnyPrefix(status, "等待"):
		return statusWait
	default: // 连接中 / 执行: xxx / 上传中 / 下载中
		return statusRun
	}
}

// statusColors 返回设备状态的文字色与色块底色。
func statusColors(status string) (fg, bg color.Color) {
	switch classifyStatus(status) {
	case statusOK:
		return colorSuccess, colorSuccessSoft
	case statusFail:
		return colorDanger, colorDangerSoft
	case statusWait:
		return colorWarning, colorWarningSoft
	case statusRun:
		return colorRunning, colorRunningSoft
	}
	return colorTextMuted, nil
}

func hasAnyPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}
