//go:build !headless

package main

// 表格单元格控件。
//
// 为什么不用 widget.Label：Fyne 的 Label 只有 Low/Medium/High/Danger/Warning
// 五档 Importance，无法给「成功」上绿色，也画不了状态色块。这里用 canvas 自绘：
//   - 行背景（表头底色 / 选中行高亮）；
//   - 可选「色块」模式：文字外包一个圆角浅底，用于执行状态与操作类型；
//   - 垂直居中、超宽截断加省略号（canvas.Text 本身不会截断，会压到相邻列）。

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

const (
	cellInsetX = 10 // 单元格左右留白
	pillPadX   = 8  // 色块内左右留白
	pillPadY   = 3  // 色块内上下留白
)

type cellText struct {
	widget.BaseWidget

	full   string // 未截断的原文
	text   *canvas.Text
	rowBg  *canvas.Rectangle
	pillBg *canvas.Rectangle
	col    color.Color
	bold   bool
	pill   bool
}

func newCellText() *cellText {
	c := &cellText{
		text:   canvas.NewText("", theme.Color(theme.ColorNameForeground)),
		rowBg:  canvas.NewRectangle(color.Transparent),
		pillBg: canvas.NewRectangle(color.Transparent),
	}
	c.text.TextSize = theme.TextSize() - 1
	c.ExtendBaseWidget(c)
	return c
}

func (c *cellText) SetText(s string) {
	if c.full == s {
		return
	}
	c.full = s
	c.Refresh()
}

func (c *cellText) Text() string { return c.full }

// SetColor 指定文字颜色；nil 表示跟随主题前景色。
func (c *cellText) SetColor(col color.Color) {
	c.col = col
	c.Refresh()
}

func (c *cellText) SetBold(b bool) {
	if c.bold == b {
		return
	}
	c.bold = b
	c.Refresh()
}

// SetRowBackground 设置整格背景；nil 为透明。
func (c *cellText) SetRowBackground(col color.Color) {
	if col == nil {
		col = color.Transparent
	}
	c.rowBg.FillColor = col
	c.rowBg.Refresh()
}

// SetPill 开启/关闭色块模式；bg 为 nil 时关闭。
func (c *cellText) SetPill(bg color.Color) {
	c.pill = bg != nil
	if bg == nil {
		bg = color.Transparent
	}
	c.pillBg.FillColor = bg
	c.Refresh()
}

func (c *cellText) CreateRenderer() fyne.WidgetRenderer {
	return &cellTextRenderer{c: c}
}

type cellTextRenderer struct {
	c *cellText
}

func (r *cellTextRenderer) Layout(size fyne.Size) {
	c := r.c
	c.rowBg.Resize(size)
	c.rowBg.Move(fyne.NewPos(0, 0))

	avail := size.Width - 2*cellInsetX
	if c.pill {
		avail -= 2 * pillPadX
	}
	c.text.Text = fitText(c.full, c.text.TextSize, c.text.TextStyle, avail)
	ts := fyne.MeasureText(c.text.Text, c.text.TextSize, c.text.TextStyle)

	x := float32(cellInsetX)
	y := (size.Height - ts.Height) / 2
	if c.pill && c.text.Text != "" {
		ph := ts.Height + 2*pillPadY
		c.pillBg.CornerRadius = ph / 2
		c.pillBg.Resize(fyne.NewSize(ts.Width+2*pillPadX, ph))
		c.pillBg.Move(fyne.NewPos(x, (size.Height-ph)/2))
		c.pillBg.Show()
		x += pillPadX
	} else {
		c.pillBg.Hide()
	}
	c.text.Resize(ts)
	c.text.Move(fyne.NewPos(x, y))
}

func (r *cellTextRenderer) MinSize() fyne.Size {
	s := fyne.MeasureText("国", r.c.text.TextSize, r.c.text.TextStyle)
	// 行高固定为舒适值，避免中文被顶死。
	return fyne.NewSize(s.Width, s.Height+2*theme.Padding()+8)
}

func (r *cellTextRenderer) Refresh() {
	c := r.c
	if c.col != nil {
		c.text.Color = c.col
	} else {
		c.text.Color = theme.Color(theme.ColorNameForeground)
	}
	c.text.TextStyle = fyne.TextStyle{Bold: c.bold}
	r.Layout(c.Size())
	c.text.Refresh()
	c.pillBg.Refresh()
	c.rowBg.Refresh()
}

func (r *cellTextRenderer) Objects() []fyne.CanvasObject {
	return []fyne.CanvasObject{r.c.rowBg, r.c.pillBg, r.c.text}
}

func (r *cellTextRenderer) Destroy() {}

// fitText 超出可用宽度时按字符截断并补「...」。
func fitText(s string, size float32, style fyne.TextStyle, avail float32) string {
	if s == "" || avail <= 0 || fyne.MeasureText(s, size, style).Width <= avail {
		return s
	}
	rs := []rune(s)
	// 二分查找能放下的最长前缀
	lo, hi := 0, len(rs)
	for lo < hi {
		mid := (lo + hi + 1) / 2
		if fyne.MeasureText(string(rs[:mid])+"...", size, style).Width <= avail {
			lo = mid
		} else {
			hi = mid - 1
		}
	}
	return string(rs[:lo]) + "..."
}

// statusText 把内部状态字符串规范成界面用词。
// 失败状态里带具体原因时（"失败/..."），表格只显示结论，详情在日志区。
func statusText(s string) string {
	if s == "" {
		return "未执行"
	}
	for _, p := range []string{"成功", "失败", "等待中"} {
		if hasAnyPrefix(s, p) {
			return p
		}
	}
	return s
}
