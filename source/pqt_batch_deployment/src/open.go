package main

import (
	"os/exec"
	"runtime"
)

// openPath 用系统默认程序打开目录/文件（对应旧版 QDesktopServices::openUrl）。
func openPath(p string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("explorer", p)
	case "darwin":
		cmd = exec.Command("open", p)
	default:
		cmd = exec.Command("xdg-open", p)
	}
	return cmd.Start()
}
