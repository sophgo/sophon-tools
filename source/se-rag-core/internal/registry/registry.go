// Package registry 读取技能根目录的 registry.json：实体（产品 / 模组 / 芯片）、
// 别名、目录、索引、关联关系与边界的唯一真源。
//
// 注册表里的路径一律相对 registry.json 所在目录（下称"技能根"），
// 由本包解析成绝对路径；调用方只关心实体 id，不拼路径。
//
// schema v2 的关系是"产品 → 模组 → 芯片"三层：product.modules 指向 module，
// module.chips 指向 chip。产品可选用 specs 描述"哪种规格用哪个模组"（如 SE9 16 / SE9 8），
// 但规格只是产品的一个属性，不是实体：没有 id，不进入实体命名空间，`-entity` 也不接受。
//
// schema v3（本卡）新增第四层 sdk：chip.sdk 指向 sdk 实体，sdk 按版本（versions）各建一套
// 索引。原有的 chip.sdk_family "复用别家 SDK 文档"语义由 chip.sdk + chip.sdk_since 承接。
package registry

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// SchemaVersion 本包支持的注册表 schema 版本。
//
// v3（本卡）：新增 sdk 实体（按版本建索引）与顶层 shared_sources；chip 去掉 sdk_family，
// 改用 sdk / sdk_since。
const SchemaVersion = 3

// 实体类型。
type EntityType string

const (
	TypeProduct EntityType = "product"
	TypeChip    EntityType = "chip"
	TypeModule  EntityType = "module"
	// TypeToolkit 随箱工具：跨芯片交付、不隶属任何产品，产品通过 toolkits 关系引用它。
	TypeToolkit EntityType = "toolkit"
	// TypeSDK 芯片 SDK（如 sophonsdk / sophonsdk-edge）：按版本（Version）各建一套索引，
	// 芯片通过 sdk 关系引用它。SDK 文档与芯片资料分开存放，不混在一个索引里。
	TypeSDK EntityType = "sdk"
)

// 实体状态。ready 有文档与索引目录；placeholder 只有路由信息（用于"知道它存在，
// 但没有独立资料"的模组/芯片/SDK），两者路径均为 null。
type Status string

const (
	StatusReady       Status = "ready"
	StatusPlaceholder Status = "placeholder"
)

// Spec 产品规格（如 SE9 16 / SE9 8）。
//
// 用户裁定（2026-11-05）：SE9 是一个实体，SE9 16 / SE9 8 只是规格不同。因此规格
// **没有 id**，不进入实体命名空间——它只是产品上的一个属性，用来说明"哪种规格用
// 哪个模组"。规格名在产品内唯一，规格别名参与全局别名唯一校验；命中规格别名时
// 解析到的仍是父产品，检索目标也不受规格影响。
type Spec struct {
	Name    string   `json:"name"`
	Aliases []string `json:"aliases"`
	Modules []string `json:"modules"`
}

// Version SDK 的一个版本（如 v2.3）。每个版本有自己的文档目录与索引目录，
// 因此检索目标要精确到版本，不只是 SDK 实体。
//
// Slug 是版本在技能内的稳定标识（如 v2.3、v23.09-sp5），同时也是 -sdk-version 的取值
// 与 `<sdk-id>@<slug>` 写法的后半段；在所属 SDK 内唯一。ReleaseDate 形如 YYYY-MM-DD，
// 是"最新版本"的排序依据（官网版本号大小并不等于时间先后）。
type Version struct {
	Version string `json:"version"`
	Slug    string `json:"slug"`
	// ReleaseDate YYYY-MM-DD；用于"最新版本"排序，空值排在最后（旧于任何有日期的版本）。
	ReleaseDate string `json:"release_date"`
	DocsDir     string `json:"docs_dir"`
	IndexDir    string `json:"index_dir"`
	// AppliesTo 该版本适用的芯片 id；为空表示 SDK 里登记的全部芯片通用。
	AppliesTo []string `json:"applies_to"`
}

// Sources SDK 的源码登记（只登记，不下载、不索引——源码体积大且由阶段 7 填写）。
type Sources struct {
	Repos    []SourceRepo `json:"repos"`
	Manifest *Manifest    `json:"manifest"`
	Notes    []string     `json:"notes"`
}

// SourceRepo 一个源码仓库的登记项。
type SourceRepo struct {
	Name    string `json:"name"`
	URL     string `json:"url"`
	Purpose string `json:"purpose"`
}

// Manifest repo 工具用的 manifest（多个仓库一次性同步的入口）。
type Manifest struct {
	URL     string         `json:"url"`
	Files   []ManifestFile `json:"files"`
	Default string         `json:"default"`
}

// ManifestFile manifest 仓库里的一个清单文件。
type ManifestFile struct {
	Path  string `json:"path"`
	Label string `json:"label"`
}

// Entity 注册表中的一个实体。
//
// DocsDir / IndexDir 为 null 时解码为空串（JSON null 对 string 字段是 no-op），
// 因此 placeholder 实体的"两者都为 null"等价于"两者都为空"。
//
// Modules 只有 product 使用（该产品用到的全部模组）；Specs 只有 product 使用，是可选
// 属性，不参与实体命名。Chips 只有 module 使用——schema v2 的 product 不得再出现 chips
// 字段，校验靠 hasChipsField 判断"字段有没有写"（空数组也算写了）。
//
// SDK / SDKSince 只有 chip 使用（schema v3）：SDK 指向 sdk 实体，SDKSince 是该芯片
// 从哪个 SDK 版本 slug 起被支持（可空）。Versions / Sources 只有 sdk 使用。
//
// 这里刻意不保留 schema v2 的 sdk_family 字段：它的语义已被 sdk + sdk_since 取代，
// 留着会让人以为还能用。写了这个字段的注册表由 Validate 直接报错（见 hasSDKFamilyField）。
type Entity struct {
	ID         string     `json:"id"`
	Type       EntityType `json:"type"`
	Name       string     `json:"name"`
	Status     Status     `json:"status"`
	Aliases    []string   `json:"aliases"`
	Modules    []string   `json:"modules"`
	Specs      []Spec     `json:"specs"`
	Chips      []string   `json:"chips"`
	Toolkits   []string   `json:"toolkits"`
	SDK        string     `json:"sdk"`
	SDKSince   string     `json:"sdk_since"`
	Versions   []Version  `json:"versions"`
	Sources    *Sources   `json:"sources"`
	DocsDir    string     `json:"docs_dir"`
	IndexDir   string     `json:"index_dir"`
	Scope      string     `json:"scope"`
	Boundaries []string   `json:"boundaries"`
	QueryHints []string   `json:"query_hints"`

	// hasChipsField 注册表 JSON 里是否显式写了 chips（schema v2 的 product 不允许）。
	hasChipsField bool
	// hasSDKFamilyField 是否写了已废弃的 sdk_family（schema v3 起 chip 改用 sdk）。
	hasSDKFamilyField bool
}

// UnmarshalJSON 解码实体，并记录 chips / sdk_family 字段是否出现过。
// 只看 len(Chips)>0 不够：`"chips": []` 也是写了这个字段，schema v2 的 product 同样不允许；
// sdk_family 同理——写成 null 也算"还在用旧字段"。
func (e *Entity) UnmarshalJSON(b []byte) error {
	type plain Entity
	var p plain
	if err := json.Unmarshal(b, &p); err != nil {
		return err
	}
	*e = Entity(p)
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(b, &keys); err != nil {
		return err
	}
	_, e.hasChipsField = keys["chips"]
	_, e.hasSDKFamilyField = keys["sdk_family"]
	return nil
}

// HasChipsField 注册表里是否显式声明了 chips 字段。
func (e *Entity) HasChipsField() bool { return e.hasChipsField }

// HasSDKFamilyField 注册表里是否还写着 schema v2 的 sdk_family 字段。
func (e *Entity) HasSDKFamilyField() bool { return e.hasSDKFamilyField }

// Registry 一份已解析的注册表。root 是 registry.json 所在目录的绝对路径。
type Registry struct {
	SchemaVersion int      `json:"schema_version"`
	Entities      []Entity `json:"entities"`
	// SharedSources 两个系列共用的源码仓库（sophon-demo、LLM-TPU、sophon-tools 等）。
	// 与 sdk.sources.repos 同结构，只是不归属任何单个 SDK。
	SharedSources []SourceRepo `json:"shared_sources"`

	root   string
	byID   map[string]*Entity
	specOf map[string]specRef
	// verOf (sdk id, slug) → 版本项；slug 在所属 SDK 内唯一，不是全局唯一。
	verOf map[string]versionRef
	// warnings 最近一次 Validate 产出的非致命提示（sdk_since 暂存等）。
	warnings []string
}

// specRef 规格名 → 所属产品与该规格的索引项。
type specRef struct {
	ParentID string
	Spec     *Spec
}

// versionRef SDK 版本 → 所属 SDK 与该版本的索引项。
type versionRef struct {
	ParentID string
	Version  *Version
}

// Load 读取并解析注册表文件。只做解析，不做语义校验——调用方应随后调用 Validate，
// 以便把"文件读不出来"与"内容不合法"两类错误分开报。
func Load(p string) (*Registry, error) {
	b, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("read registry %s: %w", p, err)
	}
	var r Registry
	if err := json.Unmarshal(b, &r); err != nil {
		return nil, fmt.Errorf("parse registry %s: %w", p, err)
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return nil, fmt.Errorf("resolve registry path %s: %w", p, err)
	}
	r.root = filepath.Dir(abs)
	r.reindex()
	return &r, nil
}

// New 用内存中的实体构造注册表（测试与调用方自建夹具用）。root 为空时按当前目录处理。
func New(root string, entities ...Entity) *Registry {
	if root == "" {
		root = "."
	}
	if abs, err := filepath.Abs(root); err == nil {
		root = abs
	}
	r := &Registry{SchemaVersion: SchemaVersion, Entities: entities, root: root}
	r.reindex()
	return r
}

// reindex 重建 id → 实体、规格名 → 规格、SDK 版本 → 版本 的索引。
// 重复 id 保留第一个（Validate 会报错）。
//
// 规格名按 (产品 id, 规格名) 索引：规格名只在产品内唯一，不同产品可以同名。
// 版本 slug 同理按 (SDK id, slug) 索引。
func (r *Registry) reindex() {
	r.byID = make(map[string]*Entity, len(r.Entities))
	r.specOf = make(map[string]specRef)
	r.verOf = make(map[string]versionRef)
	for i := range r.Entities {
		e := &r.Entities[i]
		if _, ok := r.byID[e.ID]; !ok {
			r.byID[e.ID] = e
		}
		for j := range e.Specs {
			sp := &e.Specs[j]
			key := specKey(e.ID, sp.Name)
			if _, ok := r.specOf[key]; !ok {
				r.specOf[key] = specRef{ParentID: e.ID, Spec: sp}
			}
		}
		for j := range e.Versions {
			v := &e.Versions[j]
			key := versionKey(e.ID, v.Slug)
			if _, ok := r.verOf[key]; !ok {
				r.verOf[key] = versionRef{ParentID: e.ID, Version: v}
			}
		}
	}
}

// specKey 规格的索引键（产品内唯一）。
func specKey(entityID, specName string) string { return entityID + "\x00" + specName }

// versionKey SDK 版本的索引键（所属 SDK 内唯一）。
func versionKey(entityID, slug string) string { return entityID + "\x00" + slug }

// Root 技能根目录（registry.json 所在目录）的绝对路径。
func (r *Registry) Root() string { return r.root }

// ByID 取实体。返回的指针指向注册表内部切片，调用方不得修改。
func (r *Registry) ByID(id string) (*Entity, bool) {
	e, ok := r.byID[id]
	return e, ok
}

// Spec 按产品 id + 规格名取规格。规格不是实体，只能这样定位。
func (r *Registry) Spec(entityID, specName string) (*Spec, bool) {
	ref, ok := r.specOf[specKey(entityID, specName)]
	if !ok {
		return nil, false
	}
	return ref.Spec, true
}

// Version 按 SDK id + slug 取版本。版本不是实体，只能这样定位。
func (r *Registry) Version(entityID, slug string) (*Version, bool) {
	ref, ok := r.verOf[versionKey(entityID, slug)]
	if !ok {
		return nil, false
	}
	return ref.Version, true
}

// Warnings 最近一次 Validate 产出的非致命提示（校验失败时为空）。
func (r *Registry) Warnings() []string { return r.warnings }

// IDs 按注册表顺序返回全部实体 id。
func (r *Registry) IDs() []string {
	out := make([]string, 0, len(r.Entities))
	for i := range r.Entities {
		out = append(out, r.Entities[i].ID)
	}
	return out
}

// ReadyIDs 按注册表顺序返回 status=ready 的实体 id（-all 的目标集合）。
//
// sdk 不算在内：它没有顶层文档目录，检索目标是它的各个版本，由调用方单独展开
// （见 cmd/se-rag 的 targetEntities）。把 sdk id 混进来会让 build/query 拿到空目录。
func (r *Registry) ReadyIDs() []string {
	out := make([]string, 0, len(r.Entities))
	for i := range r.Entities {
		e := &r.Entities[i]
		if e.Status == StatusReady && e.Type != TypeSDK {
			out = append(out, e.ID)
		}
	}
	return out
}

// resolve 把注册表里的相对路径解析成绝对路径（绝对路径原样返回）。
func (r *Registry) resolve(p string) string {
	if p == "" {
		return ""
	}
	if filepath.IsAbs(p) {
		return filepath.Clean(p)
	}
	return filepath.Join(r.root, filepath.FromSlash(p))
}

// DataDirEnv 索引落点覆盖用的环境变量。
//
// 技能目录只读（多 agent 共享一份只读副本、或装进只读镜像）时，索引写不进去；
// 设置它以后，所有实体的索引改落到 $SE_RAG_DATA_DIR/<index_dir 的末级目录名>。
// 只换目录前缀、保留末级名，多个实体的索引仍然互不覆盖。
const DataDirEnv = "SE_RAG_DATA_DIR"

// DataDir 当前生效的索引根覆盖目录（未设置时为空串）。
func (r *Registry) DataDir() string { return strings.TrimSpace(os.Getenv(DataDirEnv)) }

// indexPath 解析索引目录，并按 SE_RAG_DATA_DIR 覆盖前缀。
//
// rel 为空（placeholder / 未配置）时返回空串；覆盖目录存在时取 <覆盖目录>/<末级目录名>，
// 末级目录名取自 index_dir 的字面值，与技能根位置无关，因此技能整体搬目录也不影响落点。
func (r *Registry) indexPath(rel string) string {
	p := r.resolve(rel)
	if p == "" {
		return ""
	}
	if dir := r.DataDir(); dir != "" {
		return filepath.Join(dir, path.Base(filepath.ToSlash(rel)))
	}
	return p
}

// DocsPath 实体文档目录的绝对路径（placeholder / 未配置时为空串）。
func (r *Registry) DocsPath(e *Entity) string { return r.resolve(e.DocsDir) }

// IndexPath 实体索引目录的绝对路径（placeholder / 未配置时为空串）。
// 设置了 SE_RAG_DATA_DIR 时返回覆盖后的落点。
func (r *Registry) IndexPath(e *Entity) string { return r.indexPath(e.IndexDir) }

// IndexPathLabel 实体索引目录的展示路径：未覆盖时等于注册表里的 index_dir 原文，
// 覆盖时给出实际落点，让 list / doctor 的输出能说清索引到底写在哪儿。
func (r *Registry) IndexPathLabel(e *Entity) string { return r.indexLabel(e.IndexDir) }

// indexLabel 见 IndexPathLabel。
func (r *Registry) indexLabel(rel string) string {
	if rel == "" {
		return ""
	}
	if r.DataDir() == "" {
		return rel
	}
	return r.indexPath(rel)
}

// VersionDocsPath SDK 某版本文档目录的绝对路径。
func (r *Registry) VersionDocsPath(v *Version) string { return r.resolve(v.DocsDir) }

// VersionIndexPath SDK 某版本索引目录的绝对路径（受 SE_RAG_DATA_DIR 覆盖）。
func (r *Registry) VersionIndexPath(v *Version) string { return r.indexPath(v.IndexDir) }

// VersionIndexLabel 见 IndexPathLabel。
func (r *Registry) VersionIndexLabel(v *Version) string { return r.indexLabel(v.IndexDir) }

// ChunkPath 把块记录里的"文档目录内相对路径"改写成"相对技能根目录"的展示路径，
// 例如 docs/products/se9 + faq.md → docs/products/se9/faq.md。
func (r *Registry) ChunkPath(e *Entity, src string) string { return r.ChunkPathForDocs(e.DocsDir, src) }

// ChunkPathForVersion 同 ChunkPath，用于 sdk 版本（版本不是实体，文档目录挂在版本上）。
func (r *Registry) ChunkPathForVersion(v *Version, src string) string {
	return r.ChunkPathForDocs(v.DocsDir, src)
}

// ChunkPathForDocs 把一个文档目录下的相对路径改写成相对技能根目录的展示路径。
//
// docs_dir 是绝对路径（非常规用法）时退化为相对技能根计算；算不出来就原样返回。
func (r *Registry) ChunkPathForDocs(docsDir, src string) string {
	src = filepath.ToSlash(src)
	if docsDir == "" {
		return src
	}
	if !filepath.IsAbs(docsDir) {
		return path.Join(filepath.ToSlash(docsDir), src)
	}
	if rel, err := filepath.Rel(r.root, filepath.Join(filepath.FromSlash(docsDir), filepath.FromSlash(src))); err == nil {
		return filepath.ToSlash(rel)
	}
	return path.Join(filepath.ToSlash(docsDir), src)
}

// SplitIDs 解析 -entity 的取值：逗号分隔、允许空格、忽略空项。
func SplitIDs(s string) []string {
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
