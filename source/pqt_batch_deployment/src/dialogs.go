package main

// 对话框封装。
//
// Fyne 内置 dialog.ShowConfirm / ShowInformation 的按钮文案取自
// lang.L("Yes"/"No"/"OK")，没有中文语言包时就是英文——中文界面里弹出
// 「Yes / No / OK」很突兀。这里统一换成中文，并且只在这一处定义，
// 避免每个调用点各写一遍。

import (
	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/widget"
)

// showInfo 单按钮提示框。
func showInfo(title, msg string, parent fyne.Window) {
	d := dialog.NewCustom(title, "知道了", widget.NewLabel(msg), parent)
	d.Show()
}

// showError 错误提示框。
func showError(err error, parent fyne.Window) {
	d := dialog.NewCustom("错误", "知道了", widget.NewLabel(err.Error()), parent)
	d.SetOnClosed(nil)
	d.Show()
}

// showConfirm 确认框；确认键用危险色，因为本程序里它只用于删除与中止这类操作。
func showConfirm(title, msg string, onYes func(), parent fyne.Window) {
	content := widget.NewLabel(msg)
	content.Wrapping = fyne.TextWrapWord
	d := dialog.NewCustomConfirm(title, "确认", "取消", content, func(ok bool) {
		if ok && onYes != nil {
			onYes()
		}
	}, parent)
	d.SetConfirmImportance(widget.DangerImportance)
	d.Show()
}
