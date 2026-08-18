package system

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"sophliteos/database"
	"sophliteos/global"

	"github.com/gin-gonic/gin"
	"github.com/jinzhu/gorm"
)

// 升级接口对外返回的结构（与 mvc.Result 对应）
type upgradeResp struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
}

// newUpgradeUploadRequest 构造携带升级包的 multipart 上传请求。
func newUpgradeUploadRequest(t *testing.T, filename string) *http.Request {
	t.Helper()
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write([]byte("fake upgrade package")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/upgrade", body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	return req
}

func doUpgrade(t *testing.T, api *UpgradeApi, req *http.Request) upgradeResp {
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
	return resp
}

// setupDatabase 用 in-memory sqlite 初始化 database.DB，保证 SaveOptLog 等
// 数据库查询路径不因 DB 为 nil 而 panic（生产环境由 InitDB 初始化）。
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

// waitUpgradeDone 阻塞直到后台重启流程完成：注入的 execSelf 必然失败，
// 失败回滚会复位 upgradeInFlight，此函数等待其复位，保证测试结束时无遗留
// goroutine 读写注入点（否则会与后续测试的 setup 竞争）。
func waitUpgradeDone(t *testing.T) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		upgradeMu.Lock()
		done := !upgradeInFlight
		upgradeMu.Unlock()
		if done {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("等待升级流程完成超时")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// setupUpgradeTest 备份/恢复升级流程的全局状态与注入点，避免测试相互污染。
// 默认把重启延迟拉到极大并注入安全的 execSelf，防止测试进程真的被 syscall.Exec 替换。
// 启动重启 goroutine 的测试需自行覆盖注入点并在结束前 waitUpgradeDone。
func setupUpgradeTest(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	setupDatabase(t)

	upgradeMu.Lock()
	oldPending, oldInFlight := pendingUpgrade, upgradeInFlight
	pendingUpgrade, upgradeInFlight = false, false
	upgradeMu.Unlock()

	// 注入点（restartDelay/execSelf）由各测试自行设置且不做恢复：
	// confirm 启动的后台重启 goroutine 可能晚于本测试的 Cleanup 才访问它们，
	// 恢复写入会与之竞争；测试进程独立，注入值不会泄漏到其他测试。
	oldBlock := global.BlockAllRequests
	restartDelay = 24 * time.Hour
	execSelf = func() error { return errors.New("execSelf disabled in test") }

	t.Cleanup(func() {
		upgradeMu.Lock()
		pendingUpgrade, upgradeInFlight = oldPending, oldInFlight
		upgradeMu.Unlock()
		global.BlockAllRequests = oldBlock
	})
}

// TestUpgradeTwoPhaseFlow 验证两段式流程：
// 上传只暂存不执行，确认后才置 BlockAllRequests 并进入升级中状态；期间并发请求被拒绝。
func TestUpgradeTwoPhaseFlow(t *testing.T) {
	setupUpgradeTest(t)
	// 确认后会启动重启 goroutine：注入短延迟 + 必然失败的 execSelf，
	// 断言窗口（毫秒级）内 goroutine 尚未执行，测试结束时等待其完成。
	restartDelay = time.Second
	execSelf = func() error { return errors.New("exec disabled in test") }
	api := &UpgradeApi{}

	// 第一次上传：仅暂存，不应触发阻塞
	resp := doUpgrade(t, api, newUpgradeUploadRequest(t, "sophliteos-linux_arm64.tgz"))
	if resp.Code != 0 {
		t.Fatalf("upload resp code = %d, msg=%q; want 0", resp.Code, resp.Msg)
	}
	if global.BlockAllRequests {
		t.Fatal("暂存阶段不应设置 BlockAllRequests")
	}
	upgradeMu.Lock()
	pending := pendingUpgrade
	upgradeMu.Unlock()
	if !pending {
		t.Fatal("上传后应处于待确认（pending）状态")
	}

	// 确认执行：置 BlockAllRequests，进入升级中
	req := httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil)
	resp = doUpgrade(t, api, req)
	if resp.Code != 0 {
		t.Fatalf("confirm resp code = %d, msg=%q; want 0", resp.Code, resp.Msg)
	}
	if !global.BlockAllRequests {
		t.Fatal("确认执行后应设置 BlockAllRequests")
	}
	upgradeMu.Lock()
	inflight, pending := upgradeInFlight, pendingUpgrade
	upgradeMu.Unlock()
	if !inflight || pending {
		t.Fatalf("确认后状态: inflight=%v pending=%v; want inflight=true pending=false", inflight, pending)
	}

	// 升级中：再次上传与再次确认都应被拒绝
	resp = doUpgrade(t, api, newUpgradeUploadRequest(t, "sophliteos-linux_arm64.tgz"))
	if resp.Code == 0 {
		t.Fatalf("升级中上传应被拒绝, msg=%q", resp.Msg)
	}
	resp = doUpgrade(t, api, httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil))
	if resp.Code == 0 {
		t.Fatalf("升级中二次确认应被拒绝, msg=%q", resp.Msg)
	}

	// 等待后台重启流程完成（exec 失败回滚），避免遗留 goroutine 影响后续测试
	waitUpgradeDone(t)
}

// TestUpgradeConfirmWithoutPending 验证无暂存包时确认被拒绝。
func TestUpgradeConfirmWithoutPending(t *testing.T) {
	setupUpgradeTest(t)
	api := &UpgradeApi{}

	resp := doUpgrade(t, api, httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil))
	if resp.Code == 0 {
		t.Fatalf("无暂存包时确认应被拒绝, msg=%q", resp.Msg)
	}
	if global.BlockAllRequests {
		t.Fatal("确认失败不应设置 BlockAllRequests")
	}
}

// TestUpgradeConcurrentConfirm 验证并发 confirm：恰好一个成功，其余返回明确错误（幂等）。
func TestUpgradeConcurrentConfirm(t *testing.T) {
	setupUpgradeTest(t)
	// 与 TestUpgradeTwoPhaseFlow 相同：短延迟 + 失败 execSelf，断言后等待完成
	restartDelay = time.Second
	execSelf = func() error { return errors.New("exec disabled in test") }
	api := &UpgradeApi{}

	upgradeMu.Lock()
	pendingUpgrade = true
	upgradeMu.Unlock()

	const n = 10
	router := gin.New()
	router.POST("/api/upgrade/confirm", api.UpgradeConfirm)

	var wg sync.WaitGroup
	codes := make([]int, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			w := httptest.NewRecorder()
			router.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/upgrade/confirm", nil))
			var resp upgradeResp
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
				t.Errorf("invalid json %q: %v", w.Body.String(), err)
				return
			}
			codes[i] = resp.Code
		}(i)
	}
	wg.Wait()

	success := 0
	for _, code := range codes {
		if code == 0 {
			success++
		}
	}
	if success != 1 {
		t.Fatalf("并发确认成功次数 = %d, want 1 (codes=%v)", success, codes)
	}
	if !global.BlockAllRequests {
		t.Fatal("并发确认后应有一个请求成功设置 BlockAllRequests")
	}
	// 等待后台重启流程完成（exec 失败回滚），避免遗留 goroutine 影响后续测试
	waitUpgradeDone(t)
}

// TestUpgradeRejectsBadFilename 验证非法升级包名在暂存阶段就被拒绝。
func TestUpgradeRejectsBadFilename(t *testing.T) {
	setupUpgradeTest(t)
	api := &UpgradeApi{}

	resp := doUpgrade(t, api, newUpgradeUploadRequest(t, "evil.sh"))
	if resp.Code == 0 {
		t.Fatalf("非法文件名上传应被拒绝, msg=%q", resp.Msg)
	}
	upgradeMu.Lock()
	pending := pendingUpgrade
	upgradeMu.Unlock()
	if pending {
		t.Fatal("非法文件名不应进入 pending 状态")
	}
}

// TestRestartExecFailureRollback 验证 syscall.Exec 失败时回滚 BlockAllRequests 与 in-flight 状态，
// 平台继续提供服务而非永久 503。
func TestRestartExecFailureRollback(t *testing.T) {
	setupUpgradeTest(t)

	upgradeMu.Lock()
	upgradeInFlight = true
	upgradeMu.Unlock()
	global.BlockAllRequests = true

	restartDelay = 0
	execSelf = func() error { return errors.New("binary replaced or missing") }

	// 同步调用重启流程（生产环境经 go 调用；注入的 execSelf 必然失败）
	restartUpgradedProgram("sophliteos-linux_arm64.tgz")

	if global.BlockAllRequests {
		t.Fatal("Exec 失败后应回滚 BlockAllRequests，避免平台永久 503")
	}
	upgradeMu.Lock()
	inflight := upgradeInFlight
	upgradeMu.Unlock()
	if inflight {
		t.Fatal("Exec 失败后应复位 upgradeInFlight，允许后续重新升级")
	}
}
