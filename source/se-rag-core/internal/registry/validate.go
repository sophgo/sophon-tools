package registry

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

// kebabRe id 的合法形式：小写字母 / 数字，用单个连字符连接，如 se9、bm1684x、cv186ah。
// 规格没有 id，因此这里只管实体。
var kebabRe = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)

// releaseDateLayout versions[].release_date 的唯一合法格式（YYYY-MM-DD）。
const releaseDateLayout = "2006-01-02"

// parseReleaseDate 解析 release_date；格式必须是严格的 YYYY-MM-DD。
// time.Parse 对 "2026-1-2" 这类写法会放行，所以额外比对回写后的字符串。
func parseReleaseDate(s string) (time.Time, error) {
	t, err := time.Parse(releaseDateLayout, s)
	if err != nil {
		return time.Time{}, err
	}
	if t.Format(releaseDateLayout) != s {
		return time.Time{}, fmt.Errorf("not zero-padded YYYY-MM-DD")
	}
	return t, nil
}

// ValidationError 注册表校验失败，Problems 按检查顺序列出全部问题（一次报全，免得多轮试错）。
//
// Warnings 是"能跑但值得知道"的情形（例如 sdk_since 暂存、无法核对）：它们不让校验失败，
// 由调用方决定怎么展示（CLI 打到 stderr）。
type ValidationError struct {
	Path     string
	Problems []string
	Warnings []string
}

func (e *ValidationError) Error() string {
	head := "invalid registry"
	if e.Path != "" {
		head = "invalid registry " + e.Path
	}
	// 一次报全：多条问题逐行列出，避免用户改一条跑一次。
	var sb strings.Builder
	for i, p := range e.Problems {
		if i == 0 {
			sb.WriteString(head + ": " + p)
			continue
		}
		sb.WriteString("\n  - " + p)
	}
	return sb.String()
}

// normalize 别名的归一化形式：转小写并去掉空格、`-`、`_`。
// 用于"别名全局唯一"与 Resolve 的文本匹配（`SE9 16-BP1-11` 与 `se9 16bp111` 视为同一别名）。
func normalize(s string) string {
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

// Validate 校验注册表的 schema 与引用完整性，返回全部问题。
//
// 校验项（schema v3：在 v2 的"产品 → 模组 → 芯片"三层之上加 sdk 层）：
//   - schema_version = 3
//   - id 唯一且为小写 kebab；type ∈ {product,chip,module,toolkit,sdk}；status ∈ {ready,placeholder}
//   - ready：docs_dir 非空且目录存在，index_dir 非空；sdk 例外——它的文档与索引
//     挂在版本上，ready 只要求 versions 非空，顶层两个路径仍为 null
//   - placeholder：docs_dir 与 index_dir 都为 null；sdk 例外——versions 必须为空
//   - 别名非空且全局唯一（归一化后比较），规格别名一并参与
//   - product 不得出现 chips 字段；chip 不得再出现 sdk_family（v3 改用 sdk / sdk_since）
//   - product.modules / spec.modules 只引用 module；module.chips 只引用 chip；
//     product.toolkits 只引用 toolkit；chip.sdk 只引用 sdk
//   - 规格（spec）没有 id、不进实体命名空间：名称在产品内唯一、别名非空；
//     spec.modules 必须是 product.modules 的子集，且全部 spec 合起来正好覆盖 product.modules
//   - sdk.versions：slug 在所属 sdk 内唯一且非空，version 非空，release_date 形如 YYYY-MM-DD，
//     docs_dir / index_dir 非空且在全注册表内不重复，applies_to 只引用 chip
//   - chip.sdk_since 必须是该 chip 所属 sdk 已有的版本 slug；versions 为空时只给警告
//   - sdk.sources 与顶层 shared_sources 的字段类型合法（url 形如 scheme://host/…）
func (r *Registry) Validate() error {
	v := &validator{reg: r, problems: []string{}}

	if r.SchemaVersion != SchemaVersion {
		v.addf("schema_version is %d, want %d", r.SchemaVersion, SchemaVersion)
	}
	if len(r.Entities) == 0 {
		v.addf("registry has no entities")
	}

	seenID := map[string]int{}
	seenAlias := map[string]string{} // 归一化别名 → "实体id/别名原文"
	aliasOwner := map[string]string{}
	// indexDirOwner / docsDirOwner 全局唯一性：两套索引指到同一个目录会互相覆盖，
	// 两套文档指到同一个目录则索引内容来源分不清（设计硬约束）。
	indexDirOwner := map[string]string{}
	docsDirOwner := map[string]string{}

	for i := range r.Entities {
		e := &r.Entities[i]
		where := fmt.Sprintf("entity %d", i)
		if e.ID == "" {
			v.addf("%s: id is empty", where)
		} else {
			where = fmt.Sprintf("entity %q", e.ID)
			if !kebabRe.MatchString(e.ID) {
				v.addf("%s: id must be lowercase kebab-case (a-z, 0-9, single '-')", where)
			}
			if first, dup := seenID[e.ID]; dup {
				v.addf("%s: duplicate id (also at entity %d)", where, first)
			} else {
				seenID[e.ID] = i
			}
		}
		if e.Name == "" {
			v.addf("%s: name is empty", where)
		}

		switch e.Type {
		case TypeProduct, TypeChip, TypeModule, TypeToolkit, TypeSDK:
		default:
			v.addf("%s: type %q is not one of product|chip|module|toolkit|sdk", where, e.Type)
		}

		// sdk 实体的文档与索引都挂在版本上（每个版本一套），sdk 自身始终没有顶层
		// docs_dir/index_dir。因此它的 status 不是"有没有文档"的自由选择，而是 versions
		// 的派生结论：登记了版本就必须是 ready（否则 list 会把有 3 个版本文档的 SDK
		// 显示成占位），没有版本就必须是 placeholder。
		switch e.Status {
		case StatusReady:
			if e.Type == TypeSDK {
				if len(e.Versions) == 0 {
					v.addf("%s: sdk with no versions must be status=placeholder "+
						"(register the versions first, then mark it ready)", where)
				}
				break
			}
			if e.DocsDir == "" {
				v.addf("%s: status=ready requires docs_dir", where)
			} else if st, err := os.Stat(r.resolve(e.DocsDir)); err != nil {
				v.addf("%s: docs_dir %q does not exist", where, e.DocsDir)
			} else if !st.IsDir() {
				v.addf("%s: docs_dir %q is not a directory", where, e.DocsDir)
			}
			if e.IndexDir == "" {
				v.addf("%s: status=ready requires index_dir", where)
			}
		case StatusPlaceholder:
			if e.Type == TypeSDK && len(e.Versions) > 0 {
				v.addf("%s: sdk with versions must be status=ready (got placeholder); "+
					"versions are registered, so the SDK has searchable docs", where)
			}
			if e.DocsDir != "" {
				v.addf("%s: status=placeholder must have docs_dir=null, got %q", where, e.DocsDir)
			}
			if e.IndexDir != "" {
				v.addf("%s: status=placeholder must have index_dir=null, got %q", where, e.IndexDir)
			}
		default:
			v.addf("%s: status %q is not one of ready|placeholder", where, e.Status)
		}

		if len(e.Aliases) == 0 {
			v.addf("%s: aliases is empty (at least one alias is required for resolve)", where)
		}
		v.checkAliases(e.Aliases, e.ID, where, seenAlias, aliasOwner)

		// schema v2：产品不再直接挂芯片。字段写没写都要管——`"chips": []` 也是写了。
		if e.Type == TypeProduct && e.HasChipsField() {
			v.addf("%s: product must not have a chips field in schema v2 (use modules)", where)
		}
		// schema v3：芯片改用 sdk / sdk_since。"还在写 sdk_family"要报出来，
		// 否则旧的"复用别家 SDK 文档"语义会被静默忽略。
		if e.HasSDKFamilyField() {
			v.addf("%s: sdk_family is gone in schema v3 (chip uses sdk + sdk_since)", where)
		}
		if e.Type != TypeProduct && len(e.Specs) > 0 {
			v.addf("%s: only product may have specs", where)
		}
		if e.Type != TypeChip && (e.SDK != "" || e.SDKSince != "") {
			v.addf("%s: only chip may have sdk / sdk_since", where)
		}
		if e.Type != TypeSDK && (len(e.Versions) > 0 || e.Sources != nil) {
			v.addf("%s: only sdk may have versions / sources", where)
		}

		seenSpecName := map[string]bool{}
		for j := range e.Specs {
			sp := &e.Specs[j]
			// 规格没有 id，所以定位键是 (产品, 规格名)。别名归属也用这个复合键，
			// 否则两个产品的同名规格会被误判成"同一所有者内部的重复"而放行。
			owner := specKey(e.ID, sp.Name)
			swhere := fmt.Sprintf("%s spec %q", where, sp.Name)
			if sp.Name == "" {
				v.addf("%s: name is empty", swhere)
			} else if seenSpecName[sp.Name] {
				v.addf("%s: duplicate spec name within the product", swhere)
			} else {
				seenSpecName[sp.Name] = true
			}
			if len(sp.Aliases) == 0 {
				v.addf("%s: aliases is empty (at least one alias is required for resolve)", swhere)
			}
			v.checkAliases(sp.Aliases, owner, swhere, seenAlias, aliasOwner)
		}

		if e.Type == TypeSDK {
			v.checkVersions(e, where, indexDirOwner, docsDirOwner)
		}
		// 登记实体自身的路径占用（ready/placeholder 的路径约束已在上面按 status 检查过），
		// 让"两套索引指到同一个目录"在全注册表范围内可查。
		v.claimDir(e.IndexDir, where, "index_dir", indexDirOwner)
		v.claimDir(e.DocsDir, where, "docs_dir", docsDirOwner)
	}

	// 引用校验放在 id 唯一性之后：byID 已按"先出现的为准"建立，重复 id 已在上面报过。
	for i := range r.Entities {
		e := &r.Entities[i]
		where := fmt.Sprintf("entity %q", e.ID)
		for _, m := range e.Modules {
			if !v.isModule(m) {
				v.addf("%s: modules references %q, which is not a defined module", where, m)
			}
		}
		declared := map[string]bool{}
		for _, m := range e.Modules {
			declared[m] = true
		}
		covered := map[string]bool{}
		for _, sp := range e.Specs {
			for _, m := range sp.Modules {
				if !v.isModule(m) {
					v.addf("%s spec %q: modules references %q, which is not a defined module",
						where, sp.Name, m)
					continue
				}
				// 规格只是 product.modules 的再划分，不能凭空多出模组。
				if !declared[m] {
					v.addf("%s spec %q: module %q is not listed in the product's modules",
						where, sp.Name, m)
				}
				covered[m] = true
			}
		}
		// 规格合起来必须覆盖产品的全部模组，否则有模组没有任何规格认领，
		// "哪种规格用哪个模组"就不完整。
		if len(e.Specs) > 0 {
			for _, m := range e.Modules {
				if !covered[m] {
					v.addf("%s: module %q is not covered by any spec", where, m)
				}
			}
		}
		for _, c := range e.Chips {
			if !v.isChip(c) {
				v.addf("%s: chips references %q, which is not a defined chip", where, c)
			}
		}
		// toolkits 只能引用 toolkit：写错成芯片或产品会让 --with-related 展开出
		// 一个不该被检索的实体，而错误信息必须点明"只接受 toolkit"。
		for _, t := range e.Toolkits {
			if !v.isToolkit(t) {
				v.addf("%s: toolkits references %q, which is not a defined toolkit", where, t)
			}
		}
		if e.Type != TypeProduct && len(e.Toolkits) > 0 {
			v.addf("%s: only product may have toolkits", where)
		}
		// sdk / sdk_since 只能写在 chip 上，且 sdk 必须指向已定义的 sdk 实体。
		if e.SDK != "" {
			if !v.isSDK(e.SDK) {
				v.addf("%s: sdk references %q, which is not a defined sdk", where, e.SDK)
			} else if e.SDKSince != "" {
				v.checkSDKSince(e, where)
			}
		}
	}

	if len(r.SharedSources) > 0 {
		v.checkSources("shared_sources", &Sources{Repos: r.SharedSources})
	}

	// 警告挂在注册表上：校验通过时调用方仍能拿到它们（例如 sdk_since 暂存无法核对）。
	r.warnings = v.warnings

	if len(v.problems) > 0 {
		return &ValidationError{Problems: v.problems, Warnings: v.warnings}
	}
	return nil
}

type validator struct {
	reg      *Registry
	problems []string
	warnings []string
}

func (v *validator) addf(format string, args ...any) {
	v.problems = append(v.problems, fmt.Sprintf(format, args...))
}

// warnf 记录一条不影响校验结论的警告。
func (v *validator) warnf(format string, args ...any) {
	v.warnings = append(v.warnings, fmt.Sprintf(format, args...))
}

// checkAliases 校验一组别名：非空、归一化后不为空、跨所有者唯一。
// 同一所有者内部的归一化重复（如同时写了 `SE9 16-BP1-11` 与 `SE9-16-BP1-11`）
// 不构成歧义——两者指向同一个实体——所以只跳过，不报错。
func (v *validator) checkAliases(aliases []string, ownerID, where string,
	seenAlias, aliasOwner map[string]string) {
	for _, a := range aliases {
		key := normalize(a)
		if key == "" {
			v.addf("%s: alias %q is blank after normalization", where, a)
			continue
		}
		if first, dup := seenAlias[key]; dup {
			if aliasOwner[key] != ownerID {
				v.addf("%s: duplicate alias %q, already used by %s", where, a, first)
			}
			continue
		}
		seenAlias[key] = where
		aliasOwner[key] = ownerID
	}
}

// isChip 判断 id 是否指向已定义的 chip 实体。
func (v *validator) isChip(id string) bool {
	e, ok := v.reg.ByID(id)
	return ok && e.Type == TypeChip
}

// isToolkit 判断 id 是否指向已定义的 toolkit 实体。
func (v *validator) isToolkit(id string) bool {
	e, ok := v.reg.ByID(id)
	return ok && e.Type == TypeToolkit
}

// isModule 判断 id 是否指向已定义的 module 实体。
func (v *validator) isModule(id string) bool {
	e, ok := v.reg.ByID(id)
	return ok && e.Type == TypeModule
}

// isSDK 判断 id 是否指向已定义的 sdk 实体。
func (v *validator) isSDK(id string) bool {
	e, ok := v.reg.ByID(id)
	return ok && e.Type == TypeSDK
}

// claimDir 登记一个路径的占用者；同一路径被两处引用时报告冲突。
// 空路径（placeholder / 未配置）不占用任何东西。
func (v *validator) claimDir(dir, where, field string, owner map[string]string) {
	if dir == "" {
		return
	}
	if first, dup := owner[dir]; dup {
		v.addf("%s: %s %q is already used by %s", where, field, dir, first)
		return
	}
	owner[dir] = where
}

// checkVersions 校验一个 sdk 实体的 versions 列表。
//
// 版本没有 id，定位键是 (sdk id, slug)：slug 只需在所属 sdk 内唯一。每个版本必须自带
// docs_dir 与 index_dir——它们是各自的索引目标，全局不得重复（重复就互相覆盖）。
func (v *validator) checkVersions(e *Entity, where string,
	indexDirOwner, docsDirOwner map[string]string) {
	seenSlug := map[string]bool{}
	for j := range e.Versions {
		ver := &e.Versions[j]
		vwhere := fmt.Sprintf("%s version %q", where, ver.Slug)
		if ver.Slug == "" {
			vwhere = fmt.Sprintf("%s version %d", where, j)
			v.addf("%s: slug is empty (slug is the -sdk-version value and part of <sdk>@<slug>)", vwhere)
		} else if seenSlug[ver.Slug] {
			v.addf("%s: duplicate slug within the sdk", vwhere)
		} else {
			seenSlug[ver.Slug] = true
		}
		if ver.Version == "" {
			v.addf("%s: version is empty", vwhere)
		}
		if ver.ReleaseDate == "" {
			v.addf("%s: release_date is empty (it orders the versions for \"latest\")", vwhere)
		} else if _, err := parseReleaseDate(ver.ReleaseDate); err != nil {
			v.addf("%s: release_date %q is not YYYY-MM-DD", vwhere, ver.ReleaseDate)
		}
		if ver.DocsDir == "" {
			v.addf("%s: docs_dir is empty", vwhere)
		} else if st, err := os.Stat(v.reg.resolve(ver.DocsDir)); err != nil {
			v.addf("%s: docs_dir %q does not exist", vwhere, ver.DocsDir)
		} else if !st.IsDir() {
			v.addf("%s: docs_dir %q is not a directory", vwhere, ver.DocsDir)
		}
		if ver.IndexDir == "" {
			v.addf("%s: index_dir is empty", vwhere)
		}
		v.claimDir(ver.DocsDir, vwhere, "docs_dir", docsDirOwner)
		v.claimDir(ver.IndexDir, vwhere, "index_dir", indexDirOwner)
		for _, chipID := range ver.AppliesTo {
			if !v.isChip(chipID) {
				v.addf("%s: applies_to references %q, which is not a defined chip", vwhere, chipID)
			}
		}
	}
	v.checkSources(where+".sources", e.Sources)
}

// checkSources 校验源码登记的结构与字段类型（数据本身由阶段 7 填写）。
func (v *validator) checkSources(where string, s *Sources) {
	if s == nil {
		return
	}
	seenRepo := map[string]bool{}
	for i, repo := range s.Repos {
		rwhere := fmt.Sprintf("%s.repos[%d]", where, i)
		if repo.Name == "" {
			v.addf("%s: name is empty", rwhere)
		} else if seenRepo[repo.Name] {
			v.addf("%s: duplicate repo name %q", rwhere, repo.Name)
		} else {
			seenRepo[repo.Name] = true
		}
		if repo.URL == "" {
			v.addf("%s: url is empty", rwhere)
		} else if !isHTTPURL(repo.URL) {
			v.addf("%s: url %q must be an http(s) URL", rwhere, repo.URL)
		}
		if repo.Purpose == "" {
			v.addf("%s: purpose is empty", rwhere)
		}
	}
	if m := s.Manifest; m != nil {
		mwhere := where + ".manifest"
		if m.URL == "" {
			v.addf("%s: url is empty", mwhere)
		} else if !isHTTPURL(m.URL) {
			v.addf("%s: url %q must be an http(s) URL", mwhere, m.URL)
		}
		if len(m.Files) == 0 {
			v.addf("%s: files is empty", mwhere)
		}
		seenPath := map[string]bool{}
		for i, f := range m.Files {
			fwhere := fmt.Sprintf("%s.files[%d]", mwhere, i)
			if f.Path == "" {
				v.addf("%s: path is empty", fwhere)
			} else if seenPath[f.Path] {
				v.addf("%s: duplicate path %q", fwhere, f.Path)
			} else {
				seenPath[f.Path] = true
			}
			if f.Label == "" {
				v.addf("%s: label is empty", fwhere)
			}
		}
		if m.Default == "" {
			v.addf("%s: default is empty (which file repo init should use)", mwhere)
		} else if !seenPath[m.Default] {
			v.addf("%s: default %q is not listed in files", mwhere, m.Default)
		}
	}
}

// checkSDKSince 校验芯片的 sdk_since：必须是所属 sdk 已有的版本 slug。
//
// versions 为空时只给警告（此时 SDK 还没登记版本，sdk_since 属暂存，无法核对）——
// 这与"未登记版本却已声明起用版本"不同，后者永远没法核对，所以不拦。
func (v *validator) checkSDKSince(e *Entity, where string) {
	sdk, ok := v.reg.ByID(e.SDK)
	if !ok {
		return // sdk 引用缺失已单独报过
	}
	if len(sdk.Versions) == 0 {
		v.warnf("%s: sdk_since %q cannot be verified: sdk %q has no versions yet",
			where, e.SDKSince, e.SDK)
		return
	}
	if _, ok := v.reg.Version(e.SDK, e.SDKSince); !ok {
		v.addf("%s: sdk_since %q is not a version slug of sdk %q (known: %s)",
			where, e.SDKSince, e.SDK, strings.Join(versionSlugs(sdk), ","))
	}
}

// versionSlugs 一个 sdk 的全部版本 slug（按登记顺序，供错误信息使用）。
func versionSlugs(e *Entity) []string {
	out := make([]string, 0, len(e.Versions))
	for i := range e.Versions {
		out = append(out, e.Versions[i].Slug)
	}
	return out
}

// isHTTPURL 粗略校验 http(s) URL（注册表里的源码地址都是 GitHub / 官网链接）。
func isHTTPURL(s string) bool {
	return strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://")
}
