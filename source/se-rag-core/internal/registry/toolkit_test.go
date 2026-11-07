package registry

import (
	"strings"
	"testing"
)

// 随箱工具（toolkit）实体的校验与关联展开（MYS-2638 第 4 节）。
const (
	toolkitEntity = `{
		"id": "sophon-tools", "type": "toolkit", "name": "随箱工具", "status": "ready",
		"aliases": ["sophon-tools", "socbak"],
		"docs_dir": "docs/toolkits/sophon-tools", "index_dir": "rag/data/toolkit-sophon-tools"
	}`
	se9WithToolkit = `{
		"id": "se9", "type": "product", "name": "SE9 微服务器", "status": "ready",
		"aliases": ["SE9"], "modules": ["sm9-16"], "toolkits": ["sophon-tools"],
		"docs_dir": "docs/se9", "index_dir": "rag/data/product-se9"
	}`
)

// 合法的 toolkit 实体与 product.toolkits 引用应通过校验。
func TestToolkitRegistryIsValid(t *testing.T) {
	reg, _ := writeRegistry(t, validRegistry(
		se9WithToolkit+","+sm916Entity+","+bm1688Entity+","+sdkEdgeEntity+","+toolkitEntity),
		"docs/se9", "docs/bm1688", "docs/toolkits/sophon-tools", "docs/sdk")
	if err := reg.Validate(); err != nil {
		t.Fatalf("registry with toolkit rejected: %v", err)
	}
	e, ok := reg.ByID("sophon-tools")
	if !ok || e.Type != TypeToolkit {
		t.Fatalf("sophon-tools should be a toolkit entity, got %+v", e)
	}
}

// toolkits 只能引用 toolkit：指向 chip / product 必须报错并点明类型。
func TestToolkitsMustReferenceToolkit(t *testing.T) {
	cases := []struct{ name, target string }{
		{"chip", "bm1688"},
		{"product", "se9"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			body := strings.Replace(se9WithToolkit, `"toolkits": ["sophon-tools"]`,
				`"toolkits": ["`+c.target+`"]`, 1)
			reg, _ := writeRegistry(t, validRegistry(
				body+","+sm916Entity+","+bm1688Entity),
				"docs/se9", "docs/bm1688")
			err := reg.Validate()
			if err == nil {
				t.Fatalf("toolkits -> %s should be rejected", c.target)
			}
			if msg := err.Error(); !strings.Contains(msg, "not a defined toolkit") {
				t.Errorf("error should say the target is not a toolkit, got:\n%s", msg)
			}
		})
	}
}

// 只有 product 可以写 toolkits；模组/芯片写了就是放错了层。
func TestOnlyProductMayHaveToolkits(t *testing.T) {
	chipWithToolkit := `{
		"id": "bm1688", "type": "chip", "name": "BM1688", "status": "ready",
		"aliases": ["BM1688"], "toolkits": ["sophon-tools"],
		"docs_dir": "docs/bm1688", "index_dir": "rag/data/chip-bm1688"
	}`
	reg, _ := writeRegistry(t, validRegistry(
		se9Entity+","+sm916Entity+","+chipWithToolkit+","+toolkitEntity),
		"docs/se9", "docs/bm1688", "docs/toolkits/sophon-tools")
	err := reg.Validate()
	if err == nil {
		t.Fatal("chip with toolkits should be rejected")
	}
	if msg := err.Error(); !strings.Contains(msg, "only product may have toolkits") {
		t.Errorf("error should say only product may have toolkits, got:\n%s", msg)
	}
}

// --with-related 展开顺序：产品 → 模组 → 芯片 → sdk 版本 → toolkits。
func TestRelatedProductExpandsToolkitsLast(t *testing.T) {
	reg, _ := writeRegistry(t, validRegistry(
		se9WithToolkit+","+sm916Entity+","+bm1688Entity+","+cv186ahEntity+","+sdkEdgeEntity+","+toolkitEntity),
		"docs/se9", "docs/bm1688", "docs/toolkits/sophon-tools", "docs/sdk")
	if err := reg.Validate(); err != nil {
		t.Fatalf("validate: %v", err)
	}
	exp, err := reg.Related("se9")
	if err != nil {
		t.Fatalf("related: %v", err)
	}
	want := []string{"se9", "bm1688", "sophon-tools"}
	if len(exp.IDs) != len(want) {
		t.Fatalf("related ids = %v, want %v", exp.IDs, want)
	}
	for i, id := range want {
		if exp.IDs[i] != id {
			t.Errorf("related[%d] = %q, want %q (full: %v)", i, exp.IDs[i], id, exp.IDs)
		}
	}
	// sdk 版本排在 toolkits 之前：芯片展开出 sdk 的检索版本。
	if len(exp.Versions) != 1 || exp.Versions[0].Label() != "sophonsdk-edge@v2.3" {
		t.Errorf("sdk versions = %v, want [sophonsdk-edge@v2.3]", exp.Versions)
	}
}

// toolkit 自身不展开：它没有 modules/chips，也不该反向展开到产品。
func TestRelatedToolkitExpandsOnlyItself(t *testing.T) {
	reg, _ := writeRegistry(t, validRegistry(
		se9WithToolkit+","+sm916Entity+","+bm1688Entity+","+sdkEdgeEntity+","+toolkitEntity),
		"docs/se9", "docs/bm1688", "docs/toolkits/sophon-tools", "docs/sdk")
	if err := reg.Validate(); err != nil {
		t.Fatalf("validate: %v", err)
	}
	exp, err := reg.Related("sophon-tools")
	if err != nil {
		t.Fatalf("related: %v", err)
	}
	if len(exp.IDs) != 1 || exp.IDs[0] != "sophon-tools" {
		t.Errorf("toolkit should expand to itself only, got %v", exp.IDs)
	}
}

// placeholder 的 toolkits 引用仍要能通过校验（产品占位时不展开，但引用本身合法）。
func TestPlaceholderProductWithToolkitsIsValid(t *testing.T) {
	placeholder := `{
		"id": "se99", "type": "product", "name": "SE99", "status": "placeholder",
		"aliases": ["SE99"], "modules": [], "toolkits": ["sophon-tools"],
		"docs_dir": null, "index_dir": null
	}`
	reg, _ := writeRegistry(t, validRegistry(placeholder+","+toolkitEntity),
		"docs/toolkits/sophon-tools")
	if err := reg.Validate(); err != nil {
		t.Fatalf("placeholder product with toolkits rejected: %v", err)
	}
}
