package docstore

import (
	"strconv"

	"se-rag-core/internal/chunker"
)

// Meta 索引元信息，meta.json 落盘。
type Meta struct {
	Product             string `json:"product"`
	EmbedderFingerprint string `json:"embedder_fingerprint"` // "<provider>.<model>"
	Dim                 int    `json:"dim"`                  // embedding 维度
	Model               string `json:"model"`
	ChunkCount          int    `json:"chunk_count"`
	CreatedAt           string `json:"created_at"`
	BuildVersion        string `json:"build_version"`
	ChunkStrategy       string `json:"chunk_strategy,omitempty"` // chunker.StrategyVersion；旧索引为空
	// DocsHash 建索引时 docs 目录的内容指纹（文件名+内容，见 chunker.HashDocs）。
	// 索引从「打包时生成」改为「设备端按需生成」后，docs 由 deb 分发、索引留在设备上，
	// 二者可能各自演进：升级 deb 带来新 docs，而旧索引仍会被判定有效并继续使用，
	// 导致检索结果缺新文档且无任何告警。用它把索引与 docs 内容绑定。旧索引为空。
	DocsHash string `json:"docs_hash,omitempty"`
}

// StrategyStale 索引的分块策略是否落后于当前代码（旧索引没有该字段，也算落后）。
func (m Meta) StrategyStale() bool { return m.ChunkStrategy != chunker.StrategyVersion }

// DocsStale 索引是否由当前 docs 内容构建而来。want 为空表示调用方没有 docs 可比对
// （如仅做 query 的场景），此时不判定为过期；旧索引没有该字段，一律视为过期。
func (m Meta) DocsStale(want string) bool {
	if want == "" {
		return false
	}
	return m.DocsHash != want
}


// Fingerprint 产品索引的完整指纹 "<provider>.<model>@<dim>"，用于供应商/模型/维度变更检测。
func (m Meta) Fingerprint() string {
	return m.EmbedderFingerprint + "@" + strconv.Itoa(m.Dim)
}

// FpName 组合 provider 与 model 的规范名（供调用方写入 EmbeddedFingerprint）。
func FpName(providerName, model string) string {
	return providerName + "." + model
}

// FpFull 组合 provider/model/维度的完整指纹 "<provider>.<model>@<dim>"。
func FpFull(providerName, model string, dim int) string {
	return FpName(providerName, model) + "@" + strconv.Itoa(dim)
}
