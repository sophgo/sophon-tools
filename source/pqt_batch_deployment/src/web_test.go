package main

// Web 接口测试。
//
// 用 httptest 直接打真实 handler，覆盖桌面版与 headless 版共用的这条链路：
// 状态快照、设备/操作增删改、配置导入导出、执行、事件流、执行期只读。
// 不依赖浏览器，也不依赖图形栈（本文件在两种构建下都会跑）。

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func newTestWeb(t *testing.T) (*webServer, *httptest.Server) {
	t.Helper()
	ws := newWebServer()
	mux := http.NewServeMux()
	ws.routes(mux)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return ws, srv
}

func postJSON(t *testing.T, srv *httptest.Server, path string, body any) (*http.Response, []byte) {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&buf).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	resp, err := http.Post(srv.URL+path, "application/json", &buf)
	if err != nil {
		t.Fatalf("POST %s 失败: %v", path, err)
	}
	defer resp.Body.Close()
	out := make([]byte, 0, 4096)
	buf2 := make([]byte, 4096)
	for {
		n, err := resp.Body.Read(buf2)
		out = append(out, buf2[:n]...)
		if err != nil {
			break
		}
	}
	return resp, out
}

// 首页必须能拿到内嵌的 HTML（headless 构建的资源也来自 go:embed）。
func TestWebServesIndex(t *testing.T) {
	_, srv := newTestWeb(t)

	resp, err := http.Get(srv.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("首页状态码 = %d", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); !strings.Contains(ct, "text/html") {
		t.Fatalf("首页 Content-Type = %q", ct)
	}
}

// 初始状态要带上版本、预设、以及默认那一行设备/操作。
func TestWebStateSnapshot(t *testing.T) {
	_, srv := newTestWeb(t)

	resp, err := http.Get(srv.URL + "/api/state")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	var got stateDTO
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if got.Version != Version {
		t.Fatalf("版本 = %q, 期望 %q", got.Version, Version)
	}
	if len(got.Presets) == 0 {
		t.Fatal("预设列表为空")
	}
	if len(got.Devices) != 1 || len(got.Ops) != 1 {
		t.Fatalf("默认应各有一行, 实际 devices=%d ops=%d", len(got.Devices), len(got.Ops))
	}
	if !got.Ops[0].Complete {
		t.Fatal("默认操作应标记为完整")
	}
}

// 设备增删改克隆四个动作都要真的落到状态里。
func TestWebDeviceCRUD(t *testing.T) {
	_, srv := newTestWeb(t)

	// add
	resp, body := postJSON(t, srv, "/api/device", map[string]any{
		"action": "add",
		"device": map[string]any{"IP": "10.0.0.7", "Port": 2222, "Username": "u", "Password": "p"},
	})
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("add 状态码 = %d, body=%s", resp.StatusCode, body)
	}
	var st stateDTO
	_ = json.Unmarshal(body, &st)
	if len(st.Devices) != 2 || st.Devices[1].IP != "10.0.0.7" {
		t.Fatalf("add 后设备 = %+v", st.Devices)
	}

	// update
	resp, body = postJSON(t, srv, "/api/device", map[string]any{
		"action": "update", "index": 1,
		"device": map[string]any{"IP": "10.0.0.8", "Port": 22, "Username": "u2", "Password": "p"},
	})
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("update 状态码 = %d, body=%s", resp.StatusCode, body)
	}
	_ = json.Unmarshal(body, &st)
	if st.Devices[1].IP != "10.0.0.8" || st.Devices[1].Username != "u2" {
		t.Fatalf("update 未生效: %+v", st.Devices[1])
	}

	// clone
	_, body = postJSON(t, srv, "/api/device", map[string]any{"action": "clone", "index": 1})
	_ = json.Unmarshal(body, &st)
	if len(st.Devices) != 3 || st.Devices[2].IP != "10.0.0.8" {
		t.Fatalf("clone 后设备 = %+v", st.Devices)
	}

	// remove
	_, body = postJSON(t, srv, "/api/device", map[string]any{"action": "remove", "index": 1})
	_ = json.Unmarshal(body, &st)
	if len(st.Devices) != 2 {
		t.Fatalf("remove 后设备数 = %d", len(st.Devices))
	}

	// 越界必须报错而不是崩
	resp, _ = postJSON(t, srv, "/api/device", map[string]any{"action": "remove", "index": 99})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("越界 remove 状态码 = %d, 期望 400", resp.StatusCode)
	}
}

// 非法端口必须被拒，避免把明显不可用的配置存进去。
func TestWebDeviceRejectsBadPort(t *testing.T) {
	_, srv := newTestWeb(t)
	resp, _ := postJSON(t, srv, "/api/device", map[string]any{
		"action": "update", "index": 0,
		"device": map[string]any{"IP": "1.2.3.4", "Port": 70000, "Username": "u"},
	})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("非法端口状态码 = %d, 期望 400", resp.StatusCode)
	}
}

// 操作的新增/更新/删除，以及「完整度」判定要跟后端一致。
func TestWebOpCRUDAndCompleteness(t *testing.T) {
	_, srv := newTestWeb(t)

	// 加一条"不完整"的操作（下载但缺目标路径）
	_, body := postJSON(t, srv, "/api/op", map[string]any{
		"action": "add",
		"op": map[string]any{"name": "缺目标", "type": 2,
			"transferFileSourcePath": "/tmp/a", "transferFileDestinationPath": ""},
	})
	var st stateDTO
	_ = json.Unmarshal(body, &st)
	if len(st.Ops) != 2 {
		t.Fatalf("add 后操作数 = %d", len(st.Ops))
	}
	if st.Ops[1].Complete {
		t.Fatal("缺目标路径的操作不应标记为完整")
	}
	if !strings.Contains(st.Ops[1].IncompleteReason, "目标路径") {
		t.Fatalf("不完整原因应说明缺什么, got %q", st.Ops[1].IncompleteReason)
	}

	// 补上目标路径后应变完整
	_, body = postJSON(t, srv, "/api/op", map[string]any{
		"action": "update", "index": 1,
		"op": map[string]any{"name": "补全", "type": 2,
			"transferFileSourcePath": "/tmp/a", "transferFileDestinationPath": "/tmp/dir"},
	})
	_ = json.Unmarshal(body, &st)
	if !st.Ops[1].Complete {
		t.Fatalf("补全后应标记完整, reason=%q", st.Ops[1].IncompleteReason)
	}

	// 删除
	_, body = postJSON(t, srv, "/api/op", map[string]any{"action": "remove", "index": 1})
	_ = json.Unmarshal(body, &st)
	if len(st.Ops) != 1 {
		t.Fatalf("remove 后操作数 = %d", len(st.Ops))
	}
}

// 配置导入/导出必须与旧 JSON 格式双向兼容。
func TestWebConfigRoundTrip(t *testing.T) {
	_, srv := newTestWeb(t)
	legacy := map[string]any{
		"remoteInf": []map[string]any{
			{"IP": "172.16.140.11", "Port": 22, "Username": "linaro", "Password": "linaro"},
		},
		"operationInf": []map[string]any{
			{"name": "检查时间", "type": 0, "commandStr": "date",
				"checkSuccessStr": "", "checkErrorStr": "",
				"transferFileSourcePath": "", "transferFileDestinationPath": "", "checkFile": 0},
		},
	}
	resp, body := postJSON(t, srv, "/api/config", legacy)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("导入状态码 = %d, body=%s", resp.StatusCode, body)
	}

	// 导出的字段名必须仍是旧版大写形式
	r2, err := http.Get(srv.URL + "/api/config")
	if err != nil {
		t.Fatal(err)
	}
	defer r2.Body.Close()
	var raw map[string]any
	if err := json.NewDecoder(r2.Body).Decode(&raw); err != nil {
		t.Fatal(err)
	}
	devs, ok := raw["remoteInf"].([]any)
	if !ok || len(devs) != 1 {
		t.Fatalf("导出 remoteInf 结构错误: %v", raw["remoteInf"])
	}
	d := devs[0].(map[string]any)
	for _, k := range []string{"IP", "Port", "Username", "Password"} {
		if _, ok := d[k]; !ok {
			t.Fatalf("导出缺少旧版字段 %q: %v", k, d)
		}
	}
}

// 空设备列表必须被拒（旧版这里会静默跑空或崩）。
func TestWebConfigRejectsEmptyDevices(t *testing.T) {
	_, srv := newTestWeb(t)
	resp, body := postJSON(t, srv, "/api/config", map[string]any{
		"remoteInf":    []any{},
		"operationInf": []any{map[string]any{"name": "x", "type": 0, "commandStr": "date"}},
	})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("空设备状态码 = %d, 期望 400, body=%s", resp.StatusCode, body)
	}
}

// 全是空操作时不允许执行（否则会"成功执行 0 条"）。
func TestWebRunRejectsNoCompleteOps(t *testing.T) {
	_, srv := newTestWeb(t)
	postJSON(t, srv, "/api/config", map[string]any{
		"remoteInf":    []any{map[string]any{"IP": "127.0.0.1", "Port": 1, "Username": "u"}},
		"operationInf": []any{map[string]any{"name": "空", "type": 0, "commandStr": "  "}},
	})
	resp, body := postJSON(t, srv, "/api/run", nil)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("无完整操作时状态码 = %d, 期望 400, body=%s", resp.StatusCode, body)
	}
}

// 执行期间配置必须只读（否则用户在跑的时候改配置，结果对不上）。
func TestWebConfigLockedWhileRunning(t *testing.T) {
	ws, srv := newTestWeb(t)

	// 手动进入"执行中"状态
	ws.mu.Lock()
	ws.running = true
	ws.mu.Unlock()
	defer func() {
		ws.mu.Lock()
		ws.running = false
		ws.mu.Unlock()
	}()

	resp, _ := postJSON(t, srv, "/api/device", map[string]any{
		"action": "add",
		"device": map[string]any{"IP": "1.1.1.1", "Port": 22, "Username": "u"},
	})
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("执行中改设备状态码 = %d, 期望 409", resp.StatusCode)
	}

	resp, _ = postJSON(t, srv, "/api/op", map[string]any{"action": "remove", "index": 0})
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("执行中改操作状态码 = %d, 期望 409", resp.StatusCode)
	}
}

// 没有任务时点中止应给出明确错误，而不是静默成功。
func TestWebCancelWithoutRun(t *testing.T) {
	_, srv := newTestWeb(t)
	resp, _ := postJSON(t, srv, "/api/cancel", nil)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("未执行时取消状态码 = %d, 期望 409", resp.StatusCode)
	}
}

// 事件流要能收到 start/device/done 三类事件，
// 且**先连流、后执行**这个最常见顺序也不能丢事件。
func TestWebEventsDeliverRunLifecycle(t *testing.T) {
	ws, srv := newTestWeb(t)

	// 指向一个不可达端口：走完连接失败路径，很快出 done
	postJSON(t, srv, "/api/config", map[string]any{
		"remoteInf": []any{
			map[string]any{"IP": "127.0.0.1", "Port": 1, "Username": "u"},
			map[string]any{"IP": "127.0.0.1", "Port": 2, "Username": "u"},
		},
		"operationInf": []any{map[string]any{"name": "c", "type": 0, "commandStr": "date"}},
	})
	ws.state.SetMaxParallel(2)

	// 先订阅
	ch, unsub := ws.bus.subscribe()
	defer unsub()

	resp, body := postJSON(t, srv, "/api/run", nil)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("run 状态码 = %d, body=%s", resp.StatusCode, body)
	}

	seen := map[string]int{}
	deadline := time.After(30 * time.Second)
	for {
		select {
		case ev := <-ch:
			seen[ev.Kind]++
			if ev.Kind == "done" {
				if seen["start"] == 0 {
					t.Fatal("没收到 start 事件")
				}
				if seen["device"] == 0 {
					t.Fatal("没收到任何 device 事件（过程不可见）")
				}
				return
			}
		case <-deadline:
			t.Fatalf("等待 done 超时，已收到: %v", seen)
		}
	}
}

// 单设备日志接口要能取回执行输出。
func TestWebLogEndpoint(t *testing.T) {
	ws, srv := newTestWeb(t)
	ws.state.AppendLog(0, "hello from device\n")

	resp, err := http.Get(srv.URL + "/api/log?index=0")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var got struct {
		Index int    `json:"index"`
		Log   string `json:"log"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(got.Log, "hello from device") {
		t.Fatalf("日志 = %q", got.Log)
	}

	if r, _ := http.Get(srv.URL + "/api/log?index=abc"); r.StatusCode != http.StatusBadRequest {
		t.Fatalf("非法 index 状态码 = %d, 期望 400", r.StatusCode)
	}
}

// 监听地址解析：默认只监听本机，非法地址要报错。
func TestParseWebArgs(t *testing.T) {
	opts, err := parseWebArgs(nil)
	if err != nil {
		t.Fatal(err)
	}
	if opts.Listen != "127.0.0.1:8080" {
		t.Fatalf("默认监听 = %q", opts.Listen)
	}
	if !isLoopback(opts.Listen) {
		t.Fatal("默认必须是回环地址（配置里有明文密码）")
	}

	opts, err = parseWebArgs([]string{"--listen", "0.0.0.0:9000"})
	if err != nil {
		t.Fatal(err)
	}
	if opts.Listen != "0.0.0.0:9000" || isLoopback(opts.Listen) {
		t.Fatalf("显式对外监听解析错误: %+v", opts)
	}

	if _, err := parseWebArgs([]string{"--listen", "8080"}); err == nil {
		t.Fatal("缺少主机名的地址应报错")
	}
	if _, err := parseWebArgs([]string{"--bogus"}); err == nil {
		t.Fatal("未知参数应报错")
	}
}
