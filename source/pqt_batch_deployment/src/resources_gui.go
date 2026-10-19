package main

import (
	"net/url"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"

	"fyne.io/fyne/v2/theme"
)

// logoResource 把内嵌 PNG 包成 Fyne 资源（旧版走 Qt qrc，这里走 go:embed）。
func logoResource() fyne.Resource {
	data, err := ReadAsset("sophgo-logo-new2.png")
	if err != nil {
		return theme.FyneLogo()
	}
	return fyne.NewStaticResource("sophgo-logo-new2.png", data)
}

// appIcon 窗口/任务栏图标。
func appIcon() fyne.Resource {
	data, err := ReadAsset("ic_action_database.png")
	if err != nil {
		return theme.FyneLogo()
	}
	return fyne.NewStaticResource("ic_action_database.png", data)
}

func parseURL(s string) *url.URL {
	u, err := url.Parse(s)
	if err != nil {
		return nil
	}
	return u
}

// imageFromAsset 供需要 canvas.Image 的场景使用。
func imageFromAsset(name string) *canvas.Image {
	data, err := ReadAsset(name)
	if err != nil {
		return canvas.NewImageFromResource(theme.FyneLogo())
	}
	return canvas.NewImageFromResource(fyne.NewStaticResource(name, data))
}


