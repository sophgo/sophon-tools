package metrics

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestWriteReadHeaderRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.mtrc")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	const firstTS uint32 = 1720425600
	if err := writeHeader(f, firstTS); err != nil {
		f.Close()
		t.Fatalf("writeHeader: %v", err)
	}
	if err := f.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// 验证文件大小 = headerSize
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != headerSize {
		t.Errorf("file size after header = %d, want %d", info.Size(), headerSize)
	}

	// 读回头
	f2, err := os.Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer f2.Close()

	hdr, fields, err := readHeader(f2)
	if err != nil {
		t.Fatalf("readHeader: %v", err)
	}
	if string(hdr.Magic[:]) != headerMagic {
		t.Errorf("magic = %q, want %q", string(hdr.Magic[:]), headerMagic)
	}
	if hdr.Version != CurrentVersion {
		t.Errorf("version = %d, want %d", hdr.Version, CurrentVersion)
	}
	if int(hdr.RecordSize) != ArchRecordSize() {
		t.Errorf("recordSize = %d, want %d", hdr.RecordSize, ArchRecordSize())
	}
	if hdr.FirstTimestamp != firstTS {
		t.Errorf("firstTS = %d, want %d", hdr.FirstTimestamp, firstTS)
	}
	if int(hdr.FieldCount) != len(ArchFields()) {
		t.Errorf("fieldCount = %d, want %d", hdr.FieldCount, len(ArchFields()))
	}
	expectedFields := ArchFields()
	if len(fields) != len(expectedFields) {
		t.Fatalf("readHeader fields len = %d, want %d", len(fields), len(expectedFields))
	}
	for i, name := range expectedFields {
		if fields[i] != name {
			t.Errorf("field[%d] = %q, want %q", i, fields[i], name)
		}
	}
}

func TestTruncateToRecord(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "partial.mtrc")

	recordSize := ArchRecordSize()
	_ = recordSize // 后续使用

	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := writeHeader(f, 100); err != nil {
		f.Close()
		t.Fatalf("writeHeader: %v", err)
	}

	// 写 3.5 条 record（模拟崩溃后不完整）
	fullRecord := make([]byte, recordSize)
	for i := 0; i < 3; i++ {
		if _, err := f.Write(fullRecord); err != nil {
			f.Close()
			t.Fatalf("write record %d: %v", i, err)
		}
	}
	halfRecord := make([]byte, recordSize/2)
	if _, err := f.Write(halfRecord); err != nil {
		f.Close()
		t.Fatalf("write partial: %v", err)
	}
	if err := f.Sync(); err != nil {
		f.Close()
		t.Fatalf("sync: %v", err)
	}
	if err := f.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// 恢复
	f2, err := os.OpenFile(path, os.O_RDWR, 0644)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer f2.Close()
	if err := truncateToRecord(f2, recordSize); err != nil {
		t.Fatalf("truncateToRecord: %v", err)
	}

	info, _ := f2.Stat()
	expectedSize := int64(headerSize + 3*recordSize)
	if info.Size() != expectedSize {
		t.Errorf("after truncate size = %d, want %d", info.Size(), expectedSize)
	}
}

func TestReadHeaderBadMagic(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.mtrc")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	// 写垃圾数据
	f.Write(make([]byte, headerSize))
	f.Close()

	f2, err := os.Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer f2.Close()
	_, _, err = readHeader(f2)
	if err == nil {
		t.Error("expected error for bad magic, got nil")
	}
}

func TestWriteHeaderFieldNamesFit(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "fit.mtrc")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	defer f.Close()
	if err := writeHeader(f, 0); err != nil {
		t.Fatalf("writeHeader failed (field_names too long?): %v", err)
	}
}

// 辅助：构造一条完整 record（timestamp + zero ArchRecord）
func makeRecord(ts uint32) []byte {
	buf := new(bytes.Buffer)
	binary.Write(buf, binary.LittleEndian, ts)
	binary.Write(buf, binary.LittleEndian, ArchRecord{})
	return buf.Bytes()
}

func TestArchiveWriterSubmitAndReadBack(t *testing.T) {
	dir := t.TempDir()
	w := NewArchiveWriter()
	w.Start(dir, 100, 16)

	// 写 10 条 record
	ts := uint32(1720425600)
	for i := 0; i < 10; i++ {
		rec := ArchRecord{CPUUsage: float32(i * 10)}
		w.Submit(ts+uint32(i*20), &rec)
	}
	// 等 writer 消费完
	time.Sleep(500 * time.Millisecond)

	// 检查 metrics.current 存在且包含 10 条 record
	curPath := filepath.Join(dir, currentFileName)
	f, err := os.Open(curPath)
	if err != nil {
		t.Fatalf("open current: %v", err)
	}
	defer f.Close()

	hdr, fields, err := readHeader(f)
	if err != nil {
		t.Fatalf("readHeader: %v", err)
	}
	if len(fields) != len(ArchFields()) {
		t.Errorf("fields len = %d, want %d", len(fields), len(ArchFields()))
	}

	recSize := int(hdr.RecordSize)
	buf := make([]byte, recSize)
	for i := 0; i < 10; i++ {
		n, err := io.ReadFull(f, buf)
		if err != nil {
			t.Fatalf("read record %d: %v", i, err)
		}
		if n != recSize {
			t.Fatalf("record %d len = %d, want %d", i, n, recSize)
		}
	}
	// 确认无第 11 条
	_, err = io.ReadFull(f, buf)
	if err == nil {
		t.Error("should be EOF after 10 records")
	}
}

func TestArchiveWriterSubmitNonBlocking(t *testing.T) {
	dir := t.TempDir()
	w := NewArchiveWriter()
	// buffered channel 0 — 满即丢
	w.Start(dir, 100, 0)

	// 投递应成功（当前 chan buffer 为 1 - Start 会 clamp）
	rec := ArchRecord{}
	w.Submit(100, &rec)
	time.Sleep(100 * time.Millisecond)
}

func TestArchiveWriterDroppedCount(t *testing.T) {
	dir := t.TempDir()
	w := NewArchiveWriter()
	// channel 容量 1，不启动 writer goroutine 的消费端
	// Submit 第 1 条成功，第 2 条失败
	w.dir = dir
	w.maxSizeMB = 100
	w.ch = make(chan archiveJob, 1)
	w.started = true

	rec := ArchRecord{}
	w.Submit(1, &rec)
	w.Submit(2, &rec) // should drop
	w.Submit(3, &rec) // should drop

	time.Sleep(50 * time.Millisecond)
	if d := w.Dropped(); d < 2 {
		t.Errorf("dropped = %d, want >= 2", d)
	}
}

func TestArchiveWriterEvict(t *testing.T) {
	dir := t.TempDir()
	w := NewArchiveWriter()
	// 小上限 1MB
	w.dir = dir
	w.maxSizeMB = 1

	// 创建一些大的伪分段文件
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("2026-07-0%d-00.mtrc.gz", i+1)
		path := filepath.Join(dir, name)
		// 写 500KB 文件
		f, _ := os.Create(path)
		f.Write(make([]byte, 500*1024))
		f.Close()
	}

	// 触发淘汰
	w.evict()

	// 验证总大小 ≤ 1MB
	entries, _ := os.ReadDir(dir)
	var total int64
	for _, e := range entries {
		info, _ := e.Info()
		total += info.Size()
	}
	maxBytes := int64(1 * 1024 * 1024)
	if total > maxBytes {
		t.Errorf("total size after evict = %d, should be <= %d", total, maxBytes)
	}
}

func TestIsNoSpace(t *testing.T) {
	// 验证 isNoSpace 对 ENOSPC 返回 true
	err := &os.PathError{Op: "write", Path: "/fake", Err: syscall.ENOSPC}
	if !isNoSpace(err) {
		t.Error("isNoSpace(ENOSPC) = false, want true")
	}
	// 普通错误返回 false
	if isNoSpace(errors.New("some error")) {
		t.Error("isNoSpace(plain error) = true, want false")
	}
}
