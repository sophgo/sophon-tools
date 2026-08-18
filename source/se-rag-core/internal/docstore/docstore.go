package docstore

import (
	"bytes"
	"encoding/gob"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"se-rag-core/internal/bm25"
	"se-rag-core/internal/chunker"
	"se-rag-core/internal/vector"
)

// 索引文件大小上限（防御损坏/被篡改的 index 文件全量读入导致 OOM；正常索引远小于此）。
// 向量 10 万 chunk × 1024 维 × 4B ≈ 400MB，留足余量取 2GiB；chunks/BM25 同理放宽。
const (
	maxMetaSize   = 1 << 20 // 1 MiB（meta.json，元信息）
	maxVectorSize = 2 << 30 // 2 GiB（vectors.gob）
	maxBM25Size   = 1 << 30 // 1 GiB（bm25.gob）
	maxChunksSize = 1 << 30 // 1 GiB（chunks.gob）
)

// readFileChecked 读取文件前先用 stat 校验大小上限，超限报错而非全量读入。
func readFileChecked(path string, max int64) ([]byte, error) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if st.Size() > max {
		return nil, fmt.Errorf("%s: index file too large (%d bytes > %d limit)", path, st.Size(), max)
	}
	return os.ReadFile(path)
}

// Store 索引持久化：<IndexDir>/ 下直接存储（不同知识库用不同 IndexDir，无需 product 子目录）
//
//	meta.json      指纹元信息
//	vectors.gob    vector.Index
//	bm25.gob       bm25.Index（SaveIndex 始终写入，无 BM25 时写入空索引）
//	chunks.gob     []chunker.Chunk
//	.complete      完整标记：原子保存的最后一笔，Open 以其存在作为"索引完整"判据
//
// 保存采用"全部先写临时文件 → 再 rename 替换 → 最后写完成标记"，构建中途被
// kill/断电不会留下"meta 已落盘但缺 bm25.gob"的半套索引：标记缺失时 Open 显式
// 报错并提示重建，杜绝读侧 panic。
//
// product 仅用作 Meta.Product 标签，不参与磁盘路径。
type Store struct {
	IndexDir string
}

// completeMark 索引完整标记文件名。
const completeMark = ".complete"

// ErrIncomplete 索引不完整（缺完成标记或缺失 bm25.gob），需要重新运行 se-rag build 重建。
var ErrIncomplete = errors.New("index incomplete: needs rebuild")

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

	// 1) 全部先编码到内存：任何编码失败都不触碰磁盘，旧索引保持完整可用
	mb, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return err
	}
	gi := &vector.Index{Dim: meta.Dim}
	for i, v := range vecs {
		gi.Add(v, chunkIDs[i])
	}
	vb := gi.Serialize()
	if bm == nil {
		bm = bm25.Build(nil, nil) // 无 BM25 时写入空索引，保证 bm25.gob 四件套总齐全
	}
	bb := bm.Serialize()
	cb, err := gobEncode(chunks)
	if err != nil {
		return err
	}

	// 2) 临时文件全部写成功之后再改动正式文件：任一步写失败即返回，磁盘上仍是完整旧索引
	for _, f := range [...]struct {
		name string
		data []byte
	}{
		{"meta.json", mb},
		{"vectors.gob", vb},
		{"bm25.gob", bb},
		{"chunks.gob", cb},
	} {
		if err := writeTmp(dir, f.name, f.data); err != nil {
			return err
		}
	}

	// 3) 先移除旧完成标记再 rename 替换：标记存在 ⟺ 四件套完整且属同一代。
	//    旧标记若不先移除，rename 逐文件替换期间崩溃会留下"标记仍在 + 混合代文件"的
	//    静默错误状态；移除后任何中断都只可能留下"无标记"状态，读侧走到 ErrIncomplete
	//    而非读到混合代数据。代价是保存写入窗口内（毫秒级）读侧短暂不可用，离线构建可接受。
	if err := os.Remove(filepath.Join(dir, completeMark)); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	for _, name := range []string{"meta.json", "vectors.gob", "bm25.gob", "chunks.gob"} {
		if err := renameTmp(dir, name); err != nil {
			return err
		}
	}

	// 4) 完成标记最后落盘
	return writeTmpRename(dir, completeMark, []byte("ok\n"))
}

// writeTmp 写同目录临时文件（不落正式名，供统一 rename 替换）。
func writeTmp(dir, name string, data []byte) error {
	return os.WriteFile(filepath.Join(dir, "."+name+".tmp"), data, 0o644)
}

// renameTmp 将临时文件原子替换为正式名（同一文件系统内 rename 原子）。
func renameTmp(dir, name string) error {
	return os.Rename(filepath.Join(dir, "."+name+".tmp"), filepath.Join(dir, name))
}

// writeTmpRename 原子落盘：写临时文件后 rename（完成标记等需要在最后一步原子出现时使用）。
func writeTmpRename(dir, name string, data []byte) error {
	if err := writeTmp(dir, name, data); err != nil {
		return err
	}
	return renameTmp(dir, name)
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
	if _, err := os.Stat(filepath.Join(dir, completeMark)); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			// 区分"从未构建"与"半套写入"：目录都不存在时提示先构建，而非误报索引损坏
			if _, derr := os.Stat(dir); errors.Is(derr, fs.ErrNotExist) {
				return nil, fmt.Errorf("no index at %s: run `se-rag build` first", dir)
			}
			return nil, fmt.Errorf("%w: completion mark %q missing at %s (half-written index)", ErrIncomplete, completeMark, dir)
		}
		return nil, err
	}
	l := &Loaded{ChunkByID: map[string]chunker.Chunk{}}

	mb, err := readFileChecked(filepath.Join(dir, "meta.json"), maxMetaSize)
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(mb, &l.Meta); err != nil {
		return nil, err
	}

	vdata, err := readFileChecked(filepath.Join(dir, "vectors.gob"), maxVectorSize)
	if err != nil {
		return nil, err
	}
	l.Vector, err = vector.Load(vdata)
	if err != nil {
		return nil, err
	}

	// bm25.gob 为必选文件：缺失说明索引不完整（构建中断/被外部删除），显式报错而非静默容忍
	bdata, err := readFileChecked(filepath.Join(dir, "bm25.gob"), maxBM25Size)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: bm25.gob missing at %s", ErrIncomplete, dir)
		}
		return nil, err
	}
	l.BM25, err = bm25.Load(bdata)
	if err != nil {
		return nil, err
	}

	cdata, err := readFileChecked(filepath.Join(dir, "chunks.gob"), maxChunksSize)
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

// gobDecode 带消费上限解码（防御性；外层 readFileChecked 已限文件大小）。
func gobDecode(data []byte, v any) error {
	dec := gob.NewDecoder(io.LimitReader(bytes.NewReader(data), int64(len(data))))
	return dec.Decode(v)
}
