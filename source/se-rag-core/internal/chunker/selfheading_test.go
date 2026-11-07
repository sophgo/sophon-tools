package chunker

import (
	"reflect"
	"testing"
)

// 分块自身标题：跳过 heading-v3 的【祖先】前缀，取块内全部标题行（不含 `#`）。
func TestSelfHeadings(t *testing.T) {
	cases := []struct {
		name string
		text string
		want []string
	}{
		{
			"带祖先前缀与 Offset 后缀",
			"【3 系统概述 › 3.9 看门狗 › 3.9.5 寄存器描述】\n#### WDT_STAT（Offset 0x010）\n\n| Bits | Name |\n",
			[]string{"WDT_STAT（Offset 0x010）"},
		},
		{
			"祖先前缀本身不是标题",
			"【A › B】\n正文没有标题\n",
			nil,
		},
		{
			// heading-v3 会把相邻短小节打包进同一块：被问到的那节未必是第一条标题。
			"打包后的多个标题",
			"【6. 各模块编译方法】\n### 6.1 build_fsbl（FSBL / fip.bin）\n内容\n### 6.2 build_kernel（Kernel / boot.itb）\n内容\n",
			[]string{"6.1 build_fsbl（FSBL / fip.bin）", "6.2 build_kernel（Kernel / boot.itb）"},
		},
		{
			"带章节编号",
			"【祖先】\n### 6.2 build_kernel（Kernel / boot.itb）\n正文\n",
			[]string{"6.2 build_kernel（Kernel / boot.itb）"},
		},
		{
			"多级标题",
			"# 一级\n## 二级\n### 三级\n#### 四级\n",
			[]string{"一级", "二级", "三级", "四级"},
		},
		{
			// 围栏内的 # 是注释或 markdown 示例，不是标题
			"围栏代码块里的 # 不算标题",
			"【祖先】\n### build_kernel\n\n```bash\n# 这是 shell 注释\n## 这也是注释\nbuild_kernel\n```\n",
			[]string{"build_kernel"},
		},
		{
			"五级标题不算",
			"##### 五级\n#### 四级\n",
			[]string{"四级"},
		},
		{
			"空块",
			"",
			nil,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := SelfHeadings(c.text)
			if len(got) == 0 && len(c.want) == 0 {
				return
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("SelfHeadings(%q) = %v, want %v", c.text, got, c.want)
			}
		})
	}
}

// 真实分块器产出的块：从正文里确实能取回寄存器标题（防 heading-v3 前缀格式变化）。
func TestSelfHeadingsOnChunkedDatasheet(t *testing.T) {
	doc := "# 3 系统概述\n\n## 3.9 看门狗\n\n### 3.9.5 寄存器描述\n\n" +
		"#### WDT_STAT（Offset 0x010）\n\n| Bits | Name |\n| --- | --- |\n| 0 | wdt_en |\n"
	chunks := NewDefaultChunker().ChunkFile(doc, "ds.md")
	if len(chunks) == 0 {
		t.Fatal("expected at least one chunk")
	}
	found := false
	for _, c := range chunks {
		for _, h := range SelfHeadings(c.Text) {
			if h == "WDT_STAT（Offset 0x010）" {
				found = true
			}
		}
	}
	if !found {
		t.Fatalf("chunked text must expose the register heading, got chunks: %+v", chunks)
	}
}
