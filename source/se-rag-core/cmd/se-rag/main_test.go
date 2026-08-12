package main

import (
	"os"
	"path/filepath"
	"testing"

	"se-rag-core/internal/config"
	"se-rag-core/internal/embed"
)

func TestProcessArgs(t *testing.T) {
	tt := []struct {
		args []string
		want string
	}{
		{[]string{"build", "-product", "se7", "-docs-dir", "/d", "-index-dir", "/i"}, "build"},
		{[]string{"query", "-product", "se7", "-top-n", "8", "问题"}, "query"},
		{[]string{"doctor", "-product", "se7"}, "doctor"},
	}
	for _, c := range tt {
		if got := processArgsRaw(c.args); got != c.want {
			t.Errorf("args=%v got=%q want=%q", c.args, got, c.want)
		}
	}
}

// fakeFactory 用固定 2 维 fake embedder/reranker，使 build/query/doctor 全链路可离线跑通。
func fakeFactory() runCtx {
	return runCtx{
		indexDir: filepath.Join(os.TempDir(), "se-rag-test-index"),
		product:  "se7",
		topN:     5,
		embedF:   func(config.Provider) (embed.Embedder, error) { return embed.NewFakeEmbedder(2), nil },
		rerankF:  func(config.Provider) (embed.Reranker, error) { return embed.NewFakeReranker(), nil },
	}
}

func TestCLIBuildQueryDoctorHappyPath(t *testing.T) {
	dir := t.TempDir()
	docsDir := filepath.Join(dir, "docs")
	if err := os.MkdirAll(docsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 多段文档，验证内置限流下的 build 全量路径
	doc := "# SE7\n\n## 网络\n\n配置 netplan 使能 eth0 的 dhcp4。\n\n## SDK\n\nSE7 使用 BM1684X 芯片 运行 推理 任务。\n\n## FAQ\n\nOTA 升级 用于 更新 系统 镜像。\n\n## 补充\n\nWi-Fi 模块 需 安装 驱动 补丁 后 使用。\n\n## 参考\n\n参考 微服务器 SE7 产品使用手册。\n\n## 附录\n\n本附录 提供 更多 详细 配置 步骤 与 示例。"
	if err := os.WriteFile(filepath.Join(docsDir, "a.md"), []byte(doc), 0o644); err != nil {
		t.Fatal(err)
	}

	idx := filepath.Join(dir, "idx")
	rc := fakeFactory()
	rc.docsDir = docsDir
	rc.indexDir = idx

	// build（索引直接落在 idx/ 下，无 product 子目录）
	if err := runBuild(rc); err != nil {
		t.Fatalf("build failed: %v", err)
	}
	for _, f := range []string{"meta.json", "vectors.gob", "bm25.gob", "chunks.gob"} {
		if _, err := os.Stat(filepath.Join(idx, f)); err != nil {
			t.Errorf("expected %s at %s: %v", f, idx, err)
		}
	}

	// doctor：fake 是 2 维，与 config 的 1024 维不一致 → 应报告需重建（重读不误报）
	needRebuild, err := runDoctor(rc)
	if err != nil || !needRebuild {
		t.Errorf("doctor: err=%v needRebuild=%v; want rebuild-needed when dim mismatches", err, needRebuild)
	}
}

func TestCLIBuildNoDocsFails(t *testing.T) {
	rc := fakeFactory()
	rc.docsDir = filepath.Join(t.TempDir(), "missing")
	if err := runBuild(rc); err == nil {
		t.Fatal("expected error building from empty/missing docs dir")
	}
}
