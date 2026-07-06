package ota

import (
	"path/filepath"
	"sync"
	"testing"
	"time"

	"ssm/database"
)

// ---------------------------------------------------------------
// 测试夹具：可注入 runner / flags / 临时 DB
// ---------------------------------------------------------------

// recordingRunner 记录所有调用，可按需返回错误。
type recordingRunner struct {
	mu    sync.Mutex
	calls []runnerCall
	fail  bool // true 则返回错误
}

type runnerCall struct {
	Name string
	Args []string
}

func (r *recordingRunner) run(name string, args ...string) (string, string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.calls = append(r.calls, runnerCall{Name: name, Args: append([]string(nil), args...)})
	if r.fail {
		return "", "simulated failure", errNotImplemented
	}
	return "ok", "", nil
}

func (r *recordingRunner) calls_() []runnerCall {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]runnerCall, len(r.calls))
	copy(out, r.calls)
	return out
}

// fakeFlags 内存 flag 检查器，按 PathConfig 的标志路径比对，可预设 success/error。
// 用指针接收者，便于用例在运行中翻转标志（模拟 ota.sh 写入 /dev/shm 标志）。
type fakeFlags struct {
	success   bool
	error     bool
	logTail   string
	panicLine string
	paths     PathConfig
}

func (f *fakeFlags) Exists(path string) bool {
	if path == f.paths.SuccessFlag {
		return f.success
	}
	if path == f.paths.ErrorFlag {
		return f.error
	}
	return false
}

func (f *fakeFlags) ReadTail(path string, n int) string {
	if path == f.paths.ShellLog {
		return f.logTail
	}
	return ""
}

func (f *fakeFlags) ReadPanicLine(path string) string {
	if path == f.paths.ShellLog {
		return f.panicLine
	}
	return ""
}

// newTestEngine 构造带临时 DB 与可注入依赖的引擎。
// flag 标志路径重定向到临时目录，避免触碰真实 /dev/shm。
// 返回 flags 指针便于用例在运行中翻转 success/error 标志。
func newTestEngine(t *testing.T, dryRun bool) (*Engine, *recordingRunner, *fakeFlags, PathConfig) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := database.InitDB(dbPath)
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	if err := database.Migrate(db); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	runner := &recordingRunner{}
	paths := DefaultPathConfig()
	tmp := t.TempDir()
	paths.SuccessFlag = filepath.Join(tmp, "ota_success_flag")
	paths.ErrorFlag = filepath.Join(tmp, "ota_error_flag")
	paths.ShellLog = filepath.Join(tmp, "ota_shell.sh.log")
	flags := &fakeFlags{paths: paths}
	e := NewEngine(db, runner.run, flags, dryRun, paths)
	e.pollInterval = 5 * time.Millisecond
	return e, runner, flags, paths
}

// waitForStatus 轮询 workflow 状态直到匹配或超时。
func waitForStatus(t *testing.T, e *Engine, id string, want int, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		wf, err := e.Query(id)
		if err == nil && wf.Status == want {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	wf, _ := e.Query(id)
	got := -1
	if wf != nil {
		got = wf.Status
	}
	t.Fatalf("waitForStatus: id=%s want=%d, got=%d (timeout)", id, want, got)
}
