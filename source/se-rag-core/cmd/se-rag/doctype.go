package main

import (
	"fmt"
	"strings"

	"se-rag-core/internal/retriever"
)

// 文档类型（`-doc-type` 的取值）。
//
// 路径模式下类型按**块源路径的第一层子目录名**推断（源路径相对 `--docs-dir`），
// 根目录的文件一律算 overview——这是没有注册表时唯一可得的信息。文档自身写了
// frontmatter `doc_type` 时以文档自述为准（见 chunker.Chunk.DocType），路径推断
// 只在文档没写时兜底。
const (
	docTypeOverview  = "overview"
	docTypeImage     = "image"
	docTypeSpec      = "spec"
	docTypeManual    = "manual"
	docTypeFAQ       = "faq"
	docTypeTools     = "tools"
	docTypeDatasheet = "datasheet"
	docTypeSDK       = "sdk"
	docTypeModule    = "module"
	docTypeOther     = "other"
)

// docTypes 全部合法 doc_type，按展示顺序（用于 `-doc-type` 校验与用法说明）。
var docTypes = []string{
	docTypeOverview, docTypeImage,
	docTypeSpec, docTypeManual, docTypeFAQ, docTypeTools, docTypeDatasheet, docTypeSDK,
	docTypeModule, docTypeOther,
}

// isDocType 是否是合法 doc_type。
func isDocType(s string) bool {
	for _, t := range docTypes {
		if s == t {
			return true
		}
	}
	return false
}

// docTypeFilter 把 `-doc-type` 的取值转成检索期块过滤（路径模式：按源路径的第一层
// 子目录推断类型）。空串返回 nil（不过滤，输出与旧版逐字节一致）。
func docTypeFilter(spec string) (*retriever.ChunkFilter, error) {
	types := splitDocTypes(spec)
	if len(types) == 0 {
		return nil, nil
	}
	allowed := make(map[string]bool, len(types))
	for _, t := range types {
		if !isDocType(t) {
			return nil, fmt.Errorf("unknown doc type %q (one of %s)", t, strings.Join(docTypes, ","))
		}
		allowed[t] = true
	}
	return &retriever.ChunkFilter{Allowed: allowed, DocTypeOf: docTypeFromPath}, nil
}

// splitDocTypes 拆分逗号分隔的 doc_type（去空白、丢掉空项）。
func splitDocTypes(spec string) []string {
	var out []string
	for _, p := range strings.Split(spec, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// docTypeFromPath 按源路径推断 doc_type。入参是相对 `--docs-dir` 的路径
// （如 `datasheet/spec.md`、`manuals/guide.md`）；根目录下的文件算 overview。
//
// 只认第一层子目录名，且必须是合法 doc_type；`_meta/`、`assets/` 等元数据目录
// 归 other。不认识的布局也归 other，不做猜测——这与注册表模式按技能根相对路径
// 推断的口径一致（产品目录 = 这里的 docs-dir）。
func docTypeFromPath(relPath string) string {
	p := strings.TrimPrefix(strings.ReplaceAll(relPath, "\\", "/"), "./")
	p = strings.TrimPrefix(p, "/")
	parts := strings.Split(p, "/")
	if len(parts) < 2 { // 根目录文件（没有子目录）
		return docTypeOverview
	}
	sub := parts[0]
	if sub == "_meta" || sub == "assets" {
		return docTypeOther
	}
	if !isDocType(sub) || sub == docTypeOther || sub == docTypeOverview || sub == docTypeImage {
		return docTypeOther
	}
	return sub
}
