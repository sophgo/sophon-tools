package main

// 图形界面（Fyne）。
//
// 布局与旧版 mainwindow.ui 对齐：
//
//	顶部：Logo + 标题 + 帮助
//	配置行 A：根目录 [输入框] [选择根目录]
//	配置行 B：内置预设 [下拉] [载入] [保存配置] [执行配置] [并行上限 下拉]
//	中部左：远程设备信息配置（表格 + 右键克隆/删除 + 选中设备日志）
//	中部右：操作信息配置（表格 + 右键克隆/删除 + 三段式配置区）
//
// 人机功效上的改进（需求 2 允许"更优方案"）：
//   * 编辑即时生效，不再需要先按"储存该项"——旧版忘按就丢配置。
//   * 表格下方常驻"完整/不完整"标记，不完整的操作会被明确标出并跳过。
//   * 执行中禁用配置区，执行结束自动恢复；旧版靠 enableEdit 手工翻转容易漏。
//   * 删除到空表、未选中即操作等旧版崩溃场景，全部有明确提示而不是闪退。

import (
	"context"
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
	app    fyne.App
	win    fyne.Window
	state  *GUIState
	cancel context.CancelFunc
	running bool
	mu     sync.Mutex

	// 设备表
	deviceTable *widget.Table
	deviceLog   *widget.Entry
	deviceLabel *widget.Label

	// 操作表与配置区
	opTable     *widget.Table
	opName      *widget.Entry
	opType      *widget.Select
	opComplete  *widget.Label

	cmdEntry    *widget.Entry
	cmdOKCheck  *widget.Entry
	cmdErrCheck *widget.Entry

	upLocal  *widget.Entry
	upRemote *widget.Entry

	downRemote *widget.Entry
	downDir    *widget.Entry

	rootEntry  *widget.Entry
	presetSel  *widget.Select
	maxParSel  *widget.Select
	statusLbl  *widget.Label
	opTabs     *container.AppTabs

	// selectedOp 当前正在编辑的操作下标；-1 表示无。
	// 旧版直接用 currentRow()，未选中时为 -1 且不判空 -> SIGSEGV。
	selectedOp int
	// editing 为 true 时表示正在把状态写入控件，此时 OnChanged 不应回写状态。
	editing bool
}

func runGUI() int {
	g := &gui{state: NewGUIState()}
	g.app = app.NewWithID("cn.sophon.batchdeployment")
	g.win = g.app.NewWindow("批量部署工具 V" + Version)
	g.win.Resize(fyne.NewSize(1240, 800))

	g.state.SetRootDir(mustGetwd())
	g.win.SetContent(g.content())
	// 自动选中第一条操作，使配置区一打开就有内容（旧版同样默认展示首行配置）
	if len(g.state.Ops()) > 0 {
		g.loadOpIntoEditor(0)
	}
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
	return container.NewBorder(
		g.header(),   // top
		g.footer(),   // bottom
		nil, nil,
		container.NewHSplit(g.devicePane(), g.opPane()),
	)
}

func (g *gui) header() fyne.CanvasObject {
	title := widget.NewLabelWithStyle("批量部署工具 V"+Version,
		fyne.TextAlignLeading, fyne.TextStyle{Bold: true})

	link := widget.NewHyperlink("https://sophon.cn", parseURL("https://sophon.cn"))

	logo := canvas.NewImageFromResource(logoResource())
	logo.FillMode = canvas.ImageFillContain
	logo.SetMinSize(fyne.NewSize(148, 52))

	help := widget.NewButtonWithIcon("帮助", theme.HelpIcon(), g.showHelp)

	// 配置行 A：根目录
	g.rootEntry = widget.NewEntry()
	g.rootEntry.SetText(g.state.RootDir())
	g.rootEntry.OnChanged = func(s string) { g.state.SetRootDir(s) }
	pickRoot := widget.NewButton("选择根目录", func() {
		dialog.ShowFolderOpen(func(u fyne.ListableURI, err error) {
			if err != nil || u == nil {
				return
			}
			g.rootEntry.SetText(u.Path())
			g.state.SetRootDir(u.Path())
		}, g.win)
	})

	// 配置行 B：预设 / 载入 / 保存 / 执行 / 并行上限
	g.presetSel = widget.NewSelect(BuiltinPresets(), nil)
	if len(g.presetSel.Options) > 0 {
		g.presetSel.SetSelectedIndex(0)
	}
	loadBtn := widget.NewButton("载入配置文件", g.loadConfig)
	saveBtn := widget.NewButton("保存配置文件", g.saveConfig)
	runBtn := widget.NewButtonWithIcon("执行配置", theme.MediaPlayIcon(), g.runBatch)
	runBtn.Importance = widget.HighImportance

	g.maxParSel = widget.NewSelect([]string{"200", "100", "50", "20", "2"}, func(s string) {
		if n, err := strconv.Atoi(s); err == nil {
			g.state.SetMaxParallel(n)
		}
	})
	g.maxParSel.SetSelected("100")

	rowA := container.NewBorder(nil, nil,
		widget.NewLabel("选择文件操作根目录："),
		pickRoot,
		g.rootEntry,
	)
	rowB := container.NewHBox(
		widget.NewLabel("选择内置预设文件："), g.presetSel,
		loadBtn, saveBtn,
		layout.NewSpacer(),
		widget.NewLabel("并行上限："), g.maxParSel,
		runBtn,
	)

	top := container.NewVBox(
		container.NewBorder(nil, nil,
			container.NewHBox(logo, title, link),
			help,
		),
		widget.NewSeparator(),
		rowA,
		rowB,
		widget.NewSeparator(),
	)
	return top
}

func (g *gui) footer() fyne.CanvasObject {
	g.statusLbl = widget.NewLabel("就绪")
	return container.NewVBox(widget.NewSeparator(), g.statusLbl)
}

// ---------- 设备面板 ----------

func (g *gui) devicePane() fyne.CanvasObject {
	g.deviceTable = widget.NewTable(
		func() (int, int) {
			return g.state.DeviceCount() + 1, 5 // +1 表头
		},
		func() fyne.CanvasObject {
			l := widget.NewLabel("")
			l.Truncation = fyne.TextTruncateEllipsis
			return l
		},
		func(id widget.TableCellID, o fyne.CanvasObject) {
			l := o.(*widget.Label)
			if id.Row == 0 {
				headers := []string{"IPv4地址", "SSH端口", "用户名", "密码", "执行状态"}
				l.SetText(headers[id.Col])
				l.TextStyle = fyne.TextStyle{Bold: true}
				return
			}
			l.TextStyle = fyne.TextStyle{}
			devs := g.state.Devices()
			i := id.Row - 1
			if i < 0 || i >= len(devs) {
				l.SetText("")
				return
			}
			d := devs[i].Inf
			switch id.Col {
			case 0:
				l.SetText(d.IP)
			case 1:
				l.SetText(strconv.Itoa(d.Port))
			case 2:
				l.SetText(d.Username)
			case 3:
				l.SetText(strings.Repeat("•", len(d.Password)))
			case 4:
				l.SetText(devs[i].Status)
			}
		},
	)
	g.deviceTable.SetColumnWidth(0, 150)
	g.deviceTable.SetColumnWidth(1, 80)
	g.deviceTable.SetColumnWidth(2, 110)
	g.deviceTable.SetColumnWidth(3, 100)
	g.deviceTable.SetColumnWidth(4, 190)

	g.deviceTable.OnSelected = func(id widget.TableCellID) {
		if id.Row == 0 {
			g.deviceTable.UnselectAll()
			return
		}
		g.state.SelectDevice(id.Row - 1)
		g.refreshDeviceLog()
		g.deviceTable.UnselectAll()
	}

	g.deviceLabel = widget.NewLabel("设备详情（未选中）")
	g.deviceLog = widget.NewMultiLineEntry()
	g.deviceLog.Wrapping = fyne.TextWrapWord
	g.deviceLog.SetPlaceHolder("选中左侧设备行查看其执行日志")

	editBtn := widget.NewButton("编辑选中设备", g.editSelectedDevice)
	delBtn := widget.NewButton("删除选中设备", g.deleteSelectedDevice)
	cloneBtn := widget.NewButton("克隆选中设备", g.cloneSelectedDevice)
	addBtn := widget.NewButtonWithIcon("新增设备", theme.ContentAddIcon(), func() {
		g.state.AppendDevice(RemoteInf{IP: "192.168.1.1", Port: 22, Username: "linaro"})
		g.refreshTables()
	})

	toolbar := container.NewHBox(addBtn, cloneBtn, editBtn, delBtn)

	box := container.NewBorder(
		container.NewVBox(
			widget.NewLabelWithStyle("远程设备信息配置",
				fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
			toolbar,
		),
		nil, nil, nil,
		container.NewVSplit(
			container.NewStack(canvas.NewRectangle(color.NRGBA{0, 0, 0, 0}), g.deviceTable),
			container.NewBorder(
				container.NewVBox(widget.NewSeparator(), g.deviceLabel),
				nil, nil, nil, g.deviceLog),
		),
	)
	return container.NewPadded(box)
}

func (g *gui) refreshDeviceLog() {
	if _, ok := g.state.SelectedDeviceInf(); !ok {
		g.deviceLabel.SetText("设备详情（未选中）")
		g.deviceLog.SetText("")
		return
	}
	idx := g.state.SelectedDevice()
	d, _ := g.state.SelectedDeviceInf()
	g.deviceLabel.SetText(fmt.Sprintf("设备%d  %s:%d", idx+1, d.IP, d.Port))
	g.deviceLog.SetText(g.state.Log(idx))
}

func (g *gui) editSelectedDevice() {
	d, ok := g.state.SelectedDeviceInf()
	if !ok {
		dialog.ShowInformation("提示", "请先在表格中选中一台设备", g.win)
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
	dialog.ShowCustomConfirm("编辑设备", "保存", "取消", form, func(ok bool) {
		if !ok {
			return
		}
		p, err := strconv.Atoi(strings.TrimSpace(port.Text))
		if err != nil || p <= 0 || p > 65535 {
			dialog.ShowError(fmt.Errorf("端口必须是 1-65535 的整数"), g.win)
			return
		}
		if strings.TrimSpace(ip.Text) == "" {
			dialog.ShowError(fmt.Errorf("IP 不能为空"), g.win)
			return
		}
		g.state.UpdateDevice(idx, RemoteInf{
			IP: strings.TrimSpace(ip.Text), Port: p,
			Username: user.Text, Password: pass.Text,
		})
		g.refreshTables()
	}, g.win)
}

func (g *gui) deleteSelectedDevice() {
	idx := g.state.SelectedDevice()
	if idx < 0 {
		dialog.ShowInformation("提示", "请先在表格中选中一台设备", g.win)
		return
	}
	g.confirmDelete("删除设备", fmt.Sprintf("确认删除第 %d 台设备？", idx+1), func() {
		g.state.RemoveDevice(idx)
		g.refreshTables()
		g.refreshDeviceLog()
	})
}

func (g *gui) cloneSelectedDevice() {
	idx := g.state.SelectedDevice()
	if idx < 0 {
		dialog.ShowInformation("提示", "请先在表格中选中一台设备", g.win)
		return
	}
	g.state.CloneDevice(idx)
	g.refreshTables()
}

// ---------- 操作面板 ----------

func (g *gui) opPane() fyne.CanvasObject {
	g.opTable = widget.NewTable(
		func() (int, int) { return len(g.state.Ops()) + 1, 3 },
		func() fyne.CanvasObject {
			l := widget.NewLabel("")
			l.Truncation = fyne.TextTruncateEllipsis
			return l
		},
		func(id widget.TableCellID, o fyne.CanvasObject) {
			l := o.(*widget.Label)
			if id.Row == 0 {
				h := []string{"操作名称", "操作类型", "内容信息"}[id.Col]
				l.SetText(h)
				l.TextStyle = fyne.TextStyle{Bold: true}
				return
			}
			l.TextStyle = fyne.TextStyle{}
			ops := g.state.Ops()
			i := id.Row - 1
			if i < 0 || i >= len(ops) {
				l.SetText("")
				return
			}
			op := ops[i].Inf
			switch id.Col {
			case 0:
				name := op.Name
				if !op.IsComplete() {
					name = "⚠ " + name + "（不完整）"
				}
				l.SetText(name)
			case 1:
				l.SetText(op.TypeName())
			case 2:
				if op.Type == OpCommand {
					l.SetText(op.CommandStr)
				} else {
					l.SetText(op.TransferFileSourcePath + " → " + op.TransferFileDestinationPath)
				}
			}
		},
	)
	g.opTable.SetColumnWidth(0, 200)
	g.opTable.SetColumnWidth(1, 120)
	g.opTable.SetColumnWidth(2, 380)

	g.opTable.OnSelected = func(id widget.TableCellID) {
		if id.Row == 0 {
			g.opTable.UnselectAll()
			return
		}
		g.loadOpIntoEditor(id.Row - 1)
		g.opTable.UnselectAll()
	}

	// 配置区
	g.opName = widget.NewEntry()
	g.opName.OnChanged = func(string) { g.saveOpEditor() }

	g.opType = widget.NewSelect([]string{"下发命令", "上传文件", "下载文件"}, func(string) {
		g.applyOpType()
		g.saveOpEditor()
	})

	g.cmdEntry = widget.NewMultiLineEntry()
	g.cmdEntry.SetPlaceHolder("需要执行的命令")
	g.cmdEntry.OnChanged = func(string) { g.saveOpEditor() }

	g.cmdOKCheck = widget.NewEntry()
	g.cmdOKCheck.SetPlaceHolder("判断执行是否成功，为空不检查")
	g.cmdOKCheck.OnChanged = func(string) { g.saveOpEditor() }

	g.cmdErrCheck = widget.NewEntry()
	g.cmdErrCheck.SetPlaceHolder("判断执行是否失败，为空不检查")
	g.cmdErrCheck.OnChanged = func(string) { g.saveOpEditor() }

	cmdTab := container.NewVBox(
		widget.NewForm(
			widget.NewFormItem("命令", g.cmdEntry),
			widget.NewFormItem("执行成功关键字", g.cmdOKCheck),
			widget.NewFormItem("执行失败关键字", g.cmdErrCheck),
		),
	)

	g.upLocal = widget.NewEntry()
	g.upLocal.SetPlaceHolder("本地文件（相对根目录）")
	g.upLocal.OnChanged = func(string) { g.saveOpEditor() }
	pickUp := widget.NewButton("选择文件", func() {
		dialog.ShowFileOpen(func(r fyne.URIReadCloser, err error) {
			if err != nil || r == nil {
				return
			}
			defer r.Close()
			g.upLocal.SetText(relToRoot(g.state.RootDir(), r.URI().Path()))
		}, g.win)
	})
	g.upRemote = widget.NewEntry()
	g.upRemote.SetPlaceHolder("远程目标路径，例如 /tmp/a.bin")
	g.upRemote.OnChanged = func(string) { g.saveOpEditor() }

	upTab := container.NewVBox(widget.NewForm(
		widget.NewFormItem("选择本地文件", container.NewBorder(nil, nil, nil, pickUp, g.upLocal)),
		widget.NewFormItem("远程目标路径", g.upRemote),
		widget.NewFormItem("校验方式", widget.NewLabel("MD5 校验值（上传后自动校验）")),
	))

	g.downRemote = widget.NewEntry()
	g.downRemote.SetPlaceHolder("远程文件路径")
	g.downRemote.OnChanged = func(string) { g.saveOpEditor() }
	g.downDir = widget.NewEntry()
	g.downDir.SetPlaceHolder("本地目录（相对根目录）")
	g.downDir.OnChanged = func(string) { g.saveOpEditor() }
	pickDown := widget.NewButton("选择目录", func() {
		dialog.ShowFolderOpen(func(u fyne.ListableURI, err error) {
			if err != nil || u == nil {
				return
			}
			g.downDir.SetText(relToRoot(g.state.RootDir(), u.Path()))
		}, g.win)
	})
	openDown := widget.NewButton("打开下载目录", func() {
		p := g.downDir.Text
		if !filepath.IsAbs(p) {
			p = filepath.Join(g.state.RootDir(), p)
		}
		if err := openPath(p); err != nil {
			dialog.ShowError(err, g.win)
		}
	})

	downTab := container.NewVBox(widget.NewForm(
		widget.NewFormItem("远程文件路径", g.downRemote),
		widget.NewFormItem("本地目录", container.NewBorder(nil, nil, nil, pickDown, g.downDir)),
		widget.NewFormItem("校验方式", widget.NewLabel("MD5 校验值（下载后自动校验）")),
	), openDown)

	g.opTabs = container.NewAppTabs(
		container.NewTabItem("命令下发", cmdTab),
		container.NewTabItem("文件上传", upTab),
		container.NewTabItem("文件下载", downTab),
	)

	g.opComplete = widget.NewLabel("该项当前完整度：未选中")

	saveOp := widget.NewButton("保存当前操作", func() {
		if g.saveOpEditor() {
			dialog.ShowInformation("已保存", "当前操作配置已更新", g.win)
		}
	})
	addOp := widget.NewButtonWithIcon("新增操作", theme.ContentAddIcon(), func() {
		g.state.AppendOp(OperationInf{Name: "新操作", Type: OpCommand, CommandStr: ""})
		g.refreshTables()
	})
	delOp := widget.NewButton("删除选中操作", func() {
		idx := g.selectedOp
		if idx < 0 {
			dialog.ShowInformation("提示", "请先在操作表中选中一行", g.win)
			return
		}
		g.confirmDelete("删除操作", "确认删除该操作？", func() {
			g.state.RemoveOp(idx)
			g.selectedOp = -1
			g.refreshTables()
		})
	})

	editor := container.NewBorder(
		container.NewVBox(
			widget.NewForm(widget.NewFormItem("操作名称", g.opName)),
			widget.NewSeparator(),
			widget.NewSeparator(),
			g.opTabs,
			widget.NewSeparator(),
			g.opComplete,
			container.NewHBox(saveOp, addOp, delOp),
		),
		nil, nil, nil,
		widget.NewLabel(""),
	)

	box := container.NewBorder(
		widget.NewLabelWithStyle("操作信息配置",
			fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		nil, nil, nil,
		container.NewVSplit(
			container.NewStack(canvas.NewRectangle(color.NRGBA{0, 0, 0, 0}), g.opTable),
			editor,
		),
	)
	return container.NewPadded(box)
}

func (g *gui) loadOpIntoEditor(i int) {
	ops := g.state.Ops()
	if i < 0 || i >= len(ops) {
		g.selectedOp = -1
		g.opComplete.SetText("该项当前完整度：未选中")
		return
	}
	g.selectedOp = i
	op := ops[i].Inf

	g.editing = true
	defer func() { g.editing = false }()

	g.opName.SetText(op.Name)
	switch op.Type {
	case OpCommand:
		g.opType.SetSelectedIndex(0)
	case OpUpFile:
		g.opType.SetSelectedIndex(1)
	case OpDownFile:
		g.opType.SetSelectedIndex(2)
	}
	g.cmdEntry.SetText(op.CommandStr)
	g.cmdOKCheck.SetText(op.CheckSuccessStr)
	g.cmdErrCheck.SetText(op.CheckErrorStr)
	g.upLocal.SetText(op.TransferFileSourcePath)
	g.upRemote.SetText(op.TransferFileDestinationPath)
	g.downRemote.SetText(op.TransferFileSourcePath)
	g.downDir.SetText(op.TransferFileDestinationPath)
	g.applyOpType()
	g.updateOpCompleteLabel()
}

// applyOpType 让「操作类型」下拉与下方标签页保持同步。
func (g *gui) applyOpType() {
	switch g.opType.Selected {
	case "下发命令":
		g.opTabs.SelectIndex(0)
	case "上传文件":
		g.opTabs.SelectIndex(1)
	case "下载文件":
		g.opTabs.SelectIndex(2)
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

	switch g.opType.Selected {
	case "下发命令":
		op.Type = OpCommand
		op.CommandStr = g.cmdEntry.Text
		op.CheckSuccessStr = g.cmdOKCheck.Text
		op.CheckErrorStr = g.cmdErrCheck.Text
	case "上传文件":
		op.Type = OpUpFile
		op.TransferFileSourcePath = g.upLocal.Text
		op.TransferFileDestinationPath = g.upRemote.Text
		op.CheckFile = CheckMD5
	case "下载文件":
		op.Type = OpDownFile
		op.TransferFileSourcePath = g.downRemote.Text
		op.TransferFileDestinationPath = g.downDir.Text
		op.CheckFile = CheckMD5
	}

	g.state.UpdateOp(g.selectedOp, op)
	g.updateOpCompleteLabel()
	g.refreshOpTableOnly()
	return true
}

func (g *gui) updateOpCompleteLabel() {
	ops := g.state.Ops()
	if g.selectedOp < 0 || g.selectedOp >= len(ops) {
		g.opComplete.SetText("该项当前完整度：未选中")
		return
	}
	op := ops[g.selectedOp].Inf
	if op.IsComplete() {
		g.opComplete.SetText("该项当前完整度：完整 ✓")
		return
	}
	g.opComplete.SetText("该项当前完整度：不完整（不会被执行）— " + op.Validate().Error())
}

func (g *gui) refreshOpTableOnly() {
	if g.opTable != nil {
		g.opTable.Refresh()
	}
}

func (g *gui) refreshTables() {
	if g.deviceTable != nil {
		g.deviceTable.Refresh()
	}
	if g.opTable != nil {
		g.opTable.Refresh()
	}
}

// ---------- 载入 / 保存 / 执行 ----------

func (g *gui) loadConfig() {
	preset := g.presetSel.Selected
	if preset == "" {
		dialog.ShowInformation("提示", "请先选择一个内置预设", g.win)
		return
	}
	cfg, err := LoadBuiltinPreset(preset)
	if err != nil {
		dialog.ShowError(err, g.win)
		return
	}
	g.state.LoadConfig(cfg)
	g.selectedOp = -1
	g.refreshTables()
	g.refreshDeviceLog()
	g.setStatus(fmt.Sprintf("已载入预设 %s：%d 台设备，%d 条操作",
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
			dialog.ShowError(err, g.win)
			return
		}
		g.setStatus("已保存到 " + path)
	}, g.win)
}

func (g *gui) runBatch() {
	g.mu.Lock()
	if g.running {
		g.mu.Unlock()
		dialog.ShowInformation("提示", "当前已有任务在执行", g.win)
		return
	}
	g.mu.Unlock()

	cfg := g.state.ToConfig()
	if err := cfg.Validate(); err != nil {
		dialog.ShowError(fmt.Errorf("配置无效：%w", err), g.win)
		return
	}

	rootDir := g.state.RootDir()
	if st, err := os.Stat(rootDir); err != nil || !st.IsDir() {
		dialog.ShowError(fmt.Errorf("根目录不存在或不是目录：%s", rootDir), g.win)
		return
	}

	g.state.ClearLogs()
	for i := range cfg.RemoteInf {
		g.state.SetDeviceStatus(i, "等待中")
	}
	g.refreshTables()

	ctx, cancel := context.WithCancel(context.Background())
	g.mu.Lock()
	g.running = true
	g.cancel = cancel
	g.mu.Unlock()

	g.setStatus(fmt.Sprintf("开始执行：%d 台设备 × %d 条操作，并行上限 %d",
		len(cfg.RemoteInf), len(cfg.CompleteOperations()), g.state.MaxParallel()))

	exec := &Executor{
		RootDir:     rootDir,
		MaxParallel: g.state.MaxParallel(),
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

			ok, failed := 0, 0
			for _, r := range results {
				if r.OK {
					ok++
				} else {
					failed++
				}
			}
			g.refreshTables()
			msg := fmt.Sprintf("执行结束：成功 %d，失败 %d", ok, failed)
			g.setStatus(msg)
			if failed > 0 {
				dialog.ShowInformation("执行结束", msg+"\n\n失败设备可在左侧选中查看原因。", g.win)
			} else {
				dialog.ShowInformation("执行结束", msg, g.win)
			}
		})
	}()
}

// onEvent 在 UI 线程处理一条执行事件。
func (g *gui) onEvent(ev StepEvent) {
	if ev.Log != "" {
		g.state.AppendLog(ev.DeviceIndex, ev.Log+"\n")
	}
	if ev.Err != nil {
		g.state.AppendLog(ev.DeviceIndex, "错误: "+ev.Err.Error()+"\n")
		g.state.SetDeviceStatus(ev.DeviceIndex, "失败｜"+ev.Err.Error())
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
	if g.statusLbl != nil {
		g.statusLbl.SetText(s)
	}
}

func (g *gui) confirmDelete(title, msg string, onYes func()) {
	dialog.ShowConfirm(title, msg, func(ok bool) {
		if ok {
			onYes()
		}
	}, g.win)
}

func (g *gui) showHelp() {
	help := `批量部署工具 使用说明

1. 选择文件操作根目录
   上传/下载的相对路径都以此目录为基准。

2. 配置远程设备
   表格中每行一台设备，填写 IPv4 地址、SSH 端口、用户名、密码。
   选中一行后可「编辑 / 克隆 / 删除」；「新增设备」追加一行。

3. 配置操作
   操作分三类：
   · 命令下发 —— 在每台设备上执行同一条命令，可配置成功/失败关键字。
   · 文件上传 —— 本地文件上传到设备，上传后按 MD5 校验。
   · 文件下载 —— 设备上的文件下载到本地目录，下载后按 MD5 校验。
   选中操作行后在下方编辑，改动即时生效。
   「完整/不完整」会实时显示；不完整的操作不会被执行。

4. 载入 / 保存配置
   可从内置预设载入，也可保存为 JSON 复用。
   配置文件格式与旧版完全兼容。

5. 执行
   设置并行上限后点「执行配置」。
   执行过程中配置区不可编辑，结束后自动恢复。
   在左侧选中设备可查看该设备的执行日志。

6. 命令行模式
   qt_batch_deployment [根目录] [配置文件路径] [最大并行数]
   不带参数启动图形界面。`
	dialog.ShowInformation("帮助", help, g.win)
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


