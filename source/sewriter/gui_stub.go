//go:build !windows

package main

import (
	"fmt"
	"os"
)

// runGUI 非 Windows 平台无 GUI (本文件仅在 Linux/macOS 自测时编译)
func runGUI() int {
	fmt.Fprintln(os.Stderr, "图形界面仅 Windows 提供; 本平台请使用命令行: se7flash list | write | verify | hash")
	return 2
}
