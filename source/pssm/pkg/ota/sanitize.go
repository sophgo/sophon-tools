package ota

import (
	"path/filepath"
	"regexp"
	"strings"
)

// safeFileNameRE 白名单：仅字母、数字、下划线、点、连字符。
var safeFileNameRE = regexp.MustCompile(`^[a-zA-Z0-9_.-]+$`)

// sanitizeFileName 清理文件名，防止路径穿越。
// 先拒绝含路径分隔符的穿越尝试，再取 Base 经白名单与长度校验；非法返回 ""。
func sanitizeFileName(name string) string {
	// 拒绝路径分隔符（/、\）—— filepath.Base 会丢弃目录部分，
	// 但先显式拒绝可防止攻击者用合法 base 名绕过意图检测。
	if strings.ContainsAny(name, "/\\") {
		return ""
	}
	base := filepath.Base(name)
	if base == "." || base == ".." || base == "" {
		return ""
	}
	if len(base) > 255 {
		return ""
	}
	if !safeFileNameRE.MatchString(base) {
		return ""
	}
	return base
}
