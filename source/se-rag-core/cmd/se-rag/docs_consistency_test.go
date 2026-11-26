package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// 本次改造要求「配置契约、超时默认值、网关顺序」在代码与文档之间一致。
// 这类一致性靠人肉维护必然漂移（历史上已经出现过 FC-first 与 12s/18s 的矛盾），
// 因此在测试里把它们钉住。

// sourceRoot 仓库内 se-rag-core 的根目录（测试从 cmd/se-rag 运行）。
func sourceRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	return root
}

func readRepoFile(t *testing.T, rel string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(sourceRoot(t), rel))
	if err != nil {
		t.Fatalf("read %s: %v", rel, err)
	}
	return string(b)
}

// 版本只有一个权威来源：release.sh 的默认 VERSION。
// 这里校验它是 2.0.0，并确保 README 的构建示例与之一致。
func TestVersionSingleSource(t *testing.T) {
	sh := readRepoFile(t, "release.sh")
	m := regexp.MustCompile(`VERSION="\$\{2:-([0-9]+\.[0-9]+\.[0-9]+)\}"`).FindStringSubmatch(sh)
	if m == nil {
		t.Fatal("release.sh: VERSION 默认值无法解析（版本权威来源缺失）")
	}
	want := m[1]
	if want != "2.0.0" {
		t.Errorf("release.sh 默认版本 = %s, want 2.0.0", want)
	}
	// 其它地方不应再各自定义版本号：README 的示例必须用同一个值。
	readme := readRepoFile(t, "README.md")
	if !strings.Contains(readme, "release.sh all "+want) {
		t.Errorf("README 的构建示例未使用 release.sh 的实际默认版本 %s", want)
	}
	// 不能残留旧版本作为「默认版本」的说明
	if strings.Contains(readme, "release.sh all 1.9.0") {
		t.Error("README 仍在宣传旧默认版本 1.9.0")
	}
}

// 网关默认顺序必须是 CF → FC。代码里有配置测试，这里再从文档侧钉一遍，
// 避免文档继续写「FC 为主」而与实现矛盾。
func TestDocsDescribeCFFirst(t *testing.T) {
	readme := readRepoFile(t, "README.md")
	if !strings.Contains(readme, "CF 优先") {
		t.Error("README 未说明默认 CF 优先")
	}
	// 旧的「FC3.0（主）」表格措辞必须消失
	if strings.Contains(readme, "FC3.0（主）") {
		t.Error("README 仍把 FC 描述为主网关（与 CF 优先实现矛盾）")
	}
	// 旧文档里 12s 与 18s 混用的矛盾说明必须消除
	if strings.Contains(readme, "转移总预算 12s") {
		t.Error("README 仍写「转移总预算 12s」，与 18s 的实现矛盾")
	}
	// 新的时长说明必须在场
	for _, want := range []string{"6s", "18s"} {
		if !strings.Contains(readme, want) {
			t.Errorf("README 缺少超时默认值 %s 的说明", want)
		}
	}
}

// TOML 示例必须明确说明它不会被加载——不能继续宣传不存在的配置支持。
func TestTOMLExampleMarkedUnsupported(t *testing.T) {
	toml := readRepoFile(t, filepath.Join("example", "config.example.toml"))
	if !strings.Contains(toml, "不会被 se-rag-core 加载") {
		t.Error("config.example.toml 未声明它不会被加载")
	}
	// TOML 示例必须把人指向真实可用的 JSON 入口
	for _, want := range []string{"SE_RAG_CONFIG", "config.example.json"} {
		if !strings.Contains(toml, want) {
			t.Errorf("config.example.toml 未指向 %q", want)
		}
	}
	// JSON 示例必须是纯 JSON（不能带注释），且覆盖 gateway 新字段。
	// 「能否被 Load 接受」由 internal/config 的 TestShippedExampleConfigLoads 兜住。
	json := readRepoFile(t, filepath.Join("example", "config.example.json"))
	for _, want := range []string{"attempt_timeout", "failover_budget", "allow_http_fallback", "primary_url", "fallback_url"} {
		if !strings.Contains(json, want) {
			t.Errorf("config.example.json 缺少 %q", want)
		}
	}
	if strings.Contains(json, "_comment") {
		t.Error("config.example.json 含 _comment：JSON 不支持注释，示例将无法直接使用（且未知字段会报错）")
	}
	// 逐行检查注释形态（不能只搜 "//"——URL 里的 https:// 也含它）
	for i, line := range strings.Split(json, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "//") || strings.HasPrefix(trimmed, "#") {
			t.Errorf("config.example.json 第 %d 行是注释：%q", i+1, trimmed)
		}
	}
}

// CLI help 必须覆盖新增的配置入口，不能只提旧的 SE_RAG_* key。
func TestUsageMentionsConfigLayers(t *testing.T) {
	out := captureStdout(t, printUsage)
	for _, want := range []string{
		"SE_RAG_CONFIG",
		"OPENAI_BASE_URL",
		"OPENAI_API_KEY",
		"SE_RAG_GATEWAY_TIMEOUT",
		"attempt_timeout",
		"优先级",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("CLI help 缺少 %q", want)
		}
	}
	if strings.Contains(out, "SE_RAG_EMBED_KEY / SE_RAG_RERANK_KEY   用户自备 key（放开内置限流）\n  SE_RAG_FAKE_EMBED") {
		t.Error("CLI help 仍是旧的 key 说明")
	}
}
