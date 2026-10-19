package main

import (
	"flag"
	"fmt"
	"os"
)

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
	fmt.Println("Usage: se-rag <build|query|doctor> [flags]")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  build  --docs-dir <dir> -index-dir <dir>")
	fmt.Println("  query  -index-dir <dir> [-top-n N] [-offline] \"question\"")
	fmt.Println("  doctor -index-dir <dir> [--docs-dir <dir>]")
	fmt.Println()
	fmt.Println("不同知识库只需指定不同 -index-dir / --docs-dir，无需 product 维度。")
	fmt.Println()
	fmt.Println("Env:")
	fmt.Println("  SE_RAG_EMBED_KEY / SE_RAG_RERANK_KEY   用户自备 key（放开内置限流）")
	fmt.Println("  SE_RAG_FAKE_EMBED=1                    离线假 embedding（测试/离线验证）")
	fmt.Println("Flags（可写在问题文本之前或之后）:")
	fmt.Println("  -offline                               query 专用：不联网，纯 BM25 检索（不外发查询内容）")
	fmt.Println("  -builtin-key=false                     用用户 key；此时上面两个 env key 必填，缺失报错退出")
}

func dispatch(args []string) int {
	if len(args) == 0 {
		printUsage()
		return 1
	}
	sub := args[0]
	rest := args[1:]
	rc := runCtx{
		product:    metaProductLabel,
		indexDir:   defaultIndexDir(),
		topN:       8,
		useBuiltin: true,
		embedF:     realEmbed,
		rerankF:    realRerank,
	}

	switch sub {
	case "build":
		fs := flag.NewFlagSet("build", flag.ExitOnError)
		fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (default <cwd>/docs)")
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key (limits concurrency)")
		warnExtraArgs("build", parseInterspersed(fs, rest))
		if rc.docsDir == "" {
			rc.docsDir = defaultDocsDir()
		}
		if err := runBuild(rc); err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		return 0

	case "query":
		fs := flag.NewFlagSet("query", flag.ExitOnError)
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.IntVar(&rc.topN, "top-n", 8, "top N results")
		fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key")
		fs.BoolVar(&rc.offline, "offline", false, "offline: BM25 only, no network")
		fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (optional; when set, warn if the index was built from different docs)")
		pos := parseInterspersed(fs, rest)
		if len(pos) > 0 {
			rc.query = pos[0]
			warnExtraArgs("query", pos[1:])
		}
		if err := runQuery(rc); err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		return 0

	case "doctor":
		fs := flag.NewFlagSet("doctor", flag.ExitOnError)
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (optional; when set, index is also checked against docs content)")
		warnExtraArgs("doctor", parseInterspersed(fs, rest))
		fatal, err := runDoctor(rc)
		if err != nil {
			fmt.Fprintln(os.Stderr, "doctor:", err)
			return 1
		}
		if fatal {
			return 1
		}
		return 0

	default:
		printUsage()
		return 1
	}
}

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}
	os.Exit(dispatch(os.Args[1:]))
}
