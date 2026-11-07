package registry

import (
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"
)

// Match Resolve 的一次别名命中。
type Match struct {
	// EntityID 命中的实体 id。命中规格别名时这里仍是父产品 id——规格不是实体，
	// 检索目标就是父产品的索引。
	EntityID string
	// SpecName 命中规格别名时是该规格的名称（如 "SE9 8"）；命中实体本身时为空。
	// 规格没有 id，所以这里存名称。
	SpecName string
	// Alias 注册表里登记的别名原文（不是文本里的写法）。
	Alias string
	// Text 文本里实际命中的片段（归一化前的原文）。
	Text string
	// Start/End 在归一化文本中的字节偏移（含 / 不含）。
	// 归一化会删掉空格与 `-`，所以这两个偏移不能直接拿去切原文——原文片段见 Text。
	Start int
	End   int
}

// Target 命中的检索目标 id。规格不是实体，命中规格时目标仍是父产品，
// 因此这里恒等于 EntityID——保留方法是为了让调用方语义清晰。
func (m Match) Target() string { return m.EntityID }

// Resolve 在文本里按别名找实体 / 规格。
//
// 匹配发生在归一化后的文本上（转小写、去掉空格 / `-` / `_`），因此
// 「SE9 16-BP1-11」「se9 16bp111」「SE9-16-BP1-11」都能命中同一条别名。
// 同一位置有多个候选别名时取最长的一条；命中互不重叠，按出现位置先后输出。
//
// **词边界**：命中位置会映射回原文，要求原文中命中片段的前一个字符和后一个字符
// 都不是 ASCII 字母或数字（中文、标点、空格与文本首尾都算边界）。没有这一步，
// 归一化会把 "use 7 days" 压成 "use7days"，其中的 "se7" 就会误命中 SE7；
// "case8" 同理会误命中 SE8。
func (r *Registry) Resolve(text string) []Match {
	aliases := r.normalizedAliases()
	nm := normalizeWithMap(text)
	if nm.norm == "" || len(aliases) == 0 {
		return nil
	}

	var out []Match
	for i := 0; i < len(nm.norm); {
		var best *normAlias
		for k := range aliases {
			a := &aliases[k]
			if len(a.norm) > len(nm.norm)-i || nm.norm[i:i+len(a.norm)] != a.norm {
				continue
			}
			// 最长匹配优先；同样长时按目标 id 保证结果与注册表顺序无关地确定。
			if best == nil || len(a.norm) > len(best.norm) ||
				(len(a.norm) == len(best.norm) && a.targetID() < best.targetID()) {
				best = a
			}
		}
		if best == nil {
			i++
			continue
		}
		// 映射回原文判词边界；不满足就换下一个候选（同位置可能有更短的合法候选），
		// 都失败则前移一个字节继续扫描。
		if !best.accepts(nm, text, i) {
			shorter := r.nextBoundaryCandidate(aliases, nm, text, i, best)
			if shorter == nil {
				i++
				continue
			}
			best = shorter
		}
		out = append(out, Match{
			EntityID: best.entityID,
			SpecName: best.specName,
			Alias:    best.alias,
			Text:     nm.sourceText(i, i+len(best.norm)),
			Start:    i,
			End:      i + len(best.norm),
		})
		i += len(best.norm)
	}
	return out
}

// nextBoundaryCandidate 在同一位置找一个比 rejected 短、且满足词边界的候选。
// 用于"最长候选跨到了词内部"的情形（例如别名 SM9 与 SM9 16，文本 "xSM9 16"）。
func (r *Registry) nextBoundaryCandidate(aliases []normAlias, nm normMap, text string, i int, rejected *normAlias) *normAlias {
	var best *normAlias
	for k := range aliases {
		a := &aliases[k]
		if len(a.norm) >= len(rejected.norm) || len(a.norm) > len(nm.norm)-i {
			continue
		}
		if nm.norm[i:i+len(a.norm)] != a.norm || !a.accepts(nm, text, i) {
			continue
		}
		if best == nil || len(a.norm) > len(best.norm) ||
			(len(a.norm) == len(best.norm) && a.targetID() < best.targetID()) {
			best = a
		}
	}
	return best
}

// normAlias 一条待匹配的别名。
type normAlias struct {
	norm     string // 归一化后的别名
	alias    string // 别名原文
	entityID string // 所属实体 id（规格别名时为父产品 id）
	specName string // 规格名（实体别名时为空）
}

// targetID 用于同长候选的确定性排序：先比实体，再比规格名。
func (a *normAlias) targetID() string { return a.entityID + "\x00" + a.specName }

// accepts 该别名在归一化文本第 i 位命中时，原文的词边界是否成立。
func (a *normAlias) accepts(nm normMap, text string, i int) bool {
	return wordBoundaryOK(text, nm.srcStart[i], nm.srcEnd[i+len(a.norm)-1])
}

// normalizedAliases 展开全部实体与规格的别名并按归一化长度降序排列（便于最长匹配时早命中）。
// 归一化后为空或重复的别名跳过（Validate 会报重复；这里只是不让坏数据影响匹配）。
func (r *Registry) normalizedAliases() []normAlias {
	seen := map[string]bool{}
	out := make([]normAlias, 0, len(r.Entities)*2)
	add := func(aliases []string, entityID, specName string) {
		for _, a := range aliases {
			n := normalize(a)
			if n == "" || seen[n] {
				continue
			}
			seen[n] = true
			out = append(out, normAlias{norm: n, alias: a, entityID: entityID, specName: specName})
		}
	}
	for i := range r.Entities {
		e := &r.Entities[i]
		add(e.Aliases, e.ID, "")
		for j := range e.Specs {
			add(e.Specs[j].Aliases, e.ID, e.Specs[j].Name)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return len(out[i].norm) > len(out[j].norm) })
	return out
}

// ResolveIDs 只取命中的实体 id（去重、按首次出现位置）。
func (r *Registry) ResolveIDs(text string) []string {
	seen := map[string]bool{}
	var out []string
	for _, m := range r.Resolve(text) {
		if seen[m.EntityID] {
			continue
		}
		seen[m.EntityID] = true
		out = append(out, m.EntityID)
	}
	return out
}

// normMap 归一化文本 + 归一化字节 → 原文字节偏移的映射。
type normMap struct {
	norm     string
	src      string // 原文（sourceText 切片用）
	srcStart []int  // 第 i 个归一化字节对应原文的起始偏移
	srcEnd   []int  // 第 i 个归一化字节对应字符在原文中的结束偏移
}

// normalizeWithMap 与 normalize 同样的规则（小写、去掉空格 / `-` / `_`），
// 同时记录每个归一化字节来自原文的哪个区间，供词边界判断与原文片段还原。
func normalizeWithMap(s string) normMap {
	var sb strings.Builder
	nm := normMap{src: s}
	for off, r := range s {
		keep := true
		switch r {
		case ' ', '\t', '\n', '\r', '-', '_':
			keep = false
		}
		if !keep {
			continue
		}
		lower := strings.ToLower(string(r))
		sb.WriteString(lower)
		end := off + utf8.RuneLen(r)
		// 归一化文本按字节索引，所以每个归一化字节都要有一条映射
		// （ToLower 可能把一个 rune 变成多个 rune，如 'İ' → "i̇"）。
		for i := 0; i < len(lower); i++ {
			nm.srcStart = append(nm.srcStart, off)
			nm.srcEnd = append(nm.srcEnd, end)
		}
	}
	nm.norm = sb.String()
	return nm
}

// sourceText 归一化区间 [i,j) 对应的原文片段。
func (nm normMap) sourceText(i, j int) string {
	if i < 0 || j > len(nm.srcStart) || i >= j {
		return ""
	}
	return nm.src[nm.srcStart[i]:nm.srcEnd[j-1]]
}

// wordBoundaryOK 原文里 [start,end) 这段的前后字符是否都不是 ASCII 字母 / 数字。
// 中文、标点、空格与文本首尾都算边界。
func wordBoundaryOK(text string, start, end int) bool {
	if start > 0 {
		r, _ := utf8.DecodeLastRuneInString(text[:start])
		if isASCIIAlnum(r) {
			return false
		}
	}
	if end < len(text) {
		r, _ := utf8.DecodeRuneInString(text[end:])
		if isASCIIAlnum(r) {
			return false
		}
	}
	return true
}

func isASCIIAlnum(r rune) bool {
	return (r >= '0' && r <= '9') || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
}

// Skip 关联展开时被跳过的实体及原因。
type Skip struct {
	ID     string
	Reason string
}

// Expansion 一次关联展开的结果。
type Expansion struct {
	// IDs 检索目标（只有 status=ready 的实体），含自身，去重保序。
	IDs []string
	// Skipped placeholder 实体（它们参与遍历，但不进入检索目标）。
	Skipped []Skip
	// Notes 需要 Agent 知道的口径提示（如"该产品有多个规格，答案取决于芯片时要问清"）。
	Notes []string
	// Versions 展开出的 SDK 检索版本（每个版本一套索引，见 VersionRef）。
	// 顺序是"产品 → 模组 → 芯片 → sdk 版本"，与 IDs 里 sdk 实体的出现顺序一致。
	Versions []VersionRef
}

// RelatedOptions 关联展开的可选参数。
type RelatedOptions struct {
	// SDKVersion `-sdk-version` 的选择（零值 = 默认取最新版本）。
	SDKVersion SDKVersionRequest
}

// Related 展开一个实体 id 的关联检索目标，按"产品 → 模组 → 芯片 → sdk → toolkits"：
//
//   - product：自身 → 全部模组 → 各模组的芯片 → 各芯片的 sdk（选定版本）；随后是 toolkits
//   - module：自身 → 芯片 → 各芯片的 sdk（选定版本）
//   - chip：自身 → 自身 sdk（选定版本）
//   - toolkit：只有自身
//   - sdk：实体本身不进 IDs（它没有顶层文档目录），检索目标是它的版本（见 Versions）
//
// **规格不影响检索目标**：SE9 的两种规格最终都落到同一对索引（se9 + bm1688），
// 所以这里按 product.modules 展开，不看 specs。
//
// **版本是 sdk 的检索目标**：sdk 实体的文档与索引都在版本上，status=ready 只表示
// "版本已登记"，因此 sdk id 不出现在 IDs 里，而是给出 Versions；版本的选择与芯片的
// sdk_since 过滤见 SelectVersions。
//
// 不反向展开（芯片 / 模组不回到产品）。结果去重、保序；placeholder 参与遍历但不进入 IDs，
// 跳过项记入 Skipped——sm9-8（placeholder）→ cv186ah（placeholder）→ sophonsdk-edge（placeholder），
// 链要一路走到底，最后落到 sdk 的版本上。
func (r *Registry) Related(id string) (Expansion, error) {
	return r.RelatedWith(id, RelatedOptions{})
}

// RelatedWith 见 Related，可指定 SDK 版本选择。
func (r *Registry) RelatedWith(id string, opts RelatedOptions) (Expansion, error) {
	var exp Expansion
	seen := map[string]bool{}
	skippedSeen := map[string]bool{}
	versionSeen := map[string]bool{}

	add := func(target string) {
		t, ok := r.ByID(target)
		if !ok {
			// 引用缺失由 Validate 报；这里静默跳过，不让查询因坏数据崩掉。
			return
		}
		// sdk 的检索目标永远是它的版本：实体本身按设计没有顶层 docs_dir/index_dir
		// （status=ready 只表示"版本已登记"），所以不能把 sdk id 放进 IDs，否则
		// build/query 会拿到空目录。没有版本时记一条跳过说明。
		if t.Type == TypeSDK {
			if len(t.Versions) == 0 && !skippedSeen[t.ID] {
				skippedSeen[t.ID] = true
				exp.Skipped = append(exp.Skipped, Skip{ID: t.ID,
					Reason: "status=placeholder: sdk has no versions registered yet"})
			}
			return
		}
		if t.Status != StatusReady {
			if !skippedSeen[t.ID] {
				skippedSeen[t.ID] = true
				exp.Skipped = append(exp.Skipped, Skip{ID: t.ID,
					Reason: fmt.Sprintf("status=%s: no docs_dir/index_dir, nothing to search", t.Status)})
			}
			return
		}
		if seen[t.ID] {
			return
		}
		seen[t.ID] = true
		exp.IDs = append(exp.IDs, t.ID)
	}

	// followSDK 展开某个芯片的 sdk：sdk 实体本身是 placeholder（跳过并提示），
	// 真正进入检索目标的是选定版本。
	followSDK := func(chipID string) {
		c, ok := r.ByID(chipID)
		if !ok || c.SDK == "" {
			return
		}
		add(c.SDK)
		vers, notes, err := r.SelectVersions(c.SDK, opts.SDKVersion, chipID)
		if err != nil {
			// 版本选择错误（-sdk-version 指定了不存在的 slug）必须原样报给用户，
			// 不能静默少查一个版本。
			exp.Notes = append(exp.Notes, err.Error())
			return
		}
		exp.Notes = append(exp.Notes, notes...)
		for _, v := range vers {
			if versionSeen[v.Label()] {
				continue
			}
			versionSeen[v.Label()] = true
			exp.Versions = append(exp.Versions, v)
		}
	}

	// expandModule 模组 → 芯片 → sdk；模组自身可能也是 placeholder，交给 add 处理。
	expandModule := func(moduleID string) {
		add(moduleID)
		if m, ok := r.ByID(moduleID); ok {
			for _, chipID := range m.Chips {
				add(chipID)
				followSDK(chipID)
			}
		}
	}

	e, ok := r.ByID(id)
	if !ok {
		return exp, fmt.Errorf("unknown entity %q", id)
	}

	add(e.ID)

	switch e.Type {
	case TypeProduct:
		for _, moduleID := range e.Modules {
			expandModule(moduleID)
		}
		// 随箱工具挂在产品上（跨芯片共用，没有共同芯片可挂）：放在芯片之后展开，
		// 这样结果的顺序是"产品 → 模组 → 芯片 → sdk 版本 → toolkits"。
		// toolkit 自身不再往下展开（它没有 modules/chips）。
		for _, toolkitID := range e.Toolkits {
			add(toolkitID)
		}
		// 规格只是"哪种规格用哪个模组"，检索目标已经在上面按全部模组展开了；
		// 这里补一条对照，提醒 Agent 答案依赖芯片时该问清规格。
		if len(e.Specs) > 1 {
			exp.Notes = append(exp.Notes, r.specSummaryNote(e))
		}
	case TypeModule:
		for _, chipID := range e.Chips {
			add(chipID)
			followSDK(chipID)
		}
	case TypeChip:
		followSDK(e.ID)
	case TypeSDK:
		// sdk 自身：检索目标是它的版本（选版本规则与芯片展开一致）。
		add(e.ID)
		vers, notes, err := r.SelectVersions(e.ID, opts.SDKVersion, "")
		if err != nil {
			exp.Notes = append(exp.Notes, err.Error())
			break
		}
		exp.Notes = append(exp.Notes, notes...)
		for _, v := range vers {
			if versionSeen[v.Label()] {
				continue
			}
			versionSeen[v.Label()] = true
			exp.Versions = append(exp.Versions, v)
		}
	}
	return exp, nil
}

// specSummaryNote 只说产品名（没命中具体规格）时的规格对照，逐规格列出模组与芯片。
//
// 形如：
//
//	se9 specs: SE9 16 (sm9-16 → bm1688) | SE9 8 (sm9-8 → cv186ah); ask which one if the answer depends on chip
func (r *Registry) specSummaryNote(e *Entity) string {
	parts := make([]string, 0, len(e.Specs))
	for j := range e.Specs {
		parts = append(parts, specChain(r, &e.Specs[j]))
	}
	return fmt.Sprintf("%s specs: %s; ask which one if the answer depends on chip",
		e.ID, strings.Join(parts, " | "))
}

// specChain 单个规格的展示串：`SE9 8 (sm9-8 → cv186ah)`。
func specChain(r *Registry, sp *Spec) string {
	chain := make([]string, 0, len(sp.Modules))
	for _, moduleID := range sp.Modules {
		chips := []string{}
		if m, ok := r.ByID(moduleID); ok {
			chips = m.Chips
		}
		if len(chips) == 0 {
			chain = append(chain, moduleID)
			continue
		}
		sdk := make([]string, 0, len(chips))
		for _, c := range chips {
			sdk = append(sdk, c)
		}
		chain = append(chain, moduleID+" → "+strings.Join(sdk, "/"))
	}
	return fmt.Sprintf("%s (%s)", sp.Name, strings.Join(chain, ", "))
}

// SpecChips 某规格对应的芯片 id（按规格的模组顺序、去重保序）。
// 供 resolve 输出 `spec="SE9 8" chips=cv186ah`，让 Agent 知道芯片级数值该用哪颗芯片。
func (r *Registry) SpecChips(sp *Spec) []string {
	seen := map[string]bool{}
	var out []string
	for _, moduleID := range sp.Modules {
		m, ok := r.ByID(moduleID)
		if !ok {
			continue
		}
		for _, c := range m.Chips {
			if seen[c] {
				continue
			}
			seen[c] = true
			out = append(out, c)
		}
	}
	return out
}

// UsedBy 反向查询：哪些产品引用了该模组（只供 resolve 输出参考，不参与检索展开）。
// 规格不参与：规格是产品的一部分，列产品 id 就够了。
func (r *Registry) UsedBy(moduleID string) []string {
	var out []string
	for i := range r.Entities {
		e := &r.Entities[i]
		direct := false
		for _, m := range e.Modules {
			if m == moduleID {
				direct = true
				break
			}
		}
		if direct {
			out = append(out, e.ID)
		}
	}
	return out
}

// RelatedAll 对多个目标分别展开后合并（去重、保序：先按入参顺序，再按各自的展开顺序）。
// 跳过项与提示按内容去重。
func (r *Registry) RelatedAll(ids []string) (Expansion, error) {
	return r.RelatedAllWith(ids, RelatedOptions{})
}

// RelatedAllWith 见 RelatedAll，可指定 SDK 版本选择。
func (r *Registry) RelatedAllWith(ids []string, opts RelatedOptions) (Expansion, error) {
	var out Expansion
	seen := map[string]bool{}
	skipSeen := map[string]bool{}
	noteSeen := map[string]bool{}
	versionSeen := map[string]bool{}
	for _, id := range ids {
		exp, err := r.RelatedWith(id, opts)
		if err != nil {
			return Expansion{}, err
		}
		for _, g := range exp.IDs {
			if !seen[g] {
				seen[g] = true
				out.IDs = append(out.IDs, g)
			}
		}
		for _, s := range exp.Skipped {
			if !skipSeen[s.ID] {
				skipSeen[s.ID] = true
				out.Skipped = append(out.Skipped, s)
			}
		}
		for _, n := range exp.Notes {
			if !noteSeen[n] {
				noteSeen[n] = true
				out.Notes = append(out.Notes, n)
			}
		}
		for _, v := range exp.Versions {
			if versionSeen[v.Label()] {
				continue
			}
			versionSeen[v.Label()] = true
			out.Versions = append(out.Versions, v)
		}
	}
	return out, nil
}

// FormatSkips 把跳过项渲染成一行人类可读提示（空切片返回空串）。
func FormatSkips(skipped []Skip) string {
	if len(skipped) == 0 {
		return ""
	}
	parts := make([]string, 0, len(skipped))
	for _, s := range skipped {
		parts = append(parts, fmt.Sprintf("%s (%s)", s.ID, s.Reason))
	}
	return "skipped placeholder: " + strings.Join(parts, ", ")
}
