package metrics_controller

import (
	"compress/gzip"
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"bmssm/logger"
	arch "bmssm/pkg/metrics"
	"bmssm/pkg/response"
)

const maxHistoryPoints = 100000

// Controller 指标历史 MVC 控制器。
type Controller struct{}

// DefaultController 返回生产环境控制器。
func DefaultController() *Controller { return &Controller{} }

// archDir 返回存档目录（从 Archiver 获取，或默认）。
func archDir() string {
	a := arch.Archiver()
	if a != nil {
		return a.Dir()
	}
	return "/var/lib/bmssm/metrics"
}

// GetFields GET /api/v1/metrics/fields
func (ctrl *Controller) GetFields(c *gin.Context) {
	c.JSON(http.StatusOK, response.OK(arch.ArchFields()))
}

// GetHistory GET /api/v1/metrics/history?from=&to=&fields=
func (ctrl *Controller) GetHistory(c *gin.Context) {
	fromStr := c.Query("from")
	toStr := c.Query("to")
	fieldsStr := c.Query("fields")

	from, err := strconv.ParseInt(fromStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("from required (unix timestamp)"))
		return
	}
	to, err := strconv.ParseInt(toStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("to required (unix timestamp)"))
		return
	}

	dir := archDir()
	segments, scanErr := scanSegments(dir, from, to)
	if scanErr != nil {
		logger.Warn("metrics/history: scan: %v", scanErr)
	}

	requested := fieldSet(splitFields(fieldsStr))

	var allFields []string
	var points [][]float64
	var skipped []string
	truncated := false

	for _, seg := range segments {
		segFields, segPoints, err := readSeg(seg, from, to, requested)
		if err != nil {
			skipped = append(skipped, filepath.Base(seg))
			continue
		}
		if allFields == nil {
			allFields = segFields
		}
		for _, pt := range segPoints {
			if len(points) >= maxHistoryPoints {
				truncated = true
				break
			}
			points = append(points, pt)
		}
		if truncated {
			break
		}
	}
	if allFields == nil {
		allFields = []string{"timestamp"}
	}

	c.JSON(http.StatusOK, response.OK(gin.H{
		"fields":        allFields,
		"points":        points,
		"skipped_files": skipped,
		"truncated":     truncated,
	}))
}

// GetExport GET /api/v1/metrics/export?from=&to=&fields=&format=csv
// fields 为 web 端勾选的指标（逗号分隔）；不传则导出全部字段。
func (ctrl *Controller) GetExport(c *gin.Context) {
	fromStr := c.Query("from")
	toStr := c.Query("to")

	from, err := strconv.ParseInt(fromStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("from required"))
		return
	}
	to, err := strconv.ParseInt(toStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("to required"))
		return
	}

	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=metrics-%d-%d.csv", from, to))
	c.Header("Content-Type", "text/csv; charset=utf-8")

	writeExportCSV(c.Writer, archDir(), from, to, splitFields(c.Query("fields")))
}

// splitFields 解析逗号分隔的字段名，忽略空白项。
func splitFields(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	var out []string
	for _, f := range strings.Split(s, ",") {
		if f = strings.TrimSpace(f); f != "" {
			out = append(out, f)
		}
	}
	return out
}

// writeExportCSV 把 dir 下 from..to 范围内的存档写成 CSV。
// 列固定为 exportColumns(selected) 的顺序；分段缺该字段（旧 schema 写入的
// 分段）时该格留空，保证同一份 CSV 里每行列数一致、不错位。
func writeExportCSV(w io.Writer, dir string, from, to int64, selected []string) {
	cols := exportColumns(selected)
	segments, _ := scanSegments(dir, from, to)

	io.WriteString(w, strings.Join(cols, ",")+"\n")

	requested := fieldSet(selected)
	for _, seg := range segments {
		segFields, segPoints, err := readSeg(seg, from, to, requested)
		if err != nil {
			continue
		}
		pos := make(map[string]int, len(segFields))
		for i, f := range segFields {
			pos[f] = i
		}
		parts := make([]string, len(cols))
		for _, pt := range segPoints {
			for i, c := range cols {
				parts[i] = ""
				if j, ok := pos[c]; ok && j < len(pt) {
					parts[i] = strconv.FormatFloat(pt[j], 'f', 2, 64)
				}
			}
			io.WriteString(w, strings.Join(parts, ",")+"\n")
		}
	}
}

// exportColumns 返回导出列顺序：timestamp 在首位，其余按当前 schema 顺序，
// 只保留 selected 中的字段（selected 为空 → 全部）。列顺序与请求顺序无关。
func exportColumns(selected []string) []string {
	keep := fieldSet(selected)
	cols := make([]string, 0, len(arch.ArchFields()))
	for _, f := range arch.ArchFields() {
		if f == "timestamp" || keep == nil || keep[f] {
			cols = append(cols, f)
		}
	}
	return cols
}

// fieldSet 把字段名列表转成集合；空列表返回 nil（表示"不过滤"）。
func fieldSet(fields []string) map[string]bool {
	if len(fields) == 0 {
		return nil
	}
	set := make(map[string]bool, len(fields))
	for _, f := range fields {
		set[f] = true
	}
	return set
}

// --- 内部函数 ---

// scanSegments 扫描存档目录，返回匹配 from..to 时间范围的分段文件列表（按时间排序）。
func scanSegments(dir string, from, to int64) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	type named struct {
		name string
		minT int64
	}
	var items []named
	for _, e := range entries {
		name := e.Name()
		minT, maxT := timeRange(name)
		if maxT < from || minT > to {
			continue
		}
		items = append(items, named{name, minT})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].minT < items[j].minT })
	out := make([]string, len(items))
	for i, it := range items {
		out[i] = filepath.Join(dir, it.name)
	}
	return out, nil
}

// timeRange 根据文件名推断分段的时间范围。
// "2026-07-08-14.mtrc.gz" → 2026-07-08 14:00 - 15:00。
// "metrics.current" → 最近 2 小时窗口。
func timeRange(name string) (minT, maxT int64) {
	base := name
	base = strings.TrimSuffix(base, ".gz")
	base = strings.TrimSuffix(base, ".mtrc")
	// Handle active write file: metrics.current (or legacy metrics file).
	if strings.HasPrefix(name, "metrics.") {
		now := time.Now().Unix()
		return now - 3600, now + 3600
	}
	t, err := time.Parse("2006-01-02-15", base)
	if err != nil {
		return 0, 0
	}
	return t.Unix(), t.Add(time.Hour).Unix()
}

// gzipReadCloser 组合 gzip.Reader + 底层 *os.File，Close 时两者都关。
type gzipReadCloser struct {
	*gzip.Reader
	f *os.File
}

func (g *gzipReadCloser) Close() error {
	g.Reader.Close()
	return g.f.Close()
}

// readSeg 读取一个分段文件，返回匹配时间范围的数据点。
// requested 为 nil 时返回全部字段。
func readSeg(path string, from, to int64, requested map[string]bool) ([]string, [][]float64, error) {
	// Open (handle .gz)
	var r io.ReadCloser
	if strings.HasSuffix(path, ".gz") {
		f, err := os.Open(path)
		if err != nil {
			return nil, nil, err
		}
		gr, err := gzip.NewReader(f)
		if err != nil {
			f.Close()
			return nil, nil, err
		}
		r = &gzipReadCloser{Reader: gr, f: f}
	} else {
		f, err := os.Open(path)
		if err != nil {
			return nil, nil, err
		}
		r = f
	}
	defer r.Close()

	// Read header prefix (18 bytes)
	var hdr arch.ArchFileHeader
	if err := binary.Read(r, binary.LittleEndian, &hdr); err != nil {
		return nil, nil, fmt.Errorf("read header: %w", err)
	}
	if string(hdr.Magic[:]) != "MTRC" {
		return nil, nil, fmt.Errorf("bad magic in %s", filepath.Base(path))
	}

	// Read field_names (at offset 18)
	namesBytes := make([]byte, hdr.FieldNamesLen)
	if _, err := io.ReadFull(r, namesBytes); err != nil {
		return nil, nil, fmt.Errorf("read field_names: %w", err)
	}
	fieldNames := strings.Split(string(namesBytes), "\x00")

	// Seek to headerSize (start of records): skip padding after field_names
	remainingPad := int64(arch.HeaderSize) - 18 - int64(hdr.FieldNamesLen)
	if remainingPad > 0 {
		if _, err := io.CopyN(io.Discard, r, remainingPad); err != nil {
			return nil, nil, fmt.Errorf("seek to records: %w", err)
		}
	}

	recSize := int(hdr.RecordSize)
	buf := make([]byte, recSize)

	// Determine output fields order. 始终以 timestamp 为首列，
	// 便于前端按 row[0] 取时间戳；CSV 导出 header 也含 timestamp。
	var outFields []string
	outFields = append(outFields, "timestamp")
	if requested != nil {
		for _, fn := range fieldNames {
			if fn == "timestamp" {
				continue
			}
			if requested[fn] {
				outFields = append(outFields, fn)
			}
		}
	} else {
		for _, fn := range fieldNames {
			if fn != "timestamp" {
				outFields = append(outFields, fn)
			}
		}
	}

	// Build index: field name → position in the record body (after timestamp).
	// fieldNames[0] is "timestamp" → record[0:4] (uint32, special case).
	// fieldNames[i] (i>=1) corresponds to record[4+(i-1)*4 : 4+i*4] (float32).
	fieldIdx := make(map[string]int, len(fieldNames))
	for i, fn := range fieldNames {
		if fn == "timestamp" {
			fieldIdx[fn] = -1 // special: record[0:4] uint32
		} else {
			fieldIdx[fn] = i - 1 // position in record body (0-based)
		}
	}

	var points [][]float64
	for {
		_, err := io.ReadFull(r, buf)
		if err != nil {
			break // EOF or partial
		}
		ts := int64(binary.LittleEndian.Uint32(buf[0:4]))
		if ts < from {
			continue
		}
		if ts > to {
			break // records are time-ordered
		}
		pt := make([]float64, len(outFields))
		for j, fn := range outFields {
			if fn == "timestamp" {
				pt[j] = float64(ts)
				continue
			}
			idx, ok := fieldIdx[fn]
			if !ok {
				continue // field from newer version, not in this old file
			}
			byteOffset := 4 + idx*4
			if byteOffset+4 <= len(buf) {
				bits := binary.LittleEndian.Uint32(buf[byteOffset : byteOffset+4])
				pt[j] = float64(math.Float32frombits(bits))
			}
		}
		points = append(points, pt)
	}
	return outFields, points, nil
}
