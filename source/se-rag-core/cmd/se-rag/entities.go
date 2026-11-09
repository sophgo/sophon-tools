package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"se-rag-core/internal/config"
	"se-rag-core/internal/docstore"
	"se-rag-core/internal/registry"
	"se-rag-core/internal/retriever"
)

// 注册表模式的三个动作（build / query / doctor）按实体执行。
// 与路径模式的差别只有两处：docs/index 目录来自注册表、meta 的 product 写实体 id。
// 目标是单个实体且未展开关联时直接调用路径模式的同一套函数，输出与旧版逐字节一致。

// runBuildEntities 逐个目标建索引；placeholder 已在 targetEntities 里被排除或报错。
// 失败立即中止（已建好的索引保留可用），便于修好一个再继续。
//
// 目标是 sdk 的某个版本时，docs/index 取自版本本身，meta 的 product 标签写
// `<sdk-id>@<slug>`，与结果标注一致。
func runBuildEntities(base runCtx, reg *registry.Registry, ts []target) error {
	for _, t := range ts {
		rc := base
		rc.product = t.Label()
		rc.docsDir = t.DocsDir(reg)
		rc.indexDir = t.IndexDir(reg)
		fmt.Printf("==> %s: %s -> %s\n", t.Label(), docsDirLabel(reg, t), indexDirLabel(reg, t))
		if err := runBuild(rc); err != nil {
			return fmt.Errorf("%s: %w", t.Label(), err)
		}
	}
	return nil
}

// docsDirLabel 展示用的文档目录：注册表原文（相对技能根），便于对照注册表。
func docsDirLabel(reg *registry.Registry, t target) string {
	if t.Ver != nil {
		return t.Ver.DocsDir
	}
	if e, ok := reg.ByID(t.ID); ok {
		return e.DocsDir
	}
	return t.ID
}

// indexDirLabel 展示用的索引目录：实际落点（受 SE_RAG_DATA_DIR 影响）。
func indexDirLabel(reg *registry.Registry, t target) string {
	if t.Ver != nil {
		return reg.VersionIndexLabel(t.Ver)
	}
	if e, ok := reg.ByID(t.ID); ok {
		return reg.IndexPathLabel(e)
	}
	return t.ID
}

// declaredIndexDir 注册表里写的 index_dir 原文（未受 SE_RAG_DATA_DIR 覆盖）。
func declaredIndexDir(reg *registry.Registry, t target) string {
	if t.Ver != nil {
		return t.Ver.IndexDir
	}
	if e, ok := reg.ByID(t.ID); ok {
		return e.IndexDir
	}
	return ""
}

// runQueryEntities 按目标检索。
//
// 目标为单个实体（没带 -with-related 或展开后仍只有一个）且不带 -doc-type：
// 沿用 runQuery 的完整流程与输出格式——检索流程和输出与旧版逐字节一致，
// 这是本卡对单索引的硬约束。
// 目标为多个（-with-related 展开出关联实体/版本，或 -entity a,b / -all，
// 或产品默认带入了 toolkit），或带了 -doc-type（需要按块过滤 + 标注类型）：
// 走合并检索，每条结果标注 [目标]，路径改为相对技能根目录。
//
// **产品默认带入 toolkit**：`-entity` 里直接写的产品，其 `toolkits` 自动加入检索目标
// （`-no-toolkits` 关闭）。这些"经产品带入"的 toolkit 源按块 frontmatter 的
// `applies_products` 过滤；用户直接点名 toolkit 时不过滤。
func runQueryEntities(base runCtx, reg *registry.Registry, ts []target, entityFlag string,
	sdkReq registry.SDKVersionRequest) error {
	if base.query == "" {
		return fmt.Errorf("empty query")
	}
	products := explicitProducts(reg, entityFlag)
	targets, err := expandRelated(reg, entityFlag, ts, base.withRelated, sdkReq)
	if err != nil {
		return err
	}
	// 直接点名的目标（-with-related 展开前）：它们不做产品过滤。
	direct := directTargets(ts)
	// 经产品带入的 toolkit：placeholder/非 toolkit 的引用跳过并说明。
	linked, skipped := productToolkits(reg, products)
	if msg := registry.FormatSkips(skipped); msg != "" {
		fmt.Fprintf(os.Stderr, "note: %s\n", msg)
	}
	if !base.noToolkits {
		targets, _ = withProductToolkits(reg, targets, linked)
	}
	// 带进来的 toolkit（默认带入或 -with-related 带入）都要提示，并按产品过滤。
	var present []string
	for _, tk := range linked {
		if !direct[tk] && containsTarget(targets, tk) {
			present = append(present, tk)
		}
	}
	if len(present) > 0 {
		// -no-toolkits 只关掉默认带入：toolkit 是 -with-related 带回来的，
		// 或本来就已经关闭默认带入时，都不要再提这个开关。
		canDisable := !base.noToolkits && !base.withRelated
		fmt.Fprintf(os.Stderr, "note: %s\n", toolkitsNote(present, products, canDisable))
	}
	filter, err := docTypeFilter(base.docTypes)
	if err != nil {
		return err
	}
	srcs, err := entitySources(reg, targets, productSetOf(products), direct)
	if err != nil {
		return err
	}
	if len(srcs) == 1 && filter == nil && srcs[0].Products == nil {
		rc := base
		rc.product = srcs[0].Label
		rc.indexDir = srcs[0].Store.IndexDir
		rc.docsDir = targets[0].DocsDir(reg)
		return runQuery(rc)
	}
	return runMultiSourceQuery(base, srcs, filter)
}

// containsTarget 目标列表里是否已有该 id（不含版本目标，toolkit 没有版本）。
func containsTarget(ts []target, id string) bool {
	for _, t := range ts {
		if t.Ver == nil && t.ID == id {
			return true
		}
	}
	return false
}

// runMultiSourceQuery 多索引合并检索（注册表模式，也是 -doc-type 的路径）。
func runMultiSourceQuery(rc runCtx, srcs []retriever.Source, filter *retriever.ChunkFilter) error {
	rc.ensureFactories()
	rc.applyFakeMode()

	m := &retriever.MultiRetriever{Sources: srcs, Filter: filter}
	fallback := ""
	switch {
	case rc.offline:
		fallback = "offline mode (-offline)"
	case allBM25Only(srcs):
		fmt.Fprintf(os.Stderr, "note: all target indexes are bm25-only (built with -offline); query falls back to pure BM25, no text is sent out\n")
		fallback = "all indexes are bm25-only (built with build -offline)"
	default:
		cfg := config.DefaultConfig()
		p := cfg.Products[0]
		if err := applyUserKeys(&p, rc.useBuiltin, true); err != nil {
			return err
		}
		emb, err := rc.embedF(p.Embedder)
		if err != nil {
			return fmt.Errorf("embedder init: %w", err)
		}
		m.Embedder = emb
		if rr, rerr := rc.rerankF(p.Reranker); rerr == nil {
			m.Reranker = rr
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	out, err := m.Search(ctx, rc.query, rc.topN)
	if err != nil {
		return err
	}
	if fallback != "" {
		out.FallbackReason = fallback
	}
	fmt.Print(retriever.FormatMarkdown(out))
	return nil
}

// runQueryDirs 路径模式的多索引检索：没有实体信息，不标注实体、路径保持原样。
// -doc-type 同样生效（类型按块源路径的第一层子目录名推断）。
func runQueryDirs(base runCtx, dirs []string) error {
	if base.query == "" {
		return fmt.Errorf("empty query")
	}
	filter, err := pathDocTypeFilter(base.docTypes)
	if err != nil {
		return err
	}
	srcs := make([]retriever.Source, 0, len(dirs))
	for _, d := range dirs {
		srcs = append(srcs, retriever.Source{Store: &docstore.Store{IndexDir: d}, Product: base.product})
	}
	return runMultiSourceQuery(base, srcs, filter)
}

// runDoctorEntities 逐个目标检查索引，输出与路径模式同构，只是每段前加目标标题。
// 任一目标需要重建（或缺索引）即返回 fatal=true（退出码 1）。
func runDoctorEntities(base runCtx, reg *registry.Registry, ts []target) (fatal bool, err error) {
	for i, t := range ts {
		rc := base
		rc.product = t.Label()
		rc.indexDir = t.IndexDir(reg)
		rc.docsDir = t.DocsDir(reg)
		if i > 0 {
			fmt.Println()
		}
		// 实体的标题沿用 "==> entity <id>"（与旧输出一致）；版本不是实体，单独标 "sdk"。
		kind := "entity"
		if t.Ver != nil {
			kind = "sdk"
		}
		fmt.Printf("==> %s %s (%s)\n", kind, t.Label(), docsDirLabel(reg, t))
		// 索引实际落点与注册表原文不同（SE_RAG_DATA_DIR 覆盖）时点明，否则用户会去
		// 注册表的 index_dir 下找不到索引。
		if declared := declaredIndexDir(reg, t); declared != indexDirLabel(reg, t) {
			fmt.Printf("index at: %s (SE_RAG_DATA_DIR override; registry says %s)\n",
				indexDirLabel(reg, t), declared)
		}
		need, derr := runDoctor(rc)
		if derr != nil {
			// 缺索引不是致命错误：doctor 的职责就是报告它，继续检查其余目标。
			fmt.Printf("WARNING: %v\n", derr)
			fmt.Printf("  -> 建索引: se-rag build -entity %s\n", t.Label())
			fatal = true
			continue
		}
		// toolkit 额外报一行「索引里有多少块带了 applies_products」：产品查询依赖它过滤，
		// 0 说明索引是旧版建的（或这批文档都还没标注），需要重建/补 frontmatter。
		if isToolkit(reg, t) {
			reportAppliesProducts(rc.indexDir, rc.product)
		}
		if need {
			fatal = true
		}
	}
	return fatal, nil
}

// allBM25Only 目标索引是否全部为纯 BM25（离线建出的）索引；任一索引缺失时按"非 bm25"处理，
// 让 MultiRetriever 在 Open 阶段报出缺失错误。
func allBM25Only(srcs []retriever.Source) bool {
	for _, s := range srcs {
		meta, err := s.Store.ReadMeta(s.Product)
		if err != nil || !meta.BM25Only() {
			return false
		}
	}
	return true
}

// isToolkit 该目标是否是 toolkit 实体（版本目标不是）。
func isToolkit(reg *registry.Registry, t target) bool {
	if t.Ver != nil {
		return false
	}
	e, ok := reg.ByID(t.ID)
	return ok && e.Type == registry.TypeToolkit
}

// reportAppliesProducts 打印索引里带 applies_products 的块数。
//
// 产品查询靠它过滤 toolkit 文档：0 表示索引是旧版建的（或文档都还没标注），
// 此时查产品会看到全部 toolkit 文档，需要重建索引或补 frontmatter。
// 读索引失败只提示一行——索引缺失/损坏已由 runDoctor 报过，这里不重复报错。
func reportAppliesProducts(indexDir, product string) {
	loaded, err := (&docstore.Store{IndexDir: indexDir}).Open(product)
	if err != nil {
		return
	}
	declared := 0
	for _, c := range loaded.Chunks {
		if c.AppliesProductsDeclared {
			declared++
		}
	}
	line := fmt.Sprintf("applies_products: %d/%d chunks declared", declared, len(loaded.Chunks))
	if declared == 0 {
		line += " (rebuild the index after the docs declare it: product queries include all toolkit docs)"
	}
	fmt.Println(line)
}
