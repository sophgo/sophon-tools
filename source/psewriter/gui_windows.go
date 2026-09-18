//go:build windows

// Windows 图形界面 (lxn/walk)
//
// 布局按「先想清楚要做什么, 再选东西」的顺序排:
//
//	① 选择目标设备 → ② 选择要做什么 (模式 + 该模式的设置) → ③ 开始 → 日志
//
// 模式提到最前面 (MYS-1237): 现场第一件要想清楚的事是"我要干什么", 而不是
// "我要选哪个文件"。三个模式各自只显示自己需要的设置, 用不上的控件直接收起来 ——
// 以前"写入方式"这种少数情况下才要动的开关摆在主界面上, 容易让人以为必须选。
//
// 两条硬规则 (MYS-1062 七轮, 针对"控件乱/缩进错位"的反馈):
//  1. 只读信息一律用**两列「项目/内容」表格**展示, 不用空格对齐 —— 中文是双宽字符,
//     用 ASCII 空格补位必然错位 (且 TextEdit 默认是比例字体, 补位也白补)。
//  2. 每个区块一个 GroupBox (带边框与标题), 内部首行是"控件 + 右侧按钮",
//     按钮固定宽度, 不使用会把文字挤到边上的超长标签。
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

// taskMode 界面上"要做什么"
type taskMode int

const (
	modeMakeCard   taskMode = iota // 制作刷机卡: 文件包/目录 → 格式化成 MBR+FAT32 的卡
	modeWriteImage                 // 写入整盘镜像: 逐字节写 .img
	modeFormatOnly                 // 只格式化 TF 卡: 只建 MBR+FAT32, 不写文件
)

type ui struct {
	mw *walk.MainWindow

	// ① 目标设备
	devBox  *walk.ComboBox
	showAll *walk.CheckBox

	// ② 要做什么
	modeCard   *walk.RadioButton
	modeImage  *walk.RadioButton
	modeFormat *walk.RadioButton
	modeInfo   *walk.TextEdit // 当前模式的说明 (跟着模式换)

	// ② 数据源 (制作刷机卡 / 写入整盘镜像)
	srcRow  *walk.Composite
	imgEdit *walk.LineEdit
	imgInfo *walk.TextEdit
	advChk  *walk.CheckBox // 「高级选项」: 收起时下面的控件不生效
	advRow  *walk.Composite
	modeBox *walk.ComboBox
	fastFS  *walk.CheckBox

	// ② 只格式化
	fmtRow   *walk.Composite
	labelEdt *walk.LineEdit

	// ③ 核对目标磁盘
	propView  *walk.TableView
	propModel *kvModel
	partView  *walk.TableView
	partModel *partTableModel
	confirm   *walk.CheckBox

	// 底部: 状态 / 进度 / 操作 / 日志
	progress  *walk.ProgressBar
	status    *walk.Label
	log       *walk.TextEdit
	btnStart  *walk.PushButton
	btnCancel *walk.PushButton

	disks    []*DiskInfo
	prep       *PreparedSource // 当前来源的解析结果 (分析完成后可用)
	prepTarget int64           // 解析时用的目标盘容量 (判据: 换盘后需重算分区大小)
	prepFull   bool            // 解析时用的"按整卡建分区"选项
	imgPath    string          // 空 = 使用内置数据源
	useEmbed bool
	ready    bool // 来源已解析可用 (内置数据源恒为 true)
	busy     bool
	dedup    logDedup // 连续重复的日志不再刷屏

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

// mode 当前选中的模式 (没选中任何一项时按"制作刷机卡"处理, 那是默认项)
func (u *ui) mode() taskMode {
	switch {
	case u.modeImage != nil && u.modeImage.Checked():
		return modeWriteImage
	case u.modeFormat != nil && u.modeFormat.Checked():
		return modeFormatOnly
	}
	return modeMakeCard
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
		MenuItems: []MenuItem{
			Menu{Text: "文件(&F)", Items: []MenuItem{
				Action{Text: "刷新设备列表(&R)", OnTriggered: func() { u.refresh() }},
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
						Model:                 []string{"(未发现可写入的设备)"},
						CurrentIndex:          0,
						StretchFactor:         1,
						ToolTipText:           "选择要写入的目标 TF 卡。系统盘永远不会出现在这里。",
						OnCurrentIndexChanged: func() { u.onSelect() },
					},
					PushButton{
						Text:        "刷新",
						MaxSize:     Size{Width: 64},
						ToolTipText: "重新扫描本机磁盘（插拔读卡器后点这里，快捷键 F5）",
						OnClicked:   func() { u.refresh() },
					},
					CheckBox{
						AssignTo:         &u.showAll,
						Text:             "全部",
						ToolTipText:      "勾选后也会列出被判定为「需人工确认」的固定盘（SATA/NVMe 等）。\n系统盘始终不会出现在列表里。",
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
					ToolTipText: "目标设备上现有的分区。写入会覆盖这里的全部分区。",
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
			group("② 选择要做什么",
				RadioButtonGroup{
					Buttons: []RadioButton{
						{
							AssignTo: &u.modeCard,
							Text:     "制作刷机卡 — 把文件包 / 目录写进卡里（推荐）",
							ToolTipText: "卡会被格式化为 MBR+FAT32，再把文件包/目录里的文件写进去。\n" +
								"SE5 / SE7 / SE9 的恢复卡用这个。",
							OnClicked: func() { u.onModeChanged() },
						},
						{
							AssignTo: &u.modeImage,
							Text:     "写入整盘镜像 — 逐字节写入 .img 等整卡镜像",
							ToolTipText: "把 .img/.raw/.iso（或其 gz/xz/bz2/zst 压缩体）逐字节写到卡上。\n" +
								"卡上原有的分区表会被镜像里的分区表取代。",
							OnClicked: func() { u.onModeChanged() },
						},
						{
							AssignTo: &u.modeFormat,
							Text:     "只格式化 TF 卡 — 只建 MBR+FAT32，不写入任何文件",
							ToolTipText: "整张卡格式化为 MBR + 1×FAT32（与写卡时先建的那种格式完全一样）。\n" +
								"卡被格成 exFAT/NTFS/GPT、或 FAT32 被写坏时，用它快速恢复；\n" +
								"格式化完成后可以直接用资源管理器把文件拷进去。",
							OnClicked: func() { u.onModeChanged() },
						},
					},
				},
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
								ToolTipText:   "当前使用的数据源（镜像 / 压缩包 / 目录）。默认是程序内置的。",
							},
							PushButton{
								Text:    "浏览文件…",
								MaxSize: Size{Width: 84},
								ToolTipText: "选择镜像文件或压缩包：\n" +
									"· 整盘镜像 .img/.raw/.iso，或其 gz/xz/bz2/zst 压缩体\n" +
									"· 归档 zip/7z/rar/tar/tar.gz/tar.xz（内含单个镜像 → 整盘写入）\n" +
									"· 文件包（内含一批文件）→ 把卡格式化为 MBR+FAT32 后写入文件",
								OnClicked: func() { u.pickImage() },
							},
							PushButton{
								Text:    "浏览目录…",
								MaxSize: Size{Width: 84},
								ToolTipText: "直接选一个目录当数据源（不必先打包）：\n" +
									"· 目录内容原样写进卡根目录（等价于把该目录打成文件包）\n" +
									"· 目录里若多套了一层（如 se7/sdbootrecoveryfiles/…），自动定位到刷机包那一层\n" +
									"· 软链按目标文件处理；FAT32 放不下的条目（设备文件/断链）跳过并计数",
								OnClicked: func() { u.pickDir() },
							},
							PushButton{
								Text:        "内置数据源",
								MaxSize:     Size{Width: 84},
								ToolTipText: "切回程序自带的内置数据源（默认来源）",
								OnClicked:   func() { u.useEmbedded() },
							},
						),
						TextEdit{
							AssignTo:    &u.imgInfo,
							ReadOnly:    true,
							VScroll:     true,
							MinSize:     Size{Height: 60},
							ToolTipText: "当前数据源的说明。默认使用程序内置的数据源。",
						},
						row(
							CheckBox{
								AssignTo: &u.advChk,
								Text:     "高级选项",
								ToolTipText: "默认：写入方式自动识别，分区按整卡容量建（推荐）。\n" +
									"只有自动识别不准、或想按内容大小建分区时才需要展开。\n" +
									"收起时下面两项不生效。",
								OnCheckedChanged: func() { u.onAdvancedChanged() },
							},
							HSpacer{},
						),
						Composite{
							AssignTo: &u.advRow,
							Layout:   HBox{MarginsZero: true, Spacing: 6},
							Visible:  false,
							Children: []Widget{
								Label{Text: "写入方式", ToolTipText: "自动识别：归档里只有一个镜像文件 → 整盘写入；否则按文件包格式化建卡。\n识别不准时可在这里强制指定。"},
								ComboBox{
									AssignTo:              &u.modeBox,
									Model:                 []string{"自动识别", "整盘镜像", "文件包 → MBR+FAT32"},
									CurrentIndex:          0,
									MaxSize:               Size{Width: 160},
									ToolTipText:           "自动识别 / 强制整盘镜像 / 强制按文件包格式化建卡",
									OnCurrentIndexChanged: func() { u.repreview() },
								},
								CheckBox{
									AssignTo:         &u.fastFS,
									Text:             "按内容建分区",
									ToolTipText:      "勾选：只按文件内容大小建 FAT32 分区 —— 快，但卡上剩余空间不属于该分区。\n不勾（推荐）：按整卡容量格式化，整张卡都能用。\n（两种都是快速格式化，只写文件系统结构与文件，不擦除空白区）",
									OnCheckedChanged: func() { u.repreview() },
								},
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
							Label{Text: "卷标", ToolTipText: "格式化后卡在资源管理器里显示的名字（≤11 字符，仅 A-Z 0-9 _ -）"},
							LineEdit{
								AssignTo:    &u.labelEdt,
								Text:        "SE",
								MaxSize:     Size{Width: 140},
								ToolTipText: "留空则用默认卷标 SE。卷标只是给人看的，不影响设备引导。",
							},
							HSpacer{},
						),
					},
				},
			),
			// ③ 开始
			group("③ 开始",
				CheckBox{
					AssignTo:         &u.confirm,
					Text:             "我已核对目标设备，确认覆盖且不可恢复",
					ToolTipText:      "写入会覆盖目标设备上的全部分区与数据，且不可恢复。\n请确认上面选中的确实是 TF 卡，不是本机硬盘。",
					OnCheckedChanged: func() { u.updateHint() },
				},
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
						Text:        "开始写入",
						MinSize:     Size{Width: 120, Height: 32},
						MaxSize:     Size{Width: 120},
						ToolTipText: "开始写入。写完后会自动做两级校验：\n① 回读逐字节比对  ② 从卡上挂 FAT32 逐文件比对 sha256",
						OnClicked:   func() { u.start() },
					},
					PushButton{
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

	u.stretchLastColumns()

	// 模式默认选第一项 —— 显式设一下, 不依赖 Win32 对单选框组的默认勾选行为
	if u.modeCard != nil {
		u.modeCard.SetChecked(true)
	}
	// 「取消分析」只在分析期间出现
	if u.btnCancel != nil {
		u.btnCancel.SetVisible(false)
	}
	u.refresh()
	u.applyMode()   // 按默认模式摆好各区块的显隐与说明
	u.useEmbedded() // 默认使用内置数据源
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
	u.setModeInfo(m)
	if m == modeFormatOnly {
		u.btnStart.SetText("开始格式化")
		u.btnStart.SetToolTipText("开始格式化。写完后回读核对分区表 / BPB / FAT 两份副本。\n" +
			"只格式化模式不写入任何文件，所以没有文件级校验。")
	} else {
		u.btnStart.SetText("开始写入")
		u.btnStart.SetToolTipText("开始写入。写完后会自动做两级校验：\n① 回读逐字节比对  ② 从卡上挂 FAT32 逐文件比对 sha256")
	}
}

// setModeInfo ② 里那行说明: 一句话讲清"选了这个模式会发生什么"
func (u *ui) setModeInfo(m taskMode) {
	if u.modeInfo == nil {
		return
	}
	var s string
	switch m {
	case modeWriteImage:
		s = "把整卡镜像（.img/.raw/.iso，或 gz/xz/bz2/zst/zip/7z/rar/tar 压缩体）逐字节写到卡上。\r\n" +
			"卡上原有的分区表会被镜像里的分区表取代。"
	case modeFormatOnly:
		s = "整张卡格式化为 MBR + 1×FAT32（与写卡时先建的那种格式完全一样），不写入任何文件。\r\n" +
			"卡被格成 exFAT/NTFS/GPT、或 FAT32 被写坏时用它快速恢复；格式化完成后可以直接用资源管理器往里拷文件。"
	default:
		s = "卡会被格式化为 MBR + FAT32，再把文件包 / 目录里的文件写进去 —— SE5/SE7/SE9 的刷机卡用这个。\r\n" +
			"数据源优先用 .zip 发版包（打开即分析完），也可以选目录或程序内置的包。"
	}
	u.modeInfo.SetText(s)
}

// onModeChanged 用户换了模式
func (u *ui) onModeChanged() {
	m := u.mode()
	u.applyMode()
	// 换了模式就重新确认一次: 勾选确认是对"这次要做的操作"的确认, 不该跟着模式一起搬过去
	u.confirm.SetChecked(false)
	if m == modeFormatOnly {
		// 只格式化不需要数据源: 在途的分析作废, 也不再显示数据源信息
		u.cancelAnalyze()
		u.prep, u.ready = nil, true
		u.imgEdit.SetText("（只格式化不使用数据源）")
		u.appendLog("模式: 只格式化 TF 卡 — 只建 MBR+FAT32, 不写入任何文件")
	} else {
		if !u.useEmbed && u.imgPath == "" {
			u.ready = false
		}
		u.imgEdit.SetText(u.srcDisplayText())
		u.repreview()
	}
	u.updateHint()
}

// onAdvancedChanged 展开/收起高级选项。
// 收起时下面两个控件不生效 (forcedMode / fastFSWanted 都看这个勾), 所以这里要重新解析。
func (u *ui) onAdvancedChanged() {
	on := u.advChk.Checked()
	u.advRow.SetVisible(on)
	if !on {
		u.appendLog("高级选项已收起: 写入方式自动识别, 分区按整卡容量")
	}
	u.repreview()
}

// srcDisplayText 数据源输入框该显示的文字
func (u *ui) srcDisplayText() string {
	switch {
	case u.imgPath != "":
		return u.imgPath
	case u.useEmbed:
		return "内置数据源（默认）"
	}
	return "(未选择)"
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
	if u.busy || u.status == nil || u.btnStart == nil || u.analyzing.Load() {
		return
	}
	d := u.current()
	switch {
	case d == nil:
		u.setStatus("第 1 步：请选择目标设备（没有可选项时点「刷新」）")
		u.btnStart.SetEnabled(false)
	case u.mode() == modeFormatOnly:
		if u.confirm.Checked() {
			u.setStatus(fmt.Sprintf("就绪：把磁盘 %d (%s) 整盘格式化为 MBR+FAT32（不写入文件）",
				d.Index, HumanBytes(d.Size)))
		} else {
			u.setStatus("第 3 步：勾选上面的确认框，然后点「开始格式化」")
		}
		u.btnStart.SetEnabled(true)
	case !u.useEmbed && u.imgPath == "":
		u.setStatus("第 2 步：请选择数据源（或点「内置数据源」用自带的）")
		u.btnStart.SetEnabled(true)
	case !u.ready:
		u.setStatus("第 2 步：数据源尚未就绪（重新选择文件，或点「内置数据源」）")
		u.btnStart.SetEnabled(false)
	case !u.confirm.Checked():
		u.setStatus("第 3 步：勾选上面的确认框，然后点「开始写入」")
		u.btnStart.SetEnabled(true)
	default:
		u.setStatus(fmt.Sprintf("就绪：%s → 磁盘 %d (%s)", u.sourceName(), d.Index, HumanBytes(d.Size)))
		u.btnStart.SetEnabled(true)
	}
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
	walk.MsgBox(u.mw, "关于 SE写卡工具",
		fmt.Sprintf("SE写卡工具 v%s\n\n"+
			"制作 SE 系列设备（SE5/SE7/SE9）的 TF 卡，三种模式：\n"+
			"· 制作刷机卡：文件包 / 目录 → 快速格式化为 MBR+FAT32 并写入\n"+
			"· 写入整盘镜像：.img/.raw/.iso（或 gz/xz/bz2/zst/zip/7z/rar/tar 压缩体）逐字节写入\n"+
			"· 只格式化 TF 卡：只建 MBR+FAT32，不写入任何文件\n\n"+
			"写后回读校验：文件包模式回读比对 + 从卡上挂 FAT32 逐文件 sha256；\n"+
			"只格式化模式回读核对分区表 / BPB / FAT 两份副本。\n\n"+
			"安全: 系统盘永不出现在设备列表里；写盘前需勾选确认并二次确认。", toolVersion),
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
	disks, err := enumerateDisks()
	if err != nil {
		u.setStatus("枚举磁盘失败")
		u.appendLog("✗ 枚举磁盘失败: " + err.Error())
		return
	}
	shown := SelectableDisks(disks, u.showAll.Checked())
	u.disks = shown
	labels := make([]string, 0, len(shown))
	for _, d := range shown {
		labels = append(labels, deviceLabel(d))
	}
	if len(labels) == 0 {
		labels = []string{"(未发现可写入的设备 — 插入读卡器后点「刷新」)"}
		u.appendLog(fmt.Sprintf("发现 %d 个磁盘, 没有可安全烧录的设备 (插入 TF 卡读卡器; 勾选「全部」可查看固定盘)", len(disks)))
	} else {
		u.appendLog(fmt.Sprintf("发现 %d 个磁盘, 可写入 %d 个", len(disks), len(shown)))
	}
	u.devBox.SetModel(labels)
	if len(shown) > 0 {
		u.devBox.SetCurrentIndex(0)
	} else {
		u.devBox.SetCurrentIndex(0)
	}
	u.onSelect()
}

func (u *ui) current() *DiskInfo {
	i := u.devBox.CurrentIndex()
	if i < 0 || i >= len(u.disks) {
		return nil
	}
	return u.disks[i]
}

func (u *ui) onSelect() {
	d := u.current()
	if d == nil {
		u.propModel.Set([][2]string{{"状态", "未选择设备"}})
		u.partModel.Set(nil)
		u.updateHint()
		return
	}
	u.propModel.Set(d.PropertyRows())
	u.partModel.Set(d.PartitionRows())
	u.confirm.SetChecked(false)
	u.repreview()
	u.updateHint()
	if d.Safety == SafetyUnknown {
		u.appendLog(fmt.Sprintf("⚠ 磁盘 %d 判定为「%s」— 若非 TF 卡请立即改选其它设备", d.Index, d.Safety))
	}
}

// useEmbedded 切回程序内置镜像 (默认源)
func (u *ui) useEmbedded() {
	u.cancelAnalyze() // 让在途的分析结果作废
	u.prep, u.ready = nil, true
	u.setImageInfo(SourceInfoText(nil, nil))
	if !HasEmbeddedImage() {
		u.useEmbed = false
		u.imgPath = ""
		u.ready = false
		u.imgEdit.SetText("(本程序未内置数据源 — 请点「浏览文件…」/「浏览目录…」选择)")
		u.appendLog("数据源: 未内置")
		u.updateHint()
		return
	}
	u.useEmbed = true
	u.imgPath = ""
	u.imgEdit.SetText("内置数据源（默认）")
	u.appendLog("数据源: 内置 — " + EmbeddedSummary())
	// 内置数据源也要解析 (可能是整盘镜像, 也可能是文件包/压缩包): 走同一条异步分析
	u.repreview()
}

func (u *ui) pickImage() {
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

// forcedMode 界面下拉框 → 强制模式 (nil = 自动)。
// 高级选项收起时一律自动识别 —— 看不见的开关不该在背后生效。
func (u *ui) forcedMode() *SourceMode {
	if u.advChk == nil || !u.advChk.Checked() {
		return nil
	}
	switch u.modeBox.CurrentIndex() {
	case 1:
		m := ModeRawDisk
		return &m
	case 2:
		m := ModeFilePackage
		return &m
	}
	return nil
}

// fastFSWanted 勾选 = 按内容大小建分区 (同样只在高级选项展开时生效)
func (u *ui) fastFSWanted() bool {
	return u.advChk != nil && u.advChk.Checked() && u.fastFS.Checked()
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
	// 只格式化没有数据源可解析 —— 分区大小按当前这张卡现算 (见 currentPrep)
	if u.mode() == modeFormatOnly {
		u.cancelAnalyze()
		u.prep, u.ready = nil, true
		u.updateHint()
		return
	}
	// 没有内置数据源又没选文件 → 没什么可分析的
	if u.imgPath == "" && !HasEmbeddedImage() {
		u.cancelAnalyze()
		u.prep, u.ready = nil, false
		u.setImageInfo(SourceInfoText(nil, nil))
		u.updateHint()
		return
	}
	target := int64(0)
	if d := u.current(); d != nil {
		target = d.Size
	}
	// 内置数据源同样要解析: 它可能是整盘镜像, 也可能是文件包/压缩包 (十九轮修正)
	path, mode, full := u.imgPath, u.forcedMode(), !u.fastFSWanted()
	u.prepTarget, u.prepFull = target, full

	u.probeGen++
	gen := u.probeGen
	// 每次分析一个**独立的**取消令牌。共用一个标志的话, 新一轮分析一开始就把它清成
	// false, 上一轮那条还在解压 14 GiB 压缩包的 goroutine 会以为自己没被取消,
	// 继续把整条流跑完 (连点几下就是几路并发解压)。
	cancel := &atomic.Bool{}
	u.probeCancel = cancel
	u.beginAnalyze()

	go func() {
		ctl := &ProbeCtl{
			Progress: func(phase string, done, total int64) {
				u.syncUI(func() {
					if gen == u.probeGen {
						u.showAnalyzeProgress(done, total)
					}
				})
			},
			Canceled: cancel.Load,
		}
		prep, err := PrepareSource(path, mode, target, full, 0, "", ctl)
		u.syncUI(func() {
			if gen != u.probeGen {
				return // 已有更新的分析, 这次结果作废
			}
			u.endAnalyze()
			if err != nil {
				u.prep, u.ready = nil, false
				msg := err.Error()
				if errors.Is(err, ErrProbeCanceled) {
					msg = "分析已取消"
				}
				u.setImageInfo("来源：" + dataSourceLabel(path) + "\r\n状态：" + msg)
				u.appendLog("✗ 来源不可用: " + msg)
				u.updateHint()
				return
			}
			u.prep, u.ready = prep, true
			u.prepTarget, u.prepFull = target, full
			u.setImageInfo(SourceInfoText(prep.Archive, prep.Plan))
			if prep.Archive != nil {
				u.appendLog(fmt.Sprintf("来源: %s  格式 %s  写入方式 %s",
					dataSourceLabel(path), formatLabel(prep.Archive.Format), prep.Archive.Mode))
				for _, kv := range prep.Archive.BootRootLines() {
					if strings.HasPrefix(kv[0], "⚠") {
						u.appendLog("⚠ " + kv[1])
					} else {
						u.appendLog(kv[0] + "：" + kv[1])
					}
				}
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
	u.closed.Store(true)
	u.cancelProbe()
	u.mw.Close()
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

// spinFrames 动态图标的帧 (盲文点阵, 等宽字体下都显示得出来)
var spinFrames = []rune{'⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'}

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
func (u *ui) currentPrep() (*PreparedSource, error) {
	target := int64(0)
	if d := u.current(); d != nil {
		target = d.Size
	}
	// 只格式化: 计划只跟"当前这张卡 + 卷标"有关, 每次现算 (换卡必须重算分区大小)
	if u.mode() == modeFormatOnly {
		return PrepareFormat(target, u.labelEdt.Text())
	}
	full := !u.fastFSWanted()
	if u.prep != nil && u.ready && u.prepTarget == target && u.prepFull == full {
		return u.prep, nil
	}
	if u.prep == nil && !u.ready {
		return nil, fmt.Errorf("数据源尚未解析完成 (请稍候或重新选择)")
	}
	return PrepareSource(u.imgPath, u.forcedMode(), target, full, 0, "", nil)
}

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
	if u.busy {
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

	u.busy = true
	u.btnStart.SetEnabled(false)
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
			u.busy = false
			u.btnStart.SetEnabled(true)
			if err != nil {
				u.progress.SetValue(0)
				u.setStatus("生成失败 — 见日志")
				u.appendLog("✗ 生成失败: " + err.Error())
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

func (u *ui) start() {
	if u.busy || u.analyzing.Load() {
		return
	}
	d := u.current()
	if d == nil {
		walk.MsgBox(u.mw, "未选择磁盘", "请先在上方列表选择一个目标磁盘。", walk.MsgBoxIconWarning)
		return
	}
	formatOnly := u.mode() == modeFormatOnly
	if !formatOnly && !u.useEmbed && u.imgPath == "" {
		walk.MsgBox(u.mw, "未选择镜像", "请先选择镜像文件, 或点「内置数据源」。", walk.MsgBoxIconWarning)
		return
	}
	if !u.confirm.Checked() {
		walk.MsgBox(u.mw, "未确认", "请先勾选「我已核对上述磁盘与分区…」。", walk.MsgBoxIconWarning)
		return
	}
	// 来源已经解析好了 (分析阶段完成), 这里不再有"生成卡镜像"的等待
	prep, err := u.currentPrep()
	if err != nil {
		u.setStatus("来源不可用")
		walk.MsgBox(u.mw, "来源不可用", err.Error(), walk.MsgBoxIconError)
		return
	}
	u.progress.SetValue(0)
	if !formatOnly {
		if n := prep.TotalSize(); n > 0 && d.Size < n {
			walk.MsgBox(u.mw, "容量不足",
				fmt.Sprintf("目标 %s 小于镜像 %s", HumanBytes(d.Size), HumanBytes(n)), walk.MsgBoxIconError)
			return
		}
	}

	// 二次确认: 只格式化与写入的措辞分开, 让人一眼看清这次要做什么
	var title, msg, imgTag string
	if formatOnly {
		title = "二次确认 — 开始格式化?"
		msg = fmt.Sprintf("即将格式化:\n\n目标磁盘: %s (磁盘 %d, %s)\n型号: %s\n分区数: %d\n\n"+
			"操作: 只格式化 — 在卡上建 MBR + 1×FAT32, 不写入任何文件\n卷标: %s\n分区大小: %s\n\n"+
			"该磁盘全部分区与数据将被覆盖, 不可恢复。确认执行?",
			d.Path, d.Index, HumanBytes(d.Size), d.Model, len(d.Partitions),
			prep.Plan.Label, HumanBytes(prep.Plan.PartSize))
	} else {
		imgTag = "文件包 → MBR+FAT32"
		if prep.Src != nil {
			imgTag = prep.Src.Display()
			if prep.Src.Embedded() {
				imgTag += "  [内置镜像]"
			}
		}
		extra := ""
		if prep.Archive != nil {
			extra = fmt.Sprintf("\n来源: %s\n格式: %s\n写入方式: %s\n",
				filepath.Base(prep.Archive.Path), formatLabel(prep.Archive.Format), prep.Archive.Mode)
			if prep.IsCard() {
				extra += "（目标卡将被格式化为 MBR + FAT32, 原有分区与数据全部丢失）\n"
			}
		}
		title = "二次确认 — 开始烧录?"
		msg = fmt.Sprintf("即将烧录:\n\n目标磁盘: %s (磁盘 %d, %s)\n型号: %s\n分区数: %d\n%s\n镜像: %s (%s)\n\n该磁盘全部分区将被覆盖, 数据不可恢复。确认执行?",
			d.Path, d.Index, HumanBytes(d.Size), d.Model, len(d.Partitions), extra, imgTag, HumanBytes(prep.TotalSize()))
	}
	if d.Safety == SafetyUnknown {
		msg = "⚠ 目标被判为「" + d.Safety.String() + "」: " + d.Reason + "\n\n" + msg
	}
	if walk.MsgBox(u.mw, title, msg,
		walk.MsgBoxYesNo|walk.MsgBoxIconWarning|walk.MsgBoxDefButton2) != walk.DlgCmdYes {
		u.appendLog("已取消 (用户未确认)")
		return
	}

	u.busy = true
	u.btnStart.SetEnabled(false)
	u.log.SetText("")
	u.dedup.Reset()
	u.progress.SetValue(0)
	verb := "写入"
	if formatOnly {
		verb = "格式化"
	}
	u.setStatus("正在" + verb + "…")
	if formatOnly {
		u.appendLog(fmt.Sprintf("开始格式化 %s → %s (只建 MBR+FAT32, 不写入任何文件)", prep.Plan.Label, d.Path))
	} else {
		u.appendLog(fmt.Sprintf("开始写入 %s → %s", imgTag, d.Path))
		if prep.IsCard() {
			u.appendLog("写入方式: 直接在卡上建 MBR+FAT32 (不生成中间镜像, 未用空间不擦除)")
		}
	}

	go func() {
		start := time.Now()
		code := flashToDiskGUI(u, d, prep)
		u.mw.Synchronize(func() {
			u.busy = false
			u.btnStart.SetEnabled(true)
			u.appendLog(fmt.Sprintf("总耗时 %s", time.Since(start).Round(time.Second)))
			if code == 0 {
				u.setStatus("完成 — 校验通过，可以拔卡使用")
				walk.MsgBox(u.mw, verb+"完成", verb+"并回读校验通过, 可以拔卡使用。", walk.MsgBoxIconInformation)
			} else {
				u.setStatus("失败 — 见日志；请勿使用该卡")
				walk.MsgBox(u.mw, verb+"失败", "见窗口下方日志; 请勿直接使用该卡。", walk.MsgBoxIconError)
			}
		})
	}()
}

// flashToDiskGUI = RunFlash 的 GUI 版 (进度与日志都同步到窗口)
func flashToDiskGUI(u *ui, d *DiskInfo, prep *PreparedSource) int {
	prog := func(phase string, done, total int64, rate float64) {
		u.mw.Synchronize(func() {
			if total > 0 {
				u.progress.SetValue(int(float64(done) * 1000 / float64(total)))
				u.setStatus(fmt.Sprintf("%s %5.1f%%  %s/%s  %s",
					phaseName(phase), float64(done)*100/float64(total), HumanBytes(done), HumanBytes(total), HumanRate(rate)))
			} else {
				u.setStatus(fmt.Sprintf("%s %s  %s", phaseName(phase), HumanBytes(done), HumanRate(rate)))
			}
		})
	}
	out, err := RunFlash(d, prep, true, prog, func(format string, a ...interface{}) {
		u.mw.Synchronize(func() { u.appendLog(fmt.Sprintf(format, a...)) })
	})
	if err != nil {
		u.mw.Synchronize(func() { u.appendLog("✗ " + err.Error()) })
		return 1
	}

	if out.IsCard {
		res := out.Card
		doneWord := "写入完成"
		if out.FormatOnly {
			doneWord = "格式化完成"
		}
		u.mw.Synchronize(func() {
			u.progress.SetValue(1000)
			u.appendLog(fmt.Sprintf("%s: %s / %s (%.1f MiB/s)", doneWord, HumanBytes(res.WrittenBytes),
				res.Elapsed.Round(time.Millisecond), mibPerSec(res.WrittenBytes, res.Elapsed)))
			tail := "剩余空间不擦除"
			if out.FormatOnly {
				tail = "剩余空间不擦除, 卡上没有写入任何文件"
			}
			u.appendLog(fmt.Sprintf("快速格式化: 卡容量 %s, 实写 %s, 未触碰 %s (%s)",
				HumanBytes(res.TotalSize), HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes), tail))
			if out.Layout != nil {
				if out.Layout.OK() {
					u.appendLog("✓ 回读校验: " + out.Layout.Summary())
				} else {
					u.appendLog("✗ 文件系统结构核对失败: " + strings.Join(out.Layout.Problems, "; "))
				}
			}
		})
		if out.Layout == nil || !out.Layout.OK() {
			return 1
		}
		fv := out.FileVerify
		if fv == nil {
			// 只格式化: 卡上本来就没有文件, 结构核对通过即可交付
			u.mw.Synchronize(func() {
				walk.MsgBox(u.mw, "格式化完成",
					"卡已格式化为 MBR + FAT32 并通过回读校验, 可以直接用资源管理器往里拷文件。",
					walk.MsgBoxIconInformation)
			})
			return 0
		}
		u.mw.Synchronize(func() {
			u.appendLog("文件级校验 (" + fv.Summary() + "):")
			for _, f := range fv.Files {
				mark := "✓"
				note := ""
				if !f.OK {
					mark = "✗"
					note = "  " + f.Err
				}
				u.appendLog(fmt.Sprintf("  %s %-40s %10s  sha256 %s%s", mark, f.Name, HumanBytes(f.Size), shortHash(f.GotSHA), note))
			}
			if fv.OK() {
				u.appendLog(fmt.Sprintf("✓ 文件级校验通过: 卡上 %d 个文件与源压缩包完全一致", fv.OKCount))
				layoutDesc := "文件系统结构已回读确认"
				if out.Layout != nil {
					layoutDesc = out.Layout.Summary()
				}
				walk.MsgBox(u.mw, "写入完成",
					fmt.Sprintf("卡已写入并通过两级校验:\n\n① 回读校验: %s\n② 文件级校验: %s\n\n可以拔卡使用。",
						layoutDesc, fv.Summary()), walk.MsgBoxIconInformation)
			} else {
				u.appendLog("✗ 文件级校验失败: " + fv.FirstError())
				walk.MsgBox(u.mw, "文件级校验失败",
					"卡上文件与源压缩包不一致, 请勿使用该卡:\n\n"+fv.FirstError(), walk.MsgBoxIconError)
			}
		})
		if !fv.OK() {
			return 1
		}
		return 0
	}

	res := out.Image
	u.mw.Synchronize(func() {
		u.progress.SetValue(1000)
		u.appendLog(fmt.Sprintf("写入完成: 实写 %s / %s (%.1f MiB/s)", HumanBytes(res.WrittenBytes),
			res.WriteElapsed.Round(time.Millisecond), mibPerSec(res.WrittenBytes, res.WriteElapsed)))
		if res.SkippedBytes > 0 {
			u.appendLog(fmt.Sprintf("稀疏写入: 镜像共 %s, 其中 %s 全零且卡上本就是零 → 未写",
				HumanBytes(res.ImageBytes), HumanBytes(res.SkippedBytes)))
		}
		u.appendLog("镜像 sha256: " + res.SHA256)
		u.appendLog("回读 sha256: " + res.ReadSHA256)
		if res.VerifyOK {
			u.appendLog("✓ 回读校验通过: " + HumanBytes(res.VerifyBytes))
		} else {
			u.appendLog(fmt.Sprintf("✗ 回读校验失败: 首个不一致偏移 %d, 不一致字节 %d", res.MismatchOff, res.MismatchCnt))
		}
	})
	if res.VerifyOK {
		return 0
	}
	return 1
}
