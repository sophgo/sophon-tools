package filemanage

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"ssm/pkg/auth"
	"ssm/pkg/response"
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

// newRouter 构建测试路由（用临时目录作 HomeDir 不可行——HomeDir 来自 os/user.Current，
// 但所有测试用绝对路径调 handler，绕过 HomeDir）。
func newRouter(t *testing.T) (*gin.Engine, *Controller) {
	t.Helper()
	r := gin.New()
	ctrl := DefaultController()
	api := r.Group("/api/v1/files")
	api.GET("", ctrl.List)
	api.GET("/content", ctrl.ReadContent)
	api.GET("/download", ctrl.Download)
	api.POST("/upload", ctrl.Upload)
	api.POST("/chmod", ctrl.Chmod)
	api.POST("/chown", ctrl.Chown)
	api.POST("/mkdir", ctrl.Mkdir)
	api.POST("/rename", ctrl.Rename)
	api.DELETE("", ctrl.Delete)
	return r, ctrl
}

// decodeResult 解析响应为 response.Result，t.Fatal 若非预期 code。
func decodeResult(t *testing.T, body []byte, wantCode int) response.Result {
	t.Helper()
	var resp response.Result
	if err := json.Unmarshal(body, &resp); err != nil {
		t.Fatalf("unmarshal response: %v, body=%s", err, string(body))
	}
	if resp.Code != wantCode {
		t.Fatalf("code=%d, want %d, msg=%q, body=%s", resp.Code, wantCode, resp.ErrorMessage, string(body))
	}
	return resp
}

// doReq 发请求并返回 recorder。
func doReq(t *testing.T, r *gin.Engine, method, target, body string, ct string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, target, strings.NewReader(body))
	if ct != "" {
		req.Header.Set("Content-Type", ct)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// writeFile 在 tempdir 创建文件并写入内容。
func writeFile(t *testing.T, tempdir, name, content string) string {
	t.Helper()
	p := filepath.Join(tempdir, name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", p, err)
	}
	return p
}

func TestList(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "a.txt", "hello")
	if err := os.Mkdir(filepath.Join(dir, "sub"), 0o755); err != nil {
		t.Fatal(err)
	}
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodGet, "/api/v1/files?path="+dir, "", "")
	resp := decodeResult(t, w.Body.Bytes(), 0)
	m, _ := resp.Result.(map[string]interface{})
	if m["path"] != dir {
		t.Fatalf("path=%v, want %s", m["path"], dir)
	}
	files, _ := m["files"].([]interface{})
	if len(files) != 2 {
		t.Fatalf("files=%v, want 2 entries", files)
	}
}

func TestReadContent(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "hello world")
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodGet, "/api/v1/files/content?path="+p, "", "")
	resp := decodeResult(t, w.Body.Bytes(), 0)
	m, _ := resp.Result.(map[string]interface{})
	if m["content"] != "hello world" {
		t.Fatalf("content=%v", m["content"])
	}
}

func TestMkdir(t *testing.T) {
	dir := t.TempDir()
	r, _ := newRouter(t)
	body := `{"path":"` + filepath.Join(dir, "newdir") + `"}`
	w := doReq(t, r, http.MethodPost, "/api/v1/files/mkdir", body, "application/json")
	decodeResult(t, w.Body.Bytes(), 0)
	if st, err := os.Stat(filepath.Join(dir, "newdir")); err != nil || !st.IsDir() {
		t.Fatalf("newdir not created: %v", err)
	}
}

// TestMkdirRefuseTopLevel 拒建根下一级目录（/xxx，depth<=1）。
func TestMkdirRefuseTopLevel(t *testing.T) {
	r, _ := newRouter(t)
	body := `{"path":"/should-not-create"}`
	w := doReq(t, r, http.MethodPost, "/api/v1/files/mkdir", body, "application/json")
	resp := decodeResult(t, w.Body.Bytes(), 1)
	if !strings.Contains(resp.ErrorMessage, "top-level") {
		t.Fatalf("err=%q, want top-level", resp.ErrorMessage)
	}
}

func TestRename(t *testing.T) {
	dir := t.TempDir()
	old := writeFile(t, dir, "a.txt", "x")
	newp := filepath.Join(dir, "b.txt")
	r, _ := newRouter(t)
	body := `{"oldPath":"` + old + `","newPath":"` + newp + `"}`
	w := doReq(t, r, http.MethodPost, "/api/v1/files/rename", body, "application/json")
	decodeResult(t, w.Body.Bytes(), 0)
	if _, err := os.Stat(newp); err != nil {
		t.Fatalf("rename target missing: %v", err)
	}
}

func TestChmod(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "x")
	r, _ := newRouter(t)
	body := `{"path":"` + p + `","mode":"0600"}`
	w := doReq(t, r, http.MethodPost, "/api/v1/files/chmod", body, "application/json")
	decodeResult(t, w.Body.Bytes(), 0)
	st, _ := os.Stat(p)
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("mode=%o, want 600", st.Mode().Perm())
	}
}

// TestDeleteFile 删除单个文件成功。
func TestDeleteFile(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "x")
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodDelete, "/api/v1/files?path="+p, "", "")
	decodeResult(t, w.Body.Bytes(), 0)
	if _, err := os.Stat(p); !os.IsNotExist(err) {
		t.Fatalf("file still exists after delete: %v", err)
	}
}

// TestDeleteDirectoryRefused 拒删目录（只删文件）。
func TestDeleteDirectoryRefused(t *testing.T) {
	dir := t.TempDir()
	sub := filepath.Join(dir, "sub")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodDelete, "/api/v1/files?path="+sub, "", "")
	resp := decodeResult(t, w.Body.Bytes(), 1)
	if !strings.Contains(resp.ErrorMessage, "directory") {
		t.Fatalf("err=%q, want directory refusal", resp.ErrorMessage)
	}
	// 目录必须仍在
	if _, err := os.Stat(sub); err != nil {
		t.Fatalf("sub dir should still exist: %v", err)
	}
}

// TestDeleteNoRecursive 不递归：目录非空时拒绝（即便放宽目录限制，os.Remove 也不递归）。
// 这里通过拒目录语义已覆盖；额外验证单文件删除不波及同目录其他文件。
func TestDeleteNoCollateral(t *testing.T) {
	dir := t.TempDir()
	a := writeFile(t, dir, "a.txt", "x")
	writeFile(t, dir, "b.txt", "y")
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodDelete, "/api/v1/files?path="+a, "", "")
	decodeResult(t, w.Body.Bytes(), 0)
	if _, err := os.Stat(filepath.Join(dir, "b.txt")); err != nil {
		t.Fatalf("b.txt should be untouched: %v", err)
	}
}

// TestDeleteRefuseTopLevel 拒删根下一级目录（/tmp 之类 depth=1 路径，即便存在）。
func TestDeleteRefuseTopLevel(t *testing.T) {
	r, _ := newRouter(t)
	// /tmp 是 depth=1（根下一级），拒删
	w := doReq(t, r, http.MethodDelete, "/api/v1/files?path=/tmp", "", "")
	resp := decodeResult(t, w.Body.Bytes(), 1)
	if !strings.Contains(resp.ErrorMessage, "top-level") {
		t.Fatalf("err=%q, want top-level refusal", resp.ErrorMessage)
	}
}

func TestUpload(t *testing.T) {
	dir := t.TempDir()
	r, _ := newRouter(t)
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("file", "up.txt")
	if err != nil {
		t.Fatal(err)
	}
	part.Write([]byte("uploaded content"))
	writer.Close()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/files/upload?path="+dir, body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	decodeResult(t, w.Body.Bytes(), 0)
	got, err := os.ReadFile(filepath.Join(dir, "up.txt"))
	if err != nil || string(got) != "uploaded content" {
		t.Fatalf("uploaded file content=%q err=%v", string(got), err)
	}
}

// TestUploadPathTraversal 上传文件名路径穿越被拒（只取基名）。
func TestUploadPathTraversal(t *testing.T) {
	dir := t.TempDir()
	r, _ := newRouter(t)
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, _ := writer.CreateFormFile("file", "../../escape.txt")
	part.Write([]byte("x"))
	writer.Close()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/files/upload?path="+dir, body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	decodeResult(t, w.Body.Bytes(), 0)
	// 应写入 dir/escape.txt（基名），而非 dir/../../escape.txt
	if _, err := os.Stat(filepath.Join(dir, "escape.txt")); err != nil {
		t.Fatalf("expected dir/escape.txt: %v", err)
	}
}

func TestDownload(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "download me")
	r, _ := newRouter(t)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/download?path="+p+"&token="+testToken(t), nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("code=%d", w.Code)
	}
	if w.Body.String() != "download me" {
		t.Fatalf("body=%q", w.Body.String())
	}
	if !strings.Contains(w.Header().Get("Content-Disposition"), "a.txt") {
		t.Fatalf("content-disposition=%q", w.Header().Get("Content-Disposition"))
	}
}

// TestDownloadNoToken 401 缺 token 拒绝。
func TestDownloadNoToken(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "x")
	r, _ := newRouter(t)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/download?path="+p, nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("code=%d, want 401", w.Code)
	}
}

// TestBlockedPath 禁止访问 /proc /sys /dev。
func TestBlockedPath(t *testing.T) {
	r, _ := newRouter(t)
	w := doReq(t, r, http.MethodGet, "/api/v1/files?path=/proc", "", "")
	resp := decodeResult(t, w.Body.Bytes(), 1)
	if !strings.Contains(resp.ErrorMessage, "not allowed") {
		t.Fatalf("err=%q, want not allowed", resp.ErrorMessage)
	}
}
