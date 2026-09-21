package metrics_controller

import (
	"bytes"
	"encoding/binary"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	arch "bmssm/pkg/metrics"
)

// writeTestSeg 生成一个合法的 .mtrc 分段文件：4096B 文件头 + 定长 record。
// fields 为该文件的字段名（首位必须是 timestamp），records 每行为
// [ts, v1, v2, ...]，长度与 fields 一致。允许 fields 是当前 schema 的子集，
// 用于模拟升级前写入的旧分段。
func writeTestSeg(t *testing.T, dir, name string, fields []string, records [][]float64) {
	t.Helper()
	if len(fields) == 0 || fields[0] != "timestamp" {
		t.Fatalf("fields 首位必须是 timestamp: %v", fields)
	}
	if got := binary.Size(arch.ArchFileHeader{}); got != 18 {
		t.Fatalf("ArchFileHeader 大小 = %d, want 18", got)
	}
	var buf bytes.Buffer
	names := strings.Join(fields, "\x00")
	hdr := arch.ArchFileHeader{
		Version:        arch.CurrentVersion,
		RecordSize:     uint16(4 * len(fields)),
		FieldCount:     uint16(len(fields)),
		FieldNamesLen:  uint16(len(names)),
		FirstTimestamp: uint32(records[0][0]),
	}
	copy(hdr.Magic[:], "MTRC")
	if err := binary.Write(&buf, binary.LittleEndian, hdr); err != nil {
		t.Fatalf("write header: %v", err)
	}
	buf.WriteString(names)
	buf.Write(make([]byte, arch.HeaderSize-18-len(names)))
	for _, r := range records {
		if len(r) != len(fields) {
			t.Fatalf("record 列数 = %d, want %d", len(r), len(fields))
		}
		binary.Write(&buf, binary.LittleEndian, uint32(r[0]))
		for _, v := range r[1:] {
			binary.Write(&buf, binary.LittleEndian, float32(v))
		}
	}
	if err := os.WriteFile(filepath.Join(dir, name), buf.Bytes(), 0644); err != nil {
		t.Fatalf("write seg: %v", err)
	}
}

// segName 按 bmssm 分段命名规则（UTC 小时）生成文件名，保证 scanSegments
// 的时间范围推断能命中文件内的记录。
func segName(ts int64) string {
	return time.Unix(ts, 0).UTC().Format("2006-01-02-15") + ".mtrc"
}

// testBase 2026-09-21 10:00:00 UTC，与 segName 的命名口径一致。
var testBase = time.Date(2026, 9, 21, 10, 0, 0, 0, time.UTC).Unix()

// buildRecords 造 n 条全字段记录：ts = base+i*20，第 j 列（j>=1）值 = j*1000+i。
func buildRecords(base int64, n int) [][]float64 {
	fields := arch.ArchFields()
	out := make([][]float64, n)
	for i := range out {
		row := make([]float64, len(fields))
		row[0] = float64(base + int64(i)*20)
		for j := 1; j < len(fields); j++ {
			row[j] = float64(j*1000 + i)
		}
		out[i] = row
	}
	return out
}

// csvRows 把 CSV 文本切成 [表头, 数据行...]。
func csvRows(t *testing.T, csv string) [][]string {
	t.Helper()
	trimmed := strings.TrimRight(csv, "\n")
	if trimmed == "" {
		t.Fatalf("CSV 为空")
	}
	lines := strings.Split(trimmed, "\n")
	out := make([][]string, len(lines))
	for i, ln := range lines {
		out[i] = strings.Split(ln, ",")
	}
	return out
}

// csvColumn 取 CSV 中某列（不含表头）的全部值。
func csvColumn(t *testing.T, csv, col string) []string {
	t.Helper()
	rows := csvRows(t, csv)
	idx := indexOfString(rows[0], col)
	if idx < 0 {
		t.Fatalf("CSV 表头无 %s: %q", col, strings.Join(rows[0], ","))
	}
	out := make([]string, 0, len(rows)-1)
	for _, r := range rows[1:] {
		if idx >= len(r) {
			t.Fatalf("行列数不足（缺 %s）: %v", col, r)
		}
		out = append(out, r[idx])
	}
	return out
}

func indexOfString(xs []string, s string) int {
	for i, x := range xs {
		if x == s {
			return i
		}
	}
	return -1
}

func archIndex(t *testing.T, field string) int {
	t.Helper()
	if i := indexOfString(arch.ArchFields(), field); i >= 0 {
		return i
	}
	t.Fatalf("ArchFields 中无 %s", field)
	return -1
}

// num 按导出格式（float64(v) 保留 2 位小数）格式化期望值。
func num(v float64) string { return strconv.FormatFloat(v, 'f', 2, 64) }

func equalStrings(a, b []string) bool {
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

// 导出只应包含 web 端勾选的指标列，且列顺序固定按 schema（与请求顺序无关）。
func TestExportCSVOnlySelectedFields(t *testing.T) {
	dir := t.TempDir()
	base := testBase
	writeTestSeg(t, dir, segName(base), arch.ArchFields(), buildRecords(base, 3))

	// 故意逆序传入，断言导出仍按 schema 顺序排列
	selected := []string{"chip_temp_c", "cpu_usage_pct"}
	var buf bytes.Buffer
	writeExportCSV(&buf, dir, base-60, base+3600, selected)
	got := buf.String()

	rows := csvRows(t, got)
	if want := []string{"timestamp", "cpu_usage_pct", "chip_temp_c"}; !equalStrings(rows[0], want) {
		t.Errorf("CSV 表头 = %v, want %v", rows[0], want)
	}
	if len(rows) != 4 {
		t.Fatalf("CSV 行数 = %d（含表头）, want 4\n%s", len(rows), got)
	}

	cpu := archIndex(t, "cpu_usage_pct")
	wantCPU := []string{num(float64(cpu*1000 + 0)), num(float64(cpu*1000 + 1)), num(float64(cpu*1000 + 2))}
	if c := csvColumn(t, got, "cpu_usage_pct"); !equalStrings(c, wantCPU) {
		t.Errorf("cpu_usage_pct 列 = %v, want %v", c, wantCPU)
	}
	wantTS := []string{num(float64(base)), num(float64(base + 20)), num(float64(base + 40))}
	if c := csvColumn(t, got, "timestamp"); !equalStrings(c, wantTS) {
		t.Errorf("timestamp 列 = %v, want %v", c, wantTS)
	}

	for _, f := range arch.ArchFields() {
		if f == "timestamp" || indexOfString(selected, f) >= 0 {
			continue
		}
		if indexOfString(rows[0], f) >= 0 {
			t.Errorf("未勾选的字段 %s 出现在导出表头 %v", f, rows[0])
		}
	}
}

// 不传选择（nil）时导出全部字段，且列顺序 = 当前 schema。
func TestExportCSVAllFieldsWhenNotSelected(t *testing.T) {
	dir := t.TempDir()
	base := testBase
	writeTestSeg(t, dir, segName(base), arch.ArchFields(), buildRecords(base, 2))

	var buf bytes.Buffer
	writeExportCSV(&buf, dir, base-60, base+3600, nil)
	rows := csvRows(t, buf.String())

	if want := arch.ArchFields(); !equalStrings(rows[0], want) {
		t.Errorf("CSV 表头 = %v, want %v", rows[0], want)
	}
	if len(rows) != 3 {
		t.Errorf("CSV 行数 = %d（含表头）, want 3", len(rows))
	}
}

// 跨 schema 版本：旧分段缺字段时列仍按当前 schema 对齐，缺的列留空。
func TestExportCSVColumnsAlignedAcrossSchemaVersions(t *testing.T) {
	dir := t.TempDir()
	base := testBase

	// 旧分段：只有 timestamp + cpu_usage_pct 两列（模拟 v1 存档）
	oldFields := []string{"timestamp", "cpu_usage_pct"}
	oldRecs := [][]float64{
		{float64(base), 11},
		{float64(base + 20), 12},
	}
	writeTestSeg(t, dir, segName(base), oldFields, oldRecs)

	// 新分段：当前 schema 全字段
	writeTestSeg(t, dir, segName(base+3600), arch.ArchFields(), buildRecords(base+3600, 1))

	var buf bytes.Buffer
	writeExportCSV(&buf, dir, base-60, base+7200, []string{"cpu_usage_pct", "chip_temp_c"})
	got := buf.String()

	rows := csvRows(t, got)
	want := []string{"timestamp", "cpu_usage_pct", "chip_temp_c"}
	if !equalStrings(rows[0], want) {
		t.Fatalf("CSV 表头 = %v, want %v", rows[0], want)
	}
	for i, r := range rows {
		if len(r) != len(want) {
			t.Fatalf("第 %d 行列数 = %d, want %d: %v", i, len(r), len(want), r)
		}
	}
	// 旧分段无 chip_temp_c → 留空，而不是错位或补 0
	if c := csvColumn(t, got, "chip_temp_c"); c[0] != "" || c[1] != "" {
		t.Errorf("旧分段 chip_temp_c 列 = %v, want 空值", c)
	}
	// 新分段有 chip_temp_c
	if c := csvColumn(t, got, "chip_temp_c"); c[2] == "" {
		t.Errorf("新分段 chip_temp_c 列不应为空: %v", c)
	}
}
