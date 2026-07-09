// archive.go — ArchiveWriter: 二进制追加写入、文件头读写、分段轮转、淘汰。
package metrics

import (
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"bmssm/logger"
)

const (
	currentFileName  = "metrics.current"
	defaultMaxSizeMB = 100
	defaultChanSize  = 16
	maxSegmentBytes  = 5 * 1024 * 1024 // 5MB
	rotateAfter      = 1 * time.Hour
)

// writeHeader 将文件头写入 f（4096 字节）。
// firstTS: 首条记录的时间戳（此文件第一轮采集 unix ts）。
func writeHeader(f *os.File, firstTS uint32) error {
	fields := ArchFields()
	// 构建 field_names: NUL 分隔
	var namesBuf bytes.Buffer
	for i, name := range fields {
		if i > 0 {
			namesBuf.WriteByte(0)
		}
		namesBuf.WriteString(name)
	}
	namesBytes := namesBuf.Bytes()
	namesLen := len(namesBytes)
	if namesLen+18 > headerSize {
		return fmt.Errorf("field_names too long: %d bytes (max %d)", namesLen, headerSize-18)
	}

	hdr := ArchFileHeader{
		Version:        CurrentVersion,
		RecordSize:     uint16(ArchRecordSize()),
		FieldCount:     uint16(len(fields)),
		FieldNamesLen:  uint16(namesLen),
		FirstTimestamp: firstTS,
	}
	copy(hdr.Magic[:], headerMagic)

	// 写入固定前缀 (18 字节)
	if err := binary.Write(f, binary.LittleEndian, hdr); err != nil {
		return fmt.Errorf("write header prefix: %w", err)
	}
	// 写入 field_names
	if _, err := f.Write(namesBytes); err != nil {
		return fmt.Errorf("write field_names: %w", err)
	}
	// padding 补齐到 headerSize
	written := 18 + namesLen
	padding := make([]byte, headerSize-written)
	if _, err := f.Write(padding); err != nil {
		return fmt.Errorf("write header padding: %w", err)
	}
	return nil
}

// readHeader 从 f 读取文件头，返回 field_names 列表。
// 失败返回错误（调用方应跳过损坏文件）。
func readHeader(f *os.File) (*ArchFileHeader, []string, error) {
	var hdr ArchFileHeader
	if err := binary.Read(f, binary.LittleEndian, &hdr); err != nil {
		return nil, nil, fmt.Errorf("read header: %w", err)
	}
	if string(hdr.Magic[:]) != headerMagic {
		return nil, nil, errors.New("bad magic")
	}
	// 读 field_names
	namesBytes := make([]byte, hdr.FieldNamesLen)
	if _, err := io.ReadFull(f, namesBytes); err != nil {
		return nil, nil, fmt.Errorf("read field_names: %w", err)
	}
	// 定位到 headerSize 后
	if _, err := f.Seek(int64(headerSize), io.SeekStart); err != nil {
		return nil, nil, fmt.Errorf("seek past header: %w", err)
	}

	parts := strings.Split(string(namesBytes), "\x00")
	fields := make([]string, 0, len(parts))
	for _, p := range parts {
		if p != "" {
			fields = append(fields, p)
		}
	}
	return &hdr, fields, nil
}

// truncateToRecord 将 f 截断到完整 record 边界：
// newSize = headerSize + floor((size - headerSize) / recordSize) * recordSize
// 用于启动/崩溃恢复，丢弃尾部的半条 record。
func truncateToRecord(f *os.File, recordSize int) error {
	info, err := f.Stat()
	if err != nil {
		return fmt.Errorf("stat for truncate: %w", err)
	}
	size := info.Size()
	if size <= int64(headerSize) {
		// 文件只有头（或更小），保留头
		return nil
	}
	dataLen := size - int64(headerSize)
	completeRecords := dataLen / int64(recordSize)
	newSize := int64(headerSize) + completeRecords*int64(recordSize)
	if newSize != size {
		if err := f.Truncate(newSize); err != nil {
			return fmt.Errorf("truncate %d -> %d: %w", size, newSize, err)
		}
	}
	return nil
}

// parseSegFileName 解析分段文件名 "2026-07-08-14.mtrc" 或 ".gz" -> 提取时间串用于排序。
// 返回可用于字符串比较的排序键。非标准文件名排在最后。
func parseSegFileName(name string) string {
	// 去掉 .mtrc / .mtrc.gz / .mtrc_broken
	if strings.HasSuffix(name, ".gz") {
		name = name[:len(name)-3]
	}
	if strings.HasSuffix(name, ".mtrc") {
		name = name[:len(name)-5]
	}
	return name
}

// ArchiveWriter 异步写入存档指标。
// 采集 goroutine 调 Submit (非阻塞)，内部 writer goroutine 串行写磁盘。
type ArchiveWriter struct {
	ch      chan archiveJob
	done    chan struct{}
	dropped int64
	mu      sync.Mutex // 保护 dropped 计数
	started bool

	// writer goroutine 状态 (单 goroutine, 无竞态)
	dir        string
	maxSizeMB  int
	curFile    *os.File
	curCreated time.Time
}

type archiveJob struct {
	ts  uint32
	rec ArchRecord
}

// NewArchiveWriter 创建未启动的 writer。
func NewArchiveWriter() *ArchiveWriter {
	return &ArchiveWriter{}
}

// Start 启动 writer goroutine，初始化存档目录。
// path: 存档目录 (如 /var/lib/bmssm/metrics)
// maxSizeMB: 淘汰上限 MB
// chanSize: channel 缓冲大小 (16 合理)
func (w *ArchiveWriter) Start(path string, maxSizeMB int, chanSize int) {
	if maxSizeMB <= 0 {
		maxSizeMB = defaultMaxSizeMB
	}
	if chanSize <= 0 {
		chanSize = defaultChanSize
	}
	w.dir = path
	w.maxSizeMB = maxSizeMB
	w.ch = make(chan archiveJob, chanSize)
	w.done = make(chan struct{})
	w.started = true

	// 创建目录
	if err := os.MkdirAll(path, 0755); err != nil {
		logger.Error("archive: mkdir %s failed: %v", path, err)
	}

	// 启动时恢复：截断 metrics.current，处理残留
	w.recover()

	go w.loop()
	logger.Info("archive writer started, dir=%s maxSize=%dMB", path, maxSizeMB)
}

// Submit 非阻塞投递一条记录到存档队列。
// channel 满时丢弃 (dropped++)，不阻塞调用方。
func (w *ArchiveWriter) Submit(ts uint32, rec *ArchRecord) {
	if !w.started || w.ch == nil {
		return
	}
	select {
	case w.ch <- archiveJob{ts: ts, rec: *rec}:
	default:
		w.mu.Lock()
		w.dropped++
		w.mu.Unlock()
	}
}

// Dir 返回存档目录路径（供 MVC controller 查询）。
func (w *ArchiveWriter) Dir() string { return w.dir }

// Dropped 返回累计丢弃的采样数。
func (w *ArchiveWriter) Dropped() int64 {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.dropped
}

// loop writer goroutine: 消费 channel → append → fsync → 检查轮转/淘汰。
func (w *ArchiveWriter) loop() {
	for {
		select {
		case job, ok := <-w.ch:
			if !ok {
				return
			}
			w.appendAndRotate(job)
		case <-w.done:
			return
		}
	}
}

func (w *ArchiveWriter) appendAndRotate(job archiveJob) {
	// 确保 metrics.current 存在
	if w.curFile == nil {
		if err := w.openCurrent(job.ts); err != nil {
			logger.Error("archive: open metrics.current: %v", err)
			return
		}
	}

	recSize := ArchRecordSize()
	buf := make([]byte, recSize)
	binary.LittleEndian.PutUint32(buf[0:4], job.ts)
	recBytes := (*[1 << 20]byte)(unsafe.Pointer(&job.rec))[:binary.Size(job.rec)]
	copy(buf[4:], recBytes)

	// 追加写入
	if _, err := w.curFile.Write(buf); err != nil {
		if isNoSpace(err) {
			logger.Error("archive: ENOSPC, triggering immediate eviction")
			w.evict()
			// 重试
			if _, err2 := w.curFile.Write(buf); err2 != nil {
				logger.Error("archive: write retry failed: %v", err2)
				return
			}
		} else {
			logger.Error("archive: write failed: %v", err)
			return
		}
	}
	if err := w.curFile.Sync(); err != nil {
		logger.Error("archive: fsync failed: %v", err)
		return
	}

	// 检查轮转
	info, _ := w.curFile.Stat()
	needRotate := info.Size() >= maxSegmentBytes ||
		time.Since(w.curCreated) >= rotateAfter
	if needRotate {
		w.rotate()
	}
}

func (w *ArchiveWriter) openCurrent(firstTS uint32) error {
	path := filepath.Join(w.dir, currentFileName)
	// 检测 metrics.current 是否存在（启动恢复后应已不存在，或首次创建）
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("open current: %w", err)
	}
	info, err := f.Stat()
	if err != nil {
		f.Close()
		return fmt.Errorf("stat current: %w", err)
	}
	if info.Size() < headerSize {
		// 新文件或损坏：写文件头
		if err := writeHeader(f, firstTS); err != nil {
			f.Close()
			return fmt.Errorf("write header: %w", err)
		}
		w.curCreated = time.Now()
	} else {
		// 已有头+数据：读取 header 恢复 curCreated (用文件修改时间近似)
		w.curCreated = info.ModTime()
	}
	w.curFile = f
	return nil
}

func (w *ArchiveWriter) rotate() {
	if w.curFile == nil {
		return
	}
	w.curFile.Close()
	w.curFile = nil

	oldPath := filepath.Join(w.dir, currentFileName)
	segName := w.curCreated.Format("2006-01-02-15") + ".mtrc"
	newPath := filepath.Join(w.dir, segName)

	if err := os.Rename(oldPath, newPath); err != nil {
		logger.Error("archive: rename %s -> %s failed: %v", oldPath, newPath, err)
		// 恢复 curFile
		f, _ := os.OpenFile(oldPath, os.O_RDWR|os.O_APPEND, 0644)
		w.curFile = f
		return
	}

	// 后台 gzip
	go w.compressSeg(newPath)

	// 淘汰检查
	w.evict()
}

func (w *ArchiveWriter) compressSeg(mtrcPath string) {
	gzPath := mtrcPath + ".gz"
	in, err := os.Open(mtrcPath)
	if err != nil {
		logger.Error("archive: open %s for gzip: %v", mtrcPath, err)
		return
	}
	defer in.Close()

	out, err := os.Create(gzPath)
	if err != nil {
		logger.Error("archive: create %s: %v", gzPath, err)
		return
	}
	defer out.Close()

	gw := gzip.NewWriter(out)
	if _, err := io.Copy(gw, in); err != nil {
		logger.Error("archive: gzip %s: %v", mtrcPath, err)
		gw.Close()
		os.Remove(gzPath)
		return
	}
	if err := gw.Close(); err != nil {
		logger.Error("archive: close gzip %s: %v", gzPath, err)
		os.Remove(gzPath)
		return
	}

	// 成功：删除未压缩源文件
	if err := os.Remove(mtrcPath); err != nil {
		logger.Warn("archive: remove %s after gzip: %v", mtrcPath, err)
	}
}

func (w *ArchiveWriter) evict() {
	entries, err := os.ReadDir(w.dir)
	if err != nil {
		logger.Error("archive: readdir for evict: %v", err)
		return
	}

	type seg struct {
		name string
		size int64
	}
	var segs []seg
	var totalSize int64
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if name == currentFileName {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		segs = append(segs, seg{name, info.Size()})
		totalSize += info.Size()
	}

	// 排序：按文件名（时间串），最老在前
	sort.Slice(segs, func(i, j int) bool {
		ki := parseSegFileName(segs[i].name)
		kj := parseSegFileName(segs[j].name)
		return ki < kj
	})

	maxBytes := int64(w.maxSizeMB) * 1024 * 1024
	for totalSize > maxBytes && len(segs) > 0 {
		toDelete := segs[0]
		path := filepath.Join(w.dir, toDelete.name)
		if err := os.Remove(path); err != nil {
			logger.Error("archive: evict remove %s: %v", path, err)
			segs = segs[1:]
			continue
		}
		totalSize -= toDelete.size
		segs = segs[1:]
		logger.Info("archive: evicted %s (%d bytes)", toDelete.name, toDelete.size)
	}
}

// recover 启动时处理崩溃恢复。
func (w *ArchiveWriter) recover() {
	curPath := filepath.Join(w.dir, currentFileName)
	info, err := os.Stat(curPath)
	if os.IsNotExist(err) {
		return
	}
	if err != nil {
		logger.Warn("archive: stat metrics.current: %v", err)
		return
	}

	f, err := os.OpenFile(curPath, os.O_RDWR, 0644)
	if err != nil {
		logger.Warn("archive: open metrics.current for recovery: %v", err)
		return
	}
	defer f.Close()

	recSize := ArchRecordSize()

	// 1. 截断尾部半条
	if err := truncateToRecord(f, recSize); err != nil {
		logger.Error("archive: truncate recovery: %v", err)
	}

	// 1b. 版本不匹配 → 轮转旧版本文件，启动新版本 current
	//     （schema 升级时旧 v? 文件整体归档，新文件写 CurrentVersion）
	if hdr, _, err := readHeader(f); err == nil && hdr.Version != CurrentVersion {
		f.Close()
		segName := info.ModTime().Format("2006-01-02-15") + ".mtrc"
		newPath := filepath.Join(w.dir, segName)
		if err := os.Rename(curPath, newPath); err != nil {
			logger.Error("archive: version-mismatch rotate rename %s -> %s: %v", curPath, newPath, err)
		} else {
			logger.Info("archive: rotated v%d metrics.current → %s (current v%d)", hdr.Version, segName, CurrentVersion)
			go w.compressSeg(newPath)
		}
		return
	}
	// readHeader 改变了文件偏移，重置到头以便后续判断
	f.Seek(0, io.SeekStart)

	// 2. 如果文件只有头（无 record），删除它（没有数据的分段无价值）
	info2, _ := f.Stat()
	if info2.Size() <= headerSize {
		os.Remove(curPath)
		logger.Info("archive: removed empty metrics.current (post-crash)")
		return
	}

	// 3. 如果文件有数据且超过 rotateAfter，立即轮转
	//    用文件的 mtime 近似 curCreated
	if time.Since(info.ModTime()) >= rotateAfter {
		// 先假装 curFile 存在以驱动 rotate()
		// 这里简单构造一个基于 mtime 的文件名
		segName := info.ModTime().Format("2006-01-02-15") + ".mtrc"
		newPath := filepath.Join(w.dir, segName)
		if err := os.Rename(curPath, newPath); err != nil {
			logger.Error("archive: startup rotate rename %s -> %s: %v", curPath, newPath, err)
		} else {
			go w.compressSeg(newPath)
		}
	}
}

// isNoSpace 判断错误是否为磁盘满 (ENOSPC on Linux)
func isNoSpace(err error) bool {
	if pe, ok := err.(*os.PathError); ok {
		if errno, ok := pe.Err.(syscall.Errno); ok {
			return errno == syscall.ENOSPC
		}
	}
	return false
}
