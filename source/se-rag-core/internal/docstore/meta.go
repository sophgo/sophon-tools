package docstore

import (
	"strconv"

	"se-rag-core/internal/chunker"
)

// 索引检索模式（meta.json 的 search_mode）。旧索引没有该字段，见 EffectiveSearchMode。
const (
	// SearchModeHybrid 向量 + BM25 混合检索：索引含真实 embedding 向量，查询需要 embedding。
	SearchModeHybrid = "hybrid"
	// SearchModeBM25 纯 BM25：`build -offline` 产出，索引不含向量（Dim=0），
	// 建索引与查询都不外发任何文本，也不需要 key。
	SearchModeBM25 = "bm25"
	// FpBM25Only 纯 BM25 索引的 embedder_fingerprint 取值。明确表达"没有 embedding 模型"，
	// 不伪装成任何真实指纹（否则 doctor 会拿它跟当前配置的 bge-m3 比对并误报重建）。
	FpBM25Only = "bm25"
)

// Meta 索引元信息，meta.json 落盘。
type Meta struct {
	Product             string `json:"product"`
	EmbedderFingerprint string `json:"embedder_fingerprint"` // "<provider>.<model>"；纯 BM25 索引为 "bm25"
	Dim                 int    `json:"dim"`                  // embedding 维度；纯 BM25 索引为 0
	Model               string `json:"model"`
	ChunkCount          int    `json:"chunk_count"`
	CreatedAt           string `json:"created_at"`
	BuildVersion        string `json:"build_version"`
	ChunkStrategy       string `json:"chunk_strategy,omitempty"` // chunker.StrategyVersion；旧索引为空
	SearchMode          string `json:"search_mode,omitempty"`    // hybrid / bm25；旧索引为空（按 dim 推断）
	// DocsHash 建索引时 docs 目录的内容指纹（文件名+内容，见 chunker.HashDocs）。
	// 索引从「打包时生成」改为「设备端按需生成」后，docs 由 deb 分发、索引留在设备上，
	// 二者可能各自演进：升级 deb 带来新 docs，而旧索引仍会被判定有效并继续使用，
	// 导致检索结果缺新文档且无任何告警。用它把索引与 docs 内容绑定。旧索引为空。
	DocsHash string `json:"docs_hash,omitempty"`
}

// EffectiveSearchMode 索引实际可用的检索模式。
//
// search_mode 有值就以它为准；旧索引（无该字段）按维度推断：dim>0 说明存的是真实向量，
// 按 hybrid 处理（指纹缺失仍交给 doctor 报"无法验证向量空间"），dim==0 只能是 bm25。
func (m Meta) EffectiveSearchMode() string {
	switch m.SearchMode {
	case SearchModeBM25, SearchModeHybrid:
		return m.SearchMode
	}
	if m.Dim > 0 {
		return SearchModeHybrid
	}
	return SearchModeBM25
}

// BM25Only 索引是否只支持纯 BM25（无向量可检索）。
func (m Meta) BM25Only() bool { return m.EffectiveSearchMode() == SearchModeBM25 }

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
// 纯 BM25 索引为 "bm25@0"。
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
