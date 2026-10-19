package chunker

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// HashDocs 计算 docs 目录的内容指纹，用于把索引与文档库内容绑定。
//
// 索引从「打包时生成」改为「设备端按需生成」后，docs 由 deb 分发而索引留在设备上，
// 两者可能各自演进：升级 deb 带来新 docs，旧索引却仍被判为有效继续使用，检索结果
// 缺新文档且没有任何告警。构建时把该指纹写入 meta.docs_hash，doctor/query 比对即可
// 发现「docs 变了但索引没重建」。
//
// 参与哈希的文件集直接取自 chunkMap 的键，因此与真正参与分块的文件集完全一致：
// 非 .md、SEARCH_INDEX.md、以及切不出任何块的文件都不会影响指纹，避免把
// 「不参与分块的文件变了」误判成索引过期。
//
// 哈希内容 = 排序后的「相对路径 + 文件字节」，因此改文件名、改内容、增删文件都会变；
// 只改 mtime 不会变（避免 checkout / 解包时间差造成误报）。
func HashDocs(docsDir string, chunkMap map[string][]Chunk) string {
	rels := make([]string, 0, len(chunkMap))
	for rel := range chunkMap {
		rels = append(rels, rel)
	}
	sort.Strings(rels)

	h := sha256.New()
	for _, rel := range rels {
		// 统一成正斜杠：同一份 docs 在 Windows/Linux 下产出一致指纹。
		slash := filepath.ToSlash(rel)
		// 路径与内容都进哈希，并带长度前缀避免「路径+内容」边界歧义。
		fmt.Fprintf(h, "%d:%s\n", len(slash), slash)
		b, err := os.ReadFile(filepath.Join(docsDir, rel))
		if err != nil {
			// 读取失败不应让整个 build 失败：用错误标记参与哈希，使指纹必然与
			// 「正常读取」不同，从而在 doctor 侧表现为需要重建。
			fmt.Fprintf(h, "err:%v\n", err)
			continue
		}
		fmt.Fprintf(h, "%d:", len(b))
		h.Write(b)
		h.Write([]byte("\n"))
	}
	return hex.EncodeToString(h.Sum(nil))
}
