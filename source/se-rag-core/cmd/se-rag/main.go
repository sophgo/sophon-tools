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

func defaultIndexDir() string {
	if d := os.Getenv("SE_RAG_INDEX"); d != "" {
		return d
	}
	return "./rag-data"
}

func defaultDocsDir(product string) string {
	if d := os.Getenv("SE_RAG_DOCS"); d != "" {
		return d
	}
	return "./docs/" + product
}

func printUsage() {
	fmt.Println("Usage: se-rag <build|query|doctor> [flags]")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  build  -product <name> --docs-dir <dir> -index-dir <dir> [--force]")
	fmt.Println("  query  -product <name> -index-dir <dir> [-top-n N] \"question\"")
	fmt.Println("  doctor -product <name> -index-dir <dir>")
	fmt.Println()
	fmt.Println("Env:")
	fmt.Println("  SE_RAG_EMBED_KEY / SE_RAG_RERANK_KEY   用户自备 key（放开内置限流）")
	fmt.Println("  SE_RAG_FAKE_EMBED=1                    离线假 embedding（测试/离线验证）")
}

func dispatch(args []string) int {
	if len(args) == 0 {
		printUsage()
		return 1
	}
	sub := args[0]
	rest := args[1:]
	rc := runCtx{
		product:    "se7",
		indexDir:   defaultIndexDir(),
		topN:       8,
		useBuiltin: true,
		embedF:     realEmbed,
		rerankF:    realRerank,
	}

	switch sub {
	case "build":
		fs := flag.NewFlagSet("build", flag.ExitOnError)
		fs.StringVar(&rc.product, "product", "se7", "product name")
		fs.StringVar(&rc.docsDir, "docs-dir", "", "docs dir (default <cwd>/docs/<product>)")
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.BoolVar(&rc.force, "force", false, "force rebuild")
		fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key (limits concurrency)")
		fs.Parse(rest)
		if rc.docsDir == "" {
			rc.docsDir = defaultDocsDir(rc.product)
		}
		if err := runBuild(rc); err != nil {
			fmt.Fprintln(os.Stderr, "build:", err)
			return 1
		}
		return 0

	case "query":
		fs := flag.NewFlagSet("query", flag.ExitOnError)
		fs.StringVar(&rc.product, "product", "se7", "product name")
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.IntVar(&rc.topN, "top-n", 8, "top N results")
		fs.BoolVar(&rc.useBuiltin, "builtin-key", true, "use builtin key")
		fs.Parse(rest)
		rc.query = fs.Arg(0)
		if err := runQuery(rc); err != nil {
			fmt.Fprintln(os.Stderr, "query:", err)
			return 1
		}
		return 0

	case "doctor":
		fs := flag.NewFlagSet("doctor", flag.ExitOnError)
		fs.StringVar(&rc.product, "product", "se7", "product name")
		fs.StringVar(&rc.indexDir, "index-dir", defaultIndexDir(), "index dir")
		fs.Parse(rest)
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
