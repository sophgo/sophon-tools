package registry

import "strings"

// 文档类型（`-doc-type` 的取值）。
//
// v7 统一骨架里，**子目录名就是 doc_type**，根目录只有两个特例文件
// （`00-introduce.md` → overview、`image-catalog.md` → image）。运行期优先读块的
// frontmatter `doc_type`（文档自述），缺失时退回按路径推断——这样迁移期半新半旧的
// 文档也能正确分类，而完全不看内容的旧索引不受影响。
const (
	DocTypeOverview  = "overview"  // <entity>/00-introduce.md
	DocTypeImage     = "image"     // <entity>/image-catalog.md
	DocTypeSpec      = "spec"      // <entity>/spec/**
	DocTypeManual    = "manual"    // <entity>/manual/**
	DocTypeFAQ       = "faq"       // <entity>/faq/**
	DocTypeTools     = "tools"     // <entity>/tools/**
	DocTypeDatasheet = "datasheet" // <entity>/datasheet/**
	DocTypeSDK       = "sdk"       // <entity>/sdk/**
	DocTypeModule    = "module"    // docs/modules/<id>/**（本期占位，无文档）
	DocTypeOther     = "other"     // 其余（不属于任何骨架位置的文档）
)

// DocTypes 全部合法 doc_type，按展示顺序。
var DocTypes = []string{
	DocTypeOverview, DocTypeImage,
	DocTypeSpec, DocTypeManual, DocTypeFAQ, DocTypeTools, DocTypeDatasheet, DocTypeSDK,
	DocTypeModule, DocTypeOther,
}

// IsDocType 是否是合法 doc_type。
func IsDocType(s string) bool {
	for _, t := range DocTypes {
		if s == t {
			return true
		}
	}
	return false
}

// 语料层目录：docs/<layer>/<entity>/…
//
// sdks 是 schema v3 新增的一层，路径是 docs/sdks/<sdk-id>/<slug>/…——SDK 的文档挂在
// 版本上，比其它层多一级，所以它的 doc_type 不看子目录名，整层都是 sdk（见 DocType）。
var layerDirs = map[string]bool{
	"products": true,
	"chips":    true,
	"modules":  true,
	"toolkits": true,
	"sdks":     true,
}

// RootDocTypes 实体根目录下两个特例文件名 → doc_type。
var RootDocTypes = map[string]string{
	"00-introduce.md":  DocTypeOverview,
	"image-catalog.md": DocTypeImage,
}

// DocType 按块源路径推断文档类型。入参是相对技能根目录的路径
// （如 docs/products/se9/spec/se9-16-bp1-11-spec-v1.5.md）；也接受仅含 docs/ 之后部分的相对路径。
//
// 规则与统一骨架一一对应：
//
//	docs/<layer>/<entity>/00-introduce.md      → overview
//	docs/<layer>/<entity>/image-catalog.md     → image
//	docs/<layer>/<entity>/<doc_type>/<file>.md → <doc_type>（白名单内的子目录名）
//	docs/<layer>/<entity>/_meta/**             → other（元数据，不进索引）
//	docs/modules/<id>/**                       → module（本期占位，无文档）
//	docs/sdks/<sdk-id>/<slug>/**               → sdk（版本层，整层都是 SDK 文档）
//
// **不校验"该 doc_type 是否属于该实体类型"**：那需要实体类型，而这里只有路径。
// 归属校验由 `tests/test_layout.py` 按注册表的 type 逐实体检查（product 不许 datasheet、
// toolkit 只有 tools 等），Go 侧只负责把路径映射到类型，用于 -doc-type 过滤。
//
// 不认识的布局归 other，不做猜测。
func DocType(relPath string) string {
	p := strings.TrimPrefix(strings.ReplaceAll(relPath, "\\", "/"), "./")
	p = strings.TrimPrefix(p, "docs/")
	parts := strings.Split(p, "/")
	if len(parts) < 2 {
		return DocTypeOther
	}
	if parts[0] == "modules" {
		// docs/modules/<id>/** 一律算 module：模组层本期没有产物，这条规则只为
		// 兼容旧路径与将来的模组文档。
		return DocTypeModule
	}
	if parts[0] == "sdks" {
		// docs/sdks/<sdk-id>/<slug>/**：SDK 文档没有子目录分类，整层都算 sdk。
		// 少于三级（如 docs/sdks/x.md）不是合法布局，归 other。
		if len(parts) < 3 {
			return DocTypeOther
		}
		return DocTypeSDK
	}
	if !layerDirs[parts[0]] || len(parts) < 3 {
		return DocTypeOther
	}
	if len(parts) == 3 {
		if t, ok := RootDocTypes[parts[2]]; ok {
			return t
		}
		return DocTypeOther
	}
	sub := parts[2]
	if sub == "_meta" || sub == "assets" {
		return DocTypeOther
	}
	if !IsDocType(sub) || sub == DocTypeOther || sub == DocTypeOverview || sub == DocTypeImage {
		return DocTypeOther
	}
	return sub
}

// frontmatterDocType 从文档 frontmatter 里取 doc_type（缺失或为空返回空串）。
//
// 只认骨架内的必填字段，不做 YAML 完整解析：本仓库的 frontmatter 是脚本生成的
// 简单 `key: value` / 块列表，取第一行匹配即可。
func frontmatterDocType(content string) string {
	lines := strings.Split(content, "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) != "---" {
		return ""
	}
	for _, line := range lines[1:] {
		trimmed := strings.TrimSpace(line)
		if trimmed == "---" {
			return ""
		}
		if !strings.HasPrefix(trimmed, "doc_type:") {
			continue
		}
		value := strings.TrimSpace(strings.TrimPrefix(trimmed, "doc_type:"))
		if value == "" || value == "null" || value == "~" {
			return ""
		}
		return strings.Trim(value, `"'`)
	}
	return ""
}
