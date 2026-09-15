//go:build windows

// 选择"目录"的系统对话框 (MYS-1062 十八轮④)
//
// lxn/walk 只封装了文件对话框, 没有目录选择; 这里直接调 shell32 的
// SHBrowseForFolderW (Win95 起就有, Win7+ 全兼容), 不引入新依赖、不动 CGO
// (本项目 CGO_ENABLED=0 交叉编译)。
//
// 失败 (API 缺失/用户取消) 一律返回空串, 由调用方决定后续动作 —— 不做任何猜测。
package main

import (
	"syscall"
	"unsafe"
)

const (
	bifReturnOnlyFSDirs = 0x0001 // 只允许选目录 (排除"网上邻居"等虚节点)
	bifEditBox          = 0x0010 // 允许直接粘路径
	bifNewDialogStyle   = 0x0040 // 新版可调整大小的对话框
	bifUseNewUI         = bifEditBox | bifNewDialogStyle
	maxPath             = 260
)

type browseInfoW struct {
	hwndOwner      uintptr
	pidlRoot       uintptr
	pszDisplayName *uint16
	lpszTitle      *uint16
	ulFlags        uint32
	lpfn           uintptr
	lParam         uintptr
	iImage         int32
}

var (
	shell32              = syscall.NewLazyDLL("shell32.dll")
	procSHBrowseForFldr  = shell32.NewProc("SHBrowseForFolderW")
	procSHGetPathFromIDL = shell32.NewProc("SHGetPathFromIDListW")
	ole32                = syscall.NewLazyDLL("ole32.dll")
	procCoTaskMemFree    = ole32.NewProc("CoTaskMemFree")
)

// pickDirectory 弹系统目录选择框; 返回空串 = 用户取消或不可用
func pickDirectory(owner uintptr, title string) string {
	t, err := syscall.UTF16PtrFromString(title)
	if err != nil {
		return ""
	}
	buf := make([]uint16, maxPath)
	bi := browseInfoW{
		hwndOwner:      owner,
		pszDisplayName: &buf[0],
		lpszTitle:      t,
		ulFlags:        bifReturnOnlyFSDirs | bifUseNewUI,
	}
	pidl, _, _ := procSHBrowseForFldr.Call(uintptr(unsafe.Pointer(&bi)))
	if pidl == 0 {
		return "" // 用户取消
	}
	defer procCoTaskMemFree.Call(pidl)

	out := make([]uint16, maxPath)
	ok, _, _ := procSHGetPathFromIDL.Call(pidl, uintptr(unsafe.Pointer(&out[0])))
	if ok == 0 {
		return ""
	}
	return syscall.UTF16ToString(out)
}
