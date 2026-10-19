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

// 执行期禁用清单里不能混进 nil 控件：曾因区块构造顺序调整，
// 清单里登记了尚未创建的控件（typed nil），点「执行配置」即 SIGSEGV。
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
