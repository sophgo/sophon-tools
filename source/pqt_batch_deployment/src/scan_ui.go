//go:build !headless

package main

// 局域网扫描对话框（桌面版）。
//
// 交互要点：
//   * 先选网口/填网段/MAC 前缀，点「开始扫描」；
//   * 扫描结果勾选后，用一组统一的 SSH 凭据批量加入左侧设备列表；
//   * 页面上**固定标注**"可能触发网关防火墙"的提示——ARP 只在本网段广播、
//     不经过网关，但如果网段填成了跨网段，或本机装了网络监控/IDS，
//     仍可能产生告警，必须让用户知情。

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

// scanDialog 扫描对话框的状态。
type scanDialog struct {
	g *gui

	ifaceSel *widget.Select
	cidr     *widget.Entry
	macPre   *widget.Entry
	timeout  *widget.Select
	mode     *widget.Select

	status     *widget.Label
	resultHint *widget.Label
	list       *widget.List
	checks     []bool
	results    []ScanResult

	// 批量添加用的 SSH 凭据
	portE *widget.Entry
	userE *widget.Entry
	passE *widget.Entry

	scanning bool
	cancel   context.CancelFunc
	d        dialog.Dialog
}

// showScanDialog 打开局域网扫描对话框。
func (g *gui) showScanDialog() {
	sd := &scanDialog{g: g}

	sd.ifaceSel = widget.NewSelect(listScanInterfaces(), nil)
	if opts := sd.ifaceSel.Options; len(opts) > 0 {
		sd.ifaceSel.SetSelectedIndex(0)
	}

	sd.cidr = widget.NewEntry()
	sd.cidr.SetPlaceHolder("例如 192.168.1.0/24")
	sd.cidr.SetText(guessLocalCIDR(sd.ifaceSel.Selected))

	sd.macPre = widget.NewEntry()
	sd.macPre.SetPlaceHolder("留空=全部;支持 00:1a、001a2b、98:a9:2d 等任意长度")

	sd.timeout = widget.NewSelect([]string{"2 秒", "4 秒", "8 秒", "15 秒"}, nil)
	sd.timeout.SetSelected("4 秒")

	// 扫描方式：auto 优先 ARP，拿不到 MAC 时自动降级
	sd.mode = widget.NewSelect([]string{
		"自动(优先 ARP，拿不到 MAC 时改用 Ping)",
		"仅 ARP(需 root，能按 MAC 过滤)",
		"仅 Ping(无需权限，拿不到 MAC)",
	}, nil)
	sd.mode.SetSelectedIndex(0)

	sd.status = widget.NewLabel("尚未扫描")
	sd.status.TextStyle = fyne.TextStyle{Italic: true}
	sd.resultHint = widget.NewLabel("")

	sd.list = widget.NewList(
		func() int { return len(sd.results) },
		func() fyne.CanvasObject {
			chk := widget.NewCheck("", nil)
			ip := canvas.NewText("", colorText)
			mac := canvas.NewText("", colorTextMuted)
			mac.TextSize = theme.Size(theme.SizeNameCaptionText)
			return container.NewHBox(chk, ip, layout.NewSpacer(), mac)
		},
		func(i widget.ListItemID, o fyne.CanvasObject) {
			row := o.(*fyne.Container)
			chk := row.Objects[0].(*widget.Check)
			ip := row.Objects[1].(*canvas.Text)
			mac := row.Objects[3].(*canvas.Text)
			if i < 0 || i >= len(sd.results) {
				return
			}
			r := sd.results[i]
			ip.Text = r.IP
			ip.Refresh()
			mac.Text = r.MAC
			mac.Refresh()
			chk.OnChanged = func(v bool) {
				if i < len(sd.checks) {
					sd.checks[i] = v
					sd.updateHint()
				}
			}
			chk.SetChecked(sd.checks[i])
		},
	)

	// 批量 SSH 凭据
	sd.portE = widget.NewEntry()
	sd.portE.SetText("22")
	sd.userE = widget.NewEntry()
	sd.userE.SetText("linaro")
	sd.passE = widget.NewPasswordEntry()
	sd.passE.SetText("linaro")

	scanBtn := widget.NewButtonWithIcon("开始扫描", theme.SearchIcon(), func() {
		sd.startScan()
	})
	scanBtn.Importance = widget.HighImportance
	addBtn := widget.NewButtonWithIcon("添加选中设备", theme.ContentAddIcon(), func() {
		sd.addSelected()
	})
	allBtn := widget.NewButton("全选", func() { sd.setAll(true) })
	noneBtn := widget.NewButton("全不选", func() { sd.setAll(false) })

	// —— 防火墙提示（用户要求必须标注）——
	warnLabel := widget.NewLabel(
		"提示:本功能使用 ARP 在本网段广播发现设备，请求不会经过网关，也不依赖目标机开放任何端口，" +
			"因此通常不会触发目标机防火墙。但如果网段填成跨网段地址、或本机/交换机上装有网络监控与 IDS，" +
			"仍可能产生告警。请确认已获得网络管理授权后再扫描。")
	warnLabel.Wrapping = fyne.TextWrapWord
	warnLabel.TextStyle = fyne.TextStyle{}
	warnLabel.Importance = widget.WarningImportance
	warnBox := container.NewStack(
		func() fyne.CanvasObject {
			r := canvas.NewRectangle(colorWarningSoft)
			r.CornerRadius = 8
			return r
		}(),
		container.New(&insetLayout{x: 10, y: 8}, warnLabel),
	)

	form := widget.NewForm(
		widget.NewFormItem("网口", sd.ifaceSel),
		widget.NewFormItem("网段", sd.cidr),
		widget.NewFormItem("MAC 前缀", sd.macPre),
		widget.NewFormItem("等待时间", sd.timeout),
		widget.NewFormItem("扫描方式", sd.mode),
	)

	credForm := widget.NewForm(
		widget.NewFormItem("SSH 端口", sd.portE),
		widget.NewFormItem("用户名", sd.userE),
		widget.NewFormItem("密码", sd.passE),
	)

	body := container.NewBorder(
		container.NewVBox(warnBox, form, container.NewHBox(scanBtn, sd.status)),
		container.NewVBox(
			widget.NewSeparator(),
			container.NewHBox(sd.resultHint, layout.NewSpacer(), allBtn, noneBtn, addBtn),
			credForm,
		),
		nil, nil,
		listFrame(sd.list),
	)

	sd.d = dialog.NewCustom("扫描局域网设备", "关闭", body, g.win)
	sd.d.Resize(fyne.NewSize(720, 760))
	sd.d.Show()
}

func (sd *scanDialog) setAll(v bool) {
	for i := range sd.checks {
		sd.checks[i] = v
	}
	sd.list.Refresh()
	sd.updateHint()
}

func (sd *scanDialog) updateHint() {
	n := 0
	for _, v := range sd.checks {
		if v {
			n++
		}
	}
	sd.resultHint.SetText(fmt.Sprintf("共 %d 台，已选 %d 台", len(sd.results), n))
}

func (sd *scanDialog) startScan() {
	if sd.scanning {
		return
	}
	prefix, err := NormalizeMACPrefix(sd.macPre.Text)
	if err != nil {
		showError(err, sd.g.win)
		return
	}
	if _, _, err := parseScanCIDR(sd.cidr.Text); err != nil {
		showError(err, sd.g.win)
		return
	}
	timeout := 4
	if n, err := strconv.Atoi(strings.Fields(sd.timeout.Selected)[0]); err == nil {
		timeout = n
	}

	ctx, cancel := context.WithCancel(context.Background())
	sd.cancel = cancel
	sd.scanning = true
	// 提示文案要跟随所选模式，不能一律写 ARP
	switch scanModeFromIndex(sd.mode.SelectedIndex()) {
	case ScanModePing:
		sd.status.SetText("正在扫描…（ICMP echo，不需权限）")
	case ScanModeARP:
		sd.status.SetText("正在扫描…（ARP 广播，不经过网关）")
	default:
		sd.status.SetText("正在扫描…（优先 ARP，不经过网关）")
	}
	sd.results = nil
	sd.checks = nil
	sd.list.Refresh()
	sd.updateHint()

	opts := ScanOptions{
		Interface: sd.ifaceSel.Selected,
		CIDR:      sd.cidr.Text,
		MACPrefix: prefix,
		Timeout:   secondsDur(timeout),
		Mode:      scanModeFromIndex(sd.mode.SelectedIndex()),
	}

	go func() {
		res, err := ScanLAN(ctx, opts)
		fyne.Do(func() {
			sd.scanning = false
			sd.cancel = nil
			if err != nil {
				sd.status.SetText("扫描失败")
				showError(err, sd.g.win)
				return
			}
			sd.results = res.Results
			sd.checks = make([]bool, len(res.Results))
			for i := range sd.checks {
				sd.checks[i] = true // 默认全选，符合"批量添加"的意图
			}
			sd.list.Refresh()
			sd.updateHint()

			msg := fmt.Sprintf("扫描完成:网段内 %d 个地址，找到 %d 台（%.1fs）",
				res.Total, len(res.Results), res.Elapsed.Seconds())
			switch res.Method {
			case "arp":
				sd.status.SetText(msg + "，方式:ARP 广播")
			case "ping":
				sd.status.SetText(msg + "，方式:ICMP Ping（无 MAC）")
			default:
				sd.status.SetText(msg + "，方式:本机 ARP 缓存（权限不足，未主动发包）")
			}
			if res.Note != "" {
				sd.resultHint.SetText(res.Note)
			}
		})
	}()
}

func (sd *scanDialog) addSelected() {
	port, err := strconv.Atoi(strings.TrimSpace(sd.portE.Text))
	if err != nil || port <= 0 || port > 65535 {
		showError(fmt.Errorf("SSH 端口必须是 1-65535 的整数"), sd.g.win)
		return
	}
	user := strings.TrimSpace(sd.userE.Text)
	if user == "" {
		showError(fmt.Errorf("用户名不能为空"), sd.g.win)
		return
	}

	// 已在列表里的 IP 不重复添加
	existing := map[string]bool{}
	for _, d := range sd.g.state.Devices() {
		existing[d.Inf.IP] = true
	}

	added, skipped := 0, 0
	for i, r := range sd.results {
		if i >= len(sd.checks) || !sd.checks[i] {
			continue
		}
		if existing[r.IP] {
			skipped++
			continue
		}
		sd.g.state.AppendDevice(RemoteInf{
			IP: r.IP, Port: port, Username: user, Password: sd.passE.Text,
		})
		existing[r.IP] = true
		added++
	}

	sd.g.refreshTables()
	sd.g.refreshStats()

	msg := fmt.Sprintf("已添加 %d 台设备", added)
	if skipped > 0 {
		msg += fmt.Sprintf("，跳过 %d 台（已存在）", skipped)
	}
	sd.g.setStatus(msg)
	if added == 0 && skipped == 0 {
		showInfo("提示", "没有选中任何设备", sd.g.win)
	}
}

// listFrame 给 List 套上和 tableFrame 一致的圆角边框。
func listFrame(l *widget.List) fyne.CanvasObject {
	bg := canvas.NewRectangle(colorSurface)
	bg.StrokeColor = colorBorder
	bg.StrokeWidth = 1
	bg.CornerRadius = 8
	return container.NewStack(bg, container.New(&insetLayout{x: 1, y: 1}, l))
}

// scanModeFromIndex 把下拉序号映射成模式。
func scanModeFromIndex(i int) string {
	switch i {
	case 1:
		return ScanModeARP
	case 2:
		return ScanModePing
	}
	return ScanModeAuto
}
