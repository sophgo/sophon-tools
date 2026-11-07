package main

import (
	"flag"
	"fmt"
	"os"
	"strings"

	"se-rag-core/internal/registry"
)

// Version 构建版本，由 release.sh 通过 -ldflags -X 注入。
// 用显式变量而非依赖 Go 自动的 vcs.revision：后者在「有未提交改动」时
// 仍会写入上一个提交号并置 modified=true，容易被误读成「这个版本不包含新代码」
// （实测报告就这样把 1.5.2 的改动判成了 1.5.1 的提交）。
var Version = "dev"

// processArgsRaw 提取子命令名（独立可测）
func processArgsRaw(args []string) string {
	if len(args) == 0 {
		return ""
	}
	return args[0]
}

// 索引/文档库不再按 product 分隔 —— 不同知识库用不同 -index-dir 即可。
// product 仅作为 meta.json 里的元数据标签，不参与磁盘路径。
const metaProductLabel = "default"

func defaultIndexDir() string {
	if d := os.Getenv("SE_RAG_INDEX"); d != "" {
		return d
	}
	return "./rag-data"
}

func defaultDocsDir() string {
	if d := os.Getenv("SE_RAG_DOCS"); d != "" {
		return d
	}
	return "./docs"
}

// multiFlag 可重复传入、也可逗号分隔的多值 flag（`-index-dir a -index-dir b,c`）。
type multiFlag struct{ vals []string }

func (m *multiFlag) String() string { return strings.Join(m.vals, ",") }

func (m *multiFlag) Set(v string) error {
	for _, p := range strings.Split(v, ",") {
		if p = strings.TrimSpace(p); p != "" {
			m.vals = append(m.vals, p)
		}
	}
	return nil
}

// parseInterspersed 解析 flag，允许 flag 出现在位置参数之后。
// 标准库 flag 遇到第一个非 flag 参数就停止解析，导致 `query -index-dir x "问题" -builtin-key=false`
// 里的 -builtin-key=false 被静默忽略（仍走内置 key）。这里逐段解析并收集位置参数；
// `--` 之后的内容原样当作位置参数。
func parseInterspersed(fs *flag.FlagSet, args []string) []string {
	var tail []string
	for i, a := range args {
		if a == "--" {
			tail = args[i+1:]
			args = args[:i]
			break
		}
	}
	var pos []string
	for {
		fs.Parse(args) // flag.ExitOnError：解析失败直接退出
		rest := fs.Args()
		if len(rest) == 0 {
			break
		}
		pos = append(pos, rest[0])
		args = rest[1:]
	}
	return append(pos, tail...)
}

func warnExtraArgs(cmd string, extra []string) {
	if len(extra) > 0 {
		fmt.Fprintf(os.Stderr, "%s: ignored extra args: %q\n", cmd, extra)
	}
}

func printUsage() {
	fmt.Println("Usage: se-rag <list|resolve|build|query|doctor> [flags]")
	fmt.Println()
	fmt.Println("注册表模式（-registry 默认 ./registry.json）：")
	fmt.Println("  list    [-registry f] [-json]")
	fmt.Println("  resolve [-registry f] [-json] [-sdk-version v] \"文本\"")
	fmt.Println("  build   -entity a[,b] | -all [-offline] [-sdk-version v]")
	fmt.Println("  query   -entity a[,b] | -all [-with-related] [-doc-type t[,t]] [-top-n N] [-offline] [-sdk-version v] \"问题\"")
	fmt.Println("  doctor  -entity a[,b] | -all [-sdk-version v]")
	fmt.Println("  -entity 接受实体 id（产品/模组/芯片/sdk/工具）、<sdk>@<slug>，或 sdk id（按 -sdk-version 选版本）")
	fmt.Println("          规格（如 SE9 8）不是实体，用 -entity se9")
	fmt.Println("  -sdk-version  latest（默认，只查最新版本）| all（全部版本）| <slug>（指定版本）")
	fmt.Println()
	fmt.Println("路径模式（旧用法，继续可用）：")
	fmt.Println("  build  --docs-dir <dir> -index-dir <dir> [-offline]")
	fmt.Println("  query  -index-dir <dir> [-top-n N] [-offline] [-doc-type t[,t]] \"question\"")
	fmt.Println("         -index-dir 可重复传入或用逗号分隔多个目录（多索引合并检索）")
	fmt.Println("  doctor -index-dir <dir> [--docs-dir <dir>]")
	fmt.Println()
	fmt.Printf("Version: %s\n", Version)
	fmt.Println()
	fmt.Println("Env:")
	fmt.Println("  SE_RAG_DATA_DIR=<dir>                  索引改落到 <dir>/<index_dir 末级名>（技能目录只读/多 agent 共享时用）")
	fmt.Println("  SE_RAG_EMBED_KEY / SE_RAG_RERANK_KEY   用户自备 key（放开内置限流）")
	fmt.Println("  SE_RAG_FAKE_EMBED=1                    离线假 embedding（测试/离线验证）")
	fmt.Println("  SE_RAG_FAILOVER_BUDGET=18s             网关故障转移总预算（Go duration）")
	fmt.Println("  SE_RAG_ALLOW_HTTP_FALLBACK=0           禁用明文 HTTP 兜底（保传输机密性）")
	fmt.Println("  SE_RAG_FALLBACK_URL / SE_RAG_GATEWAY_URL  覆盖备/主网关地址（空=单跳）")
	fmt.Println("  SE_RAG_STATE_DIR=<dir>                 熔断与粘滞状态目录（默认用户缓存目录）")
	fmt.Println("  SE_RAG_STATE_TTL=24h                   状态标记有效期，超过即重新生成")
	fmt.Println("Flags（可写在问题文本之前或之后）:")
	fmt.Println("  -registry <f>                          注册表路径（默认 ./registry.json）")
	fmt.Println("  -entity a[,b] / -all                   目标实体（注册表模式）")
	fmt.Println("  -sdk-version latest|all|<slug>         sdk 的版本选择（默认 latest）")
	fmt.Println("  -with-related                          query 时展开关联实体（产品 → 模组 → 芯片 → sdk 版本 → toolkits）")
	fmt.Println("  -doc-type t[,t]                        query 时按块的文档类型过滤：" + strings.Join(registry.DocTypes, ","))
	fmt.Println("                                           类型取文档 frontmatter 的 doc_type，缺失时按路径推断：")
	fmt.Println("                                           注册表模式看技能根相对路径，路径模式看相对 --docs-dir 的")
	fmt.Println("                                           第一层子目录名，根目录文件为 overview")
	fmt.Println("  -offline                               build/query：纯 BM25，不联网、不要 key")
	fmt.Println("                                           build -offline 建 bm25-only 索引（dim=0，无向量）")
	fmt.Println("                                           query -offline 对该索引做纯 BM25 检索")
	fmt.Println("  -builtin-key=false                     用用户 key；此时上面两个 env key 必填，缺失报错退出")
}

// dispatch 解析子命令并执行。返回值即进程退出码。
//
// 注册表模式与路径模式共存：
//   - build/query/doctor 出现 -entity 或 -all 时走注册表，否则沿用旧的路径模式；
//   - list/resolve 只有注册表模式，-registry 缺文件即报错。
func dispatch(args []string) int {
	if len(args) == 0 {
		printUsage()
		return 1
	}
	sub := args[0]
	rest := args[1:]

	// --help / -h：打印用法并以 0 退出（与"没有子命令"的 1 区分开）。
	switch sub {
	case "-h", "--help", "help":
		printUsage()
		return 0
	}

	switch sub {
	case "list":
		return dispatchList(rest)
	case "resolve":
		return dispatchResolve(rest)
	case "build":
		return dispatchBuild(rest)
	case "query":
		return dispatchQuery(rest)
	case "doctor":
		return dispatchDoctor(rest)
	default:
		printUsage()
		return 1
	}
}

// newRunCtx 默认运行上下文（路径模式的既有缺省值）。
func newRunCtx() runCtx {
	return runCtx{
		product:    metaProductLabel,
		indexDir:   defaultIndexDir(),
		topN:       8,
		useBuiltin: true,
		embedF:     realEmbed,
		rerankF:    realRerank,
	}
}

func dispatchList(rest []string) int {
	fs := flag.NewFlagSet("list", flag.ExitOnError)
	regPath := fs.String("registry", defaultRegistryPath, "registry file")
	asJSON := fs.Bool("json", false, "output JSON")
	warnExtraArgs("list", parseInterspersed(fs, rest))
	reg, err := loadRegistry(*regPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "list:", err)
		return 1
	}
	if err := runList(reg, *asJSON); err != nil {
		fmt.Fprintln(os.Stderr, "list:", err)
		return 1
	}
	return 0
}

func dispatchResolve(rest []string) int {
	fs := flag.NewFlagSet("resolve", flag.ExitOnError)
	regPath := fs.String("registry", defaultRegistryPath, "registry file")
	asJSON := fs.Bool("json", false, "output JSON")
	sdkVersion := fs.String("sdk-version", "", "sdk version: latest|all|<slug>")
	pos := parseInterspersed(fs, rest)
	text := ""
	if len(pos) > 0 {
		text = pos[0]
		warnExtraArgs("resolve", pos[1:])
	}
	sdkReq, err := registry.ParseSDKVersion(*sdkVersion)
	if err != nil {
		fmt.Fprintln(os.Stderr, "resolve:", err)
		return 1
	}
	reg, err := loadRegistry(*regPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "resolve:", err)
		return 1
	}
	if err := runResolveWith(reg, text, *asJSON, sdkReq); err != nil {
		fmt.Fprintln(os.Stderr, "resolve:", err)
		return 1
	}
	return 0
}

func dispatchBuild(rest []string) int {
	rc := newRunCtx()
	fs := flag.NewFlagSet("build", flag.ExitOnError)
	fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (default <cwd>/docs)")
	fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
	fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key (limits concurrency)")
	fs.BoolVar(&rc.offline, "offline", false, "offline: build BM25-only index, no embedder, no key, no network")
	regPath := fs.String("registry", defaultRegistryPath, "registry file")
	entity := fs.String("entity", "", "entity id(s), comma separated; <sdk>@<slug> for one sdk version")
	all := fs.Bool("all", false, "all ready entities from the registry (every sdk version)")
	sdkVersion := fs.String("sdk-version", "", "sdk version: latest|all|<slug>")
	warnExtraArgs("build", parseInterspersed(fs, rest))

	if strings.TrimSpace(*entity) != "" || *all {
		sdkReq, err := registry.ParseSDKVersion(*sdkVersion)
		if err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		reg, err := loadRegistry(*regPath)
		if err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		ts, err := targetEntities(reg, *entity, *all, sdkReq)
		if err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		if err := runBuildEntities(rc, reg, ts); err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		return 0
	}
	if rc.docsDir == "" {
		rc.docsDir = defaultDocsDir()
	}
	if err := runBuild(rc); err != nil {
		fmt.Fprintln(os.Stderr, "build:", err)
		return 1
	}
	return 0
}

func dispatchQuery(rest []string) int {
	rc := newRunCtx()
	fs := flag.NewFlagSet("query", flag.ExitOnError)
	var indexDirs multiFlag
	fs.Var(&indexDirs, "index-dir", "index dir (repeatable or comma separated)")
	fs.IntVar(&rc.topN, "top-n", 8, "top N results")
	fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key")
	fs.BoolVar(&rc.offline, "offline", false, "offline: BM25 only, no network")
	fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (optional; when set, warn if the index was built from different docs)")
	regPath := fs.String("registry", defaultRegistryPath, "registry file")
	entity := fs.String("entity", "", "entity id(s), comma separated (specs are attributes, not entities)")
	all := fs.Bool("all", false, "all ready entities from the registry (every sdk version)")
	fs.BoolVar(&rc.withRelated, "with-related", false, "expand related entities (product → modules → chips → sdk versions → toolkits)")
	fs.StringVar(&rc.docTypes, "doc-type", "", "filter results by doc type (registry mode only): "+strings.Join(registry.DocTypes, ","))
	sdkVersion := fs.String("sdk-version", "", "sdk version: latest|all|<slug>")
	pos := parseInterspersed(fs, rest)
	if len(pos) > 0 {
		rc.query = pos[0]
		warnExtraArgs("query", pos[1:])
	}

	if strings.TrimSpace(*entity) != "" || *all {
		sdkReq, err := registry.ParseSDKVersion(*sdkVersion)
		if err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		reg, err := loadRegistry(*regPath)
		if err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		ts, err := targetEntities(reg, *entity, *all, sdkReq)
		if err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		if err := runQueryEntities(rc, reg, ts, *entity, sdkReq); err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		return 0
	}

	// 路径模式：多个 -index-dir（重复或逗号分隔）走多索引合并；单个目录保持原有行为。
	switch len(indexDirs.vals) {
	case 0:
		// 未指定：沿用默认索引目录（含 SE_RAG_INDEX）
	case 1:
		rc.indexDir = indexDirs.vals[0]
	default:
		if err := runQueryDirs(rc, indexDirs.vals); err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		return 0
	}
	if err := runQuery(rc); err != nil {
		fmt.Fprintln(os.Stderr, "query:", err)
		return 1
	}
	return 0
}

func dispatchDoctor(rest []string) int {
	rc := newRunCtx()
	fs := flag.NewFlagSet("doctor", flag.ExitOnError)
	fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
	fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (optional; when set, index is also checked against docs content)")
	regPath := fs.String("registry", defaultRegistryPath, "registry file")
	entity := fs.String("entity", "", "entity id(s), comma separated")
	all := fs.Bool("all", false, "all ready entities from the registry (every sdk version)")
	sdkVersion := fs.String("sdk-version", "", "sdk version: latest|all|<slug>")
	warnExtraArgs("doctor", parseInterspersed(fs, rest))

	if strings.TrimSpace(*entity) != "" || *all {
		sdkReq, err := registry.ParseSDKVersion(*sdkVersion)
		if err != nil {
			fmt.Fprintln(os.Stderr, "doctor:", err)
			return 1
		}
		reg, err := loadRegistry(*regPath)
		if err != nil {
			fmt.Fprintln(os.Stderr, "doctor:", err)
			return 1
		}
		ts, err := targetEntities(reg, *entity, *all, sdkReq)
		if err != nil {
			fmt.Fprintln(os.Stderr, "doctor:", err)
			return 1
		}
		fatal, err := runDoctorEntities(rc, reg, ts)
		if err != nil {
			fmt.Fprintln(os.Stderr, "doctor:", err)
			return 1
		}
		if fatal {
			return 1
		}
		return 0
	}

	fatal, err := runDoctor(rc)
	if err != nil {
		fmt.Fprintln(os.Stderr, "doctor:", err)
		return 1
	}
	if fatal {
		return 1
	}
	return 0
}

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}
	os.Exit(dispatch(os.Args[1:]))
}
