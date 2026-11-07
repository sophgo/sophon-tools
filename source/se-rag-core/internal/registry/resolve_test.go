package registry

import (
	"reflect"
	"strings"
	"testing"
)

// fixtureRegistry 与 testdata 夹具同构的注册表（纯内存，不落盘）：
//
//	se9             product ready  modules=[sm9-16, sm9-8]
//	                specs=[SE9 16 → sm9-16 → bm1688, SE9 8 → sm9-8 → cv186ah]
//	se7             product ready  modules=[sm7] → bm1684x
//	se8             product ready  modules=[sm7] → bm1684x
//	sm9-16          module  placeholder chips=[bm1688]
//	sm9-8           module  placeholder chips=[cv186ah]
//	sm7             module  ready chips=[bm1684x]
//	bm1688          chip    ready        sdk=sophonsdk-edge
//	bm1684x         chip    ready        sdk=sophonsdk
//	cv186ah         chip    placeholder  sdk=sophonsdk-edge
//	cv84x6          chip    placeholder  sdk=sophonsdk-edge sdk_since=v2.3
//	sophonsdk       sdk     ready        versions=[v23.09 (2025-09-16)]
//	sophonsdk-edge  sdk     ready        versions=[v2.3 (2026-10-12), v2.2 (2026-06-22)]
func fixtureRegistry() *Registry {
	return New("/root",
		Entity{ID: "se9", Type: TypeProduct, Name: "SE9 微服务器", Status: StatusReady,
			Aliases: []string{"SE9"},
			Modules: []string{"sm9-16", "sm9-8"},
			Specs: []Spec{
				{Name: "SE9 16", Aliases: []string{"SE9 16", "SE9 16-BP1-11"}, Modules: []string{"sm9-16"}},
				{Name: "SE9 8", Aliases: []string{"SE9 8", "SE9 8-BP1-17"}, Modules: []string{"sm9-8"}},
			},
			DocsDir: "docs/products/se9", IndexDir: "rag/data/product-se9"},
		Entity{ID: "se7", Type: TypeProduct, Name: "SE7 微服务器", Status: StatusReady,
			Aliases: []string{"SE7"}, Modules: []string{"sm7"},
			DocsDir: "docs/products/se7", IndexDir: "rag/data/product-se7"},
		Entity{ID: "se8", Type: TypeProduct, Name: "SE8 微服务器", Status: StatusReady,
			Aliases: []string{"SE8"}, Modules: []string{"sm7"},
			DocsDir: "docs/products/se8", IndexDir: "rag/data/product-se8"},
		Entity{ID: "sm9-16", Type: TypeModule, Name: "SM9 16", Status: StatusPlaceholder,
			Aliases: []string{"SM9 16"}, Chips: []string{"bm1688"}},
		Entity{ID: "sm9-8", Type: TypeModule, Name: "SM9 8", Status: StatusPlaceholder,
			Aliases: []string{"SM9 8"}, Chips: []string{"cv186ah"}},
		Entity{ID: "sm7", Type: TypeModule, Name: "SM7", Status: StatusReady,
			Aliases: []string{"SM7"}, Chips: []string{"bm1684x"},
			DocsDir: "docs/modules/sm7", IndexDir: "rag/data/module-sm7"},
		Entity{ID: "bm1688", Type: TypeChip, Name: "BM1688", Status: StatusReady,
			Aliases: []string{"BM1688"}, SDK: "sophonsdk-edge",
			DocsDir: "docs/chips/bm1688", IndexDir: "rag/data/chip-bm1688"},
		Entity{ID: "bm1684x", Type: TypeChip, Name: "BM1684X", Status: StatusReady,
			Aliases: []string{"BM1684X"}, SDK: "sophonsdk",
			DocsDir: "docs/chips/bm1684x", IndexDir: "rag/data/chip-bm1684x"},
		Entity{ID: "cv186ah", Type: TypeChip, Name: "CV186AH", Status: StatusPlaceholder,
			Aliases: []string{"CV186AH"}, SDK: "sophonsdk-edge"},
		Entity{ID: "cv84x6", Type: TypeChip, Name: "CV84X6", Status: StatusPlaceholder,
			Aliases: []string{"CV84X6"}, SDK: "sophonsdk-edge", SDKSince: "v2.3"},
		sdkFixture("sophonsdk", "SOPHONSDK",
			Version{Version: "v23.09 LTS SP5", Slug: "v23.09", ReleaseDate: "2025-09-16",
				DocsDir: "docs/sdks/sophonsdk/v23.09", IndexDir: "rag/data/sdk-sophonsdk-v23.09"}),
		sdkFixture("sophonsdk-edge", "SOPHONSDK Edge",
			Version{Version: "v2.3", Slug: "v2.3", ReleaseDate: "2026-10-12",
				DocsDir: "docs/sdks/sophonsdk-edge/v2.3", IndexDir: "rag/data/sdk-sophonsdk-edge-v2.3"},
			Version{Version: "v2.2", Slug: "v2.2", ReleaseDate: "2026-06-22",
				DocsDir: "docs/sdks/sophonsdk-edge/v2.2", IndexDir: "rag/data/sdk-sophonsdk-edge-v2.2"}),
	)
}

// sdkFixture 一个 placeholder 状态的 sdk 实体（文档与索引挂在版本上）。
// sdkFixture 一个已登记版本的 sdk：status 由 versions 决定（有版本 = ready）。
func sdkFixture(id, name string, versions ...Version) Entity {
	status := StatusPlaceholder
	if len(versions) > 0 {
		status = StatusReady
	}
	return Entity{ID: id, Type: TypeSDK, Name: name, Status: status,
		Aliases: []string{id, name}, Versions: versions}
}

// Resolve：最长匹配 —— `SE9 16-BP1-11` 不能被更短的 `SE9 16` 或 `SE9` 抢先命中。
func TestResolveLongestMatch(t *testing.T) {
	reg := fixtureRegistry()
	got := reg.Resolve("SE9 16-BP1-11 的 I2C 怎么接")
	if len(got) != 1 {
		t.Fatalf("want 1 match, got %+v", got)
	}
	if got[0].SpecName != "SE9 16" {
		t.Errorf("spec = %q, want SE9 16", got[0].SpecName)
	}
	if got[0].EntityID != "se9" {
		t.Errorf("entity = %q, want the product se9 (specs are not entities)", got[0].EntityID)
	}
	if got[0].Alias != "SE9 16-BP1-11" {
		t.Errorf("alias = %q, want the longest one %q", got[0].Alias, "SE9 16-BP1-11")
	}
	if got[0].Text != "SE9 16-BP1-11" {
		t.Errorf("text = %q, want the original span %q", got[0].Text, "SE9 16-BP1-11")
	}
}

// 仅出现短别名时命中的是短别名（产品本身，不带变体）。
func TestResolveShortAlias(t *testing.T) {
	reg := fixtureRegistry()
	got := reg.Resolve("SE9 的网络怎么配")
	if len(got) != 1 || got[0].Alias != "SE9" || got[0].SpecName != "" {
		t.Fatalf("want a bare SE9 match, got %+v", got)
	}
}

// 大小写 / 空格 / 连字符 / 下划线不敏感。
func TestResolveNormalizationInsensitive(t *testing.T) {
	texts := []string{
		"se9 16-bp1-11 的 I2C",
		"SE9 16 BP1 11 的 I2C",
		"se9_16_BP1_11 的 I2C",
		"SE9-16-BP1-11 的 I2C",
		"Se9 16-BP1-11 的 I2C",
	}
	for _, text := range texts {
		got := fixtureRegistry().Resolve(text)
		if len(got) != 1 || got[0].SpecName != "SE9 16" {
			t.Errorf("text %q: want the SE9 16 spec matched via the long alias, got %+v", text, got)
		}
		if len(got) == 1 && got[0].Alias != "SE9 16-BP1-11" {
			t.Errorf("text %q: alias = %q, want the registered form", text, got[0].Alias)
		}
	}
}

// 规格别名不带分隔符也能命中：SE916 → SE9 16，且实体仍是 se9。
func TestResolveSpecAliasWithoutSeparator(t *testing.T) {
	got := fixtureRegistry().Resolve("SE916 规格")
	if len(got) != 1 {
		t.Fatalf("SE916 should match the SE9 16 spec alias, got %+v", got)
	}
	if got[0].EntityID != "se9" || got[0].SpecName != "SE9 16" || got[0].Alias != "SE9 16" {
		t.Fatalf("got entity=%q spec=%q alias=%q, want se9 / SE9 16 / SE9 16",
			got[0].EntityID, got[0].SpecName, got[0].Alias)
	}
}

// 多实体命中：按出现位置输出，且不重叠。
func TestResolveMultipleEntities(t *testing.T) {
	reg := fixtureRegistry()
	got := reg.Resolve("SE7 换到 SE9 后 CV186AH 不识别")
	ids := make([]string, len(got))
	for i, m := range got {
		ids[i] = m.Target()
	}
	want := []string{"se7", "se9", "cv186ah"}
	if !reflect.DeepEqual(ids, want) {
		t.Fatalf("matches = %v, want %v (in text order)", ids, want)
	}
	if !(got[0].Start < got[1].Start && got[1].Start < got[2].Start) {
		t.Errorf("matches should be ordered by position: %+v", got)
	}
	// 不重叠
	for i := 1; i < len(got); i++ {
		if got[i].Start < got[i-1].End {
			t.Errorf("matches overlap: %+v", got)
		}
	}
}

// 一个实体只出现一次时 ResolveIDs 去重保序。
func TestResolveIDsDedup(t *testing.T) {
	reg := fixtureRegistry()
	got := reg.ResolveIDs("SE9 和 BM1688，再看 SE9")
	want := []string{"se9", "bm1688"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ids = %v, want %v", got, want)
	}
}

func TestResolveNoMatch(t *testing.T) {
	reg := fixtureRegistry()
	if got := reg.Resolve("完全不相关的文本"); len(got) != 0 {
		t.Errorf("want no match, got %+v", got)
	}
	if got := reg.Resolve(""); len(got) != 0 {
		t.Errorf("empty text should match nothing, got %+v", got)
	}
}

// 词边界：本卡修的就是这一类误命中。
//
// 归一化会把 "use 7 days" 压成 "use7days"，其中包含 "se7"；"case8" 里包含 "se8"。
// 两者在原文里都嵌在 ASCII 单词内部，必须判为不命中。
func TestResolveRespectsWordBoundary(t *testing.T) {
	reg := fixtureRegistry()
	negatives := []string{
		"use 7 days", // 去空格后 "use7days" 含 se7
		"case8",      // 含 se8
		"Please 8 it",
		"case7",
		"xSE9y",
	}
	for _, text := range negatives {
		if got := reg.Resolve(text); len(got) != 0 {
			t.Errorf("text %q must not match any entity inside a word, got %+v", text, got)
		}
	}

	// 正例：首尾、空格、连字符、中文相接都算边界。
	positives := []struct {
		text   string
		target string
	}{
		{"SE7", "se7"},
		{"用 SE7 的 SDK", "se7"},
		{"SE7的网口", "se7"},
		{"(SE7)", "se7"},
		{"SE9 16-BP1-11 怎么装", "se9"},
		{"SE916 规格", "se9"},
		{"SE9 的 I2C", "se9"},
	}
	for _, c := range positives {
		got := reg.Resolve(c.text)
		if len(got) != 1 || got[0].Target() != c.target {
			t.Errorf("text %q: want a single hit on %q, got %+v", c.text, c.target, got)
		}
	}
}

// 词边界的边界情形：命中片段紧邻数字 / 字母时不命中，紧邻中文 / 标点 / 空格时命中。
func TestWordBoundaryAdjacency(t *testing.T) {
	cases := []struct {
		text string
		want bool
	}{
		{"SE7", true},
		{"SE7x", false},
		{"xSE7", false},
		{"1SE7", false},
		{"SE71", false},
		{"SE7的", true},
		{"的SE7", true},
		{"-SE7-", true},
		{"a SE7 b", true},
		{"(SE7)", true},
	}
	for _, c := range cases {
		got := fixtureRegistry().Resolve(c.text)
		if c.want && len(got) != 1 {
			t.Errorf("text %q: want a match, got %+v", c.text, got)
		}
		if !c.want && len(got) != 0 {
			t.Errorf("text %q: inner-word hit must be rejected, got %+v", c.text, got)
		}
	}
}

// Related：产品按全部模组展开（规格不影响检索目标），并给出规格对照提示。
func TestRelatedProductWithSpecs(t *testing.T) {
	reg := fixtureRegistry()
	exp, err := reg.Related("se9")
	if err != nil {
		t.Fatal(err)
	}
	// 自身 → sm9-16（placeholder 跳过）→ bm1688 → sm9-8（跳过）→ cv186ah（跳过，但其 sdk_family 仍是 bm1688）
	want := []string{"se9", "bm1688"}
	if !reflect.DeepEqual(exp.IDs, want) {
		t.Fatalf("related = %v, want %v", exp.IDs, want)
	}
	// placeholder 链一路走到 sdk：两个模组与 CV186AH。sdk 自身是 ready，它的检索目标
	// 是版本，因此不出现在 Skipped 里。
	skipped := ids(exp.Skipped)
	if !reflect.DeepEqual(skipped, []string{"sm9-16", "sm9-8", "cv186ah"}) {
		t.Fatalf("skipped = %v, want [sm9-16 sm9-8 cv186ah]", skipped)
	}
	// sdk 的版本是检索目标：每个芯片各带出自己的 sdk 最新版本。
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Fatalf("versions = %v, want [sophonsdk-edge@v2.3]", got)
	}
	if len(exp.Notes) != 1 {
		t.Fatalf("want one ambiguity note, got %v", exp.Notes)
	}
	wantNote := "se9 specs: SE9 16 (sm9-16 → bm1688) | SE9 8 (sm9-8 → cv186ah); ask which one if the answer depends on chip"
	if exp.Notes[0] != wantNote {
		t.Errorf("note = %q\nwant   %q", exp.Notes[0], wantNote)
	}
}

// 规格不是实体：se9-8 这类旧变体 id 不能当 -entity 用，Related 也要报 unknown entity。
func TestRelatedRejectsSpecID(t *testing.T) {
	reg := fixtureRegistry()
	for _, id := range []string{"se9-8", "se9-16", "SE9 8"} {
		if _, err := reg.Related(id); err == nil {
			t.Errorf("Related(%q) should fail: specs are not entities", id)
		}
	}
}

// 规格只是属性：Spec / SpecChips 能按 (产品, 规格名) 取到，芯片按规格的模组顺序给出。
func TestSpecLookup(t *testing.T) {
	reg := fixtureRegistry()
	sp, ok := reg.Spec("se9", "SE9 8")
	if !ok {
		t.Fatal("Spec(se9, SE9 8) not found")
	}
	if !reflect.DeepEqual(sp.Modules, []string{"sm9-8"}) {
		t.Errorf("spec modules = %v, want [sm9-8]", sp.Modules)
	}
	if got := reg.SpecChips(sp); !reflect.DeepEqual(got, []string{"cv186ah"}) {
		t.Errorf("spec chips = %v, want [cv186ah]", got)
	}
	sp, ok = reg.Spec("se9", "SE9 16")
	if !ok {
		t.Fatal("Spec(se9, SE9 16) not found")
	}
	if got := reg.SpecChips(sp); !reflect.DeepEqual(got, []string{"bm1688"}) {
		t.Errorf("SE9 16 chips = %v, want [bm1688]", got)
	}
	// 规格名只在产品内唯一：拿别的产品也查得到同名规格时不该串
	if _, ok := reg.Spec("se7", "SE9 8"); ok {
		t.Error("Spec(se7, SE9 8) should not resolve: specs belong to their product")
	}
}

// 命中模组：模组 → 芯片 → sdk 版本，不反向展开到产品。
//
// schema v3 起 CV186AH 不再"借" BM1688 的资料，而是走它自己所属的边侧 SDK，
// 所以 sm9-8 走到底只剩 SDK 版本（没有任何 ready 实体）。
func TestRelatedModule(t *testing.T) {
	reg := fixtureRegistry()
	exp, err := reg.Related("sm9-8")
	if err != nil {
		t.Fatal(err)
	}
	if len(exp.IDs) != 0 {
		t.Fatalf("related = %v, want nothing searchable (sm9-8 and cv186ah are placeholders)", exp.IDs)
	}
	if !reflect.DeepEqual(ids(exp.Skipped), []string{"sm9-8", "cv186ah"}) {
		t.Errorf("skipped = %v, want [sm9-8 cv186ah]", ids(exp.Skipped))
	}
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Errorf("versions = %v, want [sophonsdk-edge@v2.3]", got)
	}
	// 绝不能出现 se9 这类反向引用
	for _, id := range exp.IDs {
		if strings.HasPrefix(id, "se") {
			t.Errorf("module expansion must not go back to products, got %v", exp.IDs)
		}
	}

	// ready 模组：自身 + 芯片
	exp, err = reg.Related("sm7")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(exp.IDs, []string{"sm7", "bm1684x"}) {
		t.Fatalf("sm7 related = %v, want [sm7 bm1684x]", exp.IDs)
	}
}

// chip → sdk_family，且**不反向展开到产品 / 模组**。
func TestRelatedChipDoesNotExpandToProducts(t *testing.T) {
	reg := fixtureRegistry()
	// cv186ah 自身是 placeholder，展开出的正是同系列 SDK 的版本（不再指向别的芯片）。
	exp, err := reg.Related("cv186ah")
	if err != nil {
		t.Fatal(err)
	}
	if len(exp.IDs) != 0 {
		t.Fatalf("related = %v, want nothing (cv186ah is a placeholder with no ready relatives)", exp.IDs)
	}
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Errorf("versions = %v, want [sophonsdk-edge@v2.3]", got)
	}
	exp, err = reg.Related("bm1688")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(exp.IDs, []string{"bm1688"}) {
		t.Fatalf("bm1688 related = %v, want only itself", exp.IDs)
	}
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Errorf("bm1688 versions = %v, want [sophonsdk-edge@v2.3]", got)
	}
}

// 只有 placeholder 的实体自身被跳过，但它所属的 sdk 仍然展开成版本。
func TestRelatedPlaceholderSelfSkipped(t *testing.T) {
	reg := fixtureRegistry()
	exp, err := reg.Related("cv84x6")
	if err != nil {
		t.Fatal(err)
	}
	if len(exp.IDs) != 0 {
		t.Errorf("placeholder should expand to nothing searchable, got %v", exp.IDs)
	}
	// cv84x6 声明了 sdk_since=v2.3，所以只取 v2.3（更旧的不适用）。
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Errorf("versions = %v, want [sophonsdk-edge@v2.3]", got)
	}
	if !reflect.DeepEqual(ids(exp.Skipped), []string{"cv84x6"}) {
		t.Errorf("skipped = %v, want [cv84x6]", ids(exp.Skipped))
	}
}

// 产品不带变体：产品 → 模组 → 芯片 → sdk_family 一路走通。
func TestRelatedProductWithoutSpecs(t *testing.T) {
	reg := fixtureRegistry()
	exp, err := reg.Related("se7")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(exp.IDs, []string{"se7", "sm7", "bm1684x"}) {
		t.Fatalf("related = %v, want [se7 sm7 bm1684x]", exp.IDs)
	}
	if len(exp.Notes) != 0 {
		t.Errorf("a product without specs needs no note, got %v", exp.Notes)
	}
}

func TestRelatedUnknownEntity(t *testing.T) {
	if _, err := fixtureRegistry().Related("nope"); err == nil {
		t.Fatal("expected error for unknown entity")
	}
}

// RelatedAll：多目标合并去重保序，跳过项与提示也去重。
func TestRelatedAll(t *testing.T) {
	reg := fixtureRegistry()
	exp, err := reg.RelatedAll([]string{"se9", "bm1688"})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(exp.IDs, []string{"se9", "bm1688"}) {
		t.Fatalf("related = %v, want [se9 bm1688]", exp.IDs)
	}
	if !reflect.DeepEqual(ids(exp.Skipped), []string{"sm9-16", "sm9-8", "cv186ah"}) {
		t.Fatalf("skipped = %v (want dedup'd)", ids(exp.Skipped))
	}
	if got := versionLabels(exp.Versions); !reflect.DeepEqual(got, []string{"sophonsdk-edge@v2.3"}) {
		t.Errorf("versions = %v (want dedup'd to one)", got)
	}
	if len(exp.Notes) != 1 {
		t.Errorf("notes should be dedup'd to one, got %v", exp.Notes)
	}
}

// UsedBy：模组被哪些产品 / 变体引用（只供 resolve 输出参考）。
func TestUsedBy(t *testing.T) {
	reg := fixtureRegistry()
	// 规格不参与 used_by：列产品 id 就够
	if got := reg.UsedBy("sm9-8"); !reflect.DeepEqual(got, []string{"se9"}) {
		t.Errorf("UsedBy(sm9-8) = %v, want [se9]", got)
	}
	// sm7 同时被 se7（直接引用）与 se8（同一模组）使用
	if got := reg.UsedBy("sm7"); !reflect.DeepEqual(got, []string{"se7", "se8"}) {
		t.Errorf("UsedBy(sm7) = %v, want [se7 se8]", got)
	}
	if got := reg.UsedBy("bm1688"); len(got) != 0 {
		t.Errorf("UsedBy(bm1688) = %v, want empty (chips are not referenced by products in v2)", got)
	}
}

// ChunkPath：把块记录的相对路径改写成相对技能根目录。
func TestChunkPath(t *testing.T) {
	reg := fixtureRegistry()
	e, _ := reg.ByID("se9")
	got := reg.ChunkPath(e, "faq/i2c.md")
	if want := "docs/products/se9/faq/i2c.md"; got != want {
		t.Errorf("chunk path = %q, want %q", got, want)
	}
	// docs_dir 为空（placeholder）时原样返回
	ph, _ := reg.ByID("cv84x6")
	if got := reg.ChunkPath(ph, "a.md"); got != "a.md" {
		t.Errorf("placeholder chunk path = %q, want a.md unchanged", got)
	}
}

// DocType 按统一骨架的路径推断文档类型（MYS-2638：子目录名即 doc_type）。
func TestDocTypeInference(t *testing.T) {
	cases := map[string]string{
		"docs/products/se9/spec/se9-16-bp1-11-spec-v1.5.md": DocTypeSpec,
		"docs/products/se9/manual/foo.md":                   DocTypeManual,
		"docs/products/se9/faq/media-faq.md":                DocTypeFAQ,
		"docs/products/se9/tools/flash.md":                  DocTypeTools,
		"docs/products/se9/00-introduce.md":                 DocTypeOverview,
		"docs/products/se9/image-catalog.md":                DocTypeImage,
		"docs/products/se9/assets/x.md":                     DocTypeOther, // 图片目录不进索引
		"docs/products/se9/_meta/coverage-report.md":        DocTypeOther, // 元数据不进索引
		"docs/products/se9/01-product/a.md":                 DocTypeOther, // 旧布局已废弃
		"docs/chips/bm1688/sdk/tpu-mlir.md":                 DocTypeSDK,
		"docs/chips/bm1688/datasheet/spec.md":               DocTypeDatasheet,
		"docs/chips/bm1684x/faq/media-faq.md":               DocTypeFAQ,   // 芯片也有 faq
		"docs/toolkits/sophon-tools/tools/socbak.md":        DocTypeTools, // toolkit 只有 tools
		"docs/modules/sm7/power.md":                         DocTypeModule,
		"docs/sdks/sophonsdk-edge/v2.3/sophon-sail.md":      DocTypeSDK, // schema v3：版本层整层是 sdk
		"docs/sdks/sophonsdk/v23.09/a/b.md":                 DocTypeSDK,
		"products/se9/spec/foo.md":                          DocTypeSpec, // 省略 docs/ 前缀也认
		"./docs/products/se9/tools/flash.md":                DocTypeTools,
		"docs/chips/bm1688/spec.md":                         DocTypeOther, // 芯片根目录下的散文档不在约定内
		"docs/toolkits/sophon-tools/spec/a.md":              DocTypeSpec,  // 归属由 test_layout 按实体类型校验
		"docs/other/x.md":                                   DocTypeOther,
		"a.md":                                              DocTypeOther,
	}
	for in, want := range cases {
		if got := DocType(in); got != want {
			t.Errorf("DocType(%q) = %q, want %q", in, got, want)
		}
	}
}

// 根目录两个文件必须按文件名区分：00-introduce → overview，image-catalog → image。
func TestDocTypeRootFilesAreDistinguished(t *testing.T) {
	for _, layer := range []string{"products", "chips", "toolkits"} {
		base := "docs/" + layer + "/x/"
		if got := DocType(base + "00-introduce.md"); got != DocTypeOverview {
			t.Errorf("%s00-introduce.md → %q, want overview", base, got)
		}
		if got := DocType(base + "image-catalog.md"); got != DocTypeImage {
			t.Errorf("%simage-catalog.md → %q, want image", base, got)
		}
	}
}

// FrontmatterDocType 读取文档自述；缺失或 null 返回空串（由调用方按路径推断）。
func TestFrontmatterDocType(t *testing.T) {
	cases := []struct{ in, want string }{
		{"---\ntitle: x\ndoc_type: spec\n---\n\n# x\n", DocTypeSpec},
		{"---\ntitle: x\ndoc_type: \"faq\"\n---\n", DocTypeFAQ},
		{"---\ntitle: x\ndoc_type: null\n---\n", ""},
		{"---\ntitle: x\n---\n", ""},
		{"# no frontmatter\n", ""},
		{"", ""},
	}
	for _, c := range cases {
		if got := frontmatterDocType(c.in); got != c.want {
			t.Errorf("frontmatterDocType(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// versionLabels 检索版本的展示标识列表（<sdk>@<slug>），便于断言。
func versionLabels(vs []VersionRef) []string {
	out := make([]string, 0, len(vs))
	for _, v := range vs {
		out = append(out, v.Label())
	}
	return out
}

func ids(skipped []Skip) []string {
	out := make([]string, len(skipped))
	for i, s := range skipped {
		out[i] = s.ID
	}
	return out
}
