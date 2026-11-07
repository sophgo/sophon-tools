// Package ident 识别检索词与标题里的"标识符"（寄存器名 / 函数名 / 命令名）。
//
// 判据只有两条：token 里含下划线，且去掉下划线后长度 ≥ 4。中文、纯字母词
// （I2C）与纯数字词（1080p）都不是标识符——它们是普通自然语言词，属于
// BM25 与向量的打分范围，不该拿到"标题精确匹配"这条高权重通路。
package ident

import "strings"

// MinStrippedLen 去掉下划线后保留的最短长度。
//
// 4 是"够不够像标识符"的最低门槛：rtc_ctrl_status1 → rtcctrlstatus1(14) 通过；
// rtc_ → rtc(3) 被排除，避免 `_` 附近的碎片把普通词拉进高权重通路。
const MinStrippedLen = 4

// Identifiers 抽取文本里的标识符 token（小写、去重、保持首次出现顺序）。
//
// 只认 ASCII 标识符字符集 [a-z0-9_]，因此中文不会被误判；`-` 不是标识符字符，
// `sophon-sail` 会被切成 sophon / sail 两个不含下划线的词，自然被排除。
func Identifiers(text string) []string {
	var out []string
	seen := map[string]bool{}
	for _, tok := range asciiTokens(text) {
		if !isIdentifier(tok) || seen[tok] {
			continue
		}
		seen[tok] = true
		out = append(out, tok)
	}
	return out
}

// isIdentifier 单个小写 token 是否是标识符。
func isIdentifier(tok string) bool {
	if !strings.Contains(tok, "_") {
		return false
	}
	return len(strings.ReplaceAll(tok, "_", "")) >= MinStrippedLen
}

// asciiTokens 把文本切成连续的小写 [a-z0-9_] 片段。
func asciiTokens(s string) []string {
	var out []string
	var cur strings.Builder
	flush := func() {
		if cur.Len() > 0 {
			out = append(out, cur.String())
			cur.Reset()
		}
	}
	for _, r := range strings.ToLower(s) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '_':
			cur.WriteRune(r)
		default:
			flush()
		}
	}
	flush()
	return out
}
