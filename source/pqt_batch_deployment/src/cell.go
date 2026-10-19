//go:build !headless

package main

// 表格单元格控件。
//
// 为什么不用 widget.Label：Fyne 的 Label 只有 Low/Medium/High/Danger/Warning
// 五档 Importance，无法给「成功」上绿色——而设备执行状态正是最需要语义色的地方
// （旧版 Qt 用整行背景色区分运行/成功/失败）。这里用 canvas.Text 自绘，
// 颜色可任意指定，其余样式仍与普通标签一致。

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

type cellText struct {
	widget.BaseWidget

	text     *canvas.Text
	col      color.Color
	bold     bool
	ellipsis bool
}

func newCellText() *cellText {
	c := &cellText{
		text:     canvas.NewText("", theme.ForegroundColor()),
		ellipsis: true,
	}
	c.ExtendBaseWidget(c)
	return c
}

func (c *cellText) SetText(s string) {
	if c.text.Text == s {
		return
	}
	c.text.Text = s
	c.text.Refresh()
}

func (c *cellText) Text() string { return c.text.Text }

// SetColor 指定文字颜色；nil 表示跟随主题前景色。
func (c *cellText) SetColor(col color.Color) {
	if col == nil {
		col = theme.ForegroundColor()
	}
	c.col = col
	c.text.Color = col
	c.text.Refresh()
}

func (c *cellText) SetBold(b bool) {
	if c.bold == b {
		return
	}
	c.bold = b
	c.applyStyle()
}

func (c *cellText) applyStyle() {
	if c.bold {
		c.text.TextStyle = fyne.TextStyle{Bold: true}
	} else {
		c.text.TextStyle = fyne.TextStyle{}
	}
	c.text.Refresh()
}

func (c *cellText) CreateRenderer() fyne.WidgetRenderer {
	return &cellTextRenderer{c: c}
}

type cellTextRenderer struct {
	c *cellText
}

func (r *cellTextRenderer) Layout(size fyne.Size) {
	r.c.text.Resize(size)
}

func (r *cellTextRenderer) MinSize() fyne.Size {
	s := r.c.text.MinSize()
	// 留出一点垂直余量，避免行高被文字顶死（中文尤其明显）。
	return fyne.NewSize(s.Width, s.Height+theme.Padding())
}

func (r *cellTextRenderer) Refresh() {
	if r.c.col != nil {
		r.c.text.Color = r.c.col
	}
	r.c.text.Refresh()
}

func (r *cellTextRenderer) Objects() []fyne.CanvasObject {
	return []fyne.CanvasObject{r.c.text}
}

func (r *cellTextRenderer) Destroy() {}

// statusText 把内部状态字符串规范成界面用词。
// 失败状态里带具体原因时（"失败/..."），表格只显示结论，详情在下方日志区。
func statusText(s string) string {
	if s == "" {
		return "—"
	}
	for _, p := range []string{"成功", "失败", "等待中"} {
		if hasAnyPrefix(s, p) {
			return p
		}
	}
	return s
}
