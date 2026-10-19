package chunker

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// docs 指纹必须只随「参与分块的文件内容」变化，不能被无关文件或 mtime 干扰，
// 否则 doctor 会把索引误判为过期（或漏判）。
func TestHashDocsDeterministicAndContentSensitive(t *testing.T) {
	dir := t.TempDir()
	write := func(name, body string) {
		t.Helper()
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	hash := func() string {
		t.Helper()
		m, err := NewDefaultChunker().ChunkDirectory(dir)
		if err != nil {
			t.Fatal(err)
		}
		return HashDocs(dir, m)
	}

	write("a.md", "# SE7\n\n## 网络\n\n配置 netplan 命令。")
	write("sub/b.md", "# SE8\n\n## 集群\n\n主控与算力节点。")
	base := hash()

	// 同一内容重复计算结果必须一致
	if again := hash(); again != base {
		t.Errorf("hash not deterministic: %q vs %q", base, again)
	}

	// 新增文件 → 变化
	write("sub/c.md", "# SE9\n\n## 规格\n\nBM1688。")
	afterAdd := hash()
	if afterAdd == base {
		t.Error("adding a doc must change hash")
	}

	// 改内容 → 变化
	write("a.md", "# SE7\n\n## 网络\n\n配置 netplan 命令，新增一行。")
	afterEdit := hash()
	if afterEdit == afterAdd {
		t.Error("editing a doc must change hash")
	}

	// 只改 mtime → 不变（checkout/解包时间差不该导致误报）
	touched := filepath.Join(dir, "a.md")
	future := time.Now().Add(24 * time.Hour)
	if err := os.Chtimes(touched, future, future); err != nil {
		t.Fatal(err)
	}
	if got := hash(); got != afterEdit {
		t.Error("mtime change must not affect hash")
	}

	// 不参与分块的文件（非 .md、SEARCH_INDEX.md）→ 不变
	write("notes.txt", "与知识库无关")
	write("SEARCH_INDEX.md", "# 索引说明")
	if got := hash(); got != afterEdit {
		t.Error("non-chunked files must not affect hash")
	}
}

// 空 docs 目录也要给出稳定值（不能 panic，不能随调用变化）。
func TestHashDocsEmpty(t *testing.T) {
	dir := t.TempDir()
	m, err := NewDefaultChunker().ChunkDirectory(dir)
	if err != nil {
		t.Fatal(err)
	}
	h1 := HashDocs(dir, m)
	h2 := HashDocs(dir, m)
	if h1 != h2 {
		t.Errorf("empty docs hash unstable: %q vs %q", h1, h2)
	}
	if h1 == "" {
		t.Error("empty docs hash must not be empty string")
	}
}
