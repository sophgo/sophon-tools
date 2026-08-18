package bm25

import (
	"strings"
	"unicode"
)

var stopCN = map[string]struct{}{}
var stopEN = map[string]struct{}{}

func init() {
	for _, w := range strings.Fields("的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 些 什么 而 为 所 以 之 与 及 但 或 从 被 把 对 将 能 可以 已经 因为 所以 如果 虽然 但是 然而 然后 因此 不过 此外 另外 还 又 再 更 最 非常 比较 可能 应该 必须 需要 能够 想 让 使 用 来 做 进行 通过 根据 按照 关于 对于 由于 以及 并且 而且 或者 还是 只 只是 主要 一般 一些 很多 每个 所有 任何 其他 别的 某 某个 某些") {
		stopCN[w] = struct{}{}
	}
	for _, w := range strings.Fields("a an the and or but in on at to for of with by from as is was are be been being have has had do does did will would shall should can could may might must need dare ought used this that these those it i me my we us our you your he him his she her they them their what which who whom whose when where why how all any each every both few more most other some such only own same so than too very s t don now no not just because if then else after before while during about into through above between under again further once here there and an") {
		stopEN[w] = struct{}{}
	}
}

// Tokenize 中英混合分词：汉字序列按 2-gram 滑窗切分（查询/文档片段重叠即可命中，
// 与 jieba 效果对齐的轻量替代）；英文单词/数字各一个 token；滤停用词、滤单字符。
func Tokenize(text string) []string {
	lower := strings.ToLower(text)
	runes := []rune(lower)
	var tokens []string
	i := 0
	n := len(runes)
	for i < n {
		r := runes[i]
		if unicode.Is(unicode.Han, r) {
			j := i
			for j < n && unicode.Is(unicode.Han, runes[j]) {
				j++
			}
			seq := runes[i:j]
			// 滑窗 bigram：长度 <2 的单字序列信息量低，直接丢弃
			for k := 0; k+1 < len(seq); k++ {
				w := string(seq[k : k+2])
				if _, ok := stopCN[w]; !ok {
					tokens = append(tokens, w)
				}
			}
			i = j
		} else if isAlnum(r) {
			j := i
			for j < n && isAlnum(runes[j]) {
				j++
			}
			w := string(runes[i:j])
			if len(w) > 1 {
				if _, ok := stopEN[w]; !ok {
					tokens = append(tokens, w)
				}
			}
			i = j
		} else {
			i++
		}
	}
	return tokens
}

func isAlnum(r rune) bool {
	return (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9')
}
