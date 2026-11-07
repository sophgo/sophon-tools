package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"se-rag-core/internal/docstore"
	"se-rag-core/internal/registry"
)

// 本文件覆盖 schema v3 在 CLI 层的行为：
//   - `-entity <sdk>` / `<sdk>@<slug>` 的解析（含错误提示）；
//   - `-sdk-version latest|all|<slug>`；
//   - `build -all` 建全部 sdk 版本；
//   - `list` 逐版本列出索引状态；
//   - `resolve` 输出 sdk 与版本列表；
//   - SE_RAG_DATA_DIR 下 build 的落点与 list/doctor 的展示。
// 夹具见 testdata/registry（sophonsdk 一版、sophonsdk-edge 两版；cv84x6 sdk_since=v2.3）。

// sdkFixture 夹具里的两个 sdk（testdata/registry）。
const (
	fixtureSDK     = "sophonsdk"      // 一版：v23.09
	fixtureSDKEdge = "sophonsdk-edge" // 两版：v2.3（最新）、v2.2
)

// sdk 实体默认只取最新版本：-entity <sdk> 解析成一个版本目标。
func TestEntitySDKDefaultsToLatestVersion(t *testing.T) {
	dir := testRegistryDir(t)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	ts, err := targetEntities(reg, fixtureSDKEdge, false, registry.SDKVersionRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(ts) != 1 || ts[0].Label() != "sophonsdk-edge@v2.3" {
		t.Fatalf("targets = %v, want [sophonsdk-edge@v2.3] (newest by release_date)", ts)
	}
	if ts[0].Ver == nil {
		t.Fatal("an sdk target must carry its version")
	}
}

// `<sdk>@<slug>` 精确指定版本。
func TestEntitySDKVersionRef(t *testing.T) {
	dir := testRegistryDir(t)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	ts, err := targetEntities(reg, fixtureSDKEdge+"@v2.2", false, registry.SDKVersionRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(ts) != 1 || ts[0].Label() != "sophonsdk-edge@v2.2" {
		t.Fatalf("targets = %v, want [sophonsdk-edge@v2.2]", ts)
	}
	// 文档与索引目录取自版本本身
	if !strings.HasSuffix(ts[0].DocsDir(reg), "docs/sdks/sophonsdk-edge/v2.2") {
		t.Errorf("docs dir = %q, want the v2.2 docs", ts[0].DocsDir(reg))
	}
	if !strings.HasSuffix(ts[0].IndexDir(reg), "sdk-sophonsdk-edge-v2.2") {
		t.Errorf("index dir = %q, want the v2.2 index", ts[0].IndexDir(reg))
	}
}

// `<sdk>@<slug>` 的错误写法：未知 sdk、未知版本都要报错并给出可选值。
func TestEntitySDKVersionRefErrors(t *testing.T) {
	dir := testRegistryDir(t)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	_, err = targetEntities(reg, "nosuchsdk@v1", false, registry.SDKVersionRequest{})
	if err == nil || !strings.Contains(err.Error(), "unknown sdk") {
		t.Errorf("unknown sdk should be reported, got %v", err)
	}
	_, err = targetEntities(reg, fixtureSDKEdge+"@v9.9", false, registry.SDKVersionRequest{})
	if err == nil {
		t.Fatal("an unknown version slug should fail")
	}
	for _, want := range []string{"v9.9", "v2.3,v2.2"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error should mention %q, got %q", want, err.Error())
		}
	}
	// 实体后面挂版本号也不该被当成 sdk 版本
	if _, err := targetEntities(reg, "se9@v1", false, registry.SDKVersionRequest{}); err == nil {
		t.Error("only an sdk accepts @<slug>")
	}
}

// -sdk-version all：一个 sdk 展开成多个版本目标。
func TestEntitySDKVersionAll(t *testing.T) {
	dir := testRegistryDir(t)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	req, err := registry.ParseSDKVersion("all")
	if err != nil {
		t.Fatal(err)
	}
	ts, err := targetEntities(reg, fixtureSDKEdge, false, req)
	if err != nil {
		t.Fatal(err)
	}
	var labels []string
	for _, t := range ts {
		labels = append(labels, t.Label())
	}
	want := []string{"sophonsdk-edge@v2.3", "sophonsdk-edge@v2.2"}
	if strings.Join(labels, ",") != strings.Join(want, ",") {
		t.Fatalf("targets = %v, want %v (every version, newest first)", labels, want)
	}
}

// build -all 覆盖全部 sdk 版本（不只最新版），每版一套索引。
func TestBuildAllBuildsEverySDKVersion(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)

	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"sophonsdk@v23.09", "sophonsdk-edge@v2.3", "sophonsdk-edge@v2.2"} {
		sdkID, slug, _ := strings.Cut(want, "@")
		e, _ := reg.ByID(sdkID)
		v, ok := reg.Version(sdkID, slug)
		if !ok {
			t.Fatalf("%s: version not found", want)
		}
		_ = e
		if !metaExists(reg.VersionIndexPath(v)) {
			t.Errorf("%s: index missing after build -all (path %s)", want, reg.VersionIndexPath(v))
		}
		// meta 的 product 标签写 <sdk>@<slug>，与结果标注一致
		meta, err := (&docstore.Store{IndexDir: reg.VersionIndexPath(v)}).ReadMeta(want)
		if err != nil {
			t.Fatalf("%s: read meta: %v", want, err)
		}
		if meta.Product != want {
			t.Errorf("%s: meta.product = %q, want %q", want, meta.Product, want)
		}
	}
}

// list：sdk 逐版本列出索引状态；-json 里 versions 带 index_built。
func TestListShowsSDKVersions(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir)}); rc != 0 {
			t.Fatalf("list rc=%d", rc)
		}
	})
	for _, want := range []string{"sophonsdk-edge", "v2.3", "v2.2", "released=2026-10-12"} {
		if !strings.Contains(out, want) {
			t.Errorf("list output missing %q:\n%s", want, out)
		}
	}
	// sdk 自身的 INDEX 列是 versions（索引挂在版本上）
	if !strings.Contains(out, "versions") {
		t.Errorf("sdk rows should report INDEX=versions:\n%s", out)
	}

	buildAllOffline(t, dir)
	jsonOut := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir), "-json"}); rc != 0 {
			t.Fatalf("list -json rc=%d", rc)
		}
	})
	var entries []listEntry
	if err := json.Unmarshal([]byte(jsonOut), &entries); err != nil {
		t.Fatalf("list -json is not JSON: %v\n%s", err, jsonOut)
	}
	byID := map[string]listEntry{}
	for _, e := range entries {
		byID[e.ID] = e
	}
	edge := byID[fixtureSDKEdge]
	if edge.Type != "sdk" {
		t.Fatalf("sophonsdk-edge type = %q, want sdk", edge.Type)
	}
	if len(edge.Versions) != 2 {
		t.Fatalf("sophonsdk-edge versions = %d, want 2", len(edge.Versions))
	}
	for _, v := range edge.Versions {
		if !v.IndexBuilt {
			t.Errorf("version %s should be reported as built", v.Slug)
		}
		if v.ReleaseDate == "" {
			t.Errorf("version %s should report its release_date", v.Slug)
		}
		// MYS-2661：未设 SE_RAG_DATA_DIR 时版本行显示**注册表原文**（相对技能根），
		// 与实体行同一风格，不能打出技能根的绝对路径。
		if v.IndexAt != v.IndexDir {
			t.Errorf("version %s 的 index_at = %q，应为注册表原文 %q",
				v.Slug, v.IndexAt, v.IndexDir)
		}
		if filepath.IsAbs(v.IndexAt) {
			t.Errorf("version %s 的 index_at 是绝对路径：%q", v.Slug, v.IndexAt)
		}
		if !strings.Contains(out, v.IndexDir) {
			t.Errorf("list 文本输出缺少版本索引相对路径 %q：\n%s", v.IndexDir, out)
		}
	}
}

// resolve 命中芯片时给出版本列表与本次检索目标；命中的是最新版本。
func TestResolveReportsSDKVersions(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "BM1688 的 sail"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	for _, want := range []string{"sdk=sophonsdk-edge", "v2.3", "v2.2", "search targets: sophonsdk-edge@v2.3"} {
		if !strings.Contains(out, want) {
			t.Errorf("resolve output missing %q:\n%s", want, out)
		}
	}
}

// resolve 命中 sdk 别名：sdk 自身 status=ready（版本已登记），检索目标是它的版本。
func TestResolveSDKEntityByName(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "-json", "BM1684 SDK"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(out), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
	}
	var hit *resolveHit
	for i := range hits {
		if hits[i].EntityID == fixtureSDK {
			hit = &hits[i]
		}
	}
	if hit == nil {
		t.Fatalf("resolve should hit sophonsdk via its alias:\n%s", out)
	}
	if hit.Type != "sdk" || hit.Status != "ready" {
		t.Errorf("hit type/status = %s/%s, want sdk/ready", hit.Type, hit.Status)
	}
	if len(hit.SDKVersions) != 1 || hit.SDKVersions[0].Slug != "v23.09" {
		t.Fatalf("sdk_versions = %+v, want one v23.09", hit.SDKVersions)
	}
	if !hit.SDKVersions[0].Selected {
		t.Error("the only version is the newest one, so it should be selected")
	}
}

// cv84x6 带 sdk_since=v2.3：resolve 只把 v2.3 标成检索目标，v2.2 不选。
func TestResolveRespectsSDKSince(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "-json", "CV84X6"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(out), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, out)
	}
	var selected []string
	for _, h := range hits {
		if h.EntityID != "cv84x6" {
			continue
		}
		for _, v := range h.SDKVersions {
			if v.Selected {
				selected = append(selected, v.Slug)
			}
		}
	}
	if len(selected) != 1 || selected[0] != "v2.3" {
		t.Fatalf("selected versions for cv84x6 = %v, want [v2.3] (sdk_since=v2.3)", selected)
	}
}

// query -entity <sdk>@<slug> 与 -sdk-version all 都能跑通并标注目标。
func TestQuerySDKVersions(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", loadTestRegistry(t, dir),
			"-entity", fixtureSDKEdge + "@v2.2", "-offline", "sophon-sail"}); rc != 0 {
			t.Fatalf("query one version rc=%d", rc)
		}
	})
	// 单版本单索引走路径模式的输出：不带标注，但内容必须来自 v2.2
	if !strings.Contains(out, "dpkg -i sophon-sail_2.2") {
		t.Errorf("query should search the v2.2 index:\n%s", out)
	}
	if strings.Contains(out, "sudo apt install sophon-sail") {
		t.Errorf("v2.3 的内容不应出现在 v2.2 的检索结果里:\n%s", out)
	}
}

// SE_RAG_DATA_DIR：build 落到覆盖目录；list/doctor 显示实际路径。
func TestDataDirBuildAndDoctor(t *testing.T) {
	dir := testRegistryDir(t)
	dataDir := filepath.Join(t.TempDir(), "se-rag-data")
	t.Setenv(registry.DataDirEnv, dataDir)

	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-offline"}); rc != 0 {
			t.Fatalf("build rc=%d", rc)
		}
	})
	// 索引落在 <SE_RAG_DATA_DIR>/<index_dir 末级名>
	wantIdx := filepath.Join(dataDir, "product-se9")
	if !metaExists(wantIdx) {
		entries, _ := os.ReadDir(dataDir)
		var names []string
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("index should land in %s, data dir contains %v", wantIdx, names)
	}
	// 技能根下的 indexes/ 不该被写
	if _, err := os.Stat(filepath.Join(dir, "indexes", "product-se9", "meta.json")); err == nil {
		t.Error("nothing should be written under the skill root when SE_RAG_DATA_DIR is set")
	}

	// list 的 -json 报出实际落点
	jsonOut := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir), "-json"}); rc != 0 {
			t.Fatalf("list rc=%d", rc)
		}
	})
	var entries []listEntry
	if err := json.Unmarshal([]byte(jsonOut), &entries); err != nil {
		t.Fatalf("list -json: %v\n%s", err, jsonOut)
	}
	for _, e := range entries {
		if e.ID != "se9" {
			continue
		}
		if e.IndexAt != wantIdx {
			t.Errorf("list index_at = %q, want %q", e.IndexAt, wantIdx)
		}
		if e.IndexDir != "indexes/product-se9" {
			t.Errorf("list index_dir = %q, want the registry value", e.IndexDir)
		}
		if !e.IndexBuilt {
			t.Error("se9 index should be reported as built in the override dir")
		}
	}

	// doctor 能找到覆盖目录里的索引，并说明落点
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"doctor", "-registry", loadTestRegistry(t, dir), "-entity", "se9"}); rc != 0 {
			t.Fatalf("doctor rc=%d", rc)
		}
	})
	if !strings.Contains(out, "index at: "+wantIdx) {
		t.Errorf("doctor should show the overridden index path:\n%s", out)
	}
	if !strings.Contains(out, "no rebuild needed") {
		t.Errorf("doctor should accept the index in the override dir:\n%s", out)
	}
}

// SE_RAG_DATA_DIR 下，list 的**版本行**也要显示覆盖后的绝对路径（与实体行同一规则）。
func TestListVersionRowsShowAbsPathUnderDataDir(t *testing.T) {
	dir := testRegistryDir(t)
	dataDir := filepath.Join(t.TempDir(), "se-rag-data")
	t.Setenv(registry.DataDirEnv, dataDir)
	buildAllOffline(t, dir)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir)}); rc != 0 {
			t.Fatalf("list rc=%d", rc)
		}
	})
	want := filepath.Join(dataDir, "sdk-sophonsdk-edge-v2.3")
	if !strings.Contains(out, want) {
		t.Errorf("list 的版本行应显示覆盖后的绝对路径 %q：\n%s", want, out)
	}

	jsonOut := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir), "-json"}); rc != 0 {
			t.Fatalf("list -json rc=%d", rc)
		}
	})
	var entries []listEntry
	if err := json.Unmarshal([]byte(jsonOut), &entries); err != nil {
		t.Fatalf("list -json: %v\n%s", err, jsonOut)
	}
	for _, e := range entries {
		if e.ID != fixtureSDKEdge {
			continue
		}
		for _, v := range e.Versions {
			want := filepath.Join(dataDir, "sdk-"+fixtureSDKEdge+"-"+v.Slug)
			if v.IndexAt != want {
				t.Errorf("version %s 的 index_at = %q，应为覆盖后的 %q", v.Slug, v.IndexAt, want)
			}
			if v.IndexDir == v.IndexAt {
				t.Errorf("version %s 的 index_dir 应保持注册表原文，实际被覆盖成 %q",
					v.Slug, v.IndexDir)
			}
		}
	}
}

// -all 跳过 versions 为空的 sdk 并提示（不静默少查）。
func TestBuildAllNotesEmptySDKs(t *testing.T) {
	t.Setenv("SE_RAG_EMBED_KEY", "")
	t.Setenv("SE_RAG_RERANK_KEY", "")
	dir := testRegistryDir(t)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	// 把一个 sdk 的版本清空，模拟本卡的真实状态（两个 sdk 都是占位）。
	for i := range reg.Entities {
		if reg.Entities[i].ID == fixtureSDK {
			reg.Entities[i].Versions = nil
		}
	}
	var stderr string
	captureStdout(t, func() {
		stderr = captureStderr(t, func() {
			ts, err := targetEntities(reg, "", true, registry.SDKVersionRequest{})
			if err != nil {
				t.Fatalf("targetEntities -all: %v", err)
			}
			for _, x := range ts {
				if x.ID == fixtureSDK {
					t.Errorf("-all must skip %s (no versions), got %v", fixtureSDK, x.Label())
				}
			}
			if len(ts) == 0 {
				t.Fatal("-all should still return the ready entities and the other sdk's versions")
			}
		})
	})
	if !strings.Contains(stderr, "skipped sdk "+fixtureSDK) || !strings.Contains(stderr, "no versions") {
		t.Errorf("a skipped sdk must be reported on stderr, got %q", stderr)
	}
}

// `<sdk>@<slug>` 的 splitVersionRef 细节：合法的才拆。
func TestSplitVersionRef(t *testing.T) {
	cases := []struct {
		in       string
		sdk, ver string
		ok       bool
	}{
		{"edge@v2.3", "edge", "v2.3", true},
		{"edge@v2.3-rc1", "edge", "v2.3-rc1", true},
		{"edge", "", "", false},
		{"@v2.3", "", "", false},
		{"edge@", "", "", false},
	}
	for _, c := range cases {
		sdk, ver, ok := splitVersionRef(c.in)
		if sdk != c.sdk || ver != c.ver || ok != c.ok {
			t.Errorf("splitVersionRef(%q) = (%q,%q,%v), want (%q,%q,%v)",
				c.in, sdk, ver, ok, c.sdk, c.ver, c.ok)
		}
	}
}
