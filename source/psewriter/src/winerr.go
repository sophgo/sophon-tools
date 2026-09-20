// Windows 错误分类 (MYS-1062 十九轮) —— 放在**无构建标签**的文件里, 便于在 Linux 上跑单测。
//
// 背景 (现场): 写卡到最后一步报
//     ✗ 刷盘失败 (数据可能仍在缓存): The request is not supported.
// 数据其实已经写完, 卡死在了"收尾的辅助调用"上: `winDisk.Sync()` 里有一句
// `IOCTL_DISK_UPDATE_PROPERTIES`, 它只是让 Windows 重新枚举分区表 (资源管理器里能
// 看到新分区), 跟数据是否落盘**无关**; 但 USB 读卡器的磁盘驱动普遍不实现这个
// IOCTL, 返回 ERROR_NOT_SUPPORTED, 于是整次写入被判失败。
//
// 判据: 这类"设备不实现某个请求"的错误码 (与数据错误区分开) 不应该让写入失败。
package main

import (
	"errors"
	"syscall"
)

// Win32 错误码 (与 windows.ERROR_* 同值; 这里自己定义以便非 Windows 平台也能编译/单测)
const (
	errIncorrectFunction = syscall.Errno(1)  // ERROR_INVALID_FUNCTION: 设备不实现该请求
	errNotSupported      = syscall.Errno(50) // ERROR_NOT_SUPPORTED: 设备不支持该请求
)

// deviceUnsupported 该错误是否属于"设备不实现这个请求"(而非数据/介质错误)。
// 这类错误对"收尾辅助动作"(刷新缓存 / 重枚举分区表) 可以降级为告警:
// 真正的落盘保证来自写句柄的 FILE_FLAG_WRITE_THROUGH 与写后回读校验。
func deviceUnsupported(err error) bool {
	if err == nil {
		return false
	}
	return errors.Is(err, errIncorrectFunction) || errors.Is(err, errNotSupported)
}
