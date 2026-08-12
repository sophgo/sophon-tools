package docstore

import (
	"bytes"
	"encoding/gob"
	"encoding/json"
	"os"
	"path/filepath"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/vector"
)

// Store 索引持久化：<IndexDir>/ 下直接存储（不同知识库用不同 IndexDir，无需 product 子目录）
//
//	meta.json      指纹元信息
//	vectors.gob    vector.Index
//	bm25.gob       bm25.Index
//	chunks.gob     []chunker.Chunk
//
// product 仅用作 Meta.Product 标签，不参与磁盘路径。
type Store struct {
	IndexDir string
}

func (s *Store) productDir(product string) string {
	_ = product // product 仅标签，不用于路径
	return s.IndexDir
}

// IndexPath 返回索引目录（绝对展示路径）。
func (s *Store) IndexPath() string {
	return s.IndexDir
}

// BuildMeta 构造 Meta。providerName+model 例如 ("siliconflow","BAAI/bge-m3")。
func (s *Store) BuildMeta(product, providerName, model string, dim int, chunks []chunker.Chunk) Meta {
	return Meta{
		Product:             product,
		EmbedderFingerprint: FpName(providerName, model),
		Dim:                 dim,
		Model:               model,
		ChunkCount:          len(chunks),
		BuildVersion:        "1.0",
	}
}

func (s *Store) SaveIndex(product string, meta Meta, vecs [][]float32, chunkIDs []string, bm *bm25.Index, chunks []chunker.Chunk) error {
	dir := s.productDir(product)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(dir, "meta.json"), meta); err != nil {
		return err
	}

	gi := &vector.Index{Dim: meta.Dim}
	for i, v := range vecs {
		gi.Add(v, chunkIDs[i])
	}
	if err := os.WriteFile(filepath.Join(dir, "vectors.gob"), gi.Serialize(), 0o644); err != nil {
		return err
	}

	if bm != nil {
		if err := os.WriteFile(filepath.Join(dir, "bm25.gob"), bm.Serialize(), 0o644); err != nil {
			return err
		}
	}

	cb, err := gobEncode(chunks)
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "chunks.gob"), cb, 0o644)
}

type Loaded struct {
	Meta      Meta
	Vector    *vector.Index
	BM25      *bm25.Index
	Chunks    []chunker.Chunk
	ChunkByID map[string]chunker.Chunk
}

func (s *Store) Open(product string) (*Loaded, error) {
	dir := s.productDir(product)
	l := &Loaded{ChunkByID: map[string]chunker.Chunk{}}

	mb, err := os.ReadFile(filepath.Join(dir, "meta.json"))
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(mb, &l.Meta); err != nil {
		return nil, err
	}

	vdata, err := os.ReadFile(filepath.Join(dir, "vectors.gob"))
	if err != nil {
		return nil, err
	}
	l.Vector, err = vector.Load(vdata)
	if err != nil {
		return nil, err
	}

	if bdata, rerr := os.ReadFile(filepath.Join(dir, "bm25.gob")); rerr == nil {
		l.BM25, err = bm25.Load(bdata)
		if err != nil {
			return nil, err
		}
	}

	cdata, err := os.ReadFile(filepath.Join(dir, "chunks.gob"))
	if err != nil {
		return nil, err
	}
	if err := gobDecode(cdata, &l.Chunks); err != nil {
		return nil, err
	}
	for _, c := range l.Chunks {
		l.ChunkByID[c.ChunkID] = c
	}
	return l, nil
}

// FingerprintProduct 读取指定产品索引的指纹字符串。
func (s *Store) FingerprintProduct(product string) (string, error) {
	mb, err := os.ReadFile(filepath.Join(s.productDir(product), "meta.json"))
	if err != nil {
		return "", err
	}
	var m Meta
	if err := json.Unmarshal(mb, &m); err != nil {
		return "", err
	}
	return m.Fingerprint(), nil
}

// ReadMeta 读取产品索引的 Meta。
func (s *Store) ReadMeta(product string) (*Meta, error) {
	mb, err := os.ReadFile(filepath.Join(s.productDir(product), "meta.json"))
	if err != nil {
		return nil, err
	}
	var m Meta
	if err := json.Unmarshal(mb, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

func (s *Store) IndexExists(product string) bool {
	_, err := os.Stat(filepath.Join(s.productDir(product), "meta.json"))
	return err == nil
}

func gobEncode(v any) ([]byte, error) {
	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(v); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func gobDecode(data []byte, v any) error {
	return gob.NewDecoder(bytes.NewReader(data)).Decode(v)
}

func writeFile(path string, data []byte) error {
	return os.WriteFile(path, data, 0o644)
}
