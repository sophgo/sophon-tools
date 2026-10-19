//go:build !headless

package main

// GUI 构造与状态切换冒烟测试（Fyne 内存驱动，无需显示器）。

import (
	"reflect"
	"strings"
	"testing"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/test"
	"fyne.io/fyne/v2/widget"
)

func newTestGUI(t *testing.T) *gui {
	t.Helper()
	a := test.NewApp()
	t.Cleanup(a.Quit)
	a.Settings().SetTheme(newAppTheme())

	g := &gui{state: NewGUIState(), selectedOp: -1, app: a}
	g.win = a.NewWindow("test")
	g.win.SetContent(g.content())
	return g
}

// 界面上所有已声明的控件字段都必须构造完成。
//
// 曾因区块构造顺序调整，清单里登记了尚未创建的控件（typed nil），
// 点「执行配置」即 SIGSEGV。只扫 lockable 不够：opComplete / statusDot /
// deviceLog / deviceLabel / stat* 这些不在清单里，一旦有人把
// refreshDeviceLog / setStatusKind / updateOpCompleteLabel 的调用点前移到
// content() 组装过程中（同一个坑的另一种形态），只扫清单的用例仍然全绿。
func TestGUIAllWidgetsConstructed(t *testing.T) {
	g := newTestGUI(t)

	// 用反射遍历 gui 结构体里所有「可能是控件」的字段，
	// 免得以后新增控件忘了加进这条断言。
	gv := reflect.ValueOf(g).Elem()
	gt := gv.Type()
	for i := 0; i < gt.NumField(); i++ {
		f := gt.Field(i)
		tp := f.Type
		if tp.Kind() != reflect.Ptr && tp.Kind() != reflect.Interface {
			continue
		}
		if gv.Field(i).IsNil() && (tp.Implements(canvasObjectType) || tp.Implements(disableableType)) {
			t.Errorf("字段 %s (%s) 为 nil：控件未构造就被使用，运行时会崩", f.Name, tp)
		}
	}

	// 再按名字点名。注意必须对**具体类型指针**判 nil：
	// 装进 any 之后 typed nil 不等于 nil，用 `obj == nil` 会漏判
	// （这正是当初那个 bug 骗过人工检查的原因）。
	if g.opComplete == nil {
		t.Error("opComplete 未构造（nil）")
	}
	if g.statusDot == nil {
		t.Error("statusDot 未构造（nil）")
	}
	if g.statusLbl == nil {
		t.Error("statusLbl 未构造（nil）")
	}
	if g.deviceLog == nil {
		t.Error("deviceLog 未构造（nil）")
	}
	if g.deviceLabel == nil {
		t.Error("deviceLabel 未构造（nil）")
	}
	if g.statTotal == nil || g.statOK == nil || g.statFail == nil ||
		g.statRun == nil || g.ratio == nil || g.deviceCount == nil {
		t.Error("概览统计控件未全部构造")
	}
	if g.opType == nil || g.opForms[OpCommand] == nil {
		t.Error("操作类型选择器/表单未全部构造")
	}

	// 这些路径在界面装配完成后会被立即调用，必须有控件可写。
	g.refreshDeviceLog()
	g.updateOpCompleteLabel()
	g.refreshStats()
	g.setStatusKind("就绪", colorTextMuted)
}

var (
	canvasObjectType = reflect.TypeOf((*fyne.CanvasObject)(nil)).Elem()
	disableableType  = reflect.TypeOf((*fyne.Disableable)(nil)).Elem()
)

// 执行期禁用清单里不能混进 nil 控件。
func TestGUILockableAllConstructed(t *testing.T) {
	g := newTestGUI(t)
	if len(g.lockable) == 0 {
		t.Fatal("执行期禁用清单为空")
	}
	for i, c := range g.lockable {
		if c == nil || reflect.ValueOf(c).IsNil() {
			t.Fatalf("lockable[%d] (%T) 为 nil", i, c)
		}
	}
	g.setRunningUI(true)
	if !g.opName.Disabled() || !g.rootEntry.Disabled() || !g.opType.Disabled() {
		t.Fatal("执行中配置区应被禁用")
	}
	if g.runBtn.Text != "执行中…" || !g.cancelBtn.Visible() || g.cancelBtn.Disabled() {
		t.Fatal("执行中按钮状态不对")
	}
	g.setRunningUI(false)
	if g.opName.Disabled() || g.rootEntry.Disabled() || g.opType.Disabled() {
		t.Fatal("执行结束后配置区应恢复")
	}
}

// 操作类型只有一个入口（分段选择器），切换后只显示对应表单，并写回状态。
func TestGUIOpTypeSwitch(t *testing.T) {
	g := newTestGUI(t)
	g.loadOpIntoEditor(0)
	if g.opType.Selected() != OpCommand || !g.opForms[OpCommand].Visible() {
		t.Fatal("默认操作应为命令下发且显示命令表单")
	}

	test.Tap(g.opType.btns[OpDownFile])
	if g.opType.Selected() != OpDownFile {
		t.Fatalf("切换后类型 = %d", g.opType.Selected())
	}
	for i, f := range g.opForms {
		if f.Visible() != (i == OpDownFile) {
			t.Fatalf("表单 %d 可见性不对", i)
		}
	}
	if got := g.state.Ops()[0].Inf.Type; got != OpDownFile {
		t.Fatalf("类型未写回状态: %d", got)
	}

	// 载入别的操作时只改外观，不能把类型写回去（editing 保护）。
	g.state.AppendOp(OperationInf{Name: "cmd", Type: OpCommand, CommandStr: "ls"})
	g.loadOpIntoEditor(1)
	if g.opType.Selected() != OpCommand || g.state.Ops()[0].Inf.Type != OpDownFile {
		t.Fatal("切换选中操作时串改了类型")
	}
}

// 删除到空表 / 未选中即操作，不能崩溃（旧版闪退场景）。
func TestGUIEmptyTablesNoCrash(t *testing.T) {
	g := newTestGUI(t)
	for g.state.DeviceCount() > 0 {
		g.state.RemoveDevice(0)
	}
	for len(g.state.Ops()) > 0 {
		g.state.RemoveOp(0)
	}
	g.selectedOp = -1
	g.refreshTables()
	g.refreshDeviceLog()
	g.updateOpCompleteLabel()
	if g.statTotal.value.Text != "0" {
		t.Fatalf("设备总数 = %q", g.statTotal.value.Text)
	}
	if g.saveOpEditor() {
		t.Fatal("未选中操作时不应写回")
	}
}

func TestFitText(t *testing.T) {
	s := "uname -a; echo FINAL_OK; cat /proc/cpuinfo"
	if got := fitText(s, 13, fyne.TextStyle{}, 10000); got != s {
		t.Fatalf("宽度足够时不应截断: %q", got)
	}
	got := fitText(s, 13, fyne.TextStyle{}, 80)
	if len(got) >= len(s) || got[len(got)-3:] != "..." {
		t.Fatalf("应截断并补省略号: %q", got)
	}
	if fitText("", 13, fyne.TextStyle{}, 10) != "" {
		t.Fatal("空串应原样返回")
	}
}

// 日志高频更新必须合并，但**最终内容不能被吞掉**。
// 传输过程中进度事件每 200ms 一次，每次都重建富文本会占满 UI 线程
// （2000 行实测约 18ms/次）。
//
// 断言方式：直接盯 renderNow 的调用次数，不依赖时序——若按"两次调用间隔
// 是否够长"来判断，测试跑得太快时无论有没有节流都会通过（假阳性）。
func TestLogViewThrottleKeepsFinalContent(t *testing.T) {
	a := test.NewApp()
	t.Cleanup(a.Quit)
	a.Settings().SetTheme(newAppTheme())

	v := newLogView()

	var renders int
	v.onRender = func() { renders++ }

	v.SetText("line 1\n")
	if renders != 1 {
		t.Fatalf("首次设置应立即渲染, renders=%d", renders)
	}

	// 紧接着的多次更新应被合并（不重建），原文仍要更新
	for i := 2; i <= 50; i++ {
		v.SetText(strings.Repeat("x", i) + "\n")
	}
	if renders != 1 {
		t.Fatalf("高频更新没有被合并, 重建了 %d 次", renders)
	}
	if !strings.HasSuffix(v.Text(), strings.Repeat("x", 50)+"\n") {
		t.Fatal("被合并时原文也应更新到最新")
	}

	// Flush 必须强制重建，并呈现最后一版
	v.Flush()
	if renders != 2 {
		t.Fatalf("Flush 应强制重建一次, renders=%d", renders)
	}
	last := v.rich.Segments[len(v.rich.Segments)-1].(*widget.TextSegment)
	if !strings.HasPrefix(last.Text, "xxx") {
		t.Fatalf("Flush 后日志不是最新内容: %q", last.Text)
	}

	// 已经 Flush 过就不该再重复重建
	v.Flush()
	if renders != 2 {
		t.Fatalf("无待处理内容时 Flush 不应重建, renders=%d", renders)
	}
}

// 切换设备必须立即渲染：哪怕落在节流窗口内。
// 否则标题显示 #2、正文还是 #1 的日志，而那台已完成设备不会再有事件纠正它，
// 错位会永久保留；「复制」取的是新原文，与显示不一致。
func TestLogViewSwitchSourceRendersImmediately(t *testing.T) {
	a := test.NewApp()
	t.Cleanup(a.Quit)
	a.Settings().SetTheme(newAppTheme())

	v := newLogView()
	var renders int
	v.onRender = func() { renders++ }

	v.SetTextFor("0", "device-0 log\n")
	if renders != 1 {
		t.Fatalf("首次渲染 renders=%d", renders)
	}

	// 同一来源、紧邻的更新：应被节流
	v.SetTextFor("0", "device-0 log v2\n")
	if renders != 1 {
		t.Fatalf("同来源高频更新应被合并, renders=%d", renders)
	}

	// 换来源：必须立即渲染，且立刻可见新内容
	v.SetTextFor("1", "device-1 log\n")
	if renders != 2 {
		t.Fatalf("切换设备必须立即渲染, renders=%d", renders)
	}
	last := v.rich.Segments[len(v.rich.Segments)-1].(*widget.TextSegment)
	if last.Text != "device-1 log" {
		t.Fatalf("切换后正文仍是旧内容: %q", last.Text)
	}
}

// 占位符与节流不能互相打架：曾经存在「pending=true 且 raw==""」的稳定状态，
// 之后连 Flush 都画不出东西，界面永久停在占位符。
func TestLogViewPlaceholderNotStuck(t *testing.T) {
	a := test.NewApp()
	t.Cleanup(a.Quit)
	a.Settings().SetTheme(newAppTheme())

	v := newLogView()
	var renders int
	v.onRender = func() { renders++ }

	v.SetTextFor("0", "some log\n")
	before := renders

	// 制造一个被节流的待处理状态
	v.SetTextFor("0", "some log more\n")
	if !v.pending {
		t.Fatal("应当有一个待渲染内容（用于构造后续场景）")
	}

	// 取消选中 -> 占位符：必须清掉 pending 并直接画出占位符
	v.SetPlaceholder("未选中设备")
	if v.pending {
		t.Fatal("SetPlaceholder 后不应仍处于待渲染状态")
	}
	if got := v.rich.Segments[0].(*widget.TextSegment).Text; got != "未选中设备" {
		t.Fatalf("占位符没有立即呈现: %q", got)
	}
	if renders != before {
		// 占位符是独立绘制路径，不经过 renderNow；这里只确认没有多记一次
		t.Fatalf("占位符不应走 renderNow, renders=%d want=%d", renders, before)
	}

	// 之后再选中同一台设备：即使 key 与占位符前相同，也必须立即渲染出日志
	v.SetTextFor("0", "some log more\n")
	last := v.rich.Segments[len(v.rich.Segments)-1].(*widget.TextSegment)
	if last.Text != "some log more" {
		t.Fatalf("占位符之后重新选中，正文仍是占位符: %q", last.Text)
	}
}
