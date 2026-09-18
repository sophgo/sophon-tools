// 内置界面字体 (MYS-1240)
//
// 现场有机器中文显示成一排豆腐块 —— 那些系统装的中文字体不全（或者干脆没有），
// GDI 的字体链接挑不到能覆盖的字体，界面上「选择目标设备」会画成「□□目□□□」。
// 不能指望现场每台机器都装全字体，所以把一份中文字体子集直接打进 exe，启动时
// 注册进本进程（AddFontMemResourceEx，不落盘、不改系统设置）。
//
// 字体: Noto Sans CJK SC Regular (SIL OFL 1.1, 见 assets/OFL.txt)，
//       由 assets/mkfont.py 从系统的 Noto Sans CJK 裁出常用字集（约 3.4 MiB）：
//       ASCII/拉丁 + 常用符号 + 中文标点 + 全角 + 假名 + GB2312 全部汉字。
//
// 注意: 界面上用到的字符必须都在这个字体里。缺字会画成豆腐块 —— 这个字体不在
// 系统的字体链接表里，GDI 不会替它回退到别的字体。加新图标/符号时用
// assets/mkfont.py 自查一遍（它会把源码字符串里缺的字列出来）。
package main

import (
	_ "embed"
	"unsafe"

	"github.com/lxn/win"
	. "github.com/lxn/walk/declarative"
)

//go:embed assets/NotoSansSC-Regular-subset.otf
var uiFontData []byte

const (
	// uiFontFamily 必须与字体内部的 family name 完全一致（assets/mkfont.py 会打印）
	uiFontFamily = "Noto Sans CJK SC"
	// uiFontPointSize 与 walk 的默认字号一致，换字体不改变整体观感
	uiFontPointSize = 9
)

// installUIFont 把内置字体注册进当前进程。失败返回 false，调用方退回系统默认字体
// —— 字体装不上不该拦住程序启动，大不了还是原来的显示效果。
func installUIFont() bool {
	if len(uiFontData) == 0 {
		return false
	}
	var numFonts uint32
	// uiFontData 是包级变量，生命周期与进程相同。AddFontMemResourceEx 不复制字体
	// 数据，缓冲区必须一直有效，所以这里不能传局部切片。
	h := win.AddFontMemResourceEx(
		uintptr(unsafe.Pointer(&uiFontData[0])),
		uint32(len(uiFontData)),
		nil,
		&numFonts,
	)
	return h != 0 && numFonts > 0
}

// uiFont 给 MainWindow 用的字体声明。零值 = 不设字体 = 用系统默认。
func uiFont() Font {
	if !installUIFont() {
		return Font{}
	}
	return Font{Family: uiFontFamily, PointSize: uiFontPointSize}
}
