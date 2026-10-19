//go:build !headless

package main

// 桌面构建（默认）：无参数启动 Fyne GUI；--web 也能用。

import (
	"fmt"
	"os"
)

// runDefaultUI 无参数时的入口。
func runDefaultUI() int {
	// 服务器上常见的失败是「DISPLAY 没设」——给出可操作的提示，
	// 而不是让 Fyne 抛一句 PlatformUnavailable 了事。
	if os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "" {
		fmt.Fprintln(os.Stderr, "错误: 没有检测到图形环境（DISPLAY / WAYLAND_DISPLAY 均为空）。")
		fmt.Fprintln(os.Stderr, "      本机若无图形栈，请用 Web 模式:")
		fmt.Fprintf(os.Stderr, "        %s --web --listen 127.0.0.1:8080\n", os.Args[0])
		fmt.Fprintln(os.Stderr, "      或使用 headless 构建（不链接 X11/GL，默认即 Web 模式）。")
		return 2
	}
	return runGUI()
}
