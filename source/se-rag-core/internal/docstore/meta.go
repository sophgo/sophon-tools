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
}

// StrategyStale 索引的分块策略是否落后于当前代码（旧索引没有该字段，也算落后）。
func (m Meta) StrategyStale() bool { return m.ChunkStrategy != chunker.StrategyVersion }

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
