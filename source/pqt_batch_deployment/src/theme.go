package main

// 界面主题与视觉规范。
//
// 旧版是 Qt + 一份 qt-material 的 theme.qss（黑字、20px、灰边框）；Fyne 版直接沿用
// 默认主题，只有「能用」没有「好用」：主次不分、中文标签被挤、状态只有纯文字。
// 这里集中定义一套配色/字号，让 gui.go 只负责布局，视觉决策有一处可查。
//
// 约束（见 BUILD.md）：全部通过 go:embed 内嵌，不引入任何运行时外部文件，
// 保证 Linux / Windows 都是单个可执行文件。

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/theme"
)

// 品牌色：sophgo 红（与官网链接同色系），用作主按钮与强调色。
var (
	colorBrand      = color.NRGBA{R: 0xE0, G: 0x30, B: 0x30, A: 0xFF}
	colorBrandHover = color.NRGBA{R: 0xC8, G: 0x24, B: 0x24, A: 0xFF}

	// 语义色：设备执行状态用，避免"成功/失败"只靠文字区分。
	colorSuccess = color.NRGBA{R: 0x1E, G: 0x8E, B: 0x3E, A: 0xFF}
	colorWarning = color.NRGBA{R: 0xC7, G: 0x7C, B: 0x00, A: 0xFF}
	colorDanger  = color.NRGBA{R: 0xC6, G: 0x28, B: 0x28, A: 0xFF}
	colorRunning = color.NRGBA{R: 0x15, G: 0x65, B: 0xC0, A: 0xFF}

	// 中性色
	colorTextMuted  = color.NRGBA{R: 0x6B, G: 0x70, B: 0x80, A: 0xFF}
	colorSurface    = color.NRGBA{R: 0xF6, G: 0xF7, B: 0xF9, A: 0xFF}
	colorSurfaceAlt = color.NRGBA{R: 0xEC, G: 0xEF, B: 0xF3, A: 0xFF}
	colorBorder     = color.NRGBA{R: 0xD4, G: 0xD9, B: 0xE0, A: 0xFF}
	colorHeaderText = color.NRGBA{R: 0x33, G: 0x38, B: 0x42, A: 0xFF}
)

// appTheme 在 Fyne 内置主题上覆写少量条目：
//   - 固定浅色变体（旧版 Qt 的 theme.qss 就是浅色黑字，界面对齐原设计）；
//   - 主色换成品牌红（主按钮、选中态、焦点框自然跟随）；
//   - 内边距/输入框留白放大，中文标签不再贴边；
//   - 字体换成内嵌的思源黑体，避免各平台中文字形不一致。
type appTheme struct {
	fyne.Theme

	font fyne.Resource
}

func newAppTheme() fyne.Theme {
	return &appTheme{
		// 用 LightTheme 而不是 DefaultTheme：后者跟随系统，Linux 桌面常常是深色，
		// 会让本文件定义的一套浅色中性色（surface/border）失去意义。
		Theme: theme.LightTheme(),
		font:  cjkFontResource(),
	}
}

func (t *appTheme) Color(name fyne.ThemeColorName, v fyne.ThemeVariant) color.Color {
	switch name {
	case theme.ColorNamePrimary:
		return colorBrand
	case theme.ColorNameHover:
		return colorBrandHover
	case theme.ColorNameHeaderBackground:
		return colorSurfaceAlt
	case theme.ColorNameSeparator:
		return colorBorder
	}
	return t.Theme.Color(name, v)
}

func (t *appTheme) Size(name fyne.ThemeSizeName) float32 {
	switch name {
	case theme.SizeNamePadding:
		return 6
	case theme.SizeNameInnerPadding:
		return 10
	case theme.SizeNameText:
		return 14
	case theme.SizeNameHeadingText:
		return 19
	case theme.SizeNameSubHeadingText:
		return 15
	case theme.SizeNameInputRadius:
		return 5
	case theme.SizeNameButtonRadius:
		return 5
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

// 设备状态语义色。
func statusColor(status string) color.Color {
	switch {
	case status == "":
		return colorTextMuted
	case hasAnyPrefix(status, "成功"):
		return colorSuccess
	case hasAnyPrefix(status, "失败"):
		return colorDanger
	case hasAnyPrefix(status, "等待"):
		return colorWarning
	default: // 连接中 / 执行: xxx / 上传中 / 下载中
		return colorRunning
	}
}

func hasAnyPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}
