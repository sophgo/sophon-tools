package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"se-rag-core/internal/docstore"
	"se-rag-core/internal/registry"
	"se-rag-core/internal/retriever"
)

// defaultRegistryPath 注册表默认位置：当前目录下的 registry.json（技能根目录）。
const defaultRegistryPath = "./registry.json"

// loadRegistry 读取并校验注册表。校验失败时不打印、不降级——注册表是唯一真源，
// 坏了就得先修好，否则按它建的索引与查询范围都是错的。
//
// 校验通过但带有非致命警告（如 sdk_since 暂存无法核对）时打到 stderr，不影响返回。
func loadRegistry(p string) (*registry.Registry, error) {
	if p == "" {
		p = defaultRegistryPath
	}
	reg, err := registry.Load(p)
	if err != nil {
		return nil, err
	}
	if err := reg.Validate(); err != nil {
		return nil, err
	}
	for _, w := range reg.Warnings() {
		fmt.Fprintf(os.Stderr, "warning: %s\n", w)
	}
	return reg, nil
}

// registryAvailable 判断 -registry 是否可用（显式传入时缺文件要报错，未传入时缺文件属正常）。
func registryAvailable(p string, explicit bool) bool {
	if explicit {
		return true
	}
	_, err := os.Stat(p)
	return err == nil
}

// target 一个检索目标：普通实体，或 sdk 的某个版本（sdk 的文档与索引都挂在版本上）。
//
// 版本不是实体，所以这里用 (SDKID, Ver) 表示；Label 是命令行与结果标注里使用的
// `<sdk-id>` 或 `<sdk-id>@<slug>`。
type target struct {
	// ID 实体 id；版本目标时是其所属 sdk 的 id。
	ID string
	// Ver 非 nil 表示这是 sdk 的一个版本（ID 是 sdk id，Ver 是该版本）。
	Ver *registry.Version
}

// Label 检索目标的可读标识。
func (t target) Label() string {
	if t.Ver != nil {
		return t.ID + "@" + t.Ver.Slug
	}
	return t.ID
}

// DocsDir 该目标的文档目录（绝对路径）。
func (t target) DocsDir(reg *registry.Registry) string {
	if t.Ver != nil {
		return reg.VersionDocsPath(t.Ver)
	}
	e, _ := reg.ByID(t.ID)
	return reg.DocsPath(e)
}

// IndexDir 该目标的索引目录（绝对路径，受 SE_RAG_DATA_DIR 覆盖）。
func (t target) IndexDir(reg *registry.Registry) string {
	if t.Ver != nil {
		return reg.VersionIndexPath(t.Ver)
	}
	e, _ := reg.ByID(t.ID)
	return reg.IndexPath(e)
}

// ChunkPath 把块的相对路径改写成相对技能根的展示路径。
func (t target) ChunkPath(reg *registry.Registry, src string) string {
	if t.Ver != nil {
		return reg.ChunkPathForVersion(t.Ver, src)
	}
	e, _ := reg.ByID(t.ID)
	return reg.ChunkPath(e, src)
}

// targetEntities 解析 -entity a,b / -all，得到检索目标（实体或 sdk 版本）。
//
// -all 取全部 status=ready 的实体，并**展开 sdk 的全部版本**（卡片要求：build -all 建全部版本）。
// -entity 里的 sdk 默认只取最新版本；写 `<sdk-id>@<slug>` 可指定版本；配合 -sdk-version 可
// 取 all 或某个 slug。placeholder 实体（模组、CV186AH）显式点名时报错，因为用户以为它有资料。
//
// **规格不是实体**（用户裁定：SE9 是一个实体，SE9 16 / SE9 8 只是规格），所以这里只认
// 实体 id。传入规格名或"看起来像规格"的写法一律报 unknown entity，并提示改用 -entity se9。
func targetEntities(reg *registry.Registry, entityFlag string, all bool, sdkReq registry.SDKVersionRequest) ([]target, error) {
	if all && strings.TrimSpace(entityFlag) != "" {
		return nil, fmt.Errorf("-entity and -all are mutually exclusive")
	}
	if all {
		var out []target
		for _, id := range reg.ReadyIDs() {
			out = append(out, target{ID: id})
		}
		// -all：sdk 的全部版本都建/查；显式给了 -sdk-version 时按它来。
		req := sdkReq
		if req.Default() {
			req = registry.SDKVersionRequest{All: true}
		}
		for i := range reg.Entities {
			e := &reg.Entities[i]
			if e.Type != registry.TypeSDK {
				continue
			}
			// versions 为空的 sdk 没有可建/可查的东西：照常跳过，但要说出来——
			// 否则用户会以为 -all 覆盖了它。
			if len(e.Versions) == 0 {
				fmt.Fprintf(os.Stderr, "note: skipped sdk %s: no versions registered (placeholder)\n", e.ID)
				continue
			}
			vers, _, err := reg.SelectVersions(e.ID, req, "")
			if err != nil {
				return nil, err
			}
			for j := range vers {
				out = append(out, target{ID: e.ID, Ver: vers[j].Version})
			}
		}
		if len(out) == 0 {
			return nil, fmt.Errorf("registry has no ready entity")
		}
		return out, nil
	}
	ids := registry.SplitIDs(entityFlag)
	if len(ids) == 0 {
		return nil, fmt.Errorf("-entity is empty (use -entity a,b or -all)")
	}
	seen := map[string]bool{}
	out := make([]target, 0, len(ids))
	for _, id := range ids {
		ts, err := lookupEntity(reg, id, sdkReq)
		if err != nil {
			return nil, err
		}
		for _, t := range ts {
			if seen[t.Label()] {
				continue
			}
			seen[t.Label()] = true
			out = append(out, t)
		}
	}
	return out, nil
}

// lookupEntity 把 -entity 的一个取值解析成检索目标（sdk 可能展开成多个版本目标）。
//
// 接受三种写法：
//   - 实体 id（product / chip / module / toolkit）：一个目标；
//   - sdk id：按版本选择规则展开（默认最新版；-sdk-version all 展开成全部版本，
//     指定 slug 则只取该版本）；
//   - `<sdk-id>@<slug>`：指定 sdk 的某个版本。
//
// 规格名（如 "SE9 8"）与旧的"产品-规格"拼法（如 "se9-8"）都不是实体，报 unknown entity
// 并指出该用哪个产品——不静默翻译，否则用户会以为规格是独立实体。
func lookupEntity(reg *registry.Registry, id string, sdkReq registry.SDKVersionRequest) ([]target, error) {
	if sdkID, slug, ok := splitVersionRef(id); ok {
		e, found := reg.ByID(sdkID)
		if !found || e.Type != registry.TypeSDK {
			return nil, fmt.Errorf("unknown sdk %q in %q (see se-rag list)", sdkID, id)
		}
		v, found := reg.Version(sdkID, slug)
		if !found {
			return nil, fmt.Errorf("sdk %q has no version %q (known: %s)",
				sdkID, slug, versionSlugList(e))
		}
		return []target{{ID: sdkID, Ver: v}}, nil
	}
	e, ok := reg.ByID(id)
	if !ok {
		if productID, specName := specHint(reg, id); specName != "" {
			return nil, fmt.Errorf("unknown entity %q: %q is a spec of %s, not an entity; specs are attributes, use -entity %s",
				id, specName, productID, productID)
		}
		return nil, fmt.Errorf("unknown entity %q (see se-rag list)", id)
	}
	if e.Type == registry.TypeSDK {
		vers, _, err := reg.SelectVersions(e.ID, sdkReq, "")
		if err != nil {
			return nil, err
		}
		if len(vers) == 0 {
			return nil, fmt.Errorf("sdk %q has no versions registered (status=%s): nothing to build or search; "+
				"add entries to its versions in registry.json first", e.ID, e.Status)
		}
		out := make([]target, 0, len(vers))
		for i := range vers {
			out = append(out, target{ID: e.ID, Ver: vers[i].Version})
		}
		return out, nil
	}
	if e.Status != registry.StatusReady {
		return nil, fmt.Errorf("entity %q is %s: no docs_dir/index_dir, nothing to build or search", e.ID, e.Status)
	}
	return []target{{ID: e.ID}}, nil
}

// splitVersionRef 拆分 `<sdk-id>@<slug>`；不含 @ 时返回 ok=false。
func splitVersionRef(s string) (sdkID, slug string, ok bool) {
	i := strings.LastIndex(s, "@")
	if i <= 0 || i == len(s)-1 {
		return "", "", false
	}
	return strings.TrimSpace(s[:i]), strings.TrimSpace(s[i+1:]), true
}

// versionSlugList 一个 sdk 的版本 slug 列表（错误信息用）。
func versionSlugList(e *registry.Entity) string {
	slugs := make([]string, 0, len(e.Versions))
	for i := range e.Versions {
		slugs = append(slugs, e.Versions[i].Slug)
	}
	if len(slugs) == 0 {
		return "none"
	}
	return strings.Join(slugs, ",")
}

// specHint 该取值是否是某个产品的规格名或规格别名，返回所属产品 id 与规格名。
//
// 归一化忽略大小写、空格、`-`、`_`，所以规格全名 `SE9 8`、型号别名 `SE9 8-BP1-17`、
// 以及 "产品-规格" 拼法 `se9-8` 都能被认出来——后者的归一化形式与 `SE9 8` 相同。
func specHint(reg *registry.Registry, id string) (productID, specName string) {
	want := normalizeAlias(id)
	if want == "" {
		return "", ""
	}
	for i := range reg.Entities {
		e := &reg.Entities[i]
		for j := range e.Specs {
			sp := &e.Specs[j]
			if normalizeAlias(sp.Name) == want {
				return e.ID, sp.Name
			}
			for _, a := range sp.Aliases {
				if normalizeAlias(a) == want {
					return e.ID, sp.Name
				}
			}
		}
	}
	return "", ""
}

// normalizeAlias 与 internal/registry 的别名归一化同规则：小写、去空格 / `-` / `_`。
func normalizeAlias(s string) string {
	var sb strings.Builder
	for _, r := range strings.ToLower(s) {
		switch r {
		case ' ', '\t', '\n', '\r', '-', '_':
			continue
		}
		sb.WriteRune(r)
	}
	return sb.String()
}

// expandRelated 按 -with-related 展开关联实体（去重、保序，跳过 placeholder 并提示）。
//
// 起点就是目标实体 id：规格不参与展开，SE9 的两种规格都沿 product.modules 展开成全
// 部模组，检索目标与规格无关。SDK 的版本选择由 sdkReq 决定（默认最新版）。
func expandRelated(reg *registry.Registry, entityFlag string, ts []target, withRelated bool,
	sdkReq registry.SDKVersionRequest) ([]target, error) {
	if !withRelated {
		return ts, nil
	}
	starts := make([]string, 0, len(ts))
	for _, t := range ts {
		if !containsString(starts, t.ID) {
			starts = append(starts, t.ID)
		}
	}
	if len(starts) == 0 {
		starts = registry.SplitIDs(entityFlag)
	}
	exp, err := reg.RelatedAllWith(starts, registry.RelatedOptions{SDKVersion: sdkReq})
	if err != nil {
		return nil, err
	}
	if msg := registry.FormatSkips(exp.Skipped); msg != "" {
		fmt.Fprintf(os.Stderr, "note: %s\n", msg)
	}
	for _, n := range exp.Notes {
		fmt.Fprintf(os.Stderr, "note: %s\n", n)
	}
	out := make([]target, 0, len(exp.IDs)+len(exp.Versions))
	for _, id := range exp.IDs {
		out = append(out, target{ID: id})
	}
	for _, v := range exp.Versions {
		out = append(out, target{ID: v.SDKID, Ver: v.Version})
	}
	return out, nil
}

func containsString(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}

// entitySources 把检索目标转成多索引检索源，并检查每个索引都存在。
// 缺失时报错并给出对应的 build 命令——不静默跳过没建的索引，否则用户会以为
// 查询范围覆盖了全部目标实体。
//
// productSet 非空时，**经产品带入的 toolkit** 源要按 applies_products 过滤块：
// direct 里登记的是"用户直接写进 -entity 的目标"，它们一律不过滤（同一份索引
// 既能按产品看，也能整体看）。productSet 为空（本次没有显式 product）时
// 所有源都不带产品过滤，输出与 1.8.1 逐字节一致。
func entitySources(reg *registry.Registry, ts []target, productSet map[string]bool,
	direct map[string]bool) ([]retriever.Source, error) {
	srcs := make([]retriever.Source, 0, len(ts))
	var missing []string
	for _, t := range ts {
		// go.mod 是 go 1.21：循环变量每个迭代复用，闭包必须捕获副本，
		// 否则所有源的 PathPrefix 都会指向最后一个目标。
		t := t
		dir := t.IndexDir(reg)
		label := t.Label()
		srcs = append(srcs, retriever.Source{
			Label:      label,
			Store:      &docstore.Store{IndexDir: dir},
			Product:    label,
			PathPrefix: func(src string) string { return t.ChunkPath(reg, src) },
			Products:   productFilterFor(reg, t, productSet, direct),
		})
		if _, err := os.Stat(filepath.Join(dir, "meta.json")); err != nil {
			missing = append(missing, fmt.Sprintf("  %s: no index at %s\n    -> se-rag build -entity %s", label, dir, label))
		}
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("index missing for %d of %d targets:\n%s", len(missing), len(ts), strings.Join(missing, "\n"))
	}
	return srcs, nil
}

// productFilterFor 该目标是否要按产品过滤块：只有"toolkit 且不是用户直接点名的"才过滤。
// 返回 nil 表示该源不做产品过滤。
func productFilterFor(reg *registry.Registry, t target, productSet map[string]bool,
	direct map[string]bool) map[string]bool {
	if len(productSet) == 0 || direct[t.Label()] || t.Ver != nil {
		return nil
	}
	e, ok := reg.ByID(t.ID)
	if !ok || e.Type != registry.TypeToolkit {
		return nil
	}
	return productSet
}

// explicitProducts 本次 `-entity` 里**直接写出**的产品 id（保序去重）。
//
// 只有 `-entity` 直接写的产品会带出 toolkit：芯片、模组、sdk 与 `-all` 都不触发。
// `-all` 本来就把全部 ready 实体（含 toolkit 自身）当直接目标，不需要再"带入"，
// 也不该被产品过滤掉一半。
func explicitProducts(reg *registry.Registry, entityFlag string) []string {
	var out []string
	for _, id := range registry.SplitIDs(entityFlag) {
		// `<sdk-id>@<slug>` 是版本目标，不是实体 id。
		if _, _, ok := splitVersionRef(id); ok {
			continue
		}
		e, ok := reg.ByID(id)
		if !ok || e.Type != registry.TypeProduct {
			continue
		}
		if !containsString(out, e.ID) {
			out = append(out, e.ID)
		}
	}
	return out
}

// productToolkits 这些产品引用的 toolkit（保序去重），分成可检索的与被跳过的两类。
//
// 只有 status=ready 的 toolkit 才是检索目标：placeholder 按定义没有文档目录，把它塞进
// 目标只会让查询报"索引缺失"。引用不存在或指向非 toolkit 的条目由注册表校验负责报错，
// 这里按跳过处理，不让查询因坏数据崩掉（也不会空指针）。
func productToolkits(reg *registry.Registry, products []string) (ready []string, skipped []registry.Skip) {
	seen := map[string]bool{}
	for _, pid := range products {
		e, ok := reg.ByID(pid)
		if !ok {
			continue
		}
		for _, tk := range e.Toolkits {
			if seen[tk] {
				continue
			}
			seen[tk] = true
			te, ok := reg.ByID(tk)
			if !ok {
				skipped = append(skipped, registry.Skip{ID: tk, Reason: "unknown entity in product.toolkits"})
				continue
			}
			if te.Type != registry.TypeToolkit {
				skipped = append(skipped, registry.Skip{ID: tk, Reason: "not a toolkit entity"})
				continue
			}
			if te.Status != registry.StatusReady {
				skipped = append(skipped, registry.Skip{ID: tk,
					Reason: fmt.Sprintf("status=%s: no docs_dir/index_dir, nothing to search", te.Status)})
				continue
			}
			ready = append(ready, tk)
		}
	}
	return ready, skipped
}

// withProductToolkits 把产品带入的 toolkit 追加到检索目标末尾（去重保序），
// 返回追加过的 toolkit id 列表（用于 stderr 提示）。
//
// 已经在目标里的 toolkit 不再追加：那说明用户直接写了它，或 `-with-related` 已经带进来了。
func withProductToolkits(reg *registry.Registry, targets []target, toolkits []string) ([]target, []string) {
	have := make(map[string]bool, len(targets))
	for _, t := range targets {
		have[t.Label()] = true
	}
	var added []string
	for _, tk := range toolkits {
		if have[tk] {
			continue
		}
		have[tk] = true
		targets = append(targets, target{ID: tk})
		added = append(added, tk)
	}
	return targets, added
}

// productSetOf 把产品 id 列表转成检索期过滤用的集合（空列表返回 nil）。
func productSetOf(products []string) map[string]bool {
	if len(products) == 0 {
		return nil
	}
	out := make(map[string]bool, len(products))
	for _, p := range products {
		out[p] = true
	}
	return out
}

// directTargets 用户直接点名的目标（label → true）：toolkits 展开前后的差集就是
// "经产品带入"的那部分，它们才按 applies_products 过滤。
func directTargets(ts []target) map[string]bool {
	out := make(map[string]bool, len(ts))
	for _, t := range ts {
		out[t.Label()] = true
	}
	return out
}

// toolkitsNote 经产品带入 toolkit 时打到 stderr 的一行说明。
// 写明"按哪个产品过滤"和怎么关掉，否则用户会以为 toolkit 文档被漏掉了。
// canDisable=false（toolkit 是 -with-related 带进来的）时不提 -no-toolkits：
// 那个开关只管默认带入。
func toolkitsNote(toolkits, products []string, canDisable bool) string {
	note := fmt.Sprintf("toolkits included: %s (filtered by applies_products ∋ %s",
		strings.Join(toolkits, ", "), strings.Join(products, ","))
	if canDisable {
		note += "; -no-toolkits to disable"
	}
	return note + ")"
}

// docTypeFilter 把 -doc-type 的取值转成检索期过滤器（路径按技能根相对路径推断）。
// 空串返回 nil（不过滤，输出与旧版逐字节一致）。
func docTypeFilter(spec string) (*retriever.ChunkFilter, error) {
	types := registry.SplitIDs(spec)
	if len(types) == 0 {
		return nil, nil
	}
	allowed := make(map[string]bool, len(types))
	for _, t := range types {
		if !registry.IsDocType(t) {
			return nil, fmt.Errorf("unknown doc type %q (one of %s)", t, strings.Join(registry.DocTypes, ","))
		}
		allowed[t] = true
	}
	return &retriever.ChunkFilter{Allowed: allowed, DocTypeOf: registry.DocType}, nil
}

// ---- list ----

type listEntry struct {
	ID         string      `json:"id"`
	Type       string      `json:"type"`
	Name       string      `json:"name"`
	Status     string      `json:"status"`
	Aliases    []string    `json:"aliases"`
	Modules    []string    `json:"modules,omitempty"`
	Specs      []specEntry `json:"specs,omitempty"`
	Chips      []string    `json:"chips,omitempty"`
	SDK        string      `json:"sdk,omitempty"`
	SDKSince   string      `json:"sdk_since,omitempty"`
	Versions   []verEntry  `json:"versions,omitempty"`
	DocsDir    string      `json:"docs_dir,omitempty"`
	IndexDir   string      `json:"index_dir,omitempty"`
	IndexBuilt bool        `json:"index_built"`
	// IndexAt 实际使用的索引目录。设了 SE_RAG_DATA_DIR 时它不同于 index_dir（注册表原文），
	// 用来解释"索引到底写在哪儿"。
	IndexAt string `json:"index_at,omitempty"`
}

// specEntry list -json 里的规格展示项。规格没有 id——它只是产品的一个属性。
type specEntry struct {
	Name    string   `json:"name"`
	Aliases []string `json:"aliases"`
	Modules []string `json:"modules"`
	Chain   []string `json:"chain,omitempty"` // 模组 → 芯片的展开链，便于人读
}

// verEntry list -json 里的 SDK 版本展示项。版本没有 id，slug 是它在 sdk 内的定位键。
type verEntry struct {
	Slug        string   `json:"slug"`
	Version     string   `json:"version"`
	ReleaseDate string   `json:"release_date"`
	DocsDir     string   `json:"docs_dir"`
	IndexDir    string   `json:"index_dir"`
	IndexAt     string   `json:"index_at,omitempty"`
	AppliesTo   []string `json:"applies_to,omitempty"`
	IndexBuilt  bool     `json:"index_built"`
}

func runList(reg *registry.Registry, asJSON bool) error {
	entries := make([]listEntry, 0, len(reg.Entities))
	for i := range reg.Entities {
		e := &reg.Entities[i]
		indexAt := reg.IndexPath(e)
		built := false
		// sdk 的索引在版本上（顶层 index_dir 恒为 null），不能拿实体自己的路径去判断，
		// 否则有版本的 sdk 会因为"顶层没索引"被显示成 missing。
		if e.Status == registry.StatusReady && e.Type != registry.TypeSDK {
			if _, err := os.Stat(filepath.Join(indexAt, "meta.json")); err == nil {
				built = true
			}
		}
		en := listEntry{
			ID: e.ID, Type: string(e.Type), Name: e.Name, Status: string(e.Status),
			Aliases: e.Aliases, Modules: e.Modules, Chips: e.Chips,
			SDK: e.SDK, SDKSince: e.SDKSince,
			DocsDir: e.DocsDir, IndexDir: e.IndexDir, IndexBuilt: built,
			// 展示路径：未设 SE_RAG_DATA_DIR 时是注册表原文（相对技能根），设了才是绝对路径。
			// 直接用 IndexPath 会把技能根绝对路径打出来，与其它行的相对风格不一致。
			IndexAt: reg.IndexPathLabel(e),
		}
		for j := range e.Specs {
			sp := &e.Specs[j]
			en.Specs = append(en.Specs, specEntry{
				Name: sp.Name, Aliases: sp.Aliases, Modules: sp.Modules,
				Chain: specChainList(reg, sp),
			})
		}
		// sdk 的索引状态在版本上，逐版本列出：一个 sdk 可能有多个版本，各自独立建索引。
		for j := range e.Versions {
			v := &e.Versions[j]
			en.Versions = append(en.Versions, verEntry{
				Slug: v.Slug, Version: v.Version, ReleaseDate: v.ReleaseDate,
				DocsDir: v.DocsDir, IndexDir: v.IndexDir,
				IndexAt:   reg.VersionIndexLabel(v),
				AppliesTo: v.AppliesTo, IndexBuilt: metaExists(reg.VersionIndexPath(v)),
			})
		}
		entries = append(entries, en)
	}
	if asJSON {
		b, err := json.MarshalIndent(entries, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(b))
		return nil
	}
	fmt.Printf("%-16s %-8s %-10s %-8s %-26s %s\n", "ID", "TYPE", "STATUS", "INDEX", "RELATION", "NAME")
	for _, en := range entries {
		index := "-"
		switch {
		case en.Type == string(registry.TypeSDK):
			// sdk：自身没有索引，状态逐版本列在下面（见 verEntry.IndexBuilt）。
			index = "versions"
			if len(en.Versions) == 0 {
				index = "-"
			}
		case en.Status == string(registry.StatusReady):
			index = "missing"
			if en.IndexBuilt {
				index = "built"
			}
		}
		fmt.Printf("%-16s %-8s %-10s %-8s %-26s %s\n",
			en.ID, en.Type, en.Status, index, relationLabel(en), en.Name)
		// 规格单独缩进一行：它不是实体、共用一个索引，所以不能作为独立行占 INDEX 列。
		for _, sp := range en.Specs {
			fmt.Printf("  +- %-13s %-8s %-8s %-26s %s\n", sp.Name, "spec", "shared",
				strings.Join(sp.Chain, ","), "规格")
		}
		// sdk 版本同样逐行：每个版本一套索引，INDEX 列是它自己的状态。
		for _, v := range en.Versions {
			state := "missing"
			if v.IndexBuilt {
				state = "built"
			}
			// 与实体行同一规则：IndexAt 已是展示路径（未覆盖时即注册表原文的相对路径）。
			fmt.Printf("  +- %-13s %-8s %-8s %-26s %s %s\n", v.Slug, "version", state,
				"released="+v.ReleaseDate, v.IndexAt, v.Version)
		}
	}
	return nil
}

// metaExists 索引是否已建（有 meta.json）。
func metaExists(dir string) bool {
	if dir == "" {
		return false
	}
	_, err := os.Stat(filepath.Join(dir, "meta.json"))
	return err == nil
}

// relationLabel 单行的关系摘要：产品列模组（有规格时附规格数），模组列芯片，
// 芯片列 sdk（带 sdk_since 时附上），sdk 列版本数。
func relationLabel(en listEntry) string {
	switch {
	case len(en.Modules) > 0 && len(en.Specs) > 0:
		return fmt.Sprintf("modules=%s specs=%d", strings.Join(en.Modules, ","), len(en.Specs))
	case len(en.Modules) > 0:
		return "modules=" + strings.Join(en.Modules, ",")
	case len(en.Chips) > 0:
		return "chips=" + strings.Join(en.Chips, ",")
	case en.Type == string(registry.TypeSDK):
		return fmt.Sprintf("versions=%d", len(en.Versions))
	case en.SDK != "" && en.SDKSince != "":
		return "sdk=" + en.SDK + " since=" + en.SDKSince
	case en.SDK != "":
		return "sdk=" + en.SDK
	}
	return "-"
}

// specChainList 规格的展开链（如 ["sm9-8 → cv186ah"]），只用于展示。
func specChainList(reg *registry.Registry, sp *registry.Spec) []string {
	out := make([]string, 0, len(sp.Modules))
	for _, m := range sp.Modules {
		if mod, ok := reg.ByID(m); ok && len(mod.Chips) > 0 {
			out = append(out, m+" → "+strings.Join(mod.Chips, "/"))
			continue
		}
		out = append(out, m)
	}
	return out
}

// ---- resolve ----

type resolveHit struct {
	EntityID string `json:"entity_id"`
	Name     string `json:"name"`
	Type     string `json:"type"`
	Status   string `json:"status"`
	Alias    string `json:"alias"`
	// Spec 命中的规格名（如 "SE9 8"）。规格不是实体——命中规格时 EntityID 仍是 se9，
	// 这里只是告诉 Agent 用户问的是哪种规格。
	Spec string `json:"spec,omitempty"`
	// SpecChips 该规格对应的芯片（芯片级数值该用哪颗芯片）。
	SpecChips []string `json:"spec_chips,omitempty"`
	Related   []string `json:"related,omitempty"`
	Skipped   []string `json:"skipped,omitempty"`
	Notes     []string `json:"notes,omitempty"`
	// UsedBy 命中的是模组时，列出引用它的产品（只供参考，不参与检索展开）。
	UsedBy []string `json:"used_by,omitempty"`
	// SDK 命中的是芯片时，它所属的 sdk id；命中 sdk 时就是自身 id。
	SDK string `json:"sdk,omitempty"`
	// SDKVersions 命中 sdk（或带 sdk 的芯片）时，该 sdk 的版本列表。
	// 版本不是实体，这里只报 slug / 版本号 / 发布日期 / 是否已建索引。
	SDKVersions []resolveVersion `json:"sdk_versions,omitempty"`
	// SDKVersionNote 版本选择的说明（默认只取最新版、sdk_since 跳过旧版本等）。
	SDKVersionNote string `json:"sdk_version_note,omitempty"`
}

// resolveVersion resolve 输出里的 sdk 版本项。
type resolveVersion struct {
	Slug        string `json:"slug"`
	Version     string `json:"version"`
	ReleaseDate string `json:"release_date"`
	IndexBuilt  bool   `json:"index_built"`
	// Selected 本次检索是否会用到该版本（默认只有最新版，-sdk-version all 时全部）。
	Selected bool `json:"selected"`
}

func runResolve(reg *registry.Registry, text string, asJSON bool) error {
	return runResolveWith(reg, text, asJSON, registry.SDKVersionRequest{})
}

func runResolveWith(reg *registry.Registry, text string, asJSON bool, sdkReq registry.SDKVersionRequest) error {
	if strings.TrimSpace(text) == "" {
		return fmt.Errorf("empty text")
	}
	matches := reg.Resolve(text)
	hits := make([]resolveHit, 0, len(matches))
	seen := map[string]bool{}
	for _, m := range matches {
		// 去重键是 (实体, 规格)：同一实体同一规格只输出一次；同一实体的不同规格
		// （如文本里同时提到 SE9 16 与 SE9 8）各自一行，方便 Agent 分辨。
		key := m.EntityID + "\x00" + m.SpecName
		if seen[key] {
			continue
		}
		seen[key] = true
		e, ok := reg.ByID(m.EntityID)
		if !ok {
			continue
		}
		// 检索目标只看实体，规格不参与展开。
		exp, err := reg.RelatedWith(m.EntityID, registry.RelatedOptions{SDKVersion: sdkReq})
		if err != nil {
			return err
		}
		// Related 含自身；这里只列关联实体（自身已作为命中项输出）。
		var rel []string
		for _, r := range exp.IDs {
			if r != m.EntityID {
				rel = append(rel, r)
			}
		}
		var sk []string
		for _, s := range exp.Skipped {
			sk = append(sk, s.ID)
		}
		// 规格对照只在"没命中具体规格"时才有意义：已经知道是哪种规格了，
		// 再列一遍对照只会让 Agent 多读一行。query 的 -with-related 仍保留该提示。
		notes := exp.Notes
		if m.SpecName != "" {
			notes = nil
		}
		hit := resolveHit{
			EntityID: e.ID, Name: e.Name,
			Type: string(e.Type), Status: string(e.Status),
			Alias: m.Alias, Spec: m.SpecName,
			Related: rel, Skipped: sk, Notes: notes,
		}
		if m.SpecName != "" {
			if sp, ok := reg.Spec(e.ID, m.SpecName); ok {
				hit.SpecChips = reg.SpecChips(sp)
			}
		}
		if e.Type == registry.TypeModule {
			hit.UsedBy = reg.UsedBy(e.ID)
		}
		// sdk 信息：命中 sdk 时是自身；命中芯片时是它所属的 sdk（版本列表一并给出，
		// 让 Agent 知道默认查的是哪一版、还有哪些版本可选）。
		switch {
		case e.Type == registry.TypeSDK:
			hit.SDK = e.ID
			hit.SDKVersions = resolveVersions(reg, e.ID, sdkReq, "")
		case e.SDK != "":
			hit.SDK = e.SDK
			hit.SDKVersions = resolveVersions(reg, e.SDK, sdkReq, e.ID)
		}
		if exp.Versions != nil && hit.SDK != "" {
			hit.SDKVersionNote = versionSelectionNote(exp.Versions)
		}
		hits = append(hits, hit)
	}
	if asJSON {
		b, err := json.MarshalIndent(hits, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(b))
		if len(hits) == 0 {
			return fmt.Errorf("no entity matched %q", text)
		}
		return nil
	}
	if len(hits) == 0 {
		return fmt.Errorf("no entity matched %q", text)
	}
	for _, h := range hits {
		line := fmt.Sprintf("%s\t%s\t%s\talias=%q", h.EntityID, h.Type, h.Status, h.Alias)
		if h.Spec != "" {
			line += fmt.Sprintf("\tspec=%q", h.Spec)
			if len(h.SpecChips) > 0 {
				line += " chips=" + strings.Join(h.SpecChips, ",")
			}
		}
		if len(h.Related) > 0 {
			line += "\trelated=" + strings.Join(h.Related, ",")
		}
		if len(h.Skipped) > 0 {
			line += "\tskipped=" + strings.Join(h.Skipped, ",")
		}
		if len(h.UsedBy) > 0 {
			line += "\tused_by=" + strings.Join(h.UsedBy, ",")
		}
		if h.SDK != "" {
			line += "\tsdk=" + h.SDK
		}
		fmt.Println(line)
		for _, v := range h.SDKVersions {
			mark := " "
			if v.Selected {
				mark = "*"
			}
			state := "missing"
			if v.IndexBuilt {
				state = "built"
			}
			fmt.Printf("%s version %-14s %-12s released=%s index=%s\n",
				mark, v.Slug, v.Version, v.ReleaseDate, state)
		}
		if h.SDKVersionNote != "" {
			fmt.Printf("note: %s\n", h.SDKVersionNote)
		}
		for _, n := range h.Notes {
			fmt.Printf("note: %s\n", n)
		}
	}
	return nil
}

// resolveVersions 列出一个 sdk 的全部版本，并标出本次检索会用到哪些。
// chipID 非空时按其 sdk_since 判断哪些版本对它不适用。
func resolveVersions(reg *registry.Registry, sdkID string, sdkReq registry.SDKVersionRequest, chipID string) []resolveVersion {
	e, ok := reg.ByID(sdkID)
	if !ok {
		return nil
	}
	selected, _, err := reg.SelectVersions(sdkID, sdkReq, chipID)
	if err != nil {
		return nil
	}
	sel := map[string]bool{}
	for _, v := range selected {
		sel[v.Version.Slug] = true
	}
	out := make([]resolveVersion, 0, len(e.Versions))
	for i := range e.Versions {
		v := &e.Versions[i]
		out = append(out, resolveVersion{
			Slug: v.Slug, Version: v.Version, ReleaseDate: v.ReleaseDate,
			IndexBuilt: metaExists(reg.VersionIndexPath(v)),
			Selected:   sel[v.Slug],
		})
	}
	return out
}

// versionSelectionNote 把选中的版本渲染成一行提示（空切片返回空串）。
func versionSelectionNote(vs []registry.VersionRef) string {
	if len(vs) == 0 {
		return ""
	}
	parts := make([]string, 0, len(vs))
	for _, v := range vs {
		parts = append(parts, v.Label())
	}
	return "search targets: " + strings.Join(parts, ",")
}
