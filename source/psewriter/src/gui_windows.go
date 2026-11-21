//go:build windows

// Windows 图形界面 (lxn/walk)：目标设备 → 操作与数据源 → 核对写入计划。
package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"
	"github.com/lxn/win"
)

type ui struct {
	mw   *walk.MainWindow
	font Font

	// ① 目标设备
	devBox                                                     *walk.ComboBox
	refreshBtn, pickFileBtn, pickDirBtn, embeddedBtn, btnClose *walk.PushButton
	showAll                                                    *walk.CheckBox

	// ② 要做什么
	modeCard   *walk.RadioButton
	modeImage  *walk.RadioButton
	modeFormat *walk.RadioButton
	modeInfo   *walk.TextEdit // 当前模式的说明 (跟着模式换)

	// ② 数据源 (制作刷机卡 / 写入整盘镜像)
	srcRow  *walk.Composite
	imgEdit *walk.LineEdit
	imgInfo *walk.TextEdit
	fsRow   *walk.Composite
	fastFS  *walk.CheckBox

	// ② 只格式化
	fmtRow   *walk.Composite
	labelEdt *walk.LineEdit

	// ③ 核对目标磁盘
	propView  *walk.TableView
	propModel *kvModel
	partView  *walk.TableView
	partModel *partTableModel
	planInfo  *walk.TextEdit

	// 底部: 状态 / 进度 / 操作 / 日志
	progress  *walk.ProgressBar
	status    *walk.Label
	log       *walk.TextEdit
	btnStart  *walk.PushButton
	btnCancel *walk.PushButton

	disks      []*DiskInfo
	diskStamps map[int]diskStamp
	prep       *PreparedSource
	sources    []sourceFileStamp
	imgPath    string
	useEmbed   bool
	ready      bool
	busy       bool
	dedup      logDedup

	// 分析 (探测) 状态 —— 大压缩包解析很慢, 必须在后台线程做并给出进度
	analyzing   atomic.Bool  // 正在分析
	probeCancel *atomic.Bool // 当前这次分析的取消令牌 (每次分析一个, 见 repreview)
	closed      atomic.Bool  // 窗口已关闭, 不再往界面派发更新
	probeGen    int          // 代数: 过期的分析结果直接丢弃
	probeDone   int64        // 已消费的源文件字节数 / 条目数
	probeTotal  int64        // 源文件大小 (0 = 未知 → 跑马灯)
	spin        rune         // 动态图标当前帧
	spinStop    chan struct{}
}

// mode 当前选中的模式。
//
// 没选中任何一项时按「只格式化」处理 —— 正常情况下启动就会显式勾上它（见 runGUI），
// 真走到这个兜底分支时，选破坏性最小的那个模式（只建文件系统，不往里写任何东西）。
func (u *ui) mode() taskMode {
	switch {
	case u.modeImage != nil && u.modeImage.Checked():
		return modeWriteImage
	case u.modeCard != nil && u.modeCard.Checked():
		return modeMakeCard
	}
	return modeFormatOnly
}

// ---------- 表格模型 ----------

// kvModel — 两列「项目 / 内容」只读信息表 (取代空格对齐的文本框)
type kvModel struct {
	walk.TableModelBase
	keys, vals []string
}

func (m *kvModel) RowCount() int { return len(m.keys) }

func (m *kvModel) Value(row, col int) interface{} {
	if row < 0 || row >= len(m.keys) {
		return ""
	}
	if col == 0 {
		return m.keys[row]
	}
	return m.vals[row]
}

func (m *kvModel) Set(pairs [][2]string) {
	m.keys = m.keys[:0]
	m.vals = m.vals[:0]
	for _, p := range pairs {
		m.keys = append(m.keys, p[0])
		m.vals = append(m.vals, p[1])
	}
	m.PublishRowsReset()
}

// partTableModel — 分区现状表
type partTableModel struct {
	walk.TableModelBase
	rows [][]string
}

func (m *partTableModel) RowCount() int { return len(m.rows) }

func (m *partTableModel) Value(row, col int) interface{} {
	if row < 0 || row >= len(m.rows) || col < 0 || col >= len(m.rows[row]) {
		return ""
	}
	return m.rows[row][col]
}

func (m *partTableModel) Set(rows [][]string) {
	m.rows = rows
	m.PublishRowsReset()
}

// ---------- 窗口 ----------

// 按钮统一宽度, 避免不同 DPI 下按钮忽宽忽窄
const btnW = 96

func runGUI() int {
	u := &ui{
		font:      uiFont(),
		propModel: &kvModel{},
		partModel: &partTableModel{},
	}

	// 每个区块一个 GroupBox; 标题短, 说明进 tooltip
	group := func(title string, children ...Widget) GroupBox {
		return GroupBox{
			Title:    title,
			Layout:   VBox{Margins: Margins{Left: 9, Top: 6, Right: 9, Bottom: 8}, Spacing: 4},
			Children: children,
		}
	}
	row := func(children ...Widget) Composite {
		return Composite{Layout: HBox{MarginsZero: true, Spacing: 6}, Children: children}
	}
	kvTable := func(view **walk.TableView, model *kvModel, h int) TableView {
		return TableView{
			AssignTo:         view,
			Model:            model,
			AlternatingRowBG: true,
			ColumnsOrderable: false,
			// 这里**不设** LastColumnStretched: walk 在 Create 阶段就会调
			// StretchLastColumn, 它一失败整个窗口都建不出来 (现场报
			// "LVM_SETCOLUMNWIDTH failed" 直接启动失败)。改成窗口建好之后再设,
			// 见 stretchLastColumns。
			MinSize: Size{Height: h},
			Columns: []TableViewColumn{
				{Title: "项目", Width: 96},
				{Title: "内容", Width: 260},
			},
		}
	}

	if err := (MainWindow{
		AssignTo: &u.mw,
		Title:    "SE写卡工具 v" + toolVersion,
		Size:     Size{Width: 700, Height: 760},
		MinSize:  Size{Width: 660, Height: 700},
		Layout:   VBox{Margins: Margins{Left: 8, Top: 6, Right: 8, Bottom: 8}, Spacing: 6},
		// 内置中文字体 —— 现场有机器系统字体不全, 中文会画成豆腐块 (见 uifont_windows.go)
		Font: u.font,
		MenuItems: []MenuItem{
			Menu{Text: "文件(&F)", Items: []MenuItem{
				Action{Text: "刷新设备列表(&R)", Shortcut: Shortcut{Key: walk.KeyF5}, OnTriggered: func() { u.refresh() }},
				Separator{},
				Action{Text: "退出(&X)", OnTriggered: func() { u.quit() }},
			}},
			Menu{Text: "工具(&T)", Items: []MenuItem{
				Action{
					Text:        "导出自带镜像的新程序(&E)…",
					OnTriggered: func() { u.repackDialog() },
				},
				Separator{},
				Action{Text: "查看内置数据源信息(&I)…", OnTriggered: func() { u.showEmbeddedInfo() }},
			}},
			Menu{Text: "帮助(&H)", Items: []MenuItem{
				Action{Text: "关于(&A)…", OnTriggered: func() { u.about() }},
			}},
		},
		Children: []Widget{
			// ① 设备
			group("① 选择目标设备",
				row(
					ComboBox{
						AssignTo:              &u.devBox,
						Model:                 []string{"请选择目标设备"},
						CurrentIndex:          0,
						StretchFactor:         1,
						ToolTipText:           "请选择目标设备并核对型号、容量和分区。识别出的系统盘不显示；无法确认系统盘时停止。",
						OnCurrentIndexChanged: func() { u.onSelect() },
					},
					PushButton{
						AssignTo:    &u.refreshBtn,
						Text:        "刷新",
						MaxSize:     Size{Width: 64},
						ToolTipText: "重新扫描本机磁盘（插拔读卡器后点这里，快捷键 F5）",
						OnClicked:   func() { u.refresh() },
					},
					CheckBox{
						AssignTo:         &u.showAll,
						Text:             "显示固定磁盘",
						ToolTipText:      "仅在确需操作非 TF 卡时使用。USB 磁盘不一定是 TF 卡，请核对实际设备。",
						OnCheckedChanged: func() { u.refresh() },
					},
				),
				kvTable(&u.propView, u.propModel, 76),
				TableView{
					AssignTo:         &u.partView,
					Model:            u.partModel,
					AlternatingRowBG: true,
					ColumnsOrderable: false,
					// 同 kvTable: LastColumnStretched 放到窗口建好之后再设
					MinSize:     Size{Height: 56},
					ToolTipText: "目标设备现有的分区。先核对容量、卷标和盘符，再继续。",
					Columns: []TableViewColumn{
						{Title: "分区", Width: 46},
						{Title: "大小", Width: 84},
						{Title: "起始偏移", Width: 84},
						{Title: "文件系统", Width: 90},
						{Title: "卷标", Width: 110},
						{Title: "盘符", Width: 56},
					},
				},
			),
			// ② 要做什么 (模式) + 该模式要用的设置
			// 顺序 = 默认项在最前: 只格式化 → 制作刷机卡 → 写入整盘镜像
			group("② 操作与数据源",
				row(RadioButtonGroup{
					Buttons: []RadioButton{
						{
							AssignTo: &u.modeFormat,
							Text:     "只格式化",
							ToolTipText: "重建 MBR + FAT32，不写文件，不作安全擦除。\n" +
								"卡被格成 exFAT/NTFS/GPT、或 FAT32 被写坏时，用它快速恢复；\n" +
								"格式化完成后可以直接用资源管理器把文件拷进去。",
							// 单选框自己不定宽, 不写 Alignment 会被 VBox 居中
							Alignment: AlignHNearVCenter,
							OnClicked: func() { u.onModeChanged() },
						},
						{
							AssignTo: &u.modeCard,
							Text:     "制作刷机卡",
							ToolTipText: "卡会被格式化为 MBR+FAT32，再把文件包/目录里的文件写进去。\n" +
								"SE5 / SE7 / SE9 的恢复卡用这个。",
							Alignment: AlignHNearVCenter,
							OnClicked: func() { u.onModeChanged() },
						},
						{
							AssignTo: &u.modeImage,
							Text:     "写入整盘镜像",
							ToolTipText: "把 .img/.raw/.iso（或其 gz/xz/bz2/zst 压缩体）逐字节写到卡上。\n" +
								"从盘首写入；只回读校验镜像覆盖的范围。",
							Alignment: AlignHNearVCenter,
							OnClicked: func() { u.onModeChanged() },
						},
					},
				}),
				// 当前模式在做什么 (跟着模式换)
				TextEdit{
					AssignTo: &u.modeInfo,
					ReadOnly: true,
					VScroll:  true,
					MinSize:  Size{Height: 46},
				},
				// ---- 数据源: 制作刷机卡 / 写入整盘镜像 ----
				Composite{
					AssignTo: &u.srcRow,
					Layout:   VBox{MarginsZero: true, Spacing: 4},
					Children: []Widget{
						row(
							LineEdit{
								AssignTo:      &u.imgEdit,
								ReadOnly:      true,
								Text:          "(未选择)",
								StretchFactor: 1,
								ToolTipText:   "显示你明确选中的来源；不会自动选中内置来源。",
							},
							PushButton{
								AssignTo: &u.pickFileBtn,
								Text:     "选文件…",
								MaxSize:  Size{Width: 84},
								ToolTipText: "选择镜像文件或压缩包：\n" +
									"· 整盘镜像 .img/.raw/.iso，或其 gz/xz/bz2/zst 压缩体\n" +
									"· 整盘镜像归档内须为一个未再压缩的镜像文件。\n" +
									"· 筛选结果必须符合当前模式；不会自动切换。",
								OnClicked: func() { u.pickImage() },
							},
							PushButton{
								AssignTo: &u.pickDirBtn,
								Text:     "选目录…",
								MaxSize:  Size{Width: 84},
								ToolTipText: "直接选一个目录当数据源（不必先打包）：\n" +
									"· 目录内容原样写进卡根目录（等价于把该目录打成文件包）\n" +
									"· 目录里若多套了一层（如 se7/sdbootrecoveryfiles/…），自动定位到刷机包那一层\n" +
									"· 软链按目标文件处理；FAT32 放不下的条目（设备文件/断链）跳过并计数",
								OnClicked: func() { u.pickDir() },
							},
							PushButton{
								AssignTo:    &u.embeddedBtn,
								Text:        "使用内置",
								MaxSize:     Size{Width: 84},
								ToolTipText: "明确选用程序自带的来源；仍需与当前模式匹配。",
								OnClicked:   func() { u.useEmbedded() },
							},
						),
						TextEdit{
							AssignTo:    &u.imgInfo,
							ReadOnly:    true,
							VScroll:     true,
							MinSize:     Size{Height: 60},
							ToolTipText: "查看已选来源的类型、大小和预检结果。",
						},
						Composite{
							AssignTo: &u.fsRow, Layout: HBox{MarginsZero: true, Spacing: 6},
							Children: []Widget{
								CheckBox{AssignTo: &u.fastFS, Text: "按文件大小并留余量建分区",
									ToolTipText:      "仅制作刷机卡时可用。默认按目标容量建分区；容量超过 FAT32 上限时保留未分配空间。",
									OnCheckedChanged: func() { u.repreview() }},
								HSpacer{},
							},
						},
					},
				},
				// ---- 只格式化: 只需要一个卷标 ----
				Composite{
					AssignTo: &u.fmtRow,
					Layout:   VBox{MarginsZero: true, Spacing: 4},
					Visible:  false,
					Children: []Widget{
						row(
							Label{Text: "卷标", ToolTipText: "最终卷标显示在写入计划中；最多 11 字符。"},
							LineEdit{
								AssignTo: &u.labelEdt,
								Text:     "SE",
								MaxSize:  Size{Width: 140},
								OnTextChanged: func() {
									if u.planInfo != nil {
										u.updateHint()
									}
								},
								ToolTipText: "转大写；空格、句点转短横线，移除其他不支持字符。留空或无有效字符时用 SE。",
							},
							HSpacer{},
						),
					},
				},
			),
			// ③ 开始
			group("③ 核对写入计划",
				TextEdit{AssignTo: &u.planInfo, ReadOnly: true, VScroll: true, MinSize: Size{Height: 63}},

				Label{AssignTo: &u.status, Text: "第 1 步：请选择目标设备"},
				ProgressBar{AssignTo: &u.progress, MaxValue: 1000},
				row(
					HSpacer{},
					PushButton{
						AssignTo:    &u.btnCancel,
						Text:        "取消分析",
						MinSize:     Size{Width: 90, Height: 32},
						MaxSize:     Size{Width: 90},
						Visible:     false,
						ToolTipText: "中止正在进行的镜像分析",
						OnClicked:   func() { u.cancelProbe(); u.setStatus("正在取消分析…") },
					},
					PushButton{
						AssignTo:    &u.btnStart,
						Text:        "核对并继续",
						MinSize:     Size{Width: 120, Height: 32},
						MaxSize:     Size{Width: 120},
						ToolTipText: "下一步仅展示确认框，不会立即写盘。",
						OnClicked:   func() { u.start() },
					},
					PushButton{
						AssignTo:    &u.btnClose,
						Text:        "关闭",
						MinSize:     Size{Width: 80, Height: 32},
						MaxSize:     Size{Width: 80},
						ToolTipText: "关闭程序",
						OnClicked:   func() { u.quit() },
					},
				),
			),
			group("日志",
				TextEdit{
					AssignTo:    &u.log,
					ReadOnly:    true,
					VScroll:     true,
					MinSize:     Size{Height: 52},
					ToolTipText: "写入进度与校验结果；出错时这里会有详细信息",
				},
			),
		},
	}).Create(); err != nil {
		walk.MsgBox(nil, "启动失败",
			"图形界面初始化失败:\n\n"+err.Error()+"\n\n"+envSummary()+
				"\n命令行功能不受影响, 可在管理员 cmd / PowerShell 中直接使用:\n"+
				"  sewriter.exe info                    查看内置数据源信息\n"+
				"  sewriter.exe list                    列出磁盘\n"+
				"  sewriter.exe write --disk 3 --yes    烧录到磁盘 3\n"+
				"  sewriter.exe repack --image <镜像>    换镜像生成新程序\n\n"+
				"请把本窗口内容反馈给开发者。", walk.MsgBoxIconError)
		return 1
	}

	u.mw.Closing().Attach(func(canceled *bool, _ walk.CloseReason) {
		if u.busy {
			*canceled = true
			return
		}
		u.closed.Store(true)
		u.cancelProbe()
	})
	u.stretchLastColumns()
	u.modeFormat.SetChecked(true)
	u.btnCancel.SetVisible(false)
	u.applyMode()
	u.refresh()
	u.updateHint()
	u.mw.Run()
	return 0
}

// stretchLastColumns 让两个表格的最后一列铺满剩余宽度。
//
// 为什么不在声明式里写 LastColumnStretched: walk 把它当成 Create 的一部分 ——
// TableView.Create 里直接调 SetLastColumnStretched → StretchLastColumn, 一失败就
// 整个 MainWindow.Create 返回错误, 程序弹「启动失败」直接退出。现场有机器就卡在
// 这一步 (报 LVM_SETCOLUMNWIDTH failed, 见 MYS-1240)。但这只是"最后一列铺满"的
// 观感设置, 铺不满最多是右边留白, 不该拦住启动 —— 所以挪到窗口建好之后再设,
// 失败就退化成固定列宽, 只记一行日志。
func (u *ui) stretchLastColumns() {
	for _, tv := range []*walk.TableView{u.propView, u.partView} {
		if tv == nil {
			continue
		}
		if err := tv.SetLastColumnStretched(true); err != nil {
			u.appendLog("提示: 表格末列自适应失败, 已退化为固定列宽 (" + err.Error() + ")")
		}
	}
}

// envSummary 启动失败时一并带上的环境信息 —— 现场只截一张图时也能看出系统/屏幕/缩放
func envSummary() string {
	cx := win.GetSystemMetrics(win.SM_CXSCREEN)
	cy := win.GetSystemMetrics(win.SM_CYSCREEN)
	hdc := win.GetDC(0)
	dpi := win.GetDeviceCaps(hdc, win.LOGPIXELSX)
	win.ReleaseDC(0, hdc)
	if dpi <= 0 {
		dpi = 96
	}
	return fmt.Sprintf("环境: Windows %s / 屏幕 %d×%d / 系统缩放 %d%%\n",
		windowsVersionText(), cx, cy, dpi*100/96)
}

// windowsVersionText 把 win.GetVersion() 的返回值翻成 "10.0 (Build 19045)" 这种短文本
func windowsVersionText() string {
	v := win.GetVersion()
	return fmt.Sprintf("%d.%d (Build %d)", byte(v), byte(v>>8), uint16(v>>16))
}

// ---------- 模式 ----------

// applyMode 按当前模式摆好各区块的显隐与文案 (不触发重新解析)
func (u *ui) applyMode() {
	m := u.mode()
	u.srcRow.SetVisible(m != modeFormatOnly)
	u.fmtRow.SetVisible(m == modeFormatOnly)
	u.fsRow.SetVisible(m == modeMakeCard)
	u.pickDirBtn.SetVisible(m == modeMakeCard)
	u.embeddedBtn.SetEnabled(!u.busy && HasEmbeddedImage())
	u.setModeInfo(m)
}

// setModeInfo ② 里那行说明: 一句话讲清"选了这个模式会发生什么"
func (u *ui) setModeInfo(m taskMode) {
	switch m {
	case modeWriteImage:
		u.modeInfo.SetText("从盘首写入选中的整盘镜像。不会把文件包当镜像写入；只核对镜像范围内的回读。")
	case modeFormatOnly:
		u.modeInfo.SetText("重建 MBR 和 FAT32，不写入文件。原有分区和文件访问会丢失；这不是安全擦除。")
	default:
		u.modeInfo.SetText("在目标卡上重建 MBR 和 FAT32，再写入刷机包文件。通过文件校验不代表设备已验证可启动。")
	}
}

// onModeChanged 用户换了模式
func (u *ui) onModeChanged() {
	if u.busy || u.planInfo == nil || u.imgEdit == nil {
		return
	}
	u.applyMode()
	// A source from another mode is never silently carried into this one.
	u.useEmbed, u.imgPath = false, ""
	u.imgEdit.SetText("未选择来源")
	u.repreview()
}

// ---------- 辅助 ----------

// deviceLabel 设备下拉框里的一行
func deviceLabel(d *DiskInfo) string {
	rm := "固定"
	if d.Removable {
		rm = "可移动"
	}
	return fmt.Sprintf("磁盘 %d — %s (%s, %s, %s)", d.Index, d.Model, HumanBytes(d.Size), d.BusType, rm)
}

// updateHint 刷新状态行的"下一步该做什么"与开始按钮可用性
func (u *ui) updateHint() {
	if u.busy || u.planInfo == nil || u.analyzing.Load() {
		return
	}
	enabled := false
	plan, status := "", ""
	d := u.current()
	switch {
	case d == nil:
		status = "请选择目标设备。刷新后也不会自动选中磁盘。"
	case u.mode() == modeFormatOnly:
		p, err := PrepareFormat(d.Size, u.labelEdt.Text())
		if err != nil {
			status = err.Error()
		} else {
			plan, status, enabled = operatorPlanText(d, p), "下一步只核对，不会立即格式化。", true
		}
	case !u.useEmbed && u.imgPath == "":
		status = "请选择与当前模式匹配的数据源。"
	case !u.ready || u.prep == nil:
		status = "预检未通过；请查看数据源区的原因。"
	default:
		plan, status, enabled = operatorPlanDetails(d, u.prep, u.sourceName()), "预检通过。下一步只核对，不会立即写盘。", true
	}
	if plan != "" {
		note := "原分区与文件访问会丢失；这不是安全擦除。"
		if u.mode() == modeWriteImage {
			note = "可能使原分区不可用；镜像范围外不校验。"
		}
		plan += "\r\n" + note
	}
	u.planInfo.SetText(plan)
	u.setStatus(status)
	u.btnStart.SetEnabled(enabled)
}

// sourceName 当前镜像来源的短名
func (u *ui) sourceName() string {
	if u.useEmbed || u.imgPath == "" {
		if m := EmbeddedImageInfo(); m != nil {
			return "内置数据源 " + m.File
		}
		return "内置数据源"
	}
	return filepath.Base(u.imgPath)
}

// showEmbeddedInfo 菜单: 查看内置数据源信息
func (u *ui) showEmbeddedInfo() {
	if u.busy {
		return
	}
	lines := EmbeddedLines()
	msg := ""
	for _, l := range lines {
		msg += l + "\r\n"
	}
	msg += "\r\n来源: " + SelfExePath()
	msg += "\r\n\r\n换掉内置数据源: 菜单「工具 → 导出自带镜像的新程序…」"
	walk.MsgBox(u.mw, "内置数据源信息", msg, walk.MsgBoxIconInformation)
}

// about 菜单: 关于
func (u *ui) about() {
	if u.busy {
		return
	}
	walk.MsgBox(u.mw, "关于 SE写卡工具",
		fmt.Sprintf("SE写卡工具 v%s\n\n"+
			"制作 SE 系列设备（SE5/SE7/SE9）的 TF 卡，三种模式：\n"+
			"· 只格式化 TF 卡：只建 MBR+FAT32，不写入任何文件\n"+
			"· 制作刷机卡：文件包 / 目录 → 快速格式化为 MBR+FAT32 并写入\n"+
			"· 写入整盘镜像：.img/.raw/.iso（或 gz/xz/bz2/zst/zip/7z/rar/tar 压缩体）逐字节写入\n\n"+
			"写后回读校验：文件包模式回读比对 + 从卡上挂 FAT32 逐文件 sha256；\n"+
			"只格式化模式回读核对分区表 / BPB / FAT 两份副本。\n\n"+
			"安全：不预选目标。系统盘未能确认时禁止写入；写入前核对设备及本次计划。", toolVersion),
		walk.MsgBoxIconInformation)
}

// ---------- 状态刷新 ----------

func (u *ui) appendLog(s string) {
	if !u.dedup.Accept(s) { // 连续重复 (例如反复刷新磁盘) 不再刷屏
		return
	}
	u.log.AppendText(s + "\r\n")
}

func (u *ui) setStatus(s string) {
	if u.status != nil {
		u.status.SetText(s)
	}
}

// refresh 重新枚举磁盘; 结果与上次相同则不重复记日志
func (u *ui) refresh() {
	if u.busy {
		return
	}
	u.cancelAnalyze()
	u.disks = nil
	u.diskStamps = map[int]diskStamp{}
	labels := []string{"请选择目标设备"}
	disks, err := enumerateDisks()
	if err == nil {
		for _, d := range SelectableDisks(disks, u.showAll.Checked()) {
			stamp, err := operatorDiskTarget(d)
			if err != nil {
				u.appendLog(fmt.Sprintf("磁盘 %d 无法复核，不可选：%v", d.Index, err))
				continue
			}
			u.diskStamps[d.Index] = stamp
			u.disks = append(u.disks, d)
			labels = append(labels, deviceLabel(d))
		}
	}
	u.devBox.SetModel(labels)
	u.devBox.SetCurrentIndex(0)
	u.onSelect()
	if err != nil {
		u.setStatus(err.Error())
		u.appendLog("无法扫描设备：" + err.Error())
	} else if len(u.disks) == 0 {
		u.setStatus("没有可核对的设备。连接读卡器后刷新。")
	}
}

func (u *ui) current() *DiskInfo {
	i := u.devBox.CurrentIndex() - 1
	if i < 0 || i >= len(u.disks) {
		return nil
	}
	return u.disks[i]
}

func (u *ui) onSelect() {
	if u.busy || u.planInfo == nil {
		return
	}
	d := u.current()
	if d == nil {
		u.propModel.Set([][2]string{{"状态", "未选择设备"}})
		u.partModel.Set(nil)
	} else {
		u.propModel.Set(d.PropertyRows())
		u.partModel.Set(d.PartitionRows())
	}
	u.repreview()
}

// useEmbedded 切回程序内置镜像 (默认源)
func (u *ui) useEmbedded() {
	if u.busy || !HasEmbeddedImage() {
		return
	}
	u.useEmbed, u.imgPath = true, ""
	u.imgEdit.SetText("内置数据源")
	u.repreview()
}

func (u *ui) pickImage() {
	if u.busy {
		return
	}
	fd := walk.FileDialog{
		Title: "选择镜像或文件包",
		Filter: "镜像 / 压缩包 (*.img;*.raw;*.iso;*.gz;*.xz;*.bz2;*.zst;*.zip;*.7z;*.rar;*.tar;*.tgz)|" +
			"*.img;*.raw;*.iso;*.gz;*.xz;*.bz2;*.zst;*.zip;*.7z;*.rar;*.tar;*.tgz|" +
			"所有文件 (*.*)|*.*",
	}
	if ok, err := fd.ShowOpen(u.mw); err != nil || !ok {
		return
	}
	u.imgPath = fd.FilePath
	u.useEmbed = false
	u.ready = false
	u.imgEdit.SetText(fd.FilePath)
	u.repreview()
}

// pickDir 选一个目录当数据源 (MYS-1062 十八轮④)
func (u *ui) pickDir() {
	if u.busy || u.mode() != modeMakeCard {
		return
	}
	dir := pickDirectory(uintptr(u.mw.Handle()), "选择作为写卡数据源的目录")
	if strings.TrimSpace(dir) == "" {
		return
	}
	u.imgPath = dir
	u.useEmbed = false
	u.ready = false
	u.imgEdit.SetText(dir)
	u.appendLog("数据源: 目录 " + dir)
	u.repreview()
}

// setImageInfo 更新 ② 的说明文字
func (u *ui) setImageInfo(text string) {
	if u.imgInfo != nil {
		u.imgInfo.SetText(text)
	}
}

// repreview 重新解析当前来源。
//
// 解析一个 14 GiB 的 .txz 文件包要把整条压缩流走一遍 (几十秒到几分钟), 放在 UI 线程
// 上就是"选完文件界面直接卡死"。所以这里一律丢到后台 goroutine, 期间:
//   - 进度条显示已消费的压缩字节数 (容器格式没有字节进度 → 跑马灯)
//   - 状态行前面的动态图标持续转, 让人一眼看出程序还在干活
//   - 「取消分析」按钮出现, 点了就中止
//
// 用 probeGen 作代数: 用户连续换文件时, 先发起的那次分析结果回来直接丢弃。
func (u *ui) repreview() {
	if u.busy || u.planInfo == nil {
		return
	}
	u.cancelAnalyze()
	u.prep, u.sources, u.ready = nil, nil, false
	d, m := u.current(), u.mode()
	if m == modeFormatOnly || d == nil || (u.imgPath == "" && !u.useEmbed) {
		note := "选中目标后预检数据源。"
		if d != nil {
			note = "请选择文件，或使用已有的内置数据源。"
		}
		if !HasEmbeddedImage() {
			note += " 当前程序未内置数据源。"
		}
		u.setImageInfo(note)
		u.updateHint()
		return
	}
	p := u.imgPath
	full := m != modeMakeCard || !u.fastFS.Checked()
	u.planInfo.SetText("")
	gen := u.probeGen
	cancel := &atomic.Bool{}
	u.probeCancel = cancel
	u.setImageInfo("来源：" + dataSourceLabel(p) + "\r\n正在预检；压缩镜像会提前核对完整解压大小。")
	u.beginAnalyze()
	go func() {
		ctl := &ProbeCtl{
			Progress: func(_ string, done, total int64) {
				u.syncUI(func() {
					if gen == u.probeGen {
						u.showAnalyzeProgress(done, total)
					}
				})
			},
			Canceled: cancel.Load,
		}
		var prep *PreparedSource
		var stamps []sourceFileStamp
		src := p
		if src == "" {
			src = SelfExePath()
		}
		check := operatorSourceVolumeCheck(d.Index)
		initial, err := readSourceStamp(src)
		if err == nil {
			err = check(src)
		}
		if err == nil {
			prep, err = prepareOperatorSource(m, p, d.Size, full, "", ctl)
		}
		if err == nil {
			stamps, err = operatorSourceStamps(p, prep, check, ctl)
		}
		if err == nil && !initial.current() {
			err = errors.New("来源在预检时已变化，请重新选择")
		}
		if cancel.Load() {
			err = ErrProbeCanceled
		}
		u.syncUI(func() {
			if gen != u.probeGen {
				return
			}
			u.endAnalyze()
			if err != nil {
				msg := err.Error()
				if errors.Is(err, ErrProbeCanceled) {
					msg = "分析已取消；可重新选择来源。"
				}
				u.setImageInfo("来源：" + dataSourceLabel(p) + "\r\n" + msg)
				u.appendLog("预检未通过：" + msg)
			} else {
				u.prep, u.sources, u.ready = prep, stamps, true
				info := SourceInfoText(prep.Archive, prep.Plan)
				if prep.Archive != nil && prep.Archive.Skipped > 0 {
					u.appendLog(fmt.Sprintf("预检警告：忽略 %d 个不受支持的来源条目", prep.Archive.Skipped))
				}
				u.setImageInfo(info)
			}
			u.updateHint()
		})
	}()
}

// cancelAnalyze 取消在途的分析并退出"分析中"状态。
//
// 两件事都要做:
//   - 把当前令牌置位, 让那条 goroutine 自己停下来 (否则它会继续解压整条压缩流);
//   - 自己调 endAnalyze。光把代数 +1 是不够的: 过期结果回来时走的是"直接丢弃"分支,
//     不会调 endAnalyze, 于是 analyzing 永远停在 true —— 状态行不再更新, 「开始」也点不动。
func (u *ui) cancelAnalyze() {
	u.probeGen++
	u.cancelProbe()
	if u.analyzing.Load() {
		u.endAnalyze()
	}
}

// cancelProbe 只置取消令牌 (「取消分析」按钮用)
func (u *ui) cancelProbe() {
	if c := u.probeCancel; c != nil {
		c.Store(true)
	}
}

// quit 关窗: 先让在途的后台分析知道别再往界面派发了
func (u *ui) quit() {
	if !u.busy {
		u.mw.Close()
	}
}

// syncUI 把界面更新派发回 UI 线程 (窗口已关就丢弃)
func (u *ui) syncUI(f func()) {
	if u.closed.Load() || u.mw == nil {
		return
	}
	u.mw.Synchronize(f)
}

// beginAnalyze 进入"分析中"状态
func (u *ui) beginAnalyze() {
	u.analyzing.Store(true)
	u.probeDone, u.probeTotal = 0, 0
	u.spin = spinFrames[0]
	u.progress.SetValue(0)
	u.progress.SetMarqueeMode(true) // 还不知道总量 → 跑马灯
	u.btnCancel.SetVisible(true)
	u.btnCancel.SetEnabled(true)
	u.btnStart.SetEnabled(false)
	u.renderAnalyzeStatus()

	// 上一次的转圈协程可能还没收 (连续 repreview 时会走到这儿) —— 不收掉就漏一个
	// 120ms 的 ticker 和一个 goroutine, 一直活到进程退出
	if u.spinStop != nil {
		close(u.spinStop)
		u.spinStop = nil
	}
	stop := make(chan struct{})
	u.spinStop = stop
	go u.spinLoop(stop)
}

// spinFrames 动态图标的帧。
//
// 用「半黑半白的圆」而不是盲文点阵: 盲文 U+28xx 在 Noto Sans CJK 里没有, 而界面
// 已经统一用内置字体画 (见 uifont_windows.go), 缺字会变成豆腐块。这几个几何图形
// 内置字体里有, 也不依赖系统装了什么。
var spinFrames = []rune{'◐', '◓', '◑', '◒'}

// spinLoop 原位刷新动态图标
func (u *ui) spinLoop(stop <-chan struct{}) {
	t := time.NewTicker(120 * time.Millisecond)
	defer t.Stop()
	i := 0
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			i++
			f := spinFrames[i%len(spinFrames)]
			u.syncUI(func() {
				if !u.analyzing.Load() {
					return
				}
				u.spin = f
				u.renderAnalyzeStatus()
			})
		}
	}
}

// showAnalyzeProgress 收到一次探测进度
func (u *ui) showAnalyzeProgress(done, total int64) {
	u.probeDone, u.probeTotal = done, total
	if total > 0 {
		u.progress.SetMarqueeMode(false)
		u.progress.SetValue(int(done * 1000 / total))
	} else {
		u.progress.SetMarqueeMode(true)
	}
	u.renderAnalyzeStatus()
}

// renderAnalyzeStatus 状态行: 动态图标 + 进度文字
func (u *ui) renderAnalyzeStatus() {
	s := fmt.Sprintf("%c 正在分析 %s", u.spin, filepath.Base(u.imgPath))
	switch {
	case u.probeTotal > 0:
		s += fmt.Sprintf(" … %5.1f%%  (%s / %s)", float64(u.probeDone)*100/float64(u.probeTotal),
			HumanBytes(u.probeDone), HumanBytes(u.probeTotal))
	case u.probeDone > 0:
		s += fmt.Sprintf(" … 已解析 %d 个条目", u.probeDone)
	}
	u.setStatus(s)
}

// endAnalyze 退出"分析中"状态
func (u *ui) endAnalyze() {
	if u.spinStop != nil {
		close(u.spinStop)
		u.spinStop = nil
	}
	u.analyzing.Store(false)
	u.progress.SetMarqueeMode(false)
	u.progress.SetValue(0)
	u.btnCancel.SetVisible(false)
	u.btnStart.SetEnabled(true)
}

// currentPrep 取当前来源的写入计划。
//
// 预览阶段已经解析过 (repview → u.prep), 正常情况下直接复用 —— 解析一个几百 MB 的
// 压缩包要好几秒, 不能在点"开始写入"时再卡一次。只有当**目标盘或分区选项变了**
// (预览参数与当前不一致) 时才重新解析, 避免"预览显示 A、实际按 B 写"。

// dataSourceLabel 来源展示名 (内置数据源没有路径)
func dataSourceLabel(path string) string {
	if strings.TrimSpace(path) == "" {
		if m := EmbeddedImageInfo(); m != nil {
			return "内置 " + m.File
		}
		return "内置数据源"
	}
	return filepath.Base(path)
}

// ---------- 生成新程序 ----------

// repackDialog 换镜像生成第二个自带镜像的程序 (无需构建机)
func (u *ui) repackDialog() {
	if u.busy || u.analyzing.Load() {
		return
	}
	fd := walk.FileDialog{
		Title:  "选择要内置到新程序的镜像",
		Filter: "镜像文件 (*.img;*.img.gz)|*.img;*.img.gz|所有文件 (*.*)|*.*",
	}
	if ok, err := fd.ShowOpen(u.mw); err != nil || !ok {
		return
	}
	imgPath := fd.FilePath
	src, err := OpenImage(imgPath)
	if err != nil {
		walk.MsgBox(u.mw, "镜像不可用", err.Error(), walk.MsgBoxIconError)
		return
	}
	self := SelfExePath()
	def := DefaultOutPath(self, src)
	sfd := walk.FileDialog{
		Title:    "新程序保存为",
		Filter:   "可执行文件 (*.exe)|*.exe|所有文件 (*.*)|*.*",
		FilePath: def,
	}
	if ok, err := sfd.ShowSave(u.mw); err != nil || !ok {
		return
	}
	out := sfd.FilePath
	if out == "" {
		return
	}
	if _, err := os.Stat(out); err == nil {
		if walk.MsgBox(u.mw, "文件已存在", "覆盖 "+out+" ?",
			walk.MsgBoxYesNo|walk.MsgBoxIconQuestion|walk.MsgBoxDefButton2) != walk.DlgCmdYes {
			return
		}
	}
	cur := "本程序未内置镜像"
	if p, err := OpenSelfPayload(); err == nil {
		cur = "本程序当前内置: " + p.Meta.File
	}
	msg := fmt.Sprintf("将从本程序剥离骨架, 换入新镜像, 生成另一个程序:\n\n"+
		"当前程序: %s\n  %s\n\n新镜像  : %s\n  解压 %s\n  sha256 %s\n\n"+
		"新程序  : %s\n\n本程序不会被修改; 生成的新程序同样可以继续换镜像。确认生成?",
		self, cur, filepath.Base(imgPath), HumanBytes(src.Size()), shortHash(sidecarOrEmpty(imgPath)),
		out)
	if walk.MsgBox(u.mw, "生成新程序?", msg,
		walk.MsgBoxYesNo|walk.MsgBoxIconQuestion|walk.MsgBoxDefButton2) != walk.DlgCmdYes {
		return
	}

	u.setBusy(true)
	u.progress.SetValue(0)
	u.setStatus("正在生成新程序…")
	u.appendLog(fmt.Sprintf("开始换镜像生成新程序: %s → %s", filepath.Base(imgPath), out))

	go func() {
		res, err := Repack(imgPath, out, self, true, func(phase string, done, total int64, rate float64) {
			u.mw.Synchronize(func() {
				if total > 0 {
					u.progress.SetValue(int(float64(done) * 1000 / float64(total)))
					u.setStatus(fmt.Sprintf("生成中 [%s] %5.1f%%  %s/%s  %s",
						phaseName(phase), float64(done)*100/float64(total), HumanBytes(done), HumanBytes(total), HumanRate(rate)))
				} else {
					u.setStatus(fmt.Sprintf("生成中 [%s] %s  %s", phaseName(phase), HumanBytes(done), HumanRate(rate)))
				}
			})
		})
		u.mw.Synchronize(func() {
			u.setBusy(false)
			if err != nil {
				u.progress.SetValue(0)
				u.setStatus("生成失败 — 见日志")
				u.appendLog("× 生成失败: " + err.Error())
				walk.MsgBox(u.mw, "生成失败", err.Error(), walk.MsgBoxIconError)
				return
			}
			u.progress.SetValue(1000)
			u.setStatus("新程序已生成")
			u.appendLog(fmt.Sprintf("✓ 已生成新程序: %s (%s)", res.OutPath, HumanBytes(res.OutBytes)))
			u.appendLog("  程序 sha256: " + res.OutSHA256)
			u.appendLog(fmt.Sprintf("  内置镜像: %s  解压 %s  版本 %s",
				res.Image.File, HumanBytes(res.Image.Bytes), orDashStr(res.Image.BuildVer)))
			u.appendLog("  回读自检: 通过 (骨架一致 + 内置数据 sha256 一致)")
			walk.MsgBox(u.mw, "新程序已生成",
				fmt.Sprintf("已生成自带镜像的新程序:\n\n%s\n\n大小: %s\n程序 sha256:\n%s\n\n内置镜像: %s\n镜像内容 sha256:\n%s\n\n(回读自检通过; 新程序同样可继续换镜像)",
					res.OutPath, HumanBytes(res.OutBytes), res.OutSHA256, res.Image.File, res.Image.SHA256),
				walk.MsgBoxIconInformation)
		})
	}()
}

// sidecarOrEmpty 取镜像解压 sha256 (有 sidecar 时; 无则由 repack 现场计算)
func sidecarOrEmpty(imgPath string) string {
	return sidecarSHA256(imgPath)
}

// ---------- 烧录 ----------

func (u *ui) setBusy(b bool) {
	u.busy = b
	for _, w := range []walk.Widget{u.devBox, u.showAll, u.refreshBtn, u.modeCard, u.modeImage, u.modeFormat, u.pickFileBtn, u.pickDirBtn, u.fastFS, u.labelEdt, u.btnClose} {
		w.SetEnabled(!b)
	}
	u.embeddedBtn.SetEnabled(!b && HasEmbeddedImage())
	u.btnStart.SetEnabled(false)
	if !b {
		u.updateHint()
	}
}

func (u *ui) confirmPlan(d *DiskInfo, detail, verb string, p *PreparedSource) bool {
	var dlg *walk.Dialog
	var accept, back *walk.PushButton
	var checked *walk.CheckBox
	note := "原有分区和文件访问会丢失。这不是安全擦除。"
	if !p.IsCard() {
		note = "将覆盖盘首起的镜像范围，可能使原分区不可用。镜像范围外不校验；这不是安全擦除。"
	}
	if d.Safety == SafetyUnknown {
		note = "注意：这是需人工确认的磁盘。\r\n" + note
	}
	if err := (Dialog{AssignTo: &dlg, Title: "确认" + verb, MinSize: Size{Width: 540}, Layout: VBox{}, Font: u.font,
		DefaultButton: &back, CancelButton: &back, Children: []Widget{
			Label{Text: fmt.Sprintf("请再次核对目标：磁盘 %d · %s · %s · %s", d.Index, d.Model, HumanBytes(d.Size), d.BusType)},
			TextEdit{ReadOnly: true, VScroll: true, MinSize: Size{Height: 128}, Text: detail},
			TextEdit{ReadOnly: true, MinSize: Size{Height: 48}, Text: note},
			CheckBox{AssignTo: &checked, Text: "我已核对目标磁盘和本次计划，确认覆盖。", OnCheckedChanged: func() {
				if accept != nil {
					accept.SetEnabled(checked.Checked())
				}
			}},
			Composite{Layout: HBox{MarginsZero: true}, Children: []Widget{
				HSpacer{}, PushButton{AssignTo: &back, Text: "返回", OnClicked: func() { dlg.Cancel() }},
				PushButton{AssignTo: &accept, Text: "开始" + verb, Enabled: false, OnClicked: func() {
					if checked.Checked() {
						dlg.Accept()
					}
				}},
			}},
		},
	}).Create(u.mw); err != nil {
		u.appendLog("无法打开确认窗口：" + err.Error())
		return false
	}
	defer dlg.Dispose()
	back.SetFocus()
	return dlg.Run() == walk.DlgCmdOK
}

func (u *ui) start() {
	if u.busy || u.analyzing.Load() {
		return
	}
	d := u.current()
	if d == nil {
		return
	}
	stamp, ok := u.diskStamps[d.Index]
	if !ok {
		u.setStatus("目标身份不可用，请重新扫描。")
		return
	}
	p := u.prep
	verb := "制作刷机卡"
	switch u.mode() {
	case modeFormatOnly:
		var err error
		p, err = PrepareFormat(d.Size, u.labelEdt.Text())
		if err != nil {
			u.updateHint()
			return
		}
		verb = "格式化"
	case modeWriteImage:
		verb = "写入整盘镜像"
	}
	if p == nil || (u.mode() != modeFormatOnly && !u.ready) {
		return
	}
	sources := u.sources
	detail := operatorPlanDetails(d, p, u.sourceName())
	for _, part := range d.Partitions {
		detail += fmt.Sprintf("\r\n现有分区 %d：%s %s %s %s", part.Index, part.DriveLetter, HumanBytes(part.Size), part.FSType, part.Label)
	}
	if !u.confirmPlan(d, detail, verb, p) {
		return
	}
	u.setBusy(true)
	u.progress.SetValue(0)
	u.setStatus("正在重新核对设备与来源，请勿拔卡或关闭窗口…")
	u.appendLog("核对计划：" + detail)
	go func() {
		start := time.Now()
		mayWrite := false
		access := operatorFlashAccess(d, stamp, sources, func() { mayWrite = true })
		out, err := runFlash(d, p, true, u.flashProgress, func(format string, a ...interface{}) {
			u.syncUI(func() { u.appendLog(fmt.Sprintf(format, a...)) })
		}, access)
		u.syncUI(func() {
			if err == nil && !out.OK() {
				err = errors.New(u.flashFailure(out))
			}
			u.setBusy(false)
			u.appendLog(fmt.Sprintf("总耗时 %s", time.Since(start).Round(time.Second)))
			if err != nil {
				title, tip := "操作已停止，未写入数据", "请刷新并重新选卡或来源。"
				if mayWrite {
					title, tip = "写入或校验失败", "卡可能已部分写入，请勿直接使用。"
				}
				u.appendLog("失败：" + err.Error())
				u.setStatus(title + "。" + tip)
				walk.MsgBox(u.mw, title, err.Error()+"\r\n"+tip, walk.MsgBoxIconError)
				u.refresh()
				u.setStatus(title + "。" + tip)
				return
			}
			title, desc := u.flashSuccess(out)
			u.progress.SetValue(1000)
			u.refresh() // own writes changed the baseline; every new attempt starts with a new selection
			u.setStatus(title)
			u.appendLog(title + "：" + desc)
			walk.MsgBox(u.mw, title, desc+"\r\n设备已释放，可以移除。", walk.MsgBoxIconInformation)
		})
	}()
}

func (u *ui) flashProgress(phase string, done, total int64, rate float64) {
	u.syncUI(func() {
		if total > 0 {
			value := int(float64(done) * 1000 / float64(total))
			if value > 1000 {
				value = 1000
			}
			u.progress.SetValue(value)
			u.setStatus(fmt.Sprintf("%s · %s / %s · 请勿拔卡", phaseName(phase), HumanBytes(done), HumanBytes(total)))
		} else {
			u.setStatus(phaseName(phase) + " · 请勿拔卡")
		}
	})
}

func (u *ui) flashFailure(o *FlashOutcome) string {
	if o != nil && o.FileVerify != nil && !o.FileVerify.OK() {
		for _, f := range o.FileVerify.Files {
			if !f.OK {
				u.appendLog(fmt.Sprintf("文件失败 %s：%s", f.Name, f.Err))
			}
		}
		return "文件级校验失败：" + o.FileVerify.FirstError()
	}
	if o != nil && o.Image != nil && !o.Image.VerifyOK {
		return fmt.Sprintf("镜像回读不一致：首个偏移 %d，不一致字节 %d", o.Image.MismatchOff, o.Image.MismatchCnt)
	}
	return "未取得完整的写后校验结果"
}
func (u *ui) flashSuccess(o *FlashOutcome) (string, string) {
	if o.FormatOnly {
		return "格式化完成，未写入文件", "已回读核对 " + o.Layout.Summary() + "。这不是刷机卡，也不是安全擦除。"
	}
	if o.IsCard {
		for _, f := range o.FileVerify.Files {
			u.appendLog(fmt.Sprintf("通过 %s · SHA-256 %s", f.Name, shortHash(f.GotSHA)))
		}
		return "文件写入及校验通过", o.Layout.Summary() + "；" + o.FileVerify.Summary() + "。未验证设备启动。"
	}
	u.appendLog("镜像 SHA-256：" + o.Image.SHA256)
	u.appendLog("回读 SHA-256：" + o.Image.ReadSHA256)
	return "镜像写入范围内回读一致", "已核对 " + HumanBytes(o.Image.VerifyBytes) + "。未核验范围外区域，未验证设备启动。"
}
