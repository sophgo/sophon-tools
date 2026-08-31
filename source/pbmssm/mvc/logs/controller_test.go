package logs

import (
	"archive/tar"
	"compress/gzip"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"bmssm/pkg/auth"
)

func init() { gin.SetMode(gin.ReleaseMode) }

// testToken 签发测试用 JWT（secret=auth.DefaultSecret，与未加载配置时的 getSecret 一致）。
func testToken(t *testing.T) string {
	t.Helper()
	tok, _, err := auth.IssueToken("test", auth.DefaultSecret, false)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}
	return tok
}

// newTestRouter 用临时目录做 logRoot 构建测试路由，
// 与 router.go 保持一致：download 自鉴权（query/头）；overview 走 Auth 中间件。
func newTestRouter(t *testing.T, root string) *gin.Engine {
	t.Helper()
	old := logRoot
	logRoot = root
	t.Cleanup(func() { logRoot = old })
	r := gin.New()
	ctrl := DefaultController()
	r.GET("/api/v1/logs/download", ctrl.DownloadLogs)
	api := r.Group("/api/v1")
	api.Use(authMiddlewareMW())
	{
		api.GET("/logs/overview", ctrl.LogOverview)
	}
	return r
}

// authMiddlewareMW 复用 bmssm 真实验证中间件（保持路由行为与生产一致）。
func authMiddlewareMW() gin.HandlerFunc {
	return func(c *gin.Context) {
		// 直接按 handler 内同一规则校验 query/Authorization，避免依赖配置 JWT secret
		if !authLogToken(c) {
			c.Abort()
			return
		}
		c.Next()
	}
}

// fixture 构造 /var/log 测试夹具：
//
//	kern.log             (regular, 1024B)
//	syslog               (regular, 512B)
//	journal/a.log        (regular, 64B)
//	journal/sub/b.log    (regular, 32B)
//	dmesg -> kern.log    (symlink)
//	app.sock             (socket，应被跳过)
func fixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	write := func(rel, content string) {
		t.Helper()
		p := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatalf("mkdir %s: %v", filepath.Dir(p), err)
		}
		if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
			t.Fatalf("write %s: %v", p, err)
		}
	}
	write("kern.log", strings.Repeat("k", 1024))
	write("syslog", strings.Repeat("s", 512))
	write("journal/a.log", strings.Repeat("a", 64))
	write("journal/sub/b.log", strings.Repeat("b", 32))
	// 目录内 socket：sumDir 也应跳过（对齐 DownloadLogs）。
	if err := createSocket(filepath.Join(root, "journal", "app.sock")); err != nil {
		t.Fatalf("create socket in dir: %v", err)
	}
	if err := os.Symlink("kern.log", filepath.Join(root, "dmesg")); err != nil {
		t.Fatalf("symlink: %v", err)
	}
	sock := filepath.Join(root, "app.sock")
	if err := createSocket(sock); err != nil {
		t.Fatalf("create socket: %v", err)
	}
	return root
}

// createSocket 尽量创建 unix socket；环境不支持时跳过（不阻塞测试）。
func createSocket(path string) error {
	l, err := net.Listen("unix", path)
	if err != nil {
		return err
	}
	l.Close()
	return nil
}

func TestDownloadLogsUnauthorized(t *testing.T) {
	root := fixture(t)
	r := newTestRouter(t, root)

	for name, tc := range map[string]struct {
		target string
		want   int
	}{
		"no token":   {"/api/v1/logs/download", http.StatusUnauthorized},
		"bad token":  {"/api/v1/logs/download?token=garbage", http.StatusUnauthorized},
		"temp token": {"/api/v1/logs/download?token=" + tempToken(t), http.StatusForbidden},
	} {
		t.Run(name, func(t *testing.T) {
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodGet, tc.target, nil)
			r.ServeHTTP(w, req)
			if w.Code != tc.want {
				t.Fatalf("status=%d want %d", w.Code, tc.want)
			}
		})
	}
}

func tempToken(t *testing.T) string {
	t.Helper()
	tok, _, err := auth.IssueToken("test", auth.DefaultSecret, true)
	if err != nil {
		t.Fatalf("IssueToken temp: %v", err)
	}
	return tok
}

func TestDownloadLogsStreamsValidTarGz(t *testing.T) {
	root := fixture(t)
	r := newTestRouter(t, root)
	tok := testToken(t)

	// Authorization 头
	req := httptest.NewRequest(http.MethodGet, "/api/v1/logs/download", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d want 200", w.Code)
	}
	if ct := w.Header().Get("Content-Type"); ct != "application/gzip" {
		t.Fatalf("content-type=%q", ct)
	}
	if cd := w.Header().Get("Content-Disposition"); !strings.Contains(cd, "sys_log.tgz") {
		t.Fatalf("content-disposition=%q", cd)
	}

	names := readTarNames(t, w.Body.Bytes())
	for _, want := range []string{"kern.log", "syslog", "journal/a.log", "journal/sub/b.log"} {
		if !containsStr(names, want) {
			t.Fatalf("tar missing %q, got %v", want, names)
		}
	}
	if containsStr(names, "app.sock") {
		t.Fatalf("socket should be skipped, got %v", names)
	}
}

func TestDownloadLogsQueryToken(t *testing.T) {
	root := fixture(t)
	r := newTestRouter(t, root)
	tok := testToken(t)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/logs/download?token="+tok, nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("query token status=%d want 200", w.Code)
	}
	if len(w.Body.Bytes()) == 0 {
		t.Fatal("empty stream body")
	}
}

func TestLogOverviewAggregation(t *testing.T) {
	root := fixture(t)
	r := newTestRouter(t, root)
	tok := testToken(t)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/logs/overview", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d want 200, body=%s", w.Code, w.Body.String())
	}

	var resp struct {
		Code   int `json:"code"`
		Result struct {
			Root         string          `json:"root"`
			TotalSize    int64           `json:"total_size"`
			TotalEntries int             `json:"total_entries"`
			Entries      []OverviewEntry `json:"entries"`
		} `json:"result"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v, body=%s", err, w.Body.String())
	}
	if resp.Code != 0 {
		t.Fatalf("code=%d", resp.Code)
	}
	// kern.log 1024 + syslog 512 + journal(64+32)=96 → 1632
	if resp.Result.TotalSize != 1632 {
		t.Fatalf("total_size=%d want 1632", resp.Result.TotalSize)
	}
	// 条目数 = 各顶层条目子项数之和（不含顶层自身）：
	// kern.log 1 + syslog 1 + journal(3: a.log/sub/b.log) + dmesg 1 = 6；socket 跳过
	if resp.Result.TotalEntries != 6 {
		t.Fatalf("total_entries=%d want 6", resp.Result.TotalEntries)
	}

	byName := map[string]OverviewEntry{}
	for _, e := range resp.Result.Entries {
		byName[e.Name] = e
	}
	je, ok := byName["journal"]
	if !ok {
		t.Fatalf("journal entry missing: %+v", resp.Result.Entries)
	}
	if je.Type != "dir" || je.Size != 96 || je.Files != 3 {
		t.Fatalf("journal entry=%+v want dir/96/3", je)
	}
	if de, ok := byName["dmesg"]; !ok || de.Type != "symlink" || de.Size != 0 {
		t.Fatalf("dmesg entry=%+v want symlink/0", de)
	}
	if _, ok := byName["app.sock"]; ok {
		t.Fatal("socket should be skipped in overview")
	}
}

func TestLogOverviewNoAuth(t *testing.T) {
	root := fixture(t)
	r := newTestRouter(t, root)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/logs/overview", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	// 无 token：路由在 Auth 组外注册时 handler 应自行拒绝
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d want 401", w.Code)
	}
}

// --- helpers ---

func readTarNames(t *testing.T, gz []byte) []string {
	t.Helper()
	zr, err := gzip.NewReader(strings.NewReader(string(gz)))
	if err != nil {
		t.Fatalf("gzip open: %v", err)
	}
	defer zr.Close()
	tr := tar.NewReader(zr)
	var names []string
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("tar next: %v", err)
		}
		names = append(names, hdr.Name)
	}
	return names
}

func containsStr(s []string, want string) bool {
	for _, v := range s {
		if v == want {
			return true
		}
	}
	return false
}
