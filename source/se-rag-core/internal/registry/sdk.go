package registry

import (
	"fmt"
	"sort"
	"strings"
)

// SDK 版本选择（`-sdk-version` 的语义）。
const (
	// SDKVersionLatest 默认：按 release_date 取最新版本作为检索目标。
	SDKVersionLatest = "latest"
	// SDKVersionAll 取全部版本，各版本各一份索引。
	SDKVersionAll = "all"
)

// SDKVersionRequest 一次 -sdk-version 请求。
//
// 空串等价于 latest（CLI 的默认行为）；all 表示不限版本；其余按 slug 精确匹配。
type SDKVersionRequest struct {
	// Raw 用户传入的原文（空串 = 未指定）。
	Raw string
	// All 是否取全部版本。
	All bool
	// Slug 指定的版本 slug（All=false 且 Raw 非空且非 latest 时有意义）。
	Slug string
}

// ParseSDKVersion 解析 -sdk-version 的取值。
//
// 接受 latest / all / <slug>；大小写不敏感（`V2.3` 与 `v2.3` 等价）。
func ParseSDKVersion(s string) (SDKVersionRequest, error) {
	v := strings.TrimSpace(s)
	if v == "" {
		return SDKVersionRequest{}, nil
	}
	switch lower := strings.ToLower(v); lower {
	case SDKVersionLatest, "":
		return SDKVersionRequest{Raw: v}, nil
	case SDKVersionAll:
		return SDKVersionRequest{Raw: v, All: true}, nil
	default:
		return SDKVersionRequest{Raw: v, Slug: v}, nil
	}
}

// Default 是否走默认语义（未指定或显式 latest）。
func (q SDKVersionRequest) Default() bool { return !q.All && q.Slug == "" }

// SelectVersions 按请求挑出该 sdk 的检索版本，按 release_date 从新到旧返回。
//
// 选择规则（设计 D3）：
//   - 默认（未指定 / latest）：只取最新版本，按 release_date 排序；
//   - all：全部版本；
//   - 指定 slug：只要该版本，找不到即报错（不静默退化成最新版）。
//
// chipID 非空时按芯片的 sdk_since 过滤：早于它支持的版本跳过并给出提示。
// 跳过项不进入返回值，但会记进 Notes，让 Agent 知道"为什么少了这几个版本"。
func (r *Registry) SelectVersions(sdkID string, req SDKVersionRequest, chipID string) ([]VersionRef, []string, error) {
	e, ok := r.ByID(sdkID)
	if !ok {
		return nil, nil, fmt.Errorf("unknown sdk %q", sdkID)
	}
	if e.Type != TypeSDK {
		return nil, nil, fmt.Errorf("entity %q is a %s, not an sdk", sdkID, e.Type)
	}
	if len(e.Versions) == 0 {
		return nil, nil, nil
	}

	var picked []Version
	switch {
	case req.All:
		picked = append(picked, e.Versions...)
	case req.Slug != "":
		v, ok := r.Version(sdkID, req.Slug)
		if !ok {
			return nil, nil, fmt.Errorf("sdk %q has no version %q (known: %s)",
				sdkID, req.Slug, strings.Join(versionSlugs(e), ","))
		}
		picked = append(picked, *v)
	default:
		latest := r.LatestVersion(sdkID)
		if latest == nil {
			return nil, nil, nil
		}
		picked = append(picked, *latest)
	}

	var notes []string
	if chipID != "" {
		since := r.sdkSince(chipID, sdkID)
		if since != "" {
			kept := picked[:0]
			for _, v := range picked {
				if r.versionBefore(sdkID, v.Slug, since) {
					notes = append(notes, fmt.Sprintf(
						"sdk %s version %s skipped: chip %s is supported from %s on",
						sdkID, v.Slug, chipID, since))
					continue
				}
				kept = append(kept, v)
			}
			picked = kept
		}
	}

	sortVersionsNewestFirst(picked)
	out := make([]VersionRef, 0, len(picked))
	for i := range picked {
		out = append(out, VersionRef{SDKID: sdkID, Version: &picked[i]})
	}
	return out, notes, nil
}

// LatestVersion 该 sdk 的最新版本（按 release_date 从新到旧取第一；没有版本时返回 nil）。
//
// 同一天发布的两个版本按登记顺序取先登记的，保证结果稳定。
func (r *Registry) LatestVersion(sdkID string) *Version {
	e, ok := r.ByID(sdkID)
	if !ok || len(e.Versions) == 0 {
		return nil
	}
	best := -1
	for i := range e.Versions {
		if best < 0 {
			best = i
			continue
		}
		if r.versionAfter(&e.Versions[i], &e.Versions[best]) {
			best = i
		}
	}
	return &e.Versions[best]
}

// versionAfter a 是否严格新于 b。解析失败的日期按"最旧"处理（Validate 已报格式错误）。
func (r *Registry) versionAfter(a, b *Version) bool {
	ta, ea := parseReleaseDate(a.ReleaseDate)
	tb, eb := parseReleaseDate(b.ReleaseDate)
	if ea != nil {
		return false
	}
	if eb != nil {
		return true
	}
	return ta.After(tb)
}

// versionBefore a 是否早于 b（slug 相同不算早）。
func (r *Registry) versionBefore(sdkID, slug, than string) bool {
	a, ok := r.Version(sdkID, slug)
	if !ok || slug == than {
		return false
	}
	b, ok := r.Version(sdkID, than)
	if !ok {
		return false
	}
	ta, ea := parseReleaseDate(a.ReleaseDate)
	tb, eb := parseReleaseDate(b.ReleaseDate)
	if ea != nil || eb != nil {
		return false // 日期不可比时不跳过，宁可多查一个版本
	}
	return ta.Before(tb)
}

// sdkSince 芯片在指定 sdk 上的 sdk_since（芯片不存在或不属于该 sdk 时为空）。
func (r *Registry) sdkSince(chipID, sdkID string) string {
	c, ok := r.ByID(chipID)
	if !ok || c.Type != TypeChip || c.SDK != sdkID {
		return ""
	}
	return c.SDKSince
}

// sortVersionsNewestFirst 按 release_date 从新到旧稳定排序（同日期保留登记顺序）。
func sortVersionsNewestFirst(vs []Version) {
	sort.SliceStable(vs, func(i, j int) bool {
		return releaseDateAfter(vs[i].ReleaseDate, vs[j].ReleaseDate)
	})
}

// releaseDateAfter a 的发布日期是否晚于 b。解析失败的按最旧处理。
func releaseDateAfter(a, b string) bool {
	ta, ea := parseReleaseDate(a)
	tb, eb := parseReleaseDate(b)
	switch {
	case ea != nil && eb != nil:
		return false
	case ea != nil:
		return false
	case eb != nil:
		return true
	}
	return ta.After(tb)
}

// VersionRef 一个检索目标版本：所属 sdk + 版本本身。
//
// 版本不是实体（没有独立 id），所以检索目标用 (SDKID, Slug) 定位；
// Label 是结果标注与命令行里使用的人类可读标识 `<sdk-id>@<slug>`。
type VersionRef struct {
	SDKID   string
	Version *Version
}

// Label `<sdk-id>@<slug>`，与 `-entity <sdk>@<slug>` 的写法一致。
func (v VersionRef) Label() string { return v.SDKID + "@" + v.Version.Slug }

// DocsDir 该版本的文档目录（注册表原文，相对技能根）。
func (v VersionRef) DocsDir() string { return v.Version.DocsDir }

// IndexDir 该版本的索引目录（注册表原文，相对技能根）。
func (v VersionRef) IndexDir() string { return v.Version.IndexDir }
