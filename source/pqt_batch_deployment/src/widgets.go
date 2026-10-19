//go:build !headless

package main

// 界面基础组件：卡片、徽标、比例条、统计块、日志终端、分段选择器。
// 只封装视觉，不持有业务状态；配色全部取自 theme.go。

import (
	"image/color"
	"strconv"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

// ---------- 卡片 ----------

// newCard 白底圆角描边卡片：head 在上（下方一条分隔线），body 填满其余空间。
func newCard(head, body fyne.CanvasObject) fyne.CanvasObject {
	bg := canvas.NewRectangle(colorSurface)
	bg.StrokeColor = colorBorder
	bg.StrokeWidth = 1
	bg.CornerRadius = theme.Size(theme.SizeNameCardRadius)

	inner := body
	if head != nil {
		inner = container.NewBorder(
			container.NewVBox(container.NewPadded(head), widget.NewSeparator()),
			nil, nil, nil,
			container.NewPadded(body),
		)
	} else {
		inner = container.NewPadded(body)
	}
	return container.NewStack(bg, container.NewPadded(inner))
}

// cardTitle 卡片标题：图标 + 粗体标题 + 计数徽标。
func cardTitle(icon fyne.Resource, title string, count *canvas.Text) fyne.CanvasObject {
	ic := widget.NewIcon(theme.NewColoredResource(icon, theme.ColorNamePrimary))
	t := canvas.NewText(title, colorText)
	t.TextStyle = fyne.TextStyle{Bold: true}
	t.TextSize = theme.Size(theme.SizeNameSubHeadingText)
	items := []fyne.CanvasObject{ic, t}
	if count != nil {
		items = append(items, newChipBox(count, colorSurfaceAlt, colorBorder))
	}
	return container.NewHBox(items...)
}

// ---------- 徽标 / 标签 ----------

// newChipText 生成用于徽标的小号文字。
func newChipText(s string, fg color.Color) *canvas.Text {
	t := canvas.NewText(s, fg)
	t.TextSize = theme.Size(theme.SizeNameCaptionText)
	return t
}

// newChipBox 把文字包成圆角胶囊；stroke 为 nil 时无描边。
func newChipBox(t *canvas.Text, bg, stroke color.Color) fyne.CanvasObject {
	r := canvas.NewRectangle(bg)
	if stroke != nil {
		r.StrokeColor = stroke
		r.StrokeWidth = 1
	}
	r.CornerRadius = 10
	return container.NewStack(r, container.New(&insetLayout{x: 8, y: 2}, t))
}

// badge 可变内容的状态徽标（图标 + 文字 + 浅底），用于「完整度」提示。
type badge struct {
	box  *fyne.Container
	bg   *canvas.Rectangle
	icon *widget.Icon
	text *canvas.Text
}

func newBadge() *badge {
	b := &badge{
		bg:   canvas.NewRectangle(colorSurfaceAlt),
		icon: widget.NewIcon(nil),
		text: canvas.NewText("", colorTextMuted),
	}
	b.bg.CornerRadius = 6
	b.text.TextStyle = fyne.TextStyle{Bold: true}
	b.box = container.NewStack(b.bg,
		container.New(&insetLayout{x: 8, y: 4}, container.NewHBox(b.icon, b.text)))
	return b
}

type badgeKind int

const (
	badgeNone badgeKind = iota
	badgeOK
	badgeWarn
)

func (b *badge) Set(kind badgeKind, s string) {
	switch kind {
	case badgeOK:
		b.bg.FillColor, b.text.Color = colorSuccessSoft, colorSuccess
		b.icon.SetResource(theme.NewColoredResource(theme.ConfirmIcon(), theme.ColorNameSuccess))
		b.icon.Show()
	case badgeWarn:
		b.bg.FillColor, b.text.Color = colorWarningSoft, colorWarning
		b.icon.SetResource(theme.NewColoredResource(theme.WarningIcon(), theme.ColorNameWarning))
		b.icon.Show()
	default:
		b.bg.FillColor, b.text.Color = colorSurfaceAlt, colorTextMuted
		b.icon.Hide()
	}
	b.text.Text = s
	b.bg.Refresh()
	b.text.Refresh()
	b.box.Refresh()
}

// ---------- 比例条 ----------

// ratioBar 成功（绿）/ 失败（红）占比条，直观呈现批量执行进度。
type ratioBar struct {
	widget.BaseWidget
	ok, fail float32 // 0..1
}

func newRatioBar() *ratioBar {
	b := &ratioBar{}
	b.ExtendBaseWidget(b)
	return b
}

func (b *ratioBar) Set(ok, fail, total int) {
	if total <= 0 {
		b.ok, b.fail = 0, 0
	} else {
		b.ok, b.fail = float32(ok)/float32(total), float32(fail)/float32(total)
	}
	b.Refresh()
}

func (b *ratioBar) CreateRenderer() fyne.WidgetRenderer {
	r := &ratioBarRenderer{
		b:    b,
		bg:   canvas.NewRectangle(colorSurfaceAlt),
		ok:   canvas.NewRectangle(colorSuccess),
		fail: canvas.NewRectangle(colorDanger),
	}
	r.bg.StrokeColor = colorBorder
	r.bg.StrokeWidth = 1
	return r
}

type ratioBarRenderer struct {
	b            *ratioBar
	bg, ok, fail *canvas.Rectangle
}

func (r *ratioBarRenderer) Layout(s fyne.Size) {
	rad := s.Height / 2
	r.bg.CornerRadius = rad
	r.bg.Resize(s)
	wOK, wFail := s.Width*r.b.ok, s.Width*r.b.fail
	r.ok.Move(fyne.NewPos(0, 0))
	r.ok.Resize(fyne.NewSize(wOK, s.Height))
	r.fail.Move(fyne.NewPos(wOK, 0))
	r.fail.Resize(fyne.NewSize(wFail, s.Height))
	// 两端圆角：只给最外侧的色段圆角，中间接缝保持直角。
	r.ok.TopLeftCornerRadius, r.ok.BottomLeftCornerRadius = rad, rad
	r.ok.TopRightCornerRadius, r.ok.BottomRightCornerRadius = 0, 0
	r.fail.TopLeftCornerRadius, r.fail.BottomLeftCornerRadius = 0, 0
	r.fail.TopRightCornerRadius, r.fail.BottomRightCornerRadius = 0, 0
	if wOK == 0 {
		r.fail.TopLeftCornerRadius, r.fail.BottomLeftCornerRadius = rad, rad
	}
	if r.b.ok+r.b.fail >= 0.999 {
		if wFail > 0 {
			r.fail.TopRightCornerRadius, r.fail.BottomRightCornerRadius = rad, rad
		} else {
			r.ok.TopRightCornerRadius, r.ok.BottomRightCornerRadius = rad, rad
		}
	}
}

func (r *ratioBarRenderer) MinSize() fyne.Size { return fyne.NewSize(40, 6) }

func (r *ratioBarRenderer) Refresh() {
	r.Layout(r.b.Size())
	canvas.Refresh(r.bg)
	canvas.Refresh(r.ok)
	canvas.Refresh(r.fail)
}

func (r *ratioBarRenderer) Objects() []fyne.CanvasObject {
	return []fyne.CanvasObject{r.bg, r.ok, r.fail}
}

func (r *ratioBarRenderer) Destroy() {}

// ---------- 统计块 ----------

// statTile 概览统计块：小标题 + 大号数字。
type statTile struct {
	obj   fyne.CanvasObject
	value *canvas.Text
}

func newStatTile(label string, accent, valueColor color.Color) *statTile {
	dot := canvas.NewRectangle(accent)
	dot.CornerRadius = 2
	dot.SetMinSize(fyne.NewSize(8, 8))
	lbl := canvas.NewText(label, colorText2)
	lbl.TextSize = theme.Size(theme.SizeNameCaptionText)
	val := canvas.NewText("0", valueColor)
	val.TextSize = 22
	val.TextStyle = fyne.TextStyle{Bold: true}

	bg := canvas.NewRectangle(colorSurfaceAlt)
	bg.StrokeColor = colorBorder
	bg.StrokeWidth = 1
	bg.CornerRadius = 8
	head := container.NewHBox(container.NewCenter(dot), lbl)
	return &statTile{
		obj:   container.NewStack(bg, container.New(&insetLayout{x: 12, y: 6}, container.NewVBox(head, val))),
		value: val,
	}
}

func (s *statTile) Set(n int) {
	s.value.Text = strconv.Itoa(n)
	s.value.Refresh()
}

// ---------- 日志终端 ----------

// logView 深色等宽风格的日志区：按行着色（失败红、成功绿），只读。
//
// 不用 widget.Entry：Entry 无法做深色底与逐行配色；也不用 Monospace 字体，
// 因为 Fyne 自带等宽字体没有中文字形，日志里的中文会显示成方块。
type logView struct {
	rich   *widget.RichText
	scroll *container.Scroll
	obj    fyne.CanvasObject
	raw    string
}

func newLogView() *logView {
	v := &logView{rich: widget.NewRichText()}
	v.rich.Wrapping = fyne.TextWrapWord
	v.scroll = container.NewVScroll(v.rich)
	bg := canvas.NewRectangle(colorTermBg)
	bg.CornerRadius = 8
	v.obj = container.NewStack(bg, container.New(&insetLayout{x: 6, y: 4}, v.scroll))
	return v
}

// SetPlaceholder 显示灰色提示语。
func (v *logView) SetPlaceholder(s string) {
	v.raw = ""
	v.rich.Segments = []widget.RichTextSegment{&widget.TextSegment{
		Text: s, Style: widget.RichTextStyle{ColorName: colorNameTermDim},
	}}
	v.rich.Refresh()
	v.scroll.ScrollToTop()
}

// SetText 设置日志正文并滚动到底部。
func (v *logView) SetText(s string) {
	if s == "" {
		v.SetPlaceholder("(暂无日志)")
		return
	}
	v.raw = s
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	segs := make([]widget.RichTextSegment, 0, len(lines))
	for _, ln := range lines {
		segs = append(segs, &widget.TextSegment{
			Text:  ln,
			Style: widget.RichTextStyle{ColorName: logLineColor(ln)},
		})
	}
	v.rich.Segments = segs
	v.rich.Refresh()
	v.scroll.ScrollToBottom()
}

// Text 返回当前日志原文（无日志时为空串），供「复制」使用。
func (v *logView) Text() string { return v.raw }

func logLineColor(ln string) fyne.ThemeColorName {
	lower := strings.ToLower(ln)
	switch {
	case strings.Contains(ln, "失败") || strings.Contains(ln, "错误") ||
		strings.Contains(lower, "error") || strings.Contains(lower, "fail"):
		return colorNameTermErr
	case strings.Contains(ln, "成功") || strings.Contains(ln, "完成"):
		return colorNameTermOK
	}
	return colorNameTermFg
}

// ---------- 分段选择器 ----------

// segmented 一组互斥按钮（替代「标签页 + 下拉框」两套重复的类型选择）。
type segmented struct {
	btns     []*widget.Button
	selected int
	obj      fyne.CanvasObject
	OnChange func(int)
}

func newSegmented(labels []string, icons []fyne.Resource) *segmented {
	s := &segmented{selected: -1}
	objs := make([]fyne.CanvasObject, 0, len(labels))
	for i, l := range labels {
		i := i
		b := widget.NewButtonWithIcon(l, icons[i], func() {
			if s.selected == i {
				return
			}
			s.Select(i)
			if s.OnChange != nil {
				s.OnChange(i)
			}
		})
		s.btns = append(s.btns, b)
		objs = append(objs, b)
	}
	bg := canvas.NewRectangle(colorSurfaceAlt)
	bg.StrokeColor = colorBorder
	bg.StrokeWidth = 1
	bg.CornerRadius = 8
	s.obj = container.NewHBox(container.NewStack(bg,
		container.New(&insetLayout{x: 2, y: 2}, container.NewHBox(objs...))))
	s.Select(0)
	return s
}

// Select 只改外观，不触发 OnChange。
func (s *segmented) Select(i int) {
	s.selected = i
	for j, b := range s.btns {
		if j == i {
			b.Importance = widget.HighImportance
		} else {
			b.Importance = widget.LowImportance
		}
		b.Refresh()
	}
}

func (s *segmented) Selected() int { return s.selected }

func (s *segmented) Disable() {
	for _, b := range s.btns {
		b.Disable()
	}
}

func (s *segmented) Enable() {
	for _, b := range s.btns {
		b.Enable()
	}
}

func (s *segmented) Disabled() bool { return len(s.btns) > 0 && s.btns[0].Disabled() }

// ---------- 布局工具 ----------

// insetLayout 给单个子元素四周留出固定边距（比 NewPadded 的统一 padding 更可控）。
type insetLayout struct{ x, y float32 }

func (l *insetLayout) Layout(objs []fyne.CanvasObject, size fyne.Size) {
	for _, o := range objs {
		o.Move(fyne.NewPos(l.x, l.y))
		o.Resize(fyne.NewSize(size.Width-2*l.x, size.Height-2*l.y))
	}
}

func (l *insetLayout) MinSize(objs []fyne.CanvasObject) fyne.Size {
	var m fyne.Size
	for _, o := range objs {
		m = m.Max(o.MinSize())
	}
	return fyne.NewSize(m.Width+2*l.x, m.Height+2*l.y)
}

// fixedWidth 让子元素至少占用给定宽度（Fyne 的 Select 默认会被压到很窄）。
func fixedWidth(w float32, o fyne.CanvasObject) fyne.CanvasObject {
	sp := canvas.NewRectangle(color.Transparent)
	sp.SetMinSize(fyne.NewSize(w, 0))
	return container.NewStack(sp, o)
}

// hSpacer 固定宽度的水平空白。
func hSpacer(w float32) fyne.CanvasObject {
	sp := canvas.NewRectangle(color.Transparent)
	sp.SetMinSize(fyne.NewSize(w, 1))
	return sp
}

// fixedSizeLayout 把子元素固定为给定尺寸并居中（用于状态点等小图形）。
type fixedSizeLayout struct{ size fyne.Size }

func (l *fixedSizeLayout) Layout(objs []fyne.CanvasObject, size fyne.Size) {
	for _, o := range objs {
		o.Resize(l.size)
		o.Move(fyne.NewPos((size.Width-l.size.Width)/2, (size.Height-l.size.Height)/2))
	}
}

func (l *fixedSizeLayout) MinSize([]fyne.CanvasObject) fyne.Size { return l.size }

// framed 给控件加白底描边（Fyne 的 Select 默认无边框，放在白色卡片上看不出是下拉框）。
func framed(o fyne.CanvasObject) fyne.CanvasObject {
	bg := canvas.NewRectangle(colorSurface)
	bg.StrokeColor = colorBorderDark
	bg.StrokeWidth = 1
	bg.CornerRadius = theme.Size(theme.SizeNameInputRadius)
	return container.NewStack(bg, o)
}
