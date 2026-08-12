package docstore

import (
	"encoding/json"
	"strconv"
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
}

// Fingerprint 产品索引的完整指纹 "<provider>.<model>@<dim>"，用于供应商/模型/维度变更检测。
func (m Meta) Fingerprint() string {
	return m.EmbedderFingerprint + "@" + strconv.Itoa(m.Dim)
}

// FpName 组合 provider 与 model 的规范名（供调用方写入 EmbeddedFingerprint）。
func FpName(providerName, model string) string {
	return providerName + "." + model
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return writeFile(path, b)
}
