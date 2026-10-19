//go:build headless

package main

// headless 构建：不编译任何 Fyne 代码，因此**不链接** X11/GL/wayland，
// 可以在没有图形栈的服务器上直接运行。无参数时默认启动 Web UI。

import "fmt"

func runDefaultUI() int {
	fmt.Println("headless 构建:启动 Web UI（无图形栈环境）")
	return runWeb(webOptions{Listen: "127.0.0.1:8080"})
}
