package registry

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// 本文件覆盖 schema v3 的 sdk 实体：
//   - 版本选择（latest / 指定 slug / all）与 sdk_since 过滤；
//   - `<sdk>@<slug>` 的解析（CLI 层，见 cmd/se-rag/sdk_test.go）；
//   - SE_RAG_DATA_DIR 的索引落点覆盖；
//   - sdk 版本 / sources / shared_sources 的校验（错误用例见 registry_test.go）。

// sdkFixtureRegistry 带版本与源码登记的 sdk 夹具。
func sdkFixtureRegistry(t *testing.T) *Registry {
	t.Helper()
	root := t.TempDir()
	for _, d := range []string{"docs/sdk/v21", "docs/sdk/v22", "docs/sdk/v23"} {
		if err := os.MkdirAll(filepath.Join(root, d), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, d, "a.md"), []byte("# A\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return New(root,
		Entity{ID: "edge", Type: TypeSDK, Name: "SOPHONSDK Edge", Status: StatusPlaceholder,
			Aliases: []string{"edge", "边侧 SDK"},
			Versions: []Version{
				// 故意不按日期顺序登记：latest 必须按 release_date 判定。
				{Version: "v2.2", Slug: "v2.2", ReleaseDate: "2026-06-22",
					DocsDir: "docs/sdk/v22", IndexDir: "rag/data/sdk-edge-v2.2"},
				{Version: "v2.3", Slug: "v2.3", ReleaseDate: "2026-10-12",
					DocsDir: "docs/sdk/v23", IndexDir: "rag/data/sdk-edge-v2.3"},
				{Version: "v2.1", Slug: "v2.1", ReleaseDate: "2025-11-25",
					DocsDir: "docs/sdk/v21", IndexDir: "rag/data/sdk-edge-v2.1"},
			}},
		Entity{ID: "bm1688", Type: TypeChip, Name: "BM1688", Status: StatusPlaceholder,
			Aliases: []string{"BM1688"}, SDK: "edge"},
		Entity{ID: "cv84x6", Type: TypeChip, Name: "CV84X6", Status: StatusPlaceholder,
			Aliases: []string{"CV84X6"}, SDK: "edge", SDKSince: "v2.3"},
	)
}

// latest：只取按 release_date 最新的那一版（登记顺序不影响）。
func TestSelectVersionsLatest(t *testing.T) {
	reg := sdkFixtureRegistry(t)
	for _, req := range []SDKVersionRequest{
		{}, // 未指定
		{Raw: "latest"},
		{Raw: "LATEST"}, // 大小写不敏感
	} {
		got, notes, err := reg.SelectVersions("edge", req, "")
		if err != nil {
			t.Fatalf("req %+v: %v", req, err)
		}
		if len(got) != 1 || got[0].Version.Slug != "v2.3" {
			t.Fatalf("req %+v: versions = %v, want [v2.3] (newest by release_date)", req, versionLabels(got))
		}
		if len(notes) != 0 {
			t.Errorf("req %+v: unexpected notes %v", req, notes)
		}
	}
}

// 指定 slug：只取该版本；不存在的 slug 报错并列出可选值。
func TestSelectVersionsExplicit(t *testing.T) {
	reg := sdkFixtureRegistry(t)
	got, _, err := reg.SelectVersions("edge", SDKVersionRequest{Raw: "v2.2", Slug: "v2.2"}, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Version.Slug != "v2.2" {
		t.Fatalf("versions = %v, want [v2.2]", versionLabels(got))
	}

	_, _, err = reg.SelectVersions("edge", SDKVersionRequest{Raw: "v9", Slug: "v9"}, "")
	if err == nil {
		t.Fatal("an unknown version slug must be an error, not a silent fallback")
	}
	// 可选值按登记顺序列出（这里刻意的非时间顺序也照原样报，便于对照注册表）。
	for _, want := range []string{"v9", "v2.2,v2.3,v2.1"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error should mention %q, got %q", want, err.Error())
		}
	}
}

// all：全部版本，按 release_date 从新到旧。
func TestSelectVersionsAll(t *testing.T) {
	reg := sdkFixtureRegistry(t)
	got, _, err := reg.SelectVersions("edge", SDKVersionRequest{Raw: "all", All: true}, "")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"edge@v2.3", "edge@v2.2", "edge@v2.1"}
	if !reflect.DeepEqual(versionLabels(got), want) {
		t.Fatalf("versions = %v, want %v (newest first)", versionLabels(got), want)
	}
}

// sdk_since：早于芯片支持版本的版本跳过，并给出提示。
func TestSelectVersionsRespectsSDKSince(t *testing.T) {
	reg := sdkFixtureRegistry(t)

	// cv84x6 自 v2.3 起支持：latest 恰好是 v2.3，不受影响
	got, notes, err := reg.SelectVersions("edge", SDKVersionRequest{}, "cv84x6")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(versionLabels(got), []string{"edge@v2.3"}) {
		t.Fatalf("versions = %v, want [edge@v2.3]", versionLabels(got))
	}
	if len(notes) != 0 {
		t.Errorf("the latest version is supported, so there is nothing to skip: %v", notes)
	}

	// all：v2.1 / v2.2 早于 v2.3，跳过并各给一条提示
	got, notes, err = reg.SelectVersions("edge", SDKVersionRequest{Raw: "all", All: true}, "cv84x6")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(versionLabels(got), []string{"edge@v2.3"}) {
		t.Fatalf("versions = %v, want [edge@v2.3] only", versionLabels(got))
	}
	if len(notes) != 2 {
		t.Fatalf("want 2 skip notes (v2.2, v2.1), got %v", notes)
	}
	for _, n := range notes {
		if !strings.Contains(n, "cv84x6") || !strings.Contains(n, "v2.3") {
			t.Errorf("note should name the chip and its first supported version: %q", n)
		}
	}

	// 显式指定早于 sdk_since 的版本：跳过全部 → 没有检索目标，但要有提示
	got, notes, err = reg.SelectVersions("edge", SDKVersionRequest{Raw: "v2.2", Slug: "v2.2"}, "cv84x6")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Fatalf("v2.2 predates cv84x6 support, want no target, got %v", versionLabels(got))
	}
	if len(notes) != 1 || !strings.Contains(notes[0], "v2.2") {
		t.Errorf("want one note about v2.2, got %v", notes)
	}

	// 没有 sdk_since 的芯片不受影响
	got, _, err = reg.SelectVersions("edge", SDKVersionRequest{Raw: "all", All: true}, "bm1688")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Errorf("bm1688 has no sdk_since, so all versions apply, got %v", versionLabels(got))
	}
}

// 没有版本的 sdk：返回空，不报错（调用方负责给出"还没登记版本"的提示）。
func TestSelectVersionsEmpty(t *testing.T) {
	reg := New(t.TempDir(), Entity{ID: "s1", Type: TypeSDK, Name: "S1", Status: StatusPlaceholder,
		Aliases: []string{"S1"}})
	got, notes, err := reg.SelectVersions("s1", SDKVersionRequest{}, "")
	if err != nil || len(got) != 0 || len(notes) != 0 {
		t.Fatalf("empty sdk: versions=%v notes=%v err=%v", versionLabels(got), notes, err)
	}
	if _, _, err := reg.SelectVersions("nope", SDKVersionRequest{}, ""); err == nil {
		t.Fatal("unknown sdk must be an error")
	}
}

// 非 sdk 实体不能当 sdk 用。
func TestSelectVersionsRejectsNonSDK(t *testing.T) {
	reg := New(t.TempDir(), Entity{ID: "bm1", Type: TypeChip, Name: "BM1", Status: StatusPlaceholder,
		Aliases: []string{"BM1"}})
	_, _, err := reg.SelectVersions("bm1", SDKVersionRequest{}, "")
	if err == nil || !strings.Contains(err.Error(), "not an sdk") {
		t.Fatalf("want a 'not an sdk' error, got %v", err)
	}
}

// ParseSDKVersion：空 / latest / all / slug 四种取值。
func TestParseSDKVersion(t *testing.T) {
	cases := []struct {
		in      string
		want    SDKVersionRequest
		isDflt  bool
		wantErr bool
	}{
		{"", SDKVersionRequest{}, true, false},
		{"latest", SDKVersionRequest{Raw: "latest"}, true, false},
		{"LATEST", SDKVersionRequest{Raw: "LATEST"}, true, false},
		{"all", SDKVersionRequest{Raw: "all", All: true}, false, false},
		{" all ", SDKVersionRequest{Raw: "all", All: true}, false, false},
		{"v2.3", SDKVersionRequest{Raw: "v2.3", Slug: "v2.3"}, false, false},
		{"V2.3", SDKVersionRequest{Raw: "V2.3", Slug: "V2.3"}, false, false},
	}
	for _, c := range cases {
		got, err := ParseSDKVersion(c.in)
		if (err != nil) != c.wantErr {
			t.Fatalf("ParseSDKVersion(%q) err = %v", c.in, err)
		}
		if got != c.want {
			t.Errorf("ParseSDKVersion(%q) = %+v, want %+v", c.in, got, c.want)
		}
		if got.Default() != c.isDflt {
			t.Errorf("ParseSDKVersion(%q).Default() = %v, want %v", c.in, got.Default(), c.isDflt)
		}
	}
}

// SE_RAG_DATA_DIR：索引改落到 <覆盖目录>/<index_dir 末级名>，文档目录与展示路径不受影响。
func TestDataDirOverridesIndexPaths(t *testing.T) {
	root := t.TempDir()
	reg := New(root,
		Entity{ID: "se9", Type: TypeProduct, Name: "SE9", Status: StatusReady,
			Aliases: []string{"SE9"}, DocsDir: "docs/products/se9",
			IndexDir: "rag/data/product-se9"},
		Entity{ID: "edge", Type: TypeSDK, Name: "SDK", Status: StatusPlaceholder,
			Aliases: []string{"SDK"},
			Versions: []Version{{Version: "v2.3", Slug: "v2.3", ReleaseDate: "2026-10-12",
				DocsDir: "docs/sdks/edge/v2.3", IndexDir: "rag/data/sdk-edge-v2.3"}}},
	)
	se9, _ := reg.ByID("se9")
	ver, _ := reg.Version("edge", "v2.3")

	// 未设置：沿用注册表里的 index_dir
	if got, want := reg.IndexPath(se9), filepath.Join(root, "rag/data/product-se9"); got != want {
		t.Errorf("index path = %q, want %q", got, want)
	}
	if got := reg.IndexPathLabel(se9); got != "rag/data/product-se9" {
		t.Errorf("index label = %q, want the registry value", got)
	}

	// 设置后：只换前缀，保留末级目录名
	dataDir := filepath.Join(t.TempDir(), "se-rag-data")
	t.Setenv(DataDirEnv, dataDir)
	if got, want := reg.IndexPath(se9), filepath.Join(dataDir, "product-se9"); got != want {
		t.Errorf("index path = %q, want %q", got, want)
	}
	if got, want := reg.IndexPathLabel(se9), filepath.Join(dataDir, "product-se9"); got != want {
		t.Errorf("index label = %q, want %q", got, want)
	}
	// 版本索引同样被覆盖
	if got, want := reg.VersionIndexPath(ver), filepath.Join(dataDir, "sdk-edge-v2.3"); got != want {
		t.Errorf("version index path = %q, want %q", got, want)
	}
	// 文档目录不受影响（文档是随技能分发的，不写）
	if got, want := reg.DocsPath(se9), filepath.Join(root, "docs/products/se9"); got != want {
		t.Errorf("docs path = %q, want %q (SE_RAG_DATA_DIR must not touch docs)", got, want)
	}
	// 块路径仍按技能根相对路径展示
	if got, want := reg.ChunkPath(se9, "faq/i2c.md"), "docs/products/se9/faq/i2c.md"; got != want {
		t.Errorf("chunk path = %q, want %q", got, want)
	}
	if got, want := reg.ChunkPathForVersion(ver, "a.md"), "docs/sdks/edge/v2.3/a.md"; got != want {
		t.Errorf("version chunk path = %q, want %q", got, want)
	}
	// placeholder 仍然没有索引路径
	ph, _ := reg.ByID("edge")
	if reg.IndexPath(ph) != "" {
		t.Errorf("placeholder index path = %q, want empty even with %s set", reg.IndexPath(ph), DataDirEnv)
	}
}

// 两个实体的索引末级目录名不同，覆盖后不会互相覆盖。
func TestDataDirKeepsLastSegment(t *testing.T) {
	reg := New(t.TempDir(),
		Entity{ID: "a", Type: TypeProduct, Name: "A", Status: StatusReady,
			Aliases: []string{"A"}, DocsDir: "docs/a", IndexDir: "rag/data/product-a"},
		Entity{ID: "b", Type: TypeProduct, Name: "B", Status: StatusReady,
			Aliases: []string{"B"}, DocsDir: "docs/b", IndexDir: "rag/data/product-b"},
	)
	dataDir := t.TempDir()
	t.Setenv(DataDirEnv, dataDir)
	a, _ := reg.ByID("a")
	b, _ := reg.ByID("b")
	if reg.IndexPath(a) == reg.IndexPath(b) {
		t.Fatalf("%s made two entities share one index dir: %q", DataDirEnv, reg.IndexPath(a))
	}
	if filepath.Base(reg.IndexPath(a)) != "product-a" || filepath.Base(reg.IndexPath(b)) != "product-b" {
		t.Errorf("last path segment should be preserved: %q / %q", reg.IndexPath(a), reg.IndexPath(b))
	}
}

// sdk 版本与 sources 的合法写法要通过校验（含 shared_sources）。
func TestValidateAcceptsSDKWithSources(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "docs/sdk"), 0o755); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(root, "registry.json")
	body := `{"schema_version": 3,
	  "shared_sources": [
	    {"name":"sophon-demo","url":"https://github.com/sophgo/sophon-demo","purpose":"CV/LLM demo"}
	  ],
	  "entities": [
	    {"id":"edge","type":"sdk","name":"SOPHONSDK Edge","status":"ready",
	     "aliases":["edge","边侧 SDK"],
	     "versions":[{"version":"v2.3","slug":"v2.3","release_date":"2026-10-12",
	                  "docs_dir":"docs/sdk","index_dir":"rag/data/sdk-edge-v2.3",
	                  "applies_to":["bm1688"]}],
	     "sources":{
	       "repos":[{"name":"libsophon","url":"https://github.com/sophgo/libsophon","purpose":"BSP"}],
	       "manifest":{"url":"https://github.com/sophgo/manifest","files":[
	         {"path":"release/v2.2_all_repos.xml","label":"v2.2"}],
	         "default":"release/v2.2_all_repos.xml"},
	       "notes":["v2.3 只有源码包"]},
	     "docs_dir":null,"index_dir":null,
	     "scope":"边侧 SDK","boundaries":["b"],"query_hints":["h"]},
	    {"id":"bm1688","type":"chip","name":"BM1688","status":"placeholder",
	     "aliases":["BM1688"],"sdk":"edge","docs_dir":null,"index_dir":null,
	     "scope":"s","boundaries":["b"],"query_hints":["h"]}
	  ]}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := Load(p)
	if err != nil {
		t.Fatal(err)
	}
	if err := reg.Validate(); err != nil {
		t.Fatalf("a well-formed sdk registry was rejected: %v", err)
	}
	if len(reg.Warnings()) != 0 {
		t.Errorf("unexpected warnings: %v", reg.Warnings())
	}
	if len(reg.SharedSources) != 1 || reg.SharedSources[0].Name != "sophon-demo" {
		t.Errorf("shared_sources not parsed: %+v", reg.SharedSources)
	}
	e, _ := reg.ByID("edge")
	if e.Sources == nil || len(e.Sources.Repos) != 1 || e.Sources.Manifest == nil {
		t.Fatalf("sources not parsed: %+v", e.Sources)
	}
	if e.Versions[0].AppliesTo[0] != "bm1688" {
		t.Errorf("applies_to not parsed: %+v", e.Versions[0].AppliesTo)
	}
}

// sdk_since 在 sdk 还没有版本时只给警告（暂存），不拦校验。
func TestSDKSinceWarnsWhenVersionsAreEmpty(t *testing.T) {
	reg := New(t.TempDir(),
		Entity{ID: "edge", Type: TypeSDK, Name: "SDK", Status: StatusPlaceholder,
			Aliases: []string{"edge"}},
		Entity{ID: "cv1", Type: TypeChip, Name: "CV1", Status: StatusPlaceholder,
			Aliases: []string{"CV1"}, SDK: "edge", SDKSince: "v2.3"},
	)
	if err := reg.Validate(); err != nil {
		t.Fatalf("sdk_since on an empty-version sdk should only warn, got %v", err)
	}
	warns := reg.Warnings()
	if len(warns) != 1 || !strings.Contains(warns[0], "sdk_since") || !strings.Contains(warns[0], "cannot be verified") {
		t.Fatalf("warnings = %v, want one 'cannot be verified' note", warns)
	}
}

// 版本不是实体：ByID 查不到，-entity 也不能直接用它（CLI 层用 <sdk>@<slug>）。
func TestVersionIsNotAnEntity(t *testing.T) {
	reg := sdkFixtureRegistry(t)
	if _, ok := reg.ByID("v2.3"); ok {
		t.Error("a version slug must not be an entity id")
	}
	if _, ok := reg.Version("edge", "v2.3"); !ok {
		t.Error("Version(edge, v2.3) should exist")
	}
	if _, ok := reg.Version("other", "v2.3"); ok {
		t.Error("versions belong to their sdk; another sdk must not resolve it")
	}
}

// LatestVersion：没有版本时返回 nil；有版本时按日期取最新。
func TestLatestVersion(t *testing.T) {
	if got := New(t.TempDir(), Entity{ID: "s", Type: TypeSDK, Name: "s",
		Status: StatusPlaceholder, Aliases: []string{"s"}}).LatestVersion("s"); got != nil {
		t.Errorf("LatestVersion on an empty sdk = %+v, want nil", got)
	}
	reg := sdkFixtureRegistry(t)
	if got := reg.LatestVersion("edge"); got == nil || got.Slug != "v2.3" {
		t.Errorf("LatestVersion = %+v, want v2.3", got)
	}
	if got := reg.LatestVersion("nope"); got != nil {
		t.Errorf("LatestVersion(unknown) = %+v, want nil", got)
	}
}

// sdk 的 status 是 versions 的派生结论（MYS-2655）：有版本必须 ready，没有版本必须
// placeholder。这两条钉住"list 不会把有文档的 SDK 显示成占位"。
func TestSDKStatusFollowsVersions(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "docs/sdk"), 0o755); err != nil {
		t.Fatal(err)
	}
	write := func(body string) *ValidationError {
		t.Helper()
		p := filepath.Join(root, "registry.json")
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		reg, err := Load(p)
		if err != nil {
			t.Fatal(err)
		}
		verr, _ := reg.Validate().(*ValidationError)
		return verr
	}
	version := `{"version":"v2.3","slug":"v2.3","release_date":"2026-10-12",` +
		`"docs_dir":"docs/sdk","index_dir":"rag/data/sdk-edge-v2.3"}`

	// 有版本 + ready：通过，且顶层两个路径仍必须是 null。
	if verr := write(`{"schema_version":3,"entities":[
		{"id":"edge","type":"sdk","name":"Edge","status":"ready","aliases":["edge"],
		 "versions":[` + version + `],"docs_dir":null,"index_dir":null}]}`); verr != nil {
		t.Errorf("ready sdk with versions should validate, got %v", verr.Problems)
	}
	// 有版本 + placeholder：拒绝（这就是 list 显示成占位的那个 bug）。
	if verr := write(`{"schema_version":3,"entities":[
		{"id":"edge","type":"sdk","name":"Edge","status":"placeholder","aliases":["edge"],
		 "versions":[` + version + `],"docs_dir":null,"index_dir":null}]}`); verr == nil {
		t.Error("placeholder sdk with versions should be rejected")
	}
	// 无版本 + ready：拒绝。
	if verr := write(`{"schema_version":3,"entities":[
		{"id":"edge","type":"sdk","name":"Edge","status":"ready","aliases":["edge"],
		 "versions":[],"docs_dir":null,"index_dir":null}]}`); verr == nil {
		t.Error("ready sdk without versions should be rejected")
	}
	// sdk 仍然是唯一允许 ready + 顶层路径为 null 的类型：给它顶层 docs_dir 会被拒。
	if verr := write(`{"schema_version":3,"entities":[
		{"id":"edge","type":"sdk","name":"Edge","status":"ready","aliases":["edge"],
		 "versions":[` + version + `],"docs_dir":"docs/sdk","index_dir":null}]}`); verr == nil {
		t.Error("sdk must not carry a top-level docs_dir")
	}
}

// sdk 的检索目标永远是版本：即使 status=ready，sdk id 也不能进 IDs（否则 build/query
// 会拿到空的顶层目录），-all 的 ReadyIDs 同理不应包含 sdk。
func TestSDKReadyEntityIsNeverASearchTarget(t *testing.T) {
	reg := sdkFixtureRegistry(t)
	exp, err := reg.Related("edge")
	if err != nil {
		t.Fatal(err)
	}
	if len(exp.IDs) != 0 {
		t.Errorf("sdk ids must stay out of IDs, got %v", exp.IDs)
	}
	if exp.Skipped != nil {
		t.Errorf("a ready sdk is not skipped (its versions are the targets), got %v", exp.Skipped)
	}
	if got := versionLabels(exp.Versions); len(got) != 1 || got[0] != "edge@v2.3" {
		t.Errorf("versions = %v, want [edge@v2.3]", got)
	}
	for _, id := range reg.ReadyIDs() {
		if id == "edge" {
			t.Errorf("ReadyIDs must not include sdk entities, got %v", reg.ReadyIDs())
		}
	}
	// 没有版本的 sdk 才记一条跳过说明。
	empty := New(t.TempDir(), Entity{ID: "s2", Type: TypeSDK, Name: "S2",
		Status: StatusPlaceholder, Aliases: []string{"s2"}})
	exp, err = empty.Related("s2")
	if err != nil {
		t.Fatal(err)
	}
	if len(exp.Skipped) != 1 || exp.Skipped[0].ID != "s2" {
		t.Errorf("versionless sdk should be skipped, got %v", exp.Skipped)
	}
}
