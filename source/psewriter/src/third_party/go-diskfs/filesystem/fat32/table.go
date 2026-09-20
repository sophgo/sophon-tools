package fat32

import (
	"encoding/binary"

	"github.com/diskfs/go-diskfs/filesystem/fat12"
)

// table is fat32's in-memory FAT table. It implements fat12.FATTable so that
// fat12.FileSystem (embedded in fat32.FileSystem) can use it for all cluster-
// chain operations.
type table struct {
	fatID          uint32
	eocMarker      uint32
	unusedMarker   uint32
	clusters       []uint32
	rootDirCluster uint32
	size           uint32
	maxCluster     uint32
	// PATCH(setf) 5: 脏区间。大卡上 FAT 本身有几 MB, 而 allocateSpace 每分配一次
	// 簇都会调 WriteFat —— 上游实现每次把整张 FAT 重写一遍 (两份副本), 一个
	// 1 GiB 的文件包在 14 GiB 卡上会因此写出十几 GB。记下被改动的最小/最大表项,
	// 只回写变化的那几个扇区。
	dirtyFrom uint32
	dirtyTo   uint32
}

// Verify the interface is satisfied at compile time.
var _ fat12.FATTable = (*table)(nil)

// ── fat12.FATTable interface ──────────────────────────────────────────────────

func (t *table) ClusterValue(n uint32) uint32 { return t.clusters[n] }

func (t *table) SetCluster(n, val uint32) {
	// PATCH(setf) 5
	if n >= uint32(len(t.clusters)) {
		return
	}
	if t.clusters[n] == val {
		return
	}
	t.clusters[n] = val
	if n < t.dirtyFrom {
		t.dirtyFrom = n
	}
	if n+1 > t.dirtyTo {
		t.dirtyTo = n + 1
	}
}

// PATCH(setf) 5: 脏表项区间 [from,to), 已按扇区边界外扩 (FAT32 每表项 4 字节)。
func (t *table) DirtyRange() (uint32, uint32, bool) {
	if t.dirtyTo <= t.dirtyFrom {
		return 0, 0, false
	}
	const perSector = 512 / 4 // 每扇区的 FAT32 表项数
	from := t.dirtyFrom - t.dirtyFrom%perSector
	to := t.dirtyTo
	if r := to % perSector; r != 0 {
		to += perSector - r
	}
	if to > t.maxCluster {
		to = t.maxCluster
	}
	if from >= to {
		return 0, 0, false
	}
	return from, to, true
}

// PATCH(setf) 5: 序列化指定表项区间
func (t *table) BytesRange(from, to uint32) []byte {
	b := make([]byte, int(to-from)*4)
	for i := from; i < to; i++ {
		binary.LittleEndian.PutUint32(b[int(i-from)*4:], t.clusters[i])
	}
	return b
}

// PATCH(setf) 5: 回写完成后清空脏标记
func (t *table) ClearDirty() {
	t.dirtyFrom = t.maxCluster + 1
	t.dirtyTo = 0
}
func (t *table) IsEOC(val uint32) bool        { return val&0xFFFFFF8 == 0xFFFFFF8 }
func (t *table) EOCMarker() uint32            { return t.eocMarker }
func (t *table) UnusedMarker() uint32         { return t.unusedMarker }
func (t *table) MaxCluster() uint32           { return t.maxCluster }
func (t *table) FATID() uint32                { return t.fatID }
func (t *table) RootDirCluster() uint32       { return t.rootDirCluster }
func (t *table) Size() uint32                 { return t.size }

// FromBytes populates the table from raw FAT bytes read from disk.
func (t *table) FromBytes(b []byte) {
	for i := uint32(2); i < t.maxCluster; i++ {
		bStart := i * 4
		val := binary.LittleEndian.Uint32(b[bStart : bStart+4])
		if val != 0 {
			t.clusters[i] = val
		}
	}
}

// Bytes serialises the table to raw FAT bytes ready to write to disk.
func (t *table) Bytes() []byte {
	b := make([]byte, t.size)
	binary.LittleEndian.PutUint32(b[0:4], t.fatID)
	binary.LittleEndian.PutUint32(b[4:8], t.eocMarker)
	for i := uint32(2); i < t.maxCluster; i++ {
		bStart := i * 4
		binary.LittleEndian.PutUint32(b[bStart:bStart+4], t.clusters[i])
	}
	return b
}

// ── internal helpers (used by fat32 tests and Create/Read) ───────────────────

// isEoc is retained for the table_internal_test.go tests.
func (t *table) isEoc(cluster uint32) bool { return t.IsEOC(cluster) }

func (t *table) equal(a *table) bool {
	if (t == nil && a != nil) || (t != nil && a == nil) {
		return false
	}
	if t == nil && a == nil {
		return true
	}
	return t.fatID == a.fatID &&
		t.eocMarker == a.eocMarker &&
		t.rootDirCluster == a.rootDirCluster &&
		t.size == a.size &&
		t.maxCluster == a.maxCluster &&
		equalUint32s(a.clusters, t.clusters)
}

// tableFromBytes constructs a fat32 table from raw FAT bytes.
func tableFromBytes(b []byte) *table {
	maxCluster := uint32(len(b) / 4)
	t := &table{
		fatID:          binary.LittleEndian.Uint32(b[0:4]),
		eocMarker:      binary.LittleEndian.Uint32(b[4:8]),
		size:           uint32(len(b)),
		clusters:       make([]uint32, maxCluster+1),
		maxCluster:     maxCluster,
		rootDirCluster: 2,
	}
	t.FromBytes(b)
	return t
}

// bytes is retained so existing code that calls t.bytes() still compiles.
// New code should prefer t.Bytes().
func (t *table) bytes() []byte { return t.Bytes() }

// equalUint32s PATCH(setf) 6: 取代 slices.Equal, 以便用 Go 1.20 (Win7 最后一个受支持的
// Go 版本) 编译 —— slices/cmp 是 Go 1.21 才进标准库的。
func equalUint32s(a, b []uint32) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
