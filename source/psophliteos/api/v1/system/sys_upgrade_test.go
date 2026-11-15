package system

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"sophliteos/database"
	"sophliteos/global"

	"github.com/gin-gonic/gin"
	"github.com/jinzhu/gorm"
)

// setupDatabase 用 in-memory sqlite 初始化 database.DB，避免操作日志路径因
// DB 为 nil 而 panic（旧实现会调 SaveOptLog；修复后不再调用，保留以防回归）。
func setupDatabase(t *testing.T) {
	t.Helper()
	sqlDb, err := sql.Open("sqlite3_with_go_func", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	oldDB := database.DB
	db, err := gorm.Open("sqlite3", sqlDb)
	if err != nil {
		t.Fatal(err)
	}
	database.DB = db
	t.Cleanup(func() {
		_ = db.Close()
		database.DB = oldDB
	})
}

// 旧升级接口（/api/upgrade、/api/upgrade/confirm）的自升级实现已在 MYS-2882/MYS-2885
// 明确下线：这两个端点只返回"暂不支持"的非零业务码，不做任何副作用。
// 以下用例逐条锁定该契约：
//   - 合法名/非法名/任意内容一律失败，且失败信息明确指向"使用正式发布的软件包"；
//   - 不落盘（multipart 根本不被解析），因此无法截断 /data/sophliteos 下同名文件；
//   - 不置 BlockAllRequests、不触发 Exec/重启、不留存"待确认"状态。

// upgradeResp 升级接口对外返回的结构（与 mvc.Result 对应）。
type upgradeResp struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
}

// legacyUpgradeMsg 旧升级接口的统一失败提示。
const legacyUpgradeMsg = "此升级方式暂不支持，请使用正式发布的软件包"

// newUpgradeUploadRequest 构造携带升级包的 multipart 上传请求。
func newUpgradeUploadRequest(t *testing.T, filename string, content []byte) *http.Request {
	t.Helper()
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/upgrade", body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	return req
}

// doUpgrade 经真实 gin 路由投递请求（与生产路由同名路径）。
func doUpgrade(t *testing.T, api *UpgradeApi, req *http.Request) (upgradeResp, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.POST("/api/upgrade", api.Upgrade)
	router.POST("/api/upgrade/confirm", api.UpgradeConfirm)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%q)", w.Code, w.Body.String())
	}
	var resp upgradeResp
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid json %q: %v", w.Body.String(), err)
	}
	return resp, w
}

// assertLegacyRejected 断言一次旧升级请求被明确拒绝且无副作用。
func assertLegacyRejected(t *testing.T, resp upgradeResp) {
	t.Helper()
	if resp.Code == 0 {
		t.Fatalf("旧升级接口必须返回非零业务码，实际 code=0 msg=%q（假成功）", resp.Msg)
	}
	if !strings.Contains(resp.Msg, "暂不支持") || !strings.Contains(resp.Msg, "正式发布") {
		t.Fatalf("失败提示不明确: msg=%q, want 含 %q", resp.Msg, legacyUpgradeMsg)
	}
	if global.BlockAllRequests {
		t.Fatal("旧升级接口不得设置 BlockAllRequests（会令全平台 503）")
	}
}

// TestLegacyUpgradeRejectedForAnyFile 合法包名/非法包名/任意内容都不得成功，
// 且 multipart 不被解析、不产生任何临时文件或落盘。
func TestLegacyUpgradeRejectedForAnyFile(t *testing.T) {
	setupDatabase(t)
	gin.SetMode(gin.TestMode)
	oldBlock := global.BlockAllRequests
	global.BlockAllRequests = false
	t.Cleanup(func() { global.BlockAllRequests = oldBlock })

	// multipart 解析把大文件缓冲到 os.TempDir()：指向测试私有目录即可观测是否产生临时文件
	tmpRoot := t.TempDir()
	t.Setenv("TMPDIR", tmpRoot)

	api := &UpgradeApi{}
	cases := []struct {
		name     string
		filename string
		content  []byte
	}{
		{"合法包名", "sophliteos-linux_arm64.tgz", []byte("fake upgrade package")},
		{"非法包名", "evil.sh", []byte("#!/bin/sh\nrm -rf /\n")},
		{"空内容", "sophliteos-linux_arm64.tgz", nil},
		{"超长文件名", strings.Repeat("a", 200) + ".tgz", []byte("x")},
		{"隐藏文件", ".profile", []byte("x")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := newUpgradeUploadRequest(t, tc.filename, tc.content)
			resp, _ := doUpgrade(t, api, req)
			assertLegacyRejected(t, resp)
			if req.MultipartForm != nil {
				t.Fatal("旧升级接口不得解析 multipart（解析即会把上传内容落到临时目录）")
			}
			entries, err := os.ReadDir(tmpRoot)
			if err != nil {
				t.Fatal(err)
			}
			if len(entries) != 0 {
				names := make([]string, 0, len(entries))
				for _, e := range entries {
					names = append(names, e.Name())
				}
				t.Fatalf("旧升级接口残留临时文件: %v", names)
			}
		})
	}
}

// TestLegacyUpgradeConfirmRejected 确认端点同样明确失败，不置阻塞、不重启。
func TestLegacyUpgradeConfirmRejected(t *testing.T) {
	setupDatabase(t)
	gin.SetMode(gin.TestMode)
	oldBlock := global.BlockAllRequests
	global.BlockAllRequests = false
	t.Cleanup(func() { global.BlockAllRequests = oldBlock })

	api := &UpgradeApi{}
	resp, _ := doUpgrade(t, api, httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil))
	assertLegacyRejected(t, resp)
	// 再确认一次也不能变成成功（幂等拒绝）
	resp, _ = doUpgrade(t, api, httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil))
	assertLegacyRejected(t, resp)
}

// TestLegacyUpgradeLeavesServiceDirUntouched 旧接口不得改动服务目录（默认 /data/sophliteos/）：
// 目录内既有文件（含与升级包同名的普通文件、二进制本体）保持大小/修改时间不变，
// 且不新增任何条目 —— 这正是原缺陷（先 O_TRUNC 再校验文件名，可截断服务目录内
// 任意普通名字文件）的复现路径。
//
// 因目标目录是设备上真实的服务目录，默认不执行：万一将来回归，本用例会真的改动
// 现场文件。验收时以 MYS2885_SERVICE_DIR 显式指定（可指向真实目录或其副本）后运行：
//
//	MYS2885_SERVICE_DIR=/data/sophliteos/ go test ./api/v1/system -run TestLegacyUpgradeLeavesServiceDirUntouched -v
func TestLegacyUpgradeLeavesServiceDirUntouched(t *testing.T) {
	serviceDir := os.Getenv("MYS2885_SERVICE_DIR")
	if serviceDir == "" {
		t.Skip("未设置 MYS2885_SERVICE_DIR：跳过真实服务目录断言（验收时显式指定）")
	}
	if !strings.HasSuffix(serviceDir, "/") {
		serviceDir += "/"
	}
	if fi, err := os.Stat(serviceDir); err != nil || !fi.IsDir() {
		t.Fatalf("%s 不存在或不是目录: %v", serviceDir, err)
	}
	before, err := snapshotDir(serviceDir)
	if err != nil {
		t.Fatalf("无法读取 %s: %v", serviceDir, err)
	}

	setupDatabase(t)
	gin.SetMode(gin.TestMode)
	oldBlock := global.BlockAllRequests
	global.BlockAllRequests = false
	t.Cleanup(func() { global.BlockAllRequests = oldBlock })

	api := &UpgradeApi{}
	// 目标文件名取服务目录里真实存在的条目：旧实现会先 O_TRUNC 再校验文件名，
	// 因此这正是原缺陷（截断服务目录内同名文件）的复现路径。
	victims := make([]string, 0, len(before))
	for name := range before {
		if fi, err := os.Stat(serviceDir + name); err == nil && fi.Mode().IsRegular() {
			victims = append(victims, name)
		}
	}
	victims = append(victims, "sophliteos-linux_arm64.tgz") // 旧实现的标准升级包名
	for _, name := range victims {
		resp, _ := doUpgrade(t, api, newUpgradeUploadRequest(t, name, []byte("truncate me")))
		assertLegacyRejected(t, resp)
	}

	after, err := snapshotDir(serviceDir)
	if err != nil {
		t.Fatalf("读取 %s 失败: %v", serviceDir, err)
	}
	for name, want := range before {
		got, ok := after[name]
		if !ok {
			t.Fatalf("服务目录条目 %q 被删除", name)
		}
		if got != want {
			t.Fatalf("服务目录条目 %q 被改动: before=%+v after=%+v", name, want, got)
		}
	}
	for name := range after {
		if _, ok := before[name]; !ok {
			t.Fatalf("旧升级接口在服务目录新增条目 %q", name)
		}
	}
}

// dirEntryState 目录条目快照：大小 + 修改时间 + 是否普通文件。
type dirEntryState struct {
	Size  int64
	MTime int64
	Mode  os.FileMode
}

func snapshotDir(dir string) (map[string]dirEntryState, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	out := make(map[string]dirEntryState, len(entries))
	for _, e := range entries {
		fi, err := e.Info()
		if err != nil {
			return nil, err
		}
		out[e.Name()] = dirEntryState{Size: fi.Size(), MTime: fi.ModTime().UnixNano(), Mode: fi.Mode()}
	}
	return out, nil
}

// TestSaveFileStillWorksForOTA 保留的 saveFile（供 sys_ota.go 使用）仍能正常落盘，
// 并拒绝非法文件名、清理 multipart 临时文件，保证 OTA 上传不被本次改动破坏。
func TestSaveFileStillWorksForOTA(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "final")
	tmpRoot := filepath.Join(root, "tmp")
	if err := os.MkdirAll(tmpRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMPDIR", tmpRoot)

	req := newUpgradeUploadRequest(t, "firmware.tgz", []byte("payload"))
	name, err := saveFile(req, dir+"/")
	if err != nil {
		t.Fatalf("saveFile 正常包名失败: %v", err)
	}
	if name != "firmware.tgz" {
		t.Fatalf("saveFile name=%q want firmware.tgz", name)
	}
	got, err := os.ReadFile(filepath.Join(dir, "firmware.tgz"))
	if err != nil || string(got) != "payload" {
		t.Fatalf("saveFile 落盘内容不符: %q err=%v", got, err)
	}
	if entries, err := os.ReadDir(tmpRoot); err != nil || len(entries) != 0 {
		t.Fatalf("saveFile 成功路径残留 multipart 临时文件: %v err=%v", entries, err)
	}

	// 非法文件名：拒绝，且目录内除已保存的那个包外不新增任何条目
	for _, badName := range []string{"..", ".", ".hidden", `a\b`, strings.Repeat("a", 200)} {
		req := newUpgradeUploadRequest(t, badName, []byte("payload"))
		if _, err := saveFile(req, dir+"/"); err == nil {
			t.Fatalf("saveFile 应拒绝非法文件名 %q", badName)
		}
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "firmware.tgz" {
		names := make([]string, 0, len(entries))
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("非法文件名不应产生条目, 目录内容=%v", names)
	}
	if entries, err := os.ReadDir(tmpRoot); err != nil || len(entries) != 0 {
		t.Fatalf("saveFile 失败路径残留 multipart 临时文件: %v err=%v", entries, err)
	}
}

// TestSaveFileNeverEscapesTargetDir 上传名带目录信息时（"a/b" 这类会被 multipart
// 解析层 filepath.Base 归一化为 "b"），落点必须仍在目标目录内，目标目录之外不得被写入。
func TestSaveFileNeverEscapesTargetDir(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "final")
	outside := filepath.Join(root, "outside")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMPDIR", outside)

	cases := []string{"a/b", "../escape.tgz", "../../escape.tgz", "/etc/escape.tgz"}
	for _, raw := range cases {
		req := newUpgradeUploadRequest(t, raw, []byte("payload"))
		name, err := saveFile(req, dir+"/")
		if err != nil {
			continue // 拒绝也是合法结果
		}
		if strings.ContainsAny(name, "/\\") || name == ".." || name == "." {
			t.Fatalf("saveFile 接受了带路径成分的文件名 %q -> %q", raw, name)
		}
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			t.Fatalf("saveFile 返回 %q 但目标目录内不存在该文件: %v", name, err)
		}
	}
	// 目标目录之外（root 及其它子目录）不应出现任何 escape* 文件
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() {
			if e.Name() == filepath.Base(dir) {
				continue // 目标目录本身
			}
			sub, err := os.ReadDir(filepath.Join(root, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			for _, se := range sub {
				if strings.HasPrefix(se.Name(), "escape") {
					t.Fatalf("上传写到目标目录之外: %s/%s", e.Name(), se.Name())
				}
			}
			continue
		}
		if strings.HasPrefix(e.Name(), "escape") {
			t.Fatalf("上传写到目标目录之外: %s", e.Name())
		}
	}
}

// TestSaveFileCleansMultipartTempOnReject 非法文件名被拒时同样要清理 multipart
// 临时文件（旧实现直接 return，RemoveAll 不可达，临时文件泄漏）。
func TestSaveFileCleansMultipartTempOnReject(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "final")
	tmpRoot := filepath.Join(root, "tmp")
	if err := os.MkdirAll(tmpRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMPDIR", tmpRoot)

	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	part, err := w.CreateFormFile("file", ".hidden") // 以 '.' 开头的名字必须被拒绝
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(bytes.Repeat([]byte("x"), 8192)); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/upgrade", body)
	req.Header.Set("Content-Type", w.FormDataContentType())
	// 1 字节内存阈值：文件内容必然被缓冲到 os.TempDir()
	if err := req.ParseMultipartForm(1); err != nil {
		t.Fatalf("parse multipart: %v", err)
	}
	if entries, err := os.ReadDir(tmpRoot); err != nil || len(entries) == 0 {
		t.Fatalf("前置条件不成立：期望 multipart 已落到临时目录, entries=%v err=%v", entries, err)
	}
	if _, err := saveFile(req, dir+"/"); err == nil {
		t.Fatal("saveFile 应拒绝非法文件名")
	}
	if entries, err := os.ReadDir(tmpRoot); err != nil || len(entries) != 0 {
		t.Fatalf("saveFile 失败路径残留 multipart 临时文件: %v err=%v", entries, err)
	}
}
