package ext4

// PATCH(setf) 6: Go 1.21 起 min/max 是语言内建函数, 而 Windows 7 只能用 Go <= 1.20
// 编译 (Go 1.21 起要求 Windows 10+)。这里用泛型补上同名函数 (泛型自 Go 1.18 可用),
// 让本包在 Go 1.20 下也能编译。本工具并不使用 ext4, 保留它只是为了不动上游代码结构。
func min[T ~int | ~int32 | ~int64 | ~uint32 | ~uint64](a, b T) T {
	if a < b {
		return a
	}
	return b
}

func max[T ~int | ~int32 | ~int64 | ~uint32 | ~uint64](a, b T) T {
	if a > b {
		return a
	}
	return b
}
