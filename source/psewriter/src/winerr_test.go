// 设备"不支持该请求"错误分类 单测 (MYS-1062 十九轮, Linux 可跑)
//
// 现场: USB 读卡器上 IOCTL_DISK_UPDATE_PROPERTIES 返回 ERROR_NOT_SUPPORTED,
// 被当成致命错误 → 明明写完的卡被判成失败。这里钉住"哪些错误码属于这种情况"。
package main

import (
	"errors"
	"fmt"
	"syscall"
	"testing"
)

func TestDeviceUnsupported(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"nil", nil, false},
		{"ERROR_NOT_SUPPORTED(50) 设备不支持", syscall.Errno(50), true},
		{"ERROR_INVALID_FUNCTION(1) 设备不实现", syscall.Errno(1), true},
		{"包一层也要认出来", fmt.Errorf("刷盘失败: %w", syscall.Errno(50)), true},
		{"ERROR_ACCESS_DENIED(5) 是真错误", syscall.Errno(5), false},
		{"ERROR_WRITE_FAULT(29) 是真错误", syscall.Errno(29), false},
		{"普通错误", errors.New("boom"), false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := deviceUnsupported(c.err); got != c.want {
				t.Errorf("deviceUnsupported(%v) = %v, 期望 %v", c.err, got, c.want)
			}
		})
	}
}
