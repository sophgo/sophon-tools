package main

import (
	"encoding/json"
	"strings"
	"testing"

	"se-rag-core/internal/docstore"
	"se-rag-core/internal/registry"
)

// 本文件覆盖 schema v2 的三层关系与规格属性在 CLI 层的行为：
// 规格不是实体（-entity 不接受）、resolve 报告规格与芯片、规格不影响检索目标、
// 以及词边界的端到端表现。
// 夹具见 testdata/registry（se9 一个实体 + 两个规格、se7 → sm7、sm9-* 为 placeholder）。

// 规格不是实体：-entity 传入规格名或"产品-规格"拼法一律报 unknown entity，并提示该用哪个产品。
func TestRegistryEntityRejectsSpecIDs(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	for _, spec := range []string{"se9-8", "se9-16", "SE9 8"} {
		var rc int
		stderr := captureStderr(t, func() {
			captureStdout(t, func() {
				rc = dispatch([]string{"query", "-registry", regPath, "-entity", spec, "-offline", "I2C"})
			})
		})
		if rc == 0 {
			t.Errorf("-entity %q should fail: specs are not entities", spec)
		}
		for _, want := range []string{"unknown entity", "not an entity", "-entity se9"} {
			if !strings.Contains(stderr, want) {
				t.Errorf("-entity %q: error should mention %q, got:\n%s", spec, want, stderr)
			}
		}
	}
}

// 规格是产品的一部分：-entity se9 只查一份索引，不会因为有两个规格就查两遍。
func TestRegistryEntitySpecsShareOneIndex(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	reg, err := loadRegistry(regPath)
	if err != nil {
		t.Fatal(err)
	}
	ts, err := targetEntities(reg, "se9", false, registry.SDKVersionRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(ts) != 1 || ts[0].Label() != "se9" {
		t.Fatalf("targets = %v, want [se9] (specs share the product's index)", ts)
	}
}

// 命中规格别名：实体是 se9，并附上规格名与该规格对应的芯片。
func TestRegistryResolveSpecAlias(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	cases := []struct {
		text      string
		wantSpec  string
		wantChips []string
	}{
		{"SE9 8-BP1-17 怎么装 sail", "SE9 8", []string{"cv186ah"}},
		{"SE916 规格", "SE9 16", []string{"bm1688"}},
		{"8路和16路的区别", "", nil}, // 两个规格各一行，下面单独断言
	}
	for _, c := range cases[:2] {
		out := captureStdout(t, func() {
			if rc := dispatch([]string{"resolve", "-registry", regPath, "-json", c.text}); rc != 0 {
				t.Fatalf("resolve %q rc=%d", c.text, rc)
			}
		})
		var hits []resolveHit
		if err := json.Unmarshal([]byte(out), &hits); err != nil {
			t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
		}
		if len(hits) != 1 {
			t.Fatalf("resolve %q: want 1 hit, got %+v", c.text, hits)
		}
		if hits[0].EntityID != "se9" {
			t.Errorf("resolve %q: entity = %q, want se9 (a spec must resolve to its product)",
				c.text, hits[0].EntityID)
		}
		if hits[0].Spec != c.wantSpec {
			t.Errorf("resolve %q: spec = %q, want %q", c.text, hits[0].Spec, c.wantSpec)
		}
		if len(hits[0].SpecChips) != len(c.wantChips) {
			t.Errorf("resolve %q: spec chips = %v, want %v", c.text, hits[0].SpecChips, c.wantChips)
			continue
		}
		for i := range c.wantChips {
			if hits[0].SpecChips[i] != c.wantChips[i] {
				t.Errorf("resolve %q: spec chips = %v, want %v", c.text, hits[0].SpecChips, c.wantChips)
			}
		}
	}
}

// 文本里同时提到两个规格：各输出一行，实体都是 se9。
func TestRegistryResolveTwoSpecsOneEntity(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", regPath, "-json", "8路和16路的区别"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(out), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
	}
	if len(hits) != 2 {
		t.Fatalf("want 2 hits (one per spec), got %+v", hits)
	}
	specs := map[string]string{}
	for _, h := range hits {
		if h.EntityID != "se9" {
			t.Errorf("entity = %q, want se9 for both specs", h.EntityID)
		}
		specs[h.Spec] = strings.Join(h.SpecChips, ",")
	}
	if specs["SE9 16"] != "bm1688" || specs["SE9 8"] != "cv186ah" {
		t.Errorf("spec → chips = %v, want SE9 16→bm1688 / SE9 8→cv186ah", specs)
	}
}

// 只命中产品（没命中具体规格）：输出规格对照。
func TestRegistryResolveProductOnlyListsSpecs(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", regPath, "-json", "SE9 的 I2C"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(out), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
	}
	if len(hits) != 1 {
		t.Fatalf("want 1 hit, got %+v", hits)
	}
	if hits[0].EntityID != "se9" {
		t.Errorf("entity = %q, want se9", hits[0].EntityID)
	}
	if hits[0].Spec != "" {
		t.Errorf("plain SE9 should not bind a spec, got %q", hits[0].Spec)
	}
	if len(hits[0].Notes) != 1 {
		t.Fatalf("want exactly one spec summary note, got %v", hits[0].Notes)
	}
	// 逐项校验提示格式：`se9 specs: SE9 16 (sm9-16 → bm1688) | SE9 8 (sm9-8 → cv186ah); ...`
	for _, want := range []string{
		"se9 specs:", "SE9 16 (sm9-16 → bm1688)", "SE9 8 (sm9-8 → cv186ah)", "ask which one",
	} {
		if !strings.Contains(hits[0].Notes[0], want) {
			t.Errorf("note %q should mention %q", hits[0].Notes[0], want)
		}
	}
	// 检索目标不受规格影响：两个模组都走到，都跳过
	for _, want := range []string{"sm9-16", "sm9-8"} {
		if !containsString(hits[0].Skipped, want) {
			t.Errorf("skipped %v should contain %q", hits[0].Skipped, want)
		}
	}
}

// 命中模组：模组 → 芯片 → sdk_family，并在 resolve 输出里列出使用它的产品。
func TestRegistryResolveModule(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", regPath, "-json", "SM9 16"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(out), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
	}
	if len(hits) != 1 || hits[0].EntityID != "sm9-16" {
		t.Fatalf("hits = %+v, want sm9-16", hits)
	}
	if !containsString(hits[0].Related, "bm1688") {
		t.Errorf("module should expand to its chip, related = %v", hits[0].Related)
	}
	// 不反向展开到产品（related 里不能有产品）
	for _, r := range hits[0].Related {
		if strings.HasPrefix(r, "se") {
			t.Errorf("module expansion must not include products, related = %v", hits[0].Related)
		}
	}
	// 但 used_by 要给出参考（规格不参与，列产品 id）
	if !containsString(hits[0].UsedBy, "se9") {
		t.Errorf("used_by should name the product using this module, got %v", hits[0].UsedBy)
	}
}

// 命中 ready 模组时，模组自己的索引与芯片索引都进入检索目标。
func TestRegistryQueryModuleExpansion(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	regPath := loadTestRegistry(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "sm7", "-with-related", "-offline", "连接器"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[sm7]") {
		t.Errorf("module's own index should be searched:\n%s", out)
	}
	if !strings.Contains(out, "`docs/modules/sm7/") {
		t.Errorf("module docs path should be relative to the skill root:\n%s", out)
	}
}

// query -entity se9 -with-related：检索目标是 se9 与 bm1688，并提示跳过两个模组与 cv186ah。
// 规格不影响检索目标——两种规格的模组都会被走到。
func TestRegistryQueryProductWithRelated(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	regPath := loadTestRegistry(t, dir)

	var out string
	stderr := captureStderr(t, func() {
		out = captureStdout(t, func() {
			if rc := dispatch([]string{"query", "-registry", regPath, "-entity", "se9",
				"-with-related", "-offline", "I2C tpu-mlir"}); rc != 0 {
				t.Fatalf("query rc=%d", rc)
			}
		})
	})
	for _, want := range []string{"sm9-16", "sm9-8", "cv186ah"} {
		if !strings.Contains(stderr, want) {
			t.Errorf("stderr should report the skipped placeholder %q:\n%s", want, stderr)
		}
	}
	// 检索目标 se9 + bm1688 两个索引 → 合并输出、都带实体标注
	for _, want := range []string{"[se9]", "[bm1688]"} {
		if !strings.Contains(out, want) {
			t.Errorf("merged result should be tagged %s:\n%s", want, out)
		}
	}
}

// 词边界的端到端表现：resolve 不该被单词内部的子串骗到。
func TestRegistryResolveWordBoundaryEndToEnd(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	// 反例：都该 0 命中（rc != 0）
	for _, text := range []string{"use 7 days", "case8"} {
		var rc int
		captureStdout(t, func() {
			rc = dispatch([]string{"resolve", "-registry", regPath, text})
		})
		if rc == 0 {
			t.Errorf("%q must not match any entity (substring inside a word)", text)
		}
	}

	// 正例：都解析到 se9（规格不影响实体）
	for _, text := range []string{"SE9 16-BP1-11 怎么装", "SE916 规格", "SE9的I2C"} {
		out := captureStdout(t, func() {
			if rc := dispatch([]string{"resolve", "-registry", regPath, "-json", text}); rc != 0 {
				t.Fatalf("resolve %q rc=%d", text, rc)
			}
		})
		var hits []resolveHit
		if err := json.Unmarshal([]byte(out), &hits); err != nil {
			t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
		}
		if len(hits) == 0 || hits[0].EntityID != "se9" {
			t.Errorf("%q should resolve to se9, got %+v", text, hits)
		}
	}
}

// list：规格缩进展示在 se9 下，不作为实体行出现。
func TestRegistryListShowsSpecs(t *testing.T) {
	dir := testRegistryDir(t)
	regPath := loadTestRegistry(t, dir)

	human := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", regPath}); rc != 0 {
			t.Fatalf("list rc=%d", rc)
		}
	})
	for _, want := range []string{"SE9 16", "SE9 8", "spec", "sm9-16 → bm1688", "sm9-8 → cv186ah"} {
		if !strings.Contains(human, want) {
			t.Errorf("list output missing %q:\n%s", want, human)
		}
	}
	// 规格不作为实体行出现
	for _, unwanted := range []string{"variant", "se9-16", "se9-8"} {
		if strings.Contains(human, unwanted) {
			t.Errorf("list output must not mention %q anymore:\n%s", unwanted, human)
		}
	}

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", regPath, "-json"}); rc != 0 {
			t.Fatalf("list -json rc=%d", rc)
		}
	})
	var entries []listEntry
	if err := json.Unmarshal([]byte(out), &entries); err != nil {
		t.Fatalf("list -json is not JSON: %v\n%s", err, out)
	}
	byID := map[string]listEntry{}
	for _, e := range entries {
		byID[e.ID] = e
	}
	if _, ok := byID["se9-8"]; ok {
		t.Error("a spec must not appear as its own list entry")
	}
	se9 := byID["se9"]
	if len(se9.Specs) != 2 {
		t.Fatalf("se9 specs = %+v, want 2", se9.Specs)
	}
	if len(se9.Modules) != 2 {
		t.Errorf("se9 modules = %v, want both modules", se9.Modules)
	}
	if se9.Specs[0].Name != "SE9 16" || se9.Specs[0].Modules[0] != "sm9-16" {
		t.Errorf("first spec = %+v, want SE9 16 → sm9-16", se9.Specs[0])
	}
}

// build 只按实体：规格不是 build 目标，-all 也不会因为规格多建一份索引。
func TestRegistryBuildIgnoresSpecs(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)

	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	// ready 实体各一份索引；规格不额外产生索引目录
	for _, id := range reg.ReadyIDs() {
		e, _ := reg.ByID(id)
		if _, err := (&docstore.Store{IndexDir: reg.IndexPath(e)}).ReadMeta(id); err != nil {
			t.Errorf("entity %s: index should exist: %v", id, err)
		}
	}
	se9, _ := reg.ByID("se9")
	if !strings.HasSuffix(reg.IndexPath(se9), "product-se9") {
		t.Errorf("se9 index path = %q, want the product-level index", reg.IndexPath(se9))
	}
}
