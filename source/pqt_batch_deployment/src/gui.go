//go:build !headless

package main

// 图形界面（Fyne）。
//
// 布局（与 Web UI 同一套结构与配色）：
//
//	顶栏：Logo | 标题 + 版本 + 执行中标记 ............ 官网链接 / 帮助
//	控制卡：根目录 [输入框][浏览]；配置 [预设][载入][保存] ... 并行上限 [中止][执行配置]
//	左卡「远程设备」：工具栏 + 概览统计 + 成功/失败比例条 + 设备表 + 执行日志
//	右卡「操作序列」：工具栏 + 操作表 + 编辑区（名称 / 类型分段选择 / 表单 / 完整度）
//	底栏：状态点 + 状态文字
//
// 人机功效上的改进（需求 2 允许"更优方案"）：
//   * 编辑即时生效，不再需要先按"储存该项"——旧版忘按就丢配置。
//   * 操作类型只有一个入口（分段选择器），不再「下拉框 + 标签页」两处同步。
//   * 「完整/不完整」常驻徽标提示，不完整的操作会被明确标出并跳过。
//   * 执行中禁用配置区，执行结束自动恢复；概览统计与比例条实时反映进度。
//   * 删除到空表、未选中即操作等旧版崩溃场景，全部有明确提示而不是闪退。

import (
	"context"
	"errors"
	"fmt"
	"image/color"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

// gui 持有窗口与控件引用。
type gui struct {
	app     fyne.App
	win     fyne.Window
	state   *GUIState
	cancel  context.CancelFunc
	running bool
	mu      sync.Mutex

	// 设备表与日志
	deviceTable *widget.Table
	deviceLog   *logView
	deviceLabel *canvas.Text
	deviceCount *canvas.Text

	// 概览统计
	statTotal, statOK, statFail, statRun *statTile
	ratio                                *ratioBar

	// 操作表与编辑区
	opTable    *widget.Table
	opCount    *canvas.Text
	opName     *widget.Entry
	opType     *segmented
	opForms    [3]fyne.CanvasObject
	opComplete *badge

	cmdEntry    *widget.Entry
	cmdOKCheck  *widget.Entry
	cmdErrCheck *widget.Entry

	upLocal  *widget.Entry
	upRemote *widget.Entry

	downRemote *widget.Entry
	downDir    *widget.Entry
	upCheck    *widget.Select
	downCheck  *widget.Select

	rootEntry *widget.Entry
	presetSel *widget.Select
	maxParSel *widget.Select
	statusLbl *canvas.Text
	statusDot *canvas.Circle
	liveChip  fyne.CanvasObject

	// 执行期间需要整体禁用/恢复的控件。README 承诺「执行期间配置区自动禁用」，
	// 这里落实为显式清单，避免漏掉某个入口。
	lockable  []fyne.Disableable
	runBtn    *widget.Button
	cancelBtn *widget.Button

	// 顶部配置行的按钮，供执行期禁用清单引用。
	loadBtn  *widget.Button
	saveBtn  *widget.Button
	pickRoot *widget.Button

	// selectedOp 当前正在编辑的操作下标；-1 表示无。
	// 旧版直接用 currentRow()，未选中时为 -1 且不判空 -> SIGSEGV。
	selectedOp int
	// editing 为 true 时表示正在把状态写入控件，此时 OnChanged 不应回写状态。
	editing bool
}

func runGUI() int {
	g := &gui{state: NewGUIState(), selectedOp: -1}
	g.app = app.NewWithID("cn.sophon.batchdeployment")
	g.app.Settings().SetTheme(newAppTheme())
	g.win = g.app.NewWindow("批量部署工具 V" + Version)
	g.win.Resize(fyne.NewSize(1360, 880))
	g.win.SetIcon(appIcon())

	g.state.SetRootDir(mustGetwd())
	g.win.SetContent(g.content())
	g.attachCloseGuard()
	// 自动选中第一条操作，使配置区一打开就有内容（旧版同样默认展示首行配置）
	if len(g.state.Ops()) > 0 {
		g.loadOpIntoEditor(0)
	}
	g.refreshTables()
	g.win.ShowAndRun()
	return 0
}

func mustGetwd() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return wd
}

// content 组装主界面。
func (g *gui) content() fyne.CanvasObject {
	split := container.NewHSplit(g.devicePane(), g.opPane())
	split.Offset = 0.47
	body := container.NewBorder(
		g.controls(), nil, nil, nil,
		split,
	)
	return container.NewBorder(
		g.appBar(), // top
		g.footer(), // bottom
		nil, nil,
		container.New(&insetLayout{x: 10, y: 8}, body),
	)
}

// appBar 顶栏：白底 + 底部分隔线。
func (g *gui) appBar() fyne.CanvasObject {
	logo := canvas.NewImageFromResource(logoResource())
	logo.FillMode = canvas.ImageFillContain
	logo.SetMinSize(fyne.NewSize(100, 35))

	vline := canvas.NewRectangle(colorBorder)
	vline.SetMinSize(fyne.NewSize(1, 24))

	title := canvas.NewText("批量部署工具", colorText)
	title.TextStyle = fyne.TextStyle{Bold: true}
	title.TextSize = theme.Size(theme.SizeNameHeadingText)

	ver := newChipBox(newChipText("V"+Version, colorText2), colorSurfaceAlt, colorBorder)
	live := newChipText("执行中", colorBrand)
	live.TextStyle = fyne.TextStyle{Bold: true}
	g.liveChip = newChipBox(live, colorBrandSoft, nil)
	g.liveChip.Hide()

	link := widget.NewHyperlink("sophon.cn", parseURL("https://sophon.cn"))
	help := widget.NewButtonWithIcon("帮助", theme.HelpIcon(), g.showHelp)

	left := container.NewHBox(logo, hSpacer(4), container.NewCenter(vline), hSpacer(4),
		container.NewCenter(title), container.NewCenter(ver), container.NewCenter(g.liveChip))
	right := container.NewHBox(link, help)

	bg := canvas.NewRectangle(colorSurface)
	bar := container.NewStack(bg, container.New(&insetLayout{x: 14, y: 6},
		container.NewBorder(nil, nil, left, right)))
	return container.NewVBox(bar, widget.NewSeparator())
}

// controls 全局配置与执行控制卡片。
func (g *gui) controls() fyne.CanvasObject {
	// 根目录
	g.rootEntry = widget.NewEntry()
	g.rootEntry.SetText(g.state.RootDir())
	g.rootEntry.SetPlaceHolder("文件上传/下载的相对路径基准目录")
	g.rootEntry.OnChanged = func(s string) { g.state.SetRootDir(s) }
	g.pickRoot = widget.NewButtonWithIcon("选择", theme.FolderOpenIcon(), func() {
		dialog.ShowFolderOpen(func(u fyne.ListableURI, err error) {
			if err != nil || u == nil {
				return
			}
			g.rootEntry.SetText(u.Path())
			g.state.SetRootDir(u.Path())
		}, g.win)
	})

	// 预设 / 载入 / 保存 / 并行上限 / 执行
	g.presetSel = widget.NewSelect(BuiltinPresets(), func(s string) {
		// 旧版选中预设即刻载入（currentTextChanged 直连读表）。
		// 这里保留该行为，但改为可撤销的显式「载入」，避免误触清空已配设备。
	})
	if len(g.presetSel.Options) > 0 {
		g.presetSel.SetSelectedIndex(0)
	}
	g.loadBtn = widget.NewButtonWithIcon("载入预设", theme.DownloadIcon(), g.loadConfig)
	g.saveBtn = widget.NewButtonWithIcon("保存配置", theme.DocumentSaveIcon(), g.saveConfig)

	g.runBtn = widget.NewButtonWithIcon("执行配置", theme.MediaPlayIcon(), g.runBatch)
	g.runBtn.Importance = widget.HighImportance
	g.cancelBtn = widget.NewButtonWithIcon("中止", theme.MediaStopIcon(), g.cancelRun)
	g.cancelBtn.Importance = widget.DangerImportance
	g.cancelBtn.Disable() // 未执行时不可点

	g.maxParSel = widget.NewSelect([]string{"200", "100", "50", "20", "2"}, func(s string) {
		if n, err := strconv.Atoi(s); err == nil {
			g.state.SetMaxParallel(n)
		}
	})
	g.maxParSel.SetSelected("100")

	// 各区块在自己的构造函数里登记执行期禁用的控件：不依赖区块的构造顺序
	// （先构造的区块若引用后构造区块的控件，拿到的是 nil，执行时 Disable 即崩溃）。
	g.lockable = append(g.lockable,
		g.rootEntry, g.pickRoot, g.loadBtn, g.saveBtn, g.presetSel, g.maxParSel)

	rowA := container.NewBorder(nil, nil,
		fixedWidth(96, fieldLabel("文件操作根目录")), g.pickRoot, g.rootEntry)
	rowB := container.NewHBox(
		fixedWidth(96, fieldLabel("配置")), fixedWidth(220, framed(g.presetSel)), g.loadBtn, g.saveBtn,
		layout.NewSpacer(),
		fieldLabel("并行上限"), fixedWidth(90, framed(g.maxParSel)),
		hSpacer(6), g.cancelBtn, g.runBtn,
	)
	return container.NewPadded(newCard(nil, container.NewVBox(rowA, rowB)))
}

// fieldLabel 行内字段名：次要色、左对齐、垂直居中；宽度由调用方的 fixedWidth 控制。
func fieldLabel(s string) fyne.CanvasObject {
	t := canvas.NewText(s, colorText2)
	t.TextStyle = fyne.TextStyle{Bold: true}
	t.TextSize = theme.TextSize() - 1
	return container.NewVBox(layout.NewSpacer(), t, layout.NewSpacer())
}

func (g *gui) footer() fyne.CanvasObject {
	g.statusDot = canvas.NewCircle(colorTextMuted)
	dotBox := container.New(&fixedSizeLayout{size: fyne.NewSize(8, 8)}, g.statusDot)
	g.statusLbl = canvas.NewText("就绪", colorText2)
	g.statusLbl.TextSize = theme.Size(theme.SizeNameCaptionText)

	ver := canvas.NewText("V"+Version, colorTextMuted)
	ver.TextSize = theme.Size(theme.SizeNameCaptionText)

	bg := canvas.NewRectangle(colorSurface)
	row := container.NewHBox(container.NewCenter(dotBox), g.statusLbl, layout.NewSpacer(), ver)
	return container.NewVBox(widget.NewSeparator(),
		container.NewStack(bg, container.New(&insetLayout{x: 14, y: 4}, row)))
}

// ---------- 设备面板 ----------

func (g *gui) devicePane() fyne.CanvasObject {
	headers := []string{"#", "IPv4地址", "SSH端口", "用户名", "密码", "执行状态"}
	g.deviceTable = widget.NewTable(
		func() (int, int) {
			return g.state.DeviceCount() + 1, len(headers) // +1 表头
		},
		func() fyne.CanvasObject { return newCellText() },
		func(id widget.TableCellID, o fyne.CanvasObject) {
			l := o.(*cellText)
			l.SetPill(nil)
			if id.Row == 0 {
				l.SetText(headers[id.Col])
				l.SetBold(true)
				l.SetColor(colorText2)
				l.SetRowBackground(colorSurfaceAlt)
				return
			}
			l.SetBold(false)
			l.SetColor(nil)
			devs := g.state.Devices()
			i := id.Row - 1
			if i < 0 || i >= len(devs) {
				l.SetText("")
				l.SetRowBackground(nil)
				return
			}
			if i == g.state.SelectedDevice() {
				l.SetRowBackground(colorBrandSoft)
			} else {
				l.SetRowBackground(nil)
			}
			d := devs[i].Inf
			switch id.Col {
			case 0:
				l.SetText(strconv.Itoa(i + 1))
				l.SetColor(colorTextMuted)
			case 1:
				l.SetText(d.IP)
			case 2:
				l.SetText(strconv.Itoa(d.Port))
			case 3:
				l.SetText(d.Username)
			case 4:
				n := len(d.Password)
				if n > 8 {
					n = 8
				}
				l.SetText(strings.Repeat("*", n))
				l.SetColor(colorTextMuted)
			case 5:
				// 状态列用「色块 + 文字」双编码，不只靠颜色区分。
				fg, bg := statusColors(devs[i].Status)
				l.SetText(statusText(devs[i].Status))
				l.SetColor(fg)
				l.SetBold(devs[i].Status != "")
				l.SetPill(bg)
			}
		},
	)
	for i, w := range []float32{40, 130, 88, 90, 76, 150} {
		g.deviceTable.SetColumnWidth(i, w)
	}

	g.deviceTable.OnSelected = func(id widget.TableCellID) {
		g.deviceTable.UnselectAll()
		if id.Row == 0 {
			return
		}
		g.state.SelectDevice(id.Row - 1)
		g.refreshDeviceLog()
		g.deviceTable.Refresh()
	}

	g.deviceLabel = canvas.NewText("未选中设备", colorTextMuted)
	g.deviceLabel.TextSize = theme.Size(theme.SizeNameCaptionText)
	g.deviceLog = newLogView()
	g.deviceLog.SetPlaceholder("在上方表格中选中一台设备，查看其执行日志")

	addBtn := widget.NewButtonWithIcon("新增", theme.ContentAddIcon(), func() {
		g.state.AppendDevice(RemoteInf{IP: "192.168.1.1", Port: 22, Username: "linaro"})
		g.state.SelectDevice(g.state.DeviceCount() - 1)
		g.refreshTables()
		g.refreshDeviceLog()
		g.editSelectedDevice()
	})
	cloneBtn := widget.NewButtonWithIcon("克隆", theme.ContentCopyIcon(), g.cloneSelectedDevice)
	editBtn := widget.NewButtonWithIcon("编辑", theme.DocumentCreateIcon(), g.editSelectedDevice)
	delBtn := dangerToolButton(g.deleteSelectedDevice)
	g.lockable = append(g.lockable, addBtn, cloneBtn, editBtn, delBtn)

	g.deviceCount = newChipText("0", colorText2)
	head := container.NewBorder(nil, nil,
		cardTitle(theme.ComputerIcon(), "远程设备", g.deviceCount), nil,
		container.NewHBox(layout.NewSpacer(), addBtn, cloneBtn, editBtn, delBtn))

	// 概览统计 + 比例条
	g.statTotal = newStatTile("设备总数", colorBorderDark, colorText)
	g.statOK = newStatTile("成功", colorSuccess, colorSuccess)
	g.statFail = newStatTile("失败", colorDanger, colorDanger)
	g.statRun = newStatTile("进行中/等待", colorRunning, colorRunning)
	g.ratio = newRatioBar()
	stats := container.NewVBox(
		container.NewGridWithColumns(4, g.statTotal.obj, g.statOK.obj, g.statFail.obj, g.statRun.obj),
		g.ratio,
	)

	copyBtn := widget.NewButtonWithIcon("复制", theme.ContentCopyIcon(), func() {
		txt := g.deviceLog.Text()
		if txt == "" {
			showInfo("提示", "没有可复制的日志", g.win)
			return
		}
		g.app.Clipboard().SetContent(txt)
		g.setStatus("日志已复制到剪贴板")
	})
	copyBtn.Importance = widget.LowImportance
	logTitle := canvas.NewText("执行日志", colorText)
	logTitle.TextStyle = fyne.TextStyle{Bold: true}
	logHead := container.NewHBox(
		widget.NewIcon(theme.NewColoredResource(theme.ListIcon(), colorNameMuted)),
		container.NewCenter(logTitle), container.NewCenter(g.deviceLabel),
		layout.NewSpacer(), copyBtn)

	tableBox := tableFrame(g.deviceTable)
	logBox := container.NewBorder(logHead, nil, nil, nil, g.deviceLog.obj)
	split := container.NewVSplit(tableBox, logBox)
	split.Offset = 0.5

	body := container.NewBorder(container.NewVBox(stats, hSpacer(0)), nil, nil, nil, split)
	return container.NewPadded(newCard(head, body))
}

// tableFrame 给表格加白底圆角描边，和卡片内其他元素对齐。
func tableFrame(t *widget.Table) fyne.CanvasObject {
	bg := canvas.NewRectangle(colorSurface)
	bg.StrokeColor = colorBorder
	bg.StrokeWidth = 1
	bg.CornerRadius = 8
	return container.NewStack(bg, container.New(&insetLayout{x: 1, y: 1}, t))
}

// dangerToolButton 工具栏里的删除按钮：红色图标 + 普通底色，
// 醒目但不像实心红按钮那样和主操作抢视线。
func dangerToolButton(onTap func()) *widget.Button {
	b := widget.NewButtonWithIcon("删除",
		theme.NewColoredResource(theme.DeleteIcon(), theme.ColorNameError), onTap)
	return b
}

func (g *gui) refreshDeviceLog() {
	if _, ok := g.state.SelectedDeviceInf(); !ok {
		g.deviceLabel.Text = "未选中设备"
		g.deviceLabel.Refresh()
		g.deviceLog.SetPlaceholder("在上方表格中选中一台设备，查看其执行日志")
		return
	}
	idx := g.state.SelectedDevice()
	d, _ := g.state.SelectedDeviceInf()
	g.deviceLabel.Text = fmt.Sprintf("#%d  %s:%d", idx+1, d.IP, d.Port)
	g.deviceLabel.Refresh()
	g.deviceLog.SetText(g.state.Log(idx))
}

// refreshStats 重算概览统计与比例条。
func (g *gui) refreshStats() {
	if g.statTotal == nil {
		return
	}
	devs := g.state.Devices()
	ok, fail, run := 0, 0, 0
	for _, d := range devs {
		switch classifyStatus(d.Status) {
		case statusOK:
			ok++
		case statusFail:
			fail++
		case statusRun, statusWait:
			run++
		}
	}
	g.statTotal.Set(len(devs))
	g.statOK.Set(ok)
	g.statFail.Set(fail)
	g.statRun.Set(run)
	g.ratio.Set(ok, fail, len(devs))
	g.deviceCount.Text = strconv.Itoa(len(devs))
	g.deviceCount.Refresh()
}

func (g *gui) editSelectedDevice() {
	d, ok := g.state.SelectedDeviceInf()
	if !ok {
		showInfo("提示", "请先在表格中选中一台设备", g.win)
		return
	}
	idx := g.state.SelectedDevice()

	ip := widget.NewEntry()
	ip.SetText(d.IP)
	port := widget.NewEntry()
	port.SetText(strconv.Itoa(d.Port))
	user := widget.NewEntry()
	user.SetText(d.Username)
	pass := widget.NewPasswordEntry()
	pass.SetText(d.Password)

	form := widget.NewForm(
		widget.NewFormItem("IPv4 地址", ip),
		widget.NewFormItem("SSH 端口", port),
		widget.NewFormItem("用户名", user),
		widget.NewFormItem("密码", pass),
	)
	dlg := dialog.NewCustomConfirm(fmt.Sprintf("编辑设备 #%d", idx+1), "保存", "取消",
		fixedWidth(380, form), func(ok bool) {
			if !ok {
				return
			}
			p, err := strconv.Atoi(strings.TrimSpace(port.Text))
			if err != nil || p <= 0 || p > 65535 {
				showError(fmt.Errorf("端口必须是 1-65535 的整数"), g.win)
				return
			}
			if strings.TrimSpace(ip.Text) == "" {
				showError(fmt.Errorf("IP 不能为空"), g.win)
				return
			}
			g.state.UpdateDevice(idx, RemoteInf{
				IP: strings.TrimSpace(ip.Text), Port: p,
				Username: user.Text, Password: pass.Text,
			})
			g.refreshTables()
			g.refreshDeviceLog()
		}, g.win)
	dlg.Show()
	g.win.Canvas().Focus(ip)
}

func (g *gui) deleteSelectedDevice() {
	idx := g.state.SelectedDevice()
	d, ok := g.state.SelectedDeviceInf()
	if idx < 0 || !ok {
		showInfo("提示", "请先在表格中选中一台设备", g.win)
		return
	}
	g.confirmDelete("删除设备", fmt.Sprintf("确认删除第 %d 台设备（%s:%d）？", idx+1, d.IP, d.Port), func() {
		g.state.RemoveDevice(idx)
		g.refreshTables()
		g.refreshDeviceLog()
	})
}

func (g *gui) cloneSelectedDevice() {
	idx := g.state.SelectedDevice()
	if idx < 0 {
		showInfo("提示", "请先在表格中选中一台设备", g.win)
		return
	}
	g.state.CloneDevice(idx)
	g.refreshTables()
}

// ---------- 操作面板 ----------

var opTypeNames = []string{"命令下发", "文件上传", "文件下载"}

func (g *gui) opPane() fyne.CanvasObject {
	headers := []string{"#", "操作名称", "类型", "内容"}
	g.opTable = widget.NewTable(
		func() (int, int) { return len(g.state.Ops()) + 1, len(headers) },
		func() fyne.CanvasObject { return newCellText() },
		func(id widget.TableCellID, o fyne.CanvasObject) {
			l := o.(*cellText)
			l.SetPill(nil)
			if id.Row == 0 {
				l.SetText(headers[id.Col])
				l.SetBold(true)
				l.SetColor(colorText2)
				l.SetRowBackground(colorSurfaceAlt)
				return
			}
			l.SetBold(false)
			l.SetColor(nil)
			ops := g.state.Ops()
			i := id.Row - 1
			if i < 0 || i >= len(ops) {
				l.SetText("")
				l.SetRowBackground(nil)
				return
			}
			if i == g.selectedOp {
				l.SetRowBackground(colorBrandSoft)
			} else {
				l.SetRowBackground(nil)
			}
			op := ops[i].Inf
			switch id.Col {
			case 0:
				l.SetText(strconv.Itoa(i + 1))
				l.SetColor(colorTextMuted)
			case 1:
				if op.IsComplete() {
					l.SetText(op.Name)
				} else {
					// 不完整的操作会被跳过，名称直接用警示色标出。
					name := op.Name
					if strings.TrimSpace(name) == "" {
						name = "(未命名)"
					}
					l.SetText("! " + name)
					l.SetColor(colorWarning)
					l.SetBold(true)
				}
			case 2:
				t := op.Type
				if t < 0 || t > 2 {
					t = 0
				}
				l.SetText(op.TypeName())
				l.SetColor(colorTypeFg[t])
				l.SetBold(true)
				l.SetPill(colorTypeBg[t])
			case 3:
				if !op.IsComplete() {
					l.SetText("配置不完整，执行时将跳过")
					l.SetColor(colorTextMuted)
				} else if op.Type == OpCommand {
					l.SetText(op.CommandStr)
				} else {
					l.SetText(op.TransferFileSourcePath + "  ->  " + op.TransferFileDestinationPath)
				}
			}
		},
	)
	for i, w := range []float32{40, 160, 104, 420} {
		g.opTable.SetColumnWidth(i, w)
	}

	g.opTable.OnSelected = func(id widget.TableCellID) {
		g.opTable.UnselectAll()
		if id.Row == 0 {
			return
		}
		// 执行期间禁止切换正在编辑的操作，避免把执行中的配置改掉。
		if g.isRunning() {
			return
		}
		g.loadOpIntoEditor(id.Row - 1)
		g.refreshOpTableOnly()
	}

	// ---- 编辑区 ----
	g.opName = widget.NewEntry()
	g.opName.SetPlaceHolder("例如 检查系统时间")
	g.opName.OnChanged = func(string) { g.saveOpEditor() }

	g.opType = newSegmented(opTypeNames,
		[]fyne.Resource{theme.ComputerIcon(), theme.UploadIcon(), theme.DownloadIcon()})
	g.opType.OnChange = func(i int) {
		// 切换类型即切换表单页；内容即时写回（与 Web 版一致）。
		g.applyOpType()
		g.saveOpEditor()
	}

	g.cmdEntry = widget.NewMultiLineEntry()
	g.cmdEntry.SetPlaceHolder("需要在设备上执行的 shell 命令")
	g.cmdEntry.SetMinRowsVisible(3)
	g.cmdEntry.OnChanged = func(string) { g.saveOpEditor() }

	g.cmdOKCheck = widget.NewEntry()
	g.cmdOKCheck.SetPlaceHolder("输出中必须包含，为空不检查")
	g.cmdOKCheck.OnChanged = func(string) { g.saveOpEditor() }

	g.cmdErrCheck = widget.NewEntry()
	g.cmdErrCheck.SetPlaceHolder("输出中一旦出现即判失败，为空不检查")
	g.cmdErrCheck.OnChanged = func(string) { g.saveOpEditor() }

	g.opForms[OpCommand] = container.NewVBox(
		widget.NewForm(
			widget.NewFormItem("命令", g.cmdEntry),
			widget.NewFormItem("成功关键字", g.cmdOKCheck),
			widget.NewFormItem("失败关键字", g.cmdErrCheck),
		),
		hintLine("两种情况判失败: 输出命中失败关键字, 或配置了成功关键字但输出里没有。"),
	)

	g.upLocal = widget.NewEntry()
	g.upLocal.SetPlaceHolder("本地文件（相对根目录，或绝对路径）")
	g.upLocal.OnChanged = func(string) { g.saveOpEditor() }
	pickUp := widget.NewButtonWithIcon("选择", theme.FileIcon(), func() {
		dialog.ShowFileOpen(func(r fyne.URIReadCloser, err error) {
			if err != nil || r == nil {
				return
			}
			defer r.Close()
			g.upLocal.SetText(relToRoot(g.state.RootDir(), r.URI().Path()))
		}, g.win)
	})
	g.upRemote = widget.NewEntry()
	g.upRemote.SetPlaceHolder("例如 /tmp/a.bin（以 / 结尾则拼上原文件名）")
	g.upRemote.OnChanged = func(string) { g.saveOpEditor() }

	// 校验方式：旧版固定 MD5，但配置格式本身支持三档（config.go CheckName）。
	// 这里把真实值暴露出来，避免"界面写 MD5、配置是不校验"的静默不一致。
	g.upCheck = widget.NewSelect(checkFileOptions(), func(string) { g.saveOpEditor() })
	g.downCheck = widget.NewSelect(checkFileOptions(), func(string) { g.saveOpEditor() })

	g.opForms[OpUpFile] = container.NewVBox(widget.NewForm(
		widget.NewFormItem("本地文件", container.NewBorder(nil, nil, nil, pickUp, g.upLocal)),
		widget.NewFormItem("远程目标路径", g.upRemote),
		widget.NewFormItem("校验方式", framed(g.upCheck)),
	))

	g.downRemote = widget.NewEntry()
	g.downRemote.SetPlaceHolder("设备上的文件路径")
	g.downRemote.OnChanged = func(string) { g.saveOpEditor() }
	g.downDir = widget.NewEntry()
	g.downDir.SetPlaceHolder("本地目录（相对根目录，或绝对路径）")
	g.downDir.OnChanged = func(string) { g.saveOpEditor() }
	pickDown := widget.NewButtonWithIcon("选择", theme.FolderOpenIcon(), func() {
		dialog.ShowFolderOpen(func(u fyne.ListableURI, err error) {
			if err != nil || u == nil {
				return
			}
			g.downDir.SetText(relToRoot(g.state.RootDir(), u.Path()))
		}, g.win)
	})
	openDown := widget.NewButtonWithIcon("打开", theme.FolderIcon(), func() {
		p := g.downDir.Text
		if !filepath.IsAbs(p) {
			p = filepath.Join(g.state.RootDir(), p)
		}
		if err := openPath(p); err != nil {
			showError(err, g.win)
		}
	})
	openDown.Importance = widget.LowImportance

	g.opForms[OpDownFile] = container.NewVBox(widget.NewForm(
		widget.NewFormItem("远程文件路径", g.downRemote),
		widget.NewFormItem("本地目录", container.NewBorder(nil, nil, nil,
			container.NewHBox(pickDown, openDown), g.downDir)),
		widget.NewFormItem("校验方式", framed(g.downCheck)),
	), hintLine("下载文件名格式: IP_端口_时间戳_原名（重名自动加序号）。"))

	g.opComplete = newBadge()
	g.opComplete.Set(badgeNone, "未选中操作")

	// 「编辑即时生效」已让保存按钮变得多余，但旧版用户习惯按一下才安心；
	// 保留它作为显式确认（不改变语义：内容本来就已经写回了）。
	saveOp := widget.NewButtonWithIcon("确认当前操作", theme.ConfirmIcon(), func() {
		if g.saveOpEditor() {
			g.setStatus("当前操作配置已更新")
		}
	})
	addOp := widget.NewButtonWithIcon("新增", theme.ContentAddIcon(), func() {
		g.state.AppendOp(OperationInf{Name: "新操作", Type: OpCommand, CommandStr: ""})
		g.loadOpIntoEditor(len(g.state.Ops()) - 1)
		g.refreshTables()
		g.win.Canvas().Focus(g.opName)
	})
	cloneOp := widget.NewButtonWithIcon("克隆", theme.ContentCopyIcon(), func() {
		idx := g.selectedOp
		if idx < 0 {
			showInfo("提示", "请先在操作表中选中一行", g.win)
			return
		}
		g.state.CloneOp(idx)
		g.loadOpIntoEditor(idx + 1)
		g.refreshTables()
	})
	delOp := dangerToolButton(func() {
		idx := g.selectedOp
		ops := g.state.Ops()
		if idx < 0 || idx >= len(ops) {
			showInfo("提示", "请先在操作表中选中一行", g.win)
			return
		}
		g.confirmDelete("删除操作", fmt.Sprintf("确认删除操作（%s）？", ops[idx].Inf.Name), func() {
			g.state.RemoveOp(idx)
			g.selectedOp = -1
			// 清空编辑区：否则选中已删除项的内容还留在界面上，
			// 用户继续输入会被 saveOpEditor 静默丢弃（selectedOp<0）。
			g.clearOpEditor()
			g.refreshTables()
		})
	})

	// 执行期间禁用的控件清单（对应 README「执行期间配置区自动禁用」）。
	// 表格不支持 Disable，其交互改由 isRunning() 在回调里拦下。
	g.lockable = append(g.lockable,
		g.opName, g.opType, g.cmdEntry, g.cmdOKCheck, g.cmdErrCheck,
		g.upLocal, g.upRemote, g.downRemote, g.downDir, g.upCheck, g.downCheck,
		pickUp, pickDown, saveOp, addOp, cloneOp, delOp,
	)

	editTitle := canvas.NewText("编辑操作", colorText)
	editTitle.TextStyle = fyne.TextStyle{Bold: true}
	editHint := canvas.NewText("改动即时生效", colorTextMuted)
	editHint.TextSize = theme.Size(theme.SizeNameCaptionText)

	editor := container.NewVBox(
		container.NewHBox(container.NewCenter(editTitle), container.NewCenter(editHint)),
		widget.NewForm(
			widget.NewFormItem("操作名称", g.opName),
			widget.NewFormItem("操作类型", g.opType.obj),
		),
		container.NewStack(g.opForms[0], g.opForms[1], g.opForms[2]),
		container.NewBorder(nil, nil, g.opComplete.box, saveOp),
	)
	g.applyOpType()

	g.opCount = newChipText("0", colorText2)
	hint := canvas.NewText("按顺序在每台设备上执行", colorTextMuted)
	hint.TextSize = theme.Size(theme.SizeNameCaptionText)
	head := container.NewBorder(nil, nil,
		container.NewHBox(cardTitle(theme.ListIcon(), "操作序列", g.opCount), container.NewCenter(hint)),
		nil,
		container.NewHBox(layout.NewSpacer(), addOp, cloneOp, delOp))

	split := container.NewVSplit(tableFrame(g.opTable),
		container.NewVScroll(container.NewVBox(widget.NewSeparator(), editor)))
	split.Offset = 0.24
	return container.NewPadded(newCard(head, split))
}

// hintLine 表单下方的说明文字（小号、次要色，可换行）。
func hintLine(s string) fyne.CanvasObject {
	rt := widget.NewRichText(&widget.TextSegment{Text: s, Style: widget.RichTextStyle{
		ColorName: colorNameMuted, SizeName: theme.SizeNameCaptionText}})
	rt.Wrapping = fyne.TextWrapWord
	return rt
}

func (g *gui) loadOpIntoEditor(i int) {
	ops := g.state.Ops()
	if i < 0 || i >= len(ops) {
		g.selectedOp = -1
		g.opComplete.Set(badgeNone, "未选中操作")
		return
	}
	g.selectedOp = i
	op := ops[i].Inf

	g.editing = true
	defer func() { g.editing = false }()

	g.opName.SetText(op.Name)
	if op.Type >= OpCommand && op.Type <= OpDownFile {
		g.opType.Select(op.Type)
	}
	g.cmdEntry.SetText(op.CommandStr)
	g.cmdOKCheck.SetText(op.CheckSuccessStr)
	g.cmdErrCheck.SetText(op.CheckErrorStr)
	g.upLocal.SetText(op.TransferFileSourcePath)
	g.upRemote.SetText(op.TransferFileDestinationPath)
	g.downRemote.SetText(op.TransferFileSourcePath)
	g.downDir.SetText(op.TransferFileDestinationPath)
	g.upCheck.SetSelected(op.CheckName())
	g.downCheck.SetSelected(op.CheckName())
	g.applyOpType()
	g.updateOpCompleteLabel()
}

// applyOpType 只显示当前操作类型对应的表单。
func (g *gui) applyOpType() {
	sel := g.opType.Selected()
	for i, f := range g.opForms {
		if f == nil {
			continue
		}
		if i == sel {
			f.Show()
		} else {
			f.Hide()
		}
	}
}

// saveOpEditor 把编辑区内容写回状态；返回是否成功。
//
// 这是相对旧版的关键改进：旧版必须按"储存该项"才写回，忘了就丢配置。
func (g *gui) saveOpEditor() bool {
	if g.editing || g.selectedOp < 0 {
		return false
	}
	ops := g.state.Ops()
	if g.selectedOp >= len(ops) {
		return false
	}
	op := ops[g.selectedOp].Inf
	op.Name = g.opName.Text

	switch g.opType.Selected() {
	case OpCommand:
		op.Type = OpCommand
		op.CommandStr = g.cmdEntry.Text
		op.CheckSuccessStr = g.cmdOKCheck.Text
		op.CheckErrorStr = g.cmdErrCheck.Text
	case OpUpFile:
		op.Type = OpUpFile
		op.TransferFileSourcePath = g.upLocal.Text
		op.TransferFileDestinationPath = g.upRemote.Text
		op.CheckFile = parseCheckFile(g.upCheck.Selected)
	case OpDownFile:
		op.Type = OpDownFile
		op.TransferFileSourcePath = g.downRemote.Text
		op.TransferFileDestinationPath = g.downDir.Text
		op.CheckFile = parseCheckFile(g.downCheck.Selected)
	}

	g.state.UpdateOp(g.selectedOp, op)
	g.updateOpCompleteLabel()
	g.refreshOpTableOnly()
	return true
}

func (g *gui) updateOpCompleteLabel() {
	ops := g.state.Ops()
	if g.selectedOp < 0 || g.selectedOp >= len(ops) {
		g.opComplete.Set(badgeNone, "未选中操作")
		return
	}
	op := ops[g.selectedOp].Inf
	if op.IsComplete() {
		g.opComplete.Set(badgeOK, "配置完整，可以执行")
		return
	}
	g.opComplete.Set(badgeWarn, "不完整，执行时将跳过 - "+op.Validate().Error())
}

func (g *gui) refreshOpTableOnly() {
	if g.opTable != nil {
		g.opTable.Refresh()
	}
	if g.opCount != nil {
		g.opCount.Text = strconv.Itoa(len(g.state.Ops()))
		g.opCount.Refresh()
	}
}

func (g *gui) refreshTables() {
	if g.deviceTable != nil {
		g.deviceTable.Refresh()
	}
	g.refreshOpTableOnly()
	g.refreshStats()
}

// ---------- 载入 / 保存 / 执行 ----------

func (g *gui) loadConfig() {
	preset := g.presetSel.Selected
	if preset == "" {
		showInfo("提示", "请先选择一个内置预设", g.win)
		return
	}
	cfg, err := LoadBuiltinPreset(preset)
	if err != nil {
		showError(err, g.win)
		return
	}
	g.state.LoadConfig(cfg)
	g.selectedOp = -1
	g.clearOpEditor()
	if len(g.state.Ops()) > 0 {
		g.loadOpIntoEditor(0)
	}
	g.refreshTables()
	g.refreshDeviceLog()
	g.setStatus(fmt.Sprintf("已载入预设 %s:%d 台设备，%d 条操作",
		preset, len(cfg.RemoteInf), len(cfg.OperationInf)))
}

func (g *gui) saveConfig() {
	dialog.ShowFileSave(func(w fyne.URIWriteCloser, err error) {
		if err != nil || w == nil {
			return
		}
		path := w.URI().Path()
		w.Close()
		cfg := g.state.ToConfig()
		if err := SaveConfig(path, cfg); err != nil {
			showError(err, g.win)
			return
		}
		g.setStatus("已保存到 " + path)
	}, g.win)
}

func (g *gui) runBatch() {
	g.mu.Lock()
	if g.running {
		g.mu.Unlock()
		showInfo("提示", "当前已有任务在执行", g.win)
		return
	}
	g.mu.Unlock()

	cfg := g.state.ToConfig()
	// GUI 侧只校验设备与「至少有一条完整操作」。不完整的操作不算错误——
	// 它们会明确列出并被跳过（旧版同样是这个语义）。
	if err := cfg.ValidateDevices(); err != nil {
		showError(fmt.Errorf("配置无效:%w", err), g.win)
		return
	}
	if len(cfg.CompleteOperations()) == 0 {
		showError(errors.New("没有配置完整的操作可执行，请先补全操作配置"), g.win)
		return
	}

	rootDir := g.state.RootDir()
	if st, err := os.Stat(rootDir); err != nil || !st.IsDir() {
		showError(fmt.Errorf("根目录不存在或不是目录:%s", rootDir), g.win)
		return
	}

	g.state.ClearLogs()
	for i := range cfg.RemoteInf {
		g.state.SetDeviceStatus(i, "等待中")
	}
	g.refreshTables()
	g.refreshDeviceLog()

	ctx, cancel := context.WithCancel(context.Background())
	g.mu.Lock()
	g.running = true
	g.cancel = cancel
	g.mu.Unlock()
	g.setRunningUI(true)

	skipped := len(cfg.OperationInf) - len(cfg.CompleteOperations())
	msg := fmt.Sprintf("开始执行:%d 台设备 x %d 条操作，并行上限 %d",
		len(cfg.RemoteInf), len(cfg.CompleteOperations()), g.state.MaxParallel())
	if skipped > 0 {
		msg += fmt.Sprintf("（%d 条不完整操作已跳过）", skipped)
	}
	g.setStatusKind(msg, colorRunning)

	cmdTimeout, xferTimeout := cfg.Timeouts()
	exec := &Executor{
		RootDir:         rootDir,
		MaxParallel:     g.state.MaxParallel(),
		CommandTimeout:  cmdTimeout,
		TransferTimeout: xferTimeout,
		Emit: func(ev StepEvent) {
			// Executor 的回调来自多个 goroutine，统一转回 UI 线程更新控件。
			fyne.Do(func() { g.onEvent(ev) })
		},
	}

	go func() {
		results := exec.Run(ctx, cfg)
		fyne.Do(func() {
			g.mu.Lock()
			g.running = false
			g.cancel = nil
			g.mu.Unlock()
			g.setRunningUI(false)

			ok, failed := 0, 0
			for _, r := range results {
				if r.OK {
					ok++
				} else {
					failed++
				}
			}
			g.refreshTables()
			summary := fmt.Sprintf("执行结束:成功 %d，失败 %d", ok, failed)
			if ctx.Err() != nil {
				summary = fmt.Sprintf("执行已中止:成功 %d，失败/未完成 %d", ok, failed)
			}
			if failed > 0 || ctx.Err() != nil {
				g.setStatusKind(summary, colorDanger)
				showInfo("执行结束", summary+"\n\n失败设备可在左侧选中查看原因。", g.win)
			} else {
				g.setStatusKind(summary, colorSuccess)
				showInfo("执行结束", summary, g.win)
			}
		})
	}()
}

// cancelRun 中止当前执行。取消信号会关闭底层 SSH 连接，
// 使阻塞中的命令与传输立即返回，而不是等超时。
func (g *gui) cancelRun() {
	g.mu.Lock()
	cancel := g.cancel
	running := g.running
	g.mu.Unlock()
	if !running || cancel == nil {
		return
	}
	showConfirm("中止执行", "确认中止当前批量执行？\n已完成的设备结果会保留。", func() {
		cancel()
		g.setStatusKind("正在中止…", colorRunning)
	}, g.win)
}

// isRunning 报告是否有批量任务在执行中。
func (g *gui) isRunning() bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.running
}

// setRunningUI 执行期间锁定配置区，结束后恢复。
func (g *gui) setRunningUI(running bool) {
	for _, c := range g.lockable {
		if c == nil {
			continue
		}
		if running {
			c.Disable()
		} else {
			c.Enable()
		}
	}
	if running {
		g.runBtn.SetText("执行中…")
		g.runBtn.SetIcon(theme.ViewRefreshIcon())
		g.runBtn.Disable()
		g.cancelBtn.Enable()
		g.liveChip.Show()
	} else {
		g.runBtn.SetText("执行配置")
		g.runBtn.SetIcon(theme.MediaPlayIcon())
		g.runBtn.Enable()
		g.cancelBtn.Disable()
		g.liveChip.Hide()
	}
}

// onEvent 在 UI 线程处理一条执行事件。
func (g *gui) onEvent(ev StepEvent) {
	if ev.Log != "" {
		g.state.AppendLog(ev.DeviceIndex, ev.Log+"\n")
	}
	if ev.Err != nil {
		// 失败事件的 Log 里已经带了同一句原因（见 Executor.Run），
		// 这里只在没有 Log 时补一条，避免日志里同一原因出现两遍。
		if ev.Log == "" {
			g.state.AppendLog(ev.DeviceIndex, "错误: "+ev.Err.Error()+"\n")
		}
		g.state.SetDeviceStatus(ev.DeviceIndex, "失败/"+ev.Err.Error())
	} else if ev.Done {
		// 结果以 Done 事件携带的 OK 为准，避免"连接失败却显示成功"。
		if ev.OK {
			g.state.SetDeviceStatus(ev.DeviceIndex, "成功")
		} else {
			g.state.SetDeviceStatus(ev.DeviceIndex, "失败")
		}
	} else if ev.Stage != "" {
		g.state.SetDeviceStatus(ev.DeviceIndex, ev.Stage)
	}
	g.refreshTables()
	if g.state.SelectedDevice() == ev.DeviceIndex {
		g.refreshDeviceLog()
	}
}

func (g *gui) setStatus(s string) {
	g.setStatusKind(s, colorTextMuted)
}

// setStatusKind 更新底栏状态文字与状态点颜色。
func (g *gui) setStatusKind(s string, dot color.Color) {
	if g.statusLbl == nil {
		return
	}
	g.statusLbl.Text = s
	g.statusLbl.Refresh()
	g.statusDot.FillColor = dot
	g.statusDot.Refresh()
}

func (g *gui) confirmDelete(title, msg string, onYes func()) {
	showConfirm(title, msg, onYes, g.win)
}

// helpText 帮助文案。以 # 开头的行渲染为小标题，其余每行一段。
const helpText = `批量部署工具 使用说明
# 1. 文件操作根目录
上传/下载的相对路径都以此目录为基准。
# 2. 远程设备
表格中每行一台设备，填写 IPv4 地址、SSH 端口、用户名、密码。
选中一行后可（克隆 / 编辑 / 删除）;（新增）追加一行并打开编辑框。
# 3. 操作序列
操作分三类，按表格顺序在每台设备上依次执行:
命令下发 —— 在每台设备上执行同一条命令，可配置成功/失败关键字。
文件上传 —— 本地文件上传到设备，可选 MD5 / 文件大小校验。
文件下载 —— 设备上的文件下载到本地目录，可选校验。
选中操作行后在下方编辑，改动即时生效;不完整的操作会标出并在执行时跳过。
# 4. 载入 / 保存配置
可从内置预设载入，也可保存为 JSON 复用。配置文件格式与旧版完全兼容。
# 5. 执行
设置并行上限后点（执行配置）;执行过程中配置区不可编辑，可随时点（中止）。
概览统计与进度条实时显示 成功 / 失败 / 进行中 的设备数;选中设备可查看其日志。
# 6. 命令行模式
qt_batch_deployment [根目录] [配置文件路径] [最大并行数]
qt_batch_deployment --web [--listen 地址:端口]   启动 Web 界面
不带参数启动图形界面。退出码:0 全部成功，1 有设备失败，2 参数或配置错误。`

func (g *gui) showHelp() {
	// 转成 Markdown：标题行 -> 三级标题，其余每行一段（不用列表：项目符号「•」不在内嵌字体里）。
	var md strings.Builder
	for i, ln := range strings.Split(helpText, "\n") {
		switch {
		case i == 0:
			continue // 标题由对话框标题栏显示
		case strings.HasPrefix(ln, "# "):
			md.WriteString("### " + strings.TrimPrefix(ln, "# ") + "\n\n")
		default:
			md.WriteString(ln + "\n\n")
		}
	}
	rt := widget.NewRichTextFromMarkdown(md.String())
	rt.Wrapping = fyne.TextWrapWord
	sc := container.NewVScroll(rt)
	sc.SetMinSize(fyne.NewSize(620, 480))
	dialog.NewCustom("使用说明", "知道了", sc, g.win).Show()
}

// relToRoot 把绝对路径转成相对根目录的路径，便于配置跨机器复用。
func relToRoot(root, p string) string {
	if root == "" {
		return p
	}
	rel, err := filepath.Rel(root, p)
	if err != nil || strings.HasPrefix(rel, "..") {
		return p
	}
	return rel
}

// clearOpEditor 清空操作编辑区并更新完整度提示。
// 选中项被删除后必须调用，否则残留的控件内容会让用户以为还在编辑它。
func (g *gui) clearOpEditor() {
	g.editing = true
	defer func() { g.editing = false }()

	g.opName.SetText("")
	g.cmdEntry.SetText("")
	g.cmdOKCheck.SetText("")
	g.cmdErrCheck.SetText("")
	g.upLocal.SetText("")
	g.upRemote.SetText("")
	g.downRemote.SetText("")
	g.downDir.SetText("")
	g.opComplete.Set(badgeNone, "未选中操作")
}

// attachCloseGuard 让「执行中关闭窗口」先取消任务再退出。
//
// 不做的话 ShowAndRun 返回后 main 立刻 os.Exit(0)，正在上传/下载的文件会被
// 硬生生截断——远端留下半截镜像、本地留下残缺下载文件，而这类文件后续
// 可能被直接使用。
func (g *gui) attachCloseGuard() {
	g.win.SetCloseIntercept(func() {
		if !g.isRunning() {
			g.win.Close()
			return
		}
		showConfirm("正在执行",
			"当前仍有批量任务在执行，关闭窗口会中止它。\n已完成的设备结果会保留，进行中的传输会被中断。",
			func() {
				g.mu.Lock()
				cancel := g.cancel
				g.mu.Unlock()
				if cancel != nil {
					cancel()
				}
				g.win.Close()
			}, g.win)
	})
}
