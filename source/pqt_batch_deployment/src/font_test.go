package main

// 字体覆盖回归测试。
//
// 背景：内嵌的思源黑体是**子集**（3919 个字形），并不覆盖全部标点。
// 之前界面里用了全角冒号「：」和「✓/⚠/→/•/×」，在 Linux 上因为系统还有
// 其他 CJK 字体兜底而不明显，在 Windows 上直接渲染成方块（已实拍复现）。
//
// 这里扫描所有界面字符串字面量，断言每个非 ASCII 字符都在内嵌字体里
// 有字形，避免以后再引入缺字形的标点。新增文案若触发失败，改用字体里
// 已有的等价写法（例如用半角冒号），或在 assets 里换一份覆盖更全的字体。

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"testing"

	"golang.org/x/image/font/sfnt"
)

// embeddedFontGlyphSet 返回内嵌字体覆盖的码点集合。
func embeddedFontGlyphSet(t *testing.T) map[rune]bool {
	t.Helper()

	data, err := ReadAsset("SourceHanSansCN-Medium.otf")
	if err != nil {
		t.Fatalf("读取内嵌字体失败: %v", err)
	}
	f, err := sfnt.Parse(data)
	if err != nil {
		t.Fatalf("解析内嵌字体失败: %v", err)
	}

	var buf sfnt.Buffer
	set := map[rune]bool{}
	// 只枚举 BMP + 常见 SMP 区间；覆盖不到的生僻字本来也不该出现在 UI 里。
	for r := rune(0x20); r <= 0xFFFF; r++ {
		idx, err := f.GlyphIndex(&buf, r)
		if err != nil {
			continue
		}
		if idx != 0 {
			set[r] = true
		}
	}
	return set
}

// uiStringLiterals 收集非测试 .go 文件里的所有字符串字面量。
func uiStringLiterals(t *testing.T) []string {
	t.Helper()

	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	fset := token.NewFileSet()
	var out []string
	for _, name := range files {
		if filepath.Ext(name) != ".go" || len(name) > 8 && name[len(name)-8:] == "_test.go" {
			continue
		}
		src, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		af, err := parser.ParseFile(fset, name, src, 0)
		if err != nil {
			t.Fatalf("%s 解析失败: %v", name, err)
		}
		ast.Inspect(af, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok || lit.Kind != token.STRING {
				return true
			}
			s, err := strconv.Unquote(lit.Value)
			if err != nil {
				return true
			}
			out = append(out, s)
			return true
		})
	}
	return out
}

func TestUIStringsCoveredByEmbeddedFont(t *testing.T) {
	glyphs := embeddedFontGlyphSet(t)
	if len(glyphs) < 1000 {
		t.Fatalf("内嵌字体只解析到 %d 个字形，解析大概率有问题", len(glyphs))
	}

	missing := map[rune][]string{}
	for _, s := range uiStringLiterals(t) {
		for _, r := range s {
			if r < 0x80 { // ASCII 一定安全
				continue
			}
			if !glyphs[r] {
				found := false
				for _, prev := range missing[r] {
					if prev == s {
						found = true
						break
					}
				}
				if !found {
					missing[r] = append(missing[r], s)
				}
			}
		}
	}
	if len(missing) == 0 {
		return
	}

	keys := make([]rune, 0, len(missing))
	for r := range missing {
		keys = append(keys, r)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	for _, r := range keys {
		t.Errorf("字符 %q (U+%04X) 在内嵌字体里没有字形，界面会显示成方块；出现在: %q",
			string(r), r, missing[r][0])
	}
}

// 帮助文本是用户最先看到的长文案，单独兜一层。
func TestHelpTextHasNoMissingGlyph(t *testing.T) {
	glyphs := embeddedFontGlyphSet(t)
	// 与 gui.go 的 showHelp 用同一份文案：这里直接抓取该字符串字面量。
	var help string
	for _, s := range uiStringLiterals(t) {
		if len(s) > 200 && contains(s, "批量部署工具 使用说明") {
			help = s
			break
		}
	}
	if help == "" {
		t.Fatal("没找到帮助文本字面量")
	}
	for _, r := range help {
		if r < 0x80 {
			continue
		}
		if !glyphs[r] {
			t.Errorf("帮助文本里的 %q (U+%04X) 缺字形", string(r), r)
		}
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})()
}
