package main

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/embed"
)

// testRegistryDir 夹具注册表目录（技能根）：注册表 + docs/ 都受版本控制。
// 索引目录 indexes/ 是运行产物，每个测试复制一份到临时目录再建，避免污染仓库。
func testRegistryDir(t *testing.T) string {
	t.Helper()
	src, err := filepath.Abs(filepath.Join("testdata", "registry"))
	if err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(t.TempDir(), "registry")
	if err := copyTree(src, dst); err != nil {
		t.Fatalf("copy fixture registry: %v", err)
	}
	return dst
}

// copyTree 递归复制目录（go.mod 声明 go1.21，用不了 os.CopyFS）。
func copyTree(src, dst string) error {
	return filepath.Walk(src, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
}

// loadTestRegistry 读取夹具注册表。
func loadTestRegistry(t *testing.T, dir string) (regPath string) {
	t.Helper()
	return filepath.Join(dir, "registry.json")
}

// captureStderr 捕获函数执行期间的 stderr（dispatch 把错误写到 os.Stderr）。
func captureStderr(t *testing.T, f func()) string {
	t.Helper()
	old := os.Stderr
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stderr = w
	done := make(chan string, 1)
	go func() {
		buf, _ := io.ReadAll(r)
		done <- string(buf)
	}()
	f()
	w.Close()
	os.Stderr = old
	return <-done
}

// buildAllOffline 用 -offline 建全部 ready 实体的索引（不联网、不构造 embedder）。
func buildAllOffline(t *testing.T, dir string) {
	t.Helper()
	var rc int
	captureStdout(t, func() {
		rc = dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-all", "-offline"})
	})
	if rc != 0 {
		t.Fatalf("build -all -offline rc=%d, want 0", rc)
	}
}

// fakeCtxCfg 让 runQueryEntities 的在线路径使用 2 维 fake embedder/reranker。
//
// 注册表模式的在线检索走 runQueryEntities（内部自行构造 rc），所以这里用
// SE_RAG_FAKE_EMBED 端到端跑：fake embedder 是 2 维，与 -offline 无关，
// 用于验证「在线多索引 rerank 只调用一次」。
func TestRegistryBuildAllOffline(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)

	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range reg.ReadyIDs() {
		e, _ := reg.ByID(id)
		meta, err := (&docstore.Store{IndexDir: reg.IndexPath(e)}).ReadMeta(id)
		if err != nil {
			t.Fatalf("entity %s: read meta: %v", id, err)
		}
		// meta.json 的 product 字段写实体 id（路径模式写 default）
		if meta.Product != id {
			t.Errorf("entity %s: meta.product = %q, want the entity id", id, meta.Product)
		}
		if !meta.BM25Only() {
			t.Errorf("entity %s: search_mode = %q, want bm25 (offline build)", id, meta.SearchMode)
		}
	}
	// placeholder 不该有索引目录
	for _, id := range []string{"cv186ah", "cv84x6", "sm9-16", "sm9-8"} {
		e, _ := reg.ByID(id)
		if _, err := os.Stat(filepath.Join(dir, "indexes", e.ID)); err == nil {
			t.Errorf("placeholder %s must not get an index", id)
		}
	}
}

// placeholder 显式点名时报错（它没有资料，不能静默跳过当成功）。
func TestRegistryBuildPlaceholderErrors(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	stderr := captureStderr(t, func() {
		rc = dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "cv84x6", "-offline"})
	})
	if rc == 0 {
		t.Fatal("building a placeholder entity should fail")
	}
	if !strings.Contains(stderr, "placeholder") {
		t.Errorf("error should say the entity is a placeholder, got %q", stderr)
	}
}

func TestRegistryBuildUnknownEntityErrors(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	stderr := captureStderr(t, func() {
		rc = dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "nosuch", "-offline"})
	})
	if rc == 0 {
		t.Fatal("unknown entity should fail")
	}
	if !strings.Contains(stderr, "unknown entity") {
		t.Errorf("error should name the unknown entity, got %q", stderr)
	}
}

func TestRegistryEntityAndAllMutuallyExclusive(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	stderr := captureStderr(t, func() {
		rc = dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-all", "-offline"})
	})
	if rc == 0 {
		t.Fatal("-entity with -all should fail")
	}
	if !strings.Contains(stderr, "mutually exclusive") {
		t.Errorf("error should explain the conflict, got %q", stderr)
	}
}

// list：人类可读与 -json 两种输出都要能反映 ready/placeholder 与索引是否已建。
func TestRegistryList(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir)}); rc != 0 {
			t.Fatalf("list rc=%d", rc)
		}
	})
	for _, want := range []string{"se9", "bm1688", "cv186ah", "sm9-8", "placeholder", "missing"} {
		if !strings.Contains(out, want) {
			t.Errorf("list output missing %q:\n%s", want, out)
		}
	}

	buildAllOffline(t, dir)
	jsonOut := captureStdout(t, func() {
		if rc := dispatch([]string{"list", "-registry", loadTestRegistry(t, dir), "-json"}); rc != 0 {
			t.Fatalf("list -json rc=%d", rc)
		}
	})
	var entries []listEntry
	if err := json.Unmarshal([]byte(jsonOut), &entries); err != nil {
		t.Fatalf("list -json output is not JSON: %v\n%s", err, jsonOut)
	}
	byID := map[string]listEntry{}
	for _, e := range entries {
		byID[e.ID] = e
	}
	if !byID["se9"].IndexBuilt {
		t.Error("se9 index should be reported as built after build -all")
	}
	if byID["cv186ah"].IndexBuilt {
		t.Error("placeholder cv186ah must not report a built index")
	}
	if byID["se9"].Type != "product" || byID["bm1688"].Type != "chip" {
		t.Errorf("types = %q/%q, want product/chip", byID["se9"].Type, byID["bm1688"].Type)
	}
}

// resolve：最长别名匹配 + 关联实体 + 跳过 placeholder。
func TestRegistryResolve(t *testing.T) {
	dir := testRegistryDir(t)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "SE9 16-BP1-11 的 I2C"}); rc != 0 {
			t.Fatalf("resolve rc=%d", rc)
		}
	})
	// 命中规格：实体仍是 se9，另附规格名与该规格的芯片；检索目标按全部模组展开
	if !strings.HasPrefix(out, "se9\t") {
		t.Fatalf("resolve should name the product se9 first:\n%s", out)
	}
	if !strings.Contains(out, `alias="SE9 16-BP1-11"`) {
		t.Errorf("resolve should report the longest matched alias:\n%s", out)
	}
	if !strings.Contains(out, `spec="SE9 16"`) {
		t.Errorf("resolve should report the matched spec:\n%s", out)
	}
	if !strings.Contains(out, "chips=bm1688") {
		t.Errorf("resolve should report the spec's chip:\n%s", out)
	}
	if !strings.Contains(out, "related=bm1688") {
		t.Errorf("resolve should list related entities:\n%s", out)
	}
	// 规格不影响检索目标：两个模组都走到
	for _, want := range []string{"sm9-16", "sm9-8"} {
		if !strings.Contains(out, "skipped="+want) && !strings.Contains(out, ","+want) {
			t.Errorf("skipped should contain %q:\n%s", want, out)
		}
	}

	// -json
	jsonOut := captureStdout(t, func() {
		if rc := dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "-json", "SE7 和 BM1688"}); rc != 0 {
			t.Fatalf("resolve -json rc=%d", rc)
		}
	})
	var hits []resolveHit
	if err := json.Unmarshal([]byte(jsonOut), &hits); err != nil {
		t.Fatalf("resolve -json is not JSON: %v\n%s", err, jsonOut)
	}
	if len(hits) != 2 || hits[0].EntityID != "se7" || hits[1].EntityID != "bm1688" {
		t.Fatalf("hits = %+v, want se7 then bm1688 in text order", hits)
	}
}

func TestRegistryResolveNoMatchErrors(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	captureStdout(t, func() {
		rc = dispatch([]string{"resolve", "-registry", loadTestRegistry(t, dir), "毫不相关"})
	})
	if rc == 0 {
		t.Fatal("resolve with no match should exit non-zero")
	}
}

// 缺索引：报错并给出 build 命令（不静默只查已有的索引）。
func TestRegistryQueryMissingIndexGivesBuildHint(t *testing.T) {
	dir := testRegistryDir(t)
	// 只建 se9，不建 bm1688；查询 se9 -with-related 会同时要 bm1688
	captureStdout(t, func() {
		if rc := dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-offline"}); rc != 0 {
			t.Fatalf("build se9 rc=%d", rc)
		}
	})
	var rc int
	stderr := captureStderr(t, func() {
		captureStdout(t, func() {
			rc = dispatch([]string{"query", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-with-related", "-offline", "tpu-mlir"})
		})
	})
	if rc == 0 {
		t.Fatal("query with a missing related index should fail")
	}
	if !strings.Contains(stderr, "se-rag build -entity bm1688") {
		t.Errorf("error should give the exact build command for the missing entity, got:\n%s", stderr)
	}
}

// 离线多索引合并：结果按实体标注、路径相对技能根。
func TestRegistryQueryWithRelatedOffline(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-with-related", "-offline", "tpu-mlir 编译模型"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[bm1688]") {
		t.Errorf("merged results should be tagged with the entity id:\n%s", out)
	}
	if !strings.Contains(out, "`docs/chips/bm1688/sdk/tpu-mlir.md:") {
		t.Errorf("paths should be relative to the skill root:\n%s", out)
	}
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("offline query should report mode=bm25:\n%s", out)
	}
}

// 单实体查询：检索流程与输出格式与路径模式完全一致（只多实体标注）。
func TestRegistryQuerySingleEntityMatchesPathMode(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	reg, err := loadRegistry(loadTestRegistry(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	e, _ := reg.ByID("bm1688")

	entityOut := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", loadTestRegistry(t, dir), "-entity", "bm1688", "-offline", "tpu-mlir 编译模型"}); rc != 0 {
			t.Fatalf("entity query rc=%d", rc)
		}
	})
	pathOut := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-index-dir", reg.IndexPath(e), "-offline", "tpu-mlir 编译模型"}); rc != 0 {
			t.Fatalf("path query rc=%d", rc)
		}
	})
	// 路径模式下 product 标签是 default，实体模式下是实体 id —— meta 已在 build 时写死，
	// 结果行（路径、行号、分数）必须完全一致。
	// 尾部摘要里的 `total N ms` 是实测耗时，两次调用本来就可能差 1ms（与实现无关），
	// 比对前剥掉，否则这条用例会随机失败。
	stripped := stripTiming(stripEntityTag(entityOut))
	if stripped != stripTiming(pathOut) {
		t.Errorf("single-entity output must match path mode byte for byte.\nentity mode:\n%s\npath mode:\n%s", stripped, pathOut)
	}
}

// stripTiming 去掉输出尾部的实测耗时（`total 1ms`），只保留确定性内容。
var timingRe = regexp.MustCompile(`\| total \d+ms`)

func stripTiming(out string) string { return timingRe.ReplaceAllString(out, "| total <ms>") }

// stripEntityTag 去掉结果行尾的 ` [entity]` 标注，便于与路径模式输出比对。
var entityTagRe = regexp.MustCompile(`(?m)^(### \d+ \[[0-9.]+\] ` + "`[^`]+`" + `) \[[a-z0-9-]+\]$`)

func stripEntityTag(s string) string {
	return entityTagRe.ReplaceAllString(s, "$1")
}

// 单索引输出逐字节一致：对比改动前抓的 golden（testdata/golden/single-index-query.md）。
func TestSingleIndexOutputUnchanged(t *testing.T) {
	want, err := os.ReadFile(filepath.Join("testdata", "golden", "single-index-query.md"))
	if err != nil {
		t.Fatalf("read golden: %v", err)
	}
	dir := t.TempDir()
	docsDir := goldenDocs(t, dir)
	got := goldenRun(t, docsDir, filepath.Join(dir, "idx"), "SE9 网口 bond 怎么配")
	got = durationRe.ReplaceAllString(got, "total <MS>ms")
	if got != string(want) {
		t.Errorf("single-index query output changed.\n--- got ---\n%s\n--- want ---\n%s", got, want)
	}
}

// 路径模式的多 -index-dir：支持重复传入与逗号分隔（没有实体信息，不标注实体）。
func TestQueryMultiIndexDirsPathMode(t *testing.T) {
	dir := t.TempDir()
	docsA := filepath.Join(dir, "docsA")
	docsB := filepath.Join(dir, "docsB")
	for _, d := range []string{docsA, docsB} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(docsA, "a.md"), []byte("# A\n\n## I2C\n\nI2C0 复用 GPIO3/GPIO4。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsB, "b.md"), []byte("# B\n\n## I2C\n\ntpu-mlir 编译模型时指定 --chip。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	idxA := filepath.Join(dir, "idxA")
	idxB := filepath.Join(dir, "idxB")
	for _, c := range []struct{ docs, idx string }{{docsA, idxA}, {docsB, idxB}} {
		captureStdout(t, func() {
			if rc := dispatch([]string{"build", "-offline", "--docs-dir", c.docs, "-index-dir", c.idx}); rc != 0 {
				t.Fatalf("build %s rc=%d", c.docs, rc)
			}
		})
	}

	for _, args := range [][]string{
		{"query", "-offline", "-index-dir", idxA, "-index-dir", idxB, "I2C"},
		{"query", "-offline", "-index-dir", idxA + "," + idxB, "I2C"},
	} {
		out := captureStdout(t, func() {
			if rc := dispatch(args); rc != 0 {
				t.Fatalf("dispatch %v rc=%d", args, rc)
			}
		})
		if !strings.Contains(out, "`a.md:") || !strings.Contains(out, "`b.md:") {
			t.Errorf("dispatch %v should merge both indexes:\n%s", args, out)
		}
		if strings.Contains(out, "[") && regexp.MustCompile(`\] \[[a-z]`).MatchString(out) {
			t.Errorf("path mode must not tag entity ids:\n%s", out)
		}
	}
}

// 单实体 + -with-related 但展开后仍是一个索引时，输出与单索引一致。
func TestRegistryWithRelatedSingleTarget(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	// se7 → bm1684x：两个 ready 实体，两个索引 → 合并
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", loadTestRegistry(t, dir), "-entity", "se7", "-with-related", "-offline", "BM1684X 算力"}); rc != 0 {
			t.Fatalf("query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "[bm1684x]") {
		t.Errorf("expanded query should search the chip index too:\n%s", out)
	}
}

// doctor -all：每个 ready 实体都要检查，输出带实体标题。
func TestRegistryDoctorAll(t *testing.T) {
	dir := testRegistryDir(t)
	buildAllOffline(t, dir)
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"doctor", "-registry", loadTestRegistry(t, dir), "-all"}); rc != 0 {
			t.Fatalf("doctor -all rc=%d, want 0 for freshly built indexes", rc)
		}
	})
	for _, want := range []string{"==> entity se9", "==> entity bm1688", "no rebuild needed"} {
		if !strings.Contains(out, want) {
			t.Errorf("doctor -all output missing %q:\n%s", want, out)
		}
	}
	// placeholder 不参与 -all
	if strings.Contains(out, "==> entity cv186ah") {
		t.Errorf("doctor -all must skip placeholder entities:\n%s", out)
	}
}

// doctor -entity 在索引缺失时报重建（不是直接失败退出，因为「缺索引」正是要报告的问题）。
func TestRegistryDoctorMissingIndex(t *testing.T) {
	dir := testRegistryDir(t)
	var rc int
	out := captureStdout(t, func() {
		rc = dispatch([]string{"doctor", "-registry", loadTestRegistry(t, dir), "-entity", "se9"})
	})
	if rc != 1 {
		t.Errorf("doctor on a missing index should exit 1, got %d", rc)
	}
	if !strings.Contains(out, "se-rag build -entity se9") {
		t.Errorf("doctor should suggest the entity build command:\n%s", out)
	}
}

// SE_RAG_FAKE_EMBED 在线路径：多索引合并、rerank 只调用一次、结果带实体标注。
func TestRegistryQueryOnlineFakeEmbed(t *testing.T) {
	t.Setenv("SE_RAG_FAKE_EMBED", "1")
	dir := testRegistryDir(t)
	// 在线（fake embedding）建索引：两个实体都用 fake embedder 建。
	// -with-related 现在会把芯片所属 sdk 的版本也纳入检索目标，所以它也要建。
	for _, id := range []string{"se9", "bm1688", "sophonsdk-edge"} {
		captureStdout(t, func() {
			if rc := dispatch([]string{"build", "-registry", loadTestRegistry(t, dir), "-entity", id}); rc != 0 {
				t.Fatalf("build %s rc=%d", id, rc)
			}
		})
	}
	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-registry", loadTestRegistry(t, dir), "-entity", "se9", "-with-related", "I2C 怎么接"}); rc != 0 {
			t.Fatalf("online query rc=%d", rc)
		}
	})
	if !strings.Contains(out, "mode=hybrid") {
		t.Errorf("online query on hybrid indexes should report mode=hybrid:\n%s", out)
	}
	for _, want := range []string{"[se9]", "[bm1688]", "[sophonsdk-edge@v2.3]"} {
		if !strings.Contains(out, want) {
			t.Errorf("merged online results should be tagged per target (%s):\n%s", want, out)
		}
	}
}

// 注册表损坏时必须报错退出，不能当成空注册表继续。
func TestRegistryInvalidFailsLoudly(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "registry.json")
	body := `{"schema_version": 1, "entities": [
		{"id":"a","type":"product","name":"A","status":"ready","aliases":["A"],"docs_dir":null,"index_dir":"i"}
	]}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	var rc int
	stderr := captureStderr(t, func() {
		rc = dispatch([]string{"list", "-registry", p})
	})
	if rc == 0 {
		t.Fatal("invalid registry should fail")
	}
	if !strings.Contains(stderr, "requires docs_dir") {
		t.Errorf("error should name the validation problem, got %q", stderr)
	}
}

// 未指定 -registry 且当前目录没有 registry.json 时，路径模式照常工作（不因缺注册表而失败）。
func TestPathModeWithoutRegistryFile(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte("# A\n\n## I2C\n\nI2C0 复用 GPIO3。\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	idx := filepath.Join(dir, "idx")
	if err := runBuild(runCtx{
		docsDir: docsDir, indexDir: idx, product: metaProductLabel, offline: true,
		embedF: func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
	}); err != nil {
		t.Fatalf("build: %v", err)
	}
	// 从没有 registry.json 的目录里跑路径模式
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(cwd)

	out := captureStdout(t, func() {
		if rc := dispatch([]string{"query", "-index-dir", idx, "-offline", "I2C"}); rc != 0 {
			t.Fatalf("path-mode query without a registry file should work, rc=%d", rc)
		}
	})
	if !strings.Contains(out, "mode=bm25") {
		t.Errorf("unexpected output:\n%s", out)
	}
}
