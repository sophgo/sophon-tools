package registry

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeRegistry 在临时目录里建一个技能根：写注册表 JSON 与它引用的 docs 目录。
func writeRegistry(t *testing.T, body string, docs ...string) (*Registry, string) {
	t.Helper()
	root := t.TempDir()
	for _, d := range docs {
		if err := os.MkdirAll(filepath.Join(root, filepath.FromSlash(d)), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	p := filepath.Join(root, "registry.json")
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := Load(p)
	if err != nil {
		t.Fatalf("load registry: %v", err)
	}
	return reg, root
}

// validRegistry 把实体片段包成合法的 schema v3 注册表。
func validRegistry(entities string) string {
	return `{"schema_version": 3, "entities": [` + entities + `]}`
}

const (
	se9Entity = `{
		"id": "se9", "type": "product", "name": "SE9 微服务器", "status": "ready",
		"aliases": ["SE9"], "modules": ["sm9-16"],
		"docs_dir": "docs/se9", "index_dir": "rag/data/product-se9"
	}`
	se9SpecEntity = `{
		"id": "se9", "type": "product", "name": "SE9 微服务器", "status": "ready",
		"aliases": ["SE9"], "modules": ["sm9-16", "sm9-8"],
		"specs": [
			{"name": "SE9 16", "aliases": ["SE9 16"], "modules": ["sm9-16"]},
			{"name": "SE9 8", "aliases": ["SE9 8"], "modules": ["sm9-8"]}
		],
		"docs_dir": "docs/se9", "index_dir": "rag/data/product-se9"
	}`
	sm916Entity = `{
		"id": "sm9-16", "type": "module", "name": "SM9 16", "status": "placeholder",
		"aliases": ["SM9 16"], "chips": ["bm1688"], "docs_dir": null, "index_dir": null
	}`
	sm98Entity = `{
		"id": "sm9-8", "type": "module", "name": "SM9 8", "status": "placeholder",
		"aliases": ["SM9 8"], "chips": ["cv186ah"], "docs_dir": null, "index_dir": null
	}`
	bm1688Entity = `{
		"id": "bm1688", "type": "chip", "name": "BM1688", "status": "ready",
		"aliases": ["BM1688"], "sdk": "sophonsdk-edge",
		"docs_dir": "docs/bm1688", "index_dir": "rag/data/chip-bm1688"
	}`
	cv186ahEntity = `{
		"id": "cv186ah", "type": "chip", "name": "CV186AH", "status": "placeholder",
		"aliases": ["CV186AH"], "sdk": "sophonsdk-edge",
		"docs_dir": null, "index_dir": null
	}`
)

// sdkEdgeEntity 夹具用的边侧 SDK 实体：一个版本，文档与索引都在 docs/sdk 下。
var sdkEdgeEntity = sdkEntity("sophonsdk-edge",
	versionItem("v2.3", "v2.3", "2026-10-12", "docs/sdk", "idx/sdk"))

// versionItem 一个 sdk 版本项（versions 数组里的一个元素）。
func versionItem(version, slug, releaseDate, docsDir, indexDir string) string {
	return `{"version":"` + version + `","slug":"` + slug + `","release_date":"` + releaseDate +
		`","docs_dir":"` + docsDir + `","index_dir":"` + indexDir + `"}`
}

// sdkEntity 一个 sdk 实体（文档与索引挂在版本上，status 由 versions 派生）。
// versions 是逗号分隔的版本项，空串表示 versions: []（此时 status=placeholder）。
func sdkEntity(id string, versions string) string {
	return sdkEntityExtra(id, versions, "")
}

// sdkEntityExtra 同上，extra 是非空的附加字段片段（如 `"sources":{...}`）。
func sdkEntityExtra(id, versions, extra string) string {
	if extra != "" {
		extra = "," + extra
	}
	// status 由 versions 派生（有版本 = ready，无版本 = placeholder）——校验规则如此，
	// 夹具必须跟着合法，否则每个用例都会先撞上 status 这条。
	status := "placeholder"
	if versions != "" {
		status = "ready"
	}
	return `{"id":"` + id + `","type":"sdk","name":"SDK ` + id + `","status":"` + status + `",` +
		`"aliases":["` + strings.ToUpper(id) + `"],"versions":[` + versions + `],` +
		`"docs_dir":null,"index_dir":null` + extra + `}`
}

// sdkEntityWithStatus 同 sdkEntityExtra，但显式指定 status（用于校验 status 规则的用例）。
func sdkEntityWithStatus(id, status, versions string) string {
	return `{"id":"` + id + `","type":"sdk","name":"SDK ` + id + `","status":"` + status + `",` +
		`"aliases":["` + strings.ToUpper(id) + `"],"versions":[` + versions + `],` +
		`"docs_dir":null,"index_dir":null}`
}

func TestLoadValidRegistry(t *testing.T) {
	reg, root := writeRegistry(t, validRegistry(
		se9Entity+","+sm916Entity+","+bm1688Entity+","+cv186ahEntity+","+sdkEdgeEntity),
		"docs/se9", "docs/bm1688", "docs/sdk")
	if err := reg.Validate(); err != nil {
		t.Fatalf("valid registry rejected: %v", err)
	}
	if reg.SchemaVersion != SchemaVersion {
		t.Errorf("schema_version = %d, want %d", reg.SchemaVersion, SchemaVersion)
	}
	if reg.Root() != root {
		t.Errorf("root = %q, want %q", reg.Root(), root)
	}
	if got := reg.ReadyIDs(); len(got) != 2 || got[0] != "se9" || got[1] != "bm1688" {
		t.Errorf("ready ids = %v, want [se9 bm1688] (registry order)", got)
	}
	e, ok := reg.ByID("se9")
	if !ok {
		t.Fatal("se9 not found")
	}
	// 路径相对 registry 所在目录解析
	if want := filepath.Join(root, "docs/se9"); reg.DocsPath(e) != want {
		t.Errorf("docs path = %q, want %q", reg.DocsPath(e), want)
	}
	if want := filepath.Join(root, "rag/data/product-se9"); reg.IndexPath(e) != want {
		t.Errorf("index path = %q, want %q", reg.IndexPath(e), want)
	}
	// placeholder 的 null 路径解析为空
	ph, _ := reg.ByID("cv186ah")
	if reg.DocsPath(ph) != "" || reg.IndexPath(ph) != "" {
		t.Errorf("placeholder paths should be empty, got %q / %q", reg.DocsPath(ph), reg.IndexPath(ph))
	}
}

// chips 字段"写没写"要能区分：`"chips": []` 对 schema v2 的 product 同样不允许。
func TestChipsFieldPresence(t *testing.T) {
	reg, _ := writeRegistry(t, validRegistry(
		`{"id":"a","type":"product","name":"A","status":"placeholder","aliases":["A"],"chips":[],"docs_dir":null,"index_dir":null}`))
	e, _ := reg.ByID("a")
	if !e.HasChipsField() {
		t.Error(`"chips": [] should still count as the field being present`)
	}
	reg, _ = writeRegistry(t, validRegistry(
		`{"id":"a","type":"product","name":"A","status":"placeholder","aliases":["A"],"docs_dir":null,"index_dir":null}`))
	e, _ = reg.ByID("a")
	if e.HasChipsField() {
		t.Error("a product without the chips key must report HasChipsField()=false")
	}
}

func TestLoadMissingFile(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "nope.json")); err == nil {
		t.Fatal("expected error for a missing registry file")
	}
	root := t.TempDir()
	p := filepath.Join(root, "registry.json")
	if err := os.WriteFile(p, []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(p); err == nil {
		t.Fatal("expected error for malformed JSON")
	}
}

// 校验的每一类错误都必须被报出来（本卡验收标准逐项对应）。
func TestValidateErrors(t *testing.T) {
	mk := func(id, typ, status, docs, index string, aliases ...string) string {
		al := `[]`
		if len(aliases) > 0 {
			al = `["` + strings.Join(aliases, `","`) + `"]`
		}
		return `{"id":"` + id + `","type":"` + typ + `","name":"n","status":"` + status +
			`","aliases":` + al + `,"docs_dir":` + docs + `,"index_dir":` + index + `}`
	}
	null := "null"

	tt := []struct {
		name     string
		entities string
		docs     []string
		// body 非空时整体替换注册表内容（用于 schema_version 与顶层字段的用例）。
		body string
		want []string // 错误里必须出现的片段
	}{
		{
			name:     "重复 id",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + "," + mk("se9", "chip", "ready", `"docs/a"`, `"idx/a"`, "OTHER"),
			docs:     []string{"docs/a"},
			want:     []string{"duplicate id"},
		},
		{
			name:     "id 非 kebab",
			entities: mk("SE_9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			want:     []string{"lowercase kebab-case"},
		},
		{
			name:     "非法 type",
			entities: mk("se9", "board", "ready", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			want:     []string{"type", "not one of product|chip|module"},
		},
		{
			name:     "非法 status",
			entities: mk("se9", "product", "draft", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			want:     []string{"status", "not one of ready|placeholder"},
		},
		{
			name:     "别名重复（原文相同）",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + "," + mk("se7", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			want:     []string{"duplicate alias", "SE9"},
		},
		{
			name:     "别名重复（归一化后相同：大小写 空格 连字符 下划线）",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9 16-BP1-11") + "," + mk("se7", "product", "ready", `"docs/a"`, `"idx/a"`, "se9_16_bp1 11"),
			docs:     []string{"docs/a"},
			want:     []string{"duplicate alias"},
		},
		{
			name:     "悬空 module 引用",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"se7","type":"product","name":"n","status":"ready","aliases":["SE7"],"modules":["nosuchmodule"],"docs_dir":"docs/a","index_dir":"idx/a"}`,
			docs:     []string{"docs/a"},
			want:     []string{"modules references", "nosuchmodule", "not a defined module"},
		},
		{
			name:     "modules 指向非 module 实体（chip）",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"bm1","type":"chip","name":"n","status":"ready","aliases":["BM1"],"docs_dir":"docs/a","index_dir":"idx/a"},{"id":"se7","type":"product","name":"n","status":"ready","aliases":["SE7"],"modules":["bm1"],"docs_dir":"docs/a","index_dir":"idx/a"}`,
			docs:     []string{"docs/a"},
			want:     []string{"not a defined module"},
		},
		{
			name:     "规格 modules 指向非 module 实体",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"se7","type":"product","name":"n","status":"ready","aliases":["SE7"],"modules":["sm7"],"specs":[{"name":"SE7 32","aliases":["SE7 32"],"modules":["se9"]}],"docs_dir":"docs/a","index_dir":"idx/a"}` + `,{"id":"sm7","type":"module","name":"SM7","status":"placeholder","aliases":["SM7"],"chips":[],"docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{`spec "SE7 32"`, "not a defined module"},
		},
		{
			name:     "module.chips 悬空引用",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"sm7","type":"module","name":"n","status":"placeholder","aliases":["SM7"],"chips":["nope"],"docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{"chips references", "nope", "not a defined chip"},
		},
		{
			name:     "module.chips 指向非 chip 实体（product）",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"sm7","type":"module","name":"n","status":"placeholder","aliases":["SM7"],"chips":["se9"],"docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{"not a defined chip"},
		},
		{
			name:     "product 出现 chips 字段（schema v2 禁止）",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"chips":["bm1688"],"docs_dir":null,"index_dir":null}`,
			want:     []string{"product must not have a chips field"},
		},
		{
			name:     "product 出现空 chips 字段也算写了",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"chips":[],"docs_dir":null,"index_dir":null}`,
			want:     []string{"product must not have a chips field"},
		},
		{
			name:     "spec.modules 引用未定义的 module",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"SE9 16","aliases":["SE9 16"],"modules":["nosuch"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want:     []string{`spec "SE9 16"`, "not a defined module"},
		},
		{
			name:     "spec.modules 不是 product.modules 的子集",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"SE9 8","aliases":["SE9 8"],"modules":["sm9-8"]}],"docs_dir":null,"index_dir":null},` + sm916Entity + "," + sm98Entity,
			want:     []string{"is not listed in the product's modules", "sm9-8"},
		},
		{
			name:     "规格合起来没覆盖全部模组",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16","sm9-8"],"specs":[{"name":"SE9 16","aliases":["SE9 16"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity + "," + sm98Entity,
			want:     []string{"not covered by any spec", "sm9-8"},
		},
		{
			name:     "同一产品内规格名重复",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"SE9 16","aliases":["SE9 16"],"modules":["sm9-16"]},{"name":"SE9 16","aliases":["SE9 16B"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want:     []string{"duplicate spec name"},
		},
		{
			name:     "规格别名与实体别名冲突",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9","SE9 16"],"modules":["sm9-16"],"specs":[{"name":"SE9 16","aliases":["SE9 16"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want:     []string{"duplicate alias", "SE9 16"},
		},
		{
			name: "跨产品的规格别名冲突",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"SE9 16","aliases":["共享别名"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` +
				`{"id":"se7","type":"product","name":"n","status":"placeholder","aliases":["SE7"],"modules":["sm9-16"],"specs":[{"name":"SE7 32","aliases":["共享别名"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want: []string{"duplicate alias", "共享别名"},
		},
		{
			name:     "规格别名为空",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"SE9 16","aliases":[],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want:     []string{`spec "SE9 16"`, "aliases is empty"},
		},
		{
			name:     "规格 name 为空",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"modules":["sm9-16"],"specs":[{"name":"","aliases":["X"],"modules":["sm9-16"]}],"docs_dir":null,"index_dir":null},` + sm916Entity,
			want:     []string{"name is empty"},
		},
		{
			name:     "非 product 实体带 specs",
			entities: `{"id":"bm1","type":"chip","name":"n","status":"placeholder","aliases":["BM1"],"specs":[{"name":"V1","aliases":["V1"],"modules":[]}],"docs_dir":null,"index_dir":null}`,
			want:     []string{"only product may have specs"},
		},
		{
			name:     "chip.sdk 悬空引用",
			entities: mk("se9", "chip", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"cv1","type":"chip","name":"n","status":"placeholder","aliases":["CV1"],"sdk":"nope","docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{"sdk references", "nope", "not a defined sdk"},
		},
		{
			name:     "chip.sdk 指向非 sdk 实体",
			entities: mk("se9", "chip", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `,{"id":"cv1","type":"chip","name":"n","status":"placeholder","aliases":["CV1"],"sdk":"se9","docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{"not a defined sdk"},
		},
		{
			name:     "仍写着 schema v2 的 sdk_family",
			entities: `{"id":"cv1","type":"chip","name":"n","status":"placeholder","aliases":["CV1"],"sdk_family":"bm1688","docs_dir":null,"index_dir":null}`,
			want:     []string{"sdk_family is gone in schema v3"},
		},
		{
			name:     "非 chip 实体带 sdk",
			entities: `{"id":"se9","type":"product","name":"n","status":"placeholder","aliases":["SE9"],"sdk":"s1","docs_dir":null,"index_dir":null},` + sdkEntity("s1", ""),
			want:     []string{"only chip may have sdk"},
		},
		{
			name:     "非 sdk 实体带 versions",
			entities: `{"id":"bm1","type":"chip","name":"n","status":"placeholder","aliases":["BM1"],"versions":[` + versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a") + `],"docs_dir":null,"index_dir":null}`,
			docs:     []string{"docs/a"},
			want:     []string{"only sdk may have versions"},
		},
		{
			name:     "sdk 没有版本时不能是 ready",
			entities: mk("s1", "sdk", "ready", null, null, "S1"),
			want:     []string{"sdk with no versions must be status=placeholder"},
		},
		{
			name:     "sdk 有版本时必须是 ready",
			entities: sdkEntityWithStatus("s1", "placeholder", versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"sdk with versions must be status=ready"},
		},
		{
			name:     "sdk 版本 slug 重复",
			entities: sdkEntity("s1", versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a")+","+versionItem("v1", "v1", "2026-02-01", "docs/a2", "idx/a2")),
			docs:     []string{"docs/a", "docs/a2"},
			want:     []string{"duplicate slug"},
		},
		{
			name:     "sdk 版本 slug 为空",
			entities: sdkEntity("s1", versionItem("v1", "", "2026-01-01", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"slug is empty"},
		},
		{
			name:     "sdk 版本号为空",
			entities: sdkEntity("s1", versionItem("", "v1", "2026-01-01", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"version is empty"},
		},
		{
			name:     "sdk 版本 release_date 格式非法",
			entities: sdkEntity("s1", versionItem("v1", "v1", "2026-1-1", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"release_date", "YYYY-MM-DD"},
		},
		{
			name:     "sdk 版本 release_date 为空",
			entities: sdkEntity("s1", versionItem("v1", "v1", "", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"release_date is empty"},
		},
		{
			name:     "sdk 版本 docs_dir 不存在",
			entities: sdkEntity("s1", versionItem("v1", "v1", "2026-01-01", "docs/missing", "idx/a")),
			want:     []string{"docs_dir", "does not exist"},
		},
		{
			name:     "sdk 版本 index_dir 为空",
			entities: sdkEntity("s1", `{"version":"v1","slug":"v1","release_date":"2026-01-01","docs_dir":"docs/a","index_dir":""}`),
			docs:     []string{"docs/a"},
			want:     []string{"index_dir is empty"},
		},
		{
			name: "两个版本的 index_dir 重复",
			entities: sdkEntity("s1", versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/same")+","+
				versionItem("v2", "v2", "2026-02-01", "docs/a2", "idx/same")),
			docs: []string{"docs/a", "docs/a2"},
			want: []string{"index_dir", "already used by"},
		},
		{
			name: "两个版本的 docs_dir 重复",
			entities: sdkEntity("s1", versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a")+","+
				versionItem("v2", "v2", "2026-02-01", "docs/a", "idx/b")),
			docs: []string{"docs/a"},
			want: []string{"docs_dir", "already used by"},
		},
		{
			name:     "sdk 的 applies_to 悬空引用",
			entities: `{"id":"bm1","type":"chip","name":"n","status":"placeholder","aliases":["BM1"],"docs_dir":null,"index_dir":null},` + sdkEntity("s1", strings.TrimSuffix(versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a"), "}")+`,"applies_to":["nope"]}`),
			docs:     []string{"docs/a"},
			want:     []string{"applies_to references", "nope"},
		},
		{
			name:     "sdk_since 不是该 sdk 的版本",
			entities: `{"id":"bm1","type":"chip","name":"n","status":"placeholder","aliases":["BM1"],"sdk":"s1","sdk_since":"v9","docs_dir":null,"index_dir":null},` + sdkEntity("s1", versionItem("v1", "v1", "2026-01-01", "docs/a", "idx/a")),
			docs:     []string{"docs/a"},
			want:     []string{"sdk_since", "v9", "not a version slug"},
		},
		{
			name:     "sources.repos 的 url 不是 http(s)",
			entities: sdkEntityExtra("s1", "", `"sources":{"repos":[{"name":"r","url":"git@github.com:sophgo/x.git","purpose":"p"}]}`),
			want:     []string{"must be an http(s) URL"},
		},
		{
			name:     "sources.manifest 的 default 不在 files 里",
			entities: sdkEntityExtra("s1", "", `"sources":{"manifest":{"url":"https://example.com/m.git","files":[{"path":"release/v2.2.xml","label":"v2.2"}],"default":"release/v9.xml"}}`),
			want:     []string{"default", "not listed in files"},
		},
		{
			name:     "shared_sources 的 repo 缺 purpose",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			body:     `{"schema_version": 3, "shared_sources": [{"name":"sophon-demo","url":"https://github.com/sophgo/sophon-demo","purpose":""}], "entities": [` + mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `]}`,
			want:     []string{"shared_sources.repos[0]"},
		},
		{
			name:     "ready 实体缺 docs_dir",
			entities: mk("se9", "product", "ready", null, `"idx/a"`, "SE9"),
			want:     []string{"requires docs_dir"},
		},
		{
			name:     "ready 实体的 docs_dir 不存在",
			entities: mk("se9", "product", "ready", `"docs/missing"`, `"idx/a"`, "SE9"),
			want:     []string{"does not exist"},
		},
		{
			name:     "ready 实体缺 index_dir",
			entities: mk("se9", "product", "ready", `"docs/a"`, null, "SE9"),
			docs:     []string{"docs/a"},
			want:     []string{"requires index_dir"},
		},
		{
			name:     "placeholder 实体带 docs_dir",
			entities: mk("cv1", "chip", "placeholder", `"docs/a"`, `"idx/a"`, "CV1"),
			docs:     []string{"docs/a"},
			want:     []string{"placeholder must have docs_dir=null"},
		},
		{
			name:     "placeholder 实体带 index_dir",
			entities: mk("cv1", "chip", "placeholder", null, `"idx/a"`, "CV1"),
			want:     []string{"placeholder must have index_dir=null"},
		},
		{
			name:     "别名缺失",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`),
			docs:     []string{"docs/a"},
			want:     []string{"aliases is empty"},
		},
		{
			name:     "schema_version 不支持",
			entities: mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9"),
			docs:     []string{"docs/a"},
			body:     `{"schema_version": 2, "entities": [` + mk("se9", "product", "ready", `"docs/a"`, `"idx/a"`, "SE9") + `]}`,
			want:     []string{"schema_version is 2, want 3"},
		},
		{
			name:     "空实体列表",
			entities: "",
			want:     []string{"no entities"},
		},
	}

	for _, c := range tt {
		t.Run(c.name, func(t *testing.T) {
			body := validRegistry(c.entities)
			if c.body != "" {
				body = c.body
			}
			reg, _ := writeRegistry(t, body, c.docs...)
			err := reg.Validate()
			if err == nil {
				t.Fatalf("expected validation error, got nil")
			}
			ve, ok := err.(*ValidationError)
			if !ok {
				t.Fatalf("error type = %T, want *ValidationError", err)
			}
			msg := err.Error()
			for _, w := range c.want {
				if !strings.Contains(msg, w) {
					t.Errorf("error should mention %q, got:\n%s", w, msg)
				}
			}
			if len(ve.Problems) == 0 {
				t.Error("ValidationError.Problems should list the problems")
			}
		})
	}
}

// 校验一次报全：多个问题同时存在时不能只报第一个。
func TestValidateReportsAllProblems(t *testing.T) {
	body := validRegistry(`{"id":"BAD_ID","type":"nope","name":"","status":"weird","aliases":[],"docs_dir":null,"index_dir":"x"}`)
	reg, _ := writeRegistry(t, body)
	err := reg.Validate()
	if err == nil {
		t.Fatal("expected errors")
	}
	ve := err.(*ValidationError)
	if len(ve.Problems) < 4 {
		t.Errorf("want several problems reported at once, got %d:\n%v", len(ve.Problems), ve.Problems)
	}
}

// 合法但边界的情形：多条别名、ready 的 module、规格、chip.sdk 指向带版本的 sdk 都应通过。
func TestValidateAcceptsLegitEdgeCases(t *testing.T) {
	body := validRegistry(se9SpecEntity + "," + sm916Entity + "," + sm98Entity + "," +
		bm1688Entity + "," + cv186ahEntity + "," + sdkEdgeEntity + "," +
		`{"id":"sm7","type":"module","name":"SM7","status":"ready","aliases":["SM7"],"chips":["bm1688"],"docs_dir":"docs/a","index_dir":"idx/a"}`)
	reg, _ := writeRegistry(t, body, "docs/se9", "docs/bm1688", "docs/a", "docs/sdk")
	if err := reg.Validate(); err != nil {
		t.Fatalf("legit registry rejected: %v", err)
	}
	// 规格按 (产品, 规格名) 取到；它不是实体，所以 ByID 查不到
	if _, ok := reg.Spec("se9", "SE9 8"); !ok {
		t.Error("Spec(se9, SE9 8) should exist")
	}
	if _, ok := reg.ByID("se9-8"); ok {
		t.Error("a spec must not be registered as an entity id")
	}
}

func TestSplitIDs(t *testing.T) {
	got := SplitIDs(" a, b ,,c , ")
	want := []string{"a", "b", "c"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("got %v, want %v", got, want)
			break
		}
	}
	if len(SplitIDs("")) != 0 {
		t.Errorf("empty input should yield no ids, got %v", SplitIDs(""))
	}
}
