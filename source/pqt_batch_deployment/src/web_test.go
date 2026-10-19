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
	"sync"
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

// 执行期间必须锁住**所有**会改配置的入口。
// 早先只锁了 device/op，config 与 presets 漏了——执行中用「载入预设」会整体
// 替换设备表，导致在途事件写到已经不存在的位置，日志与状态全错位。
func TestWebAllMutatingEndpointsLockedWhileRunning(t *testing.T) {
	ws, srv := newTestWeb(t)

	ws.mu.Lock()
	ws.running = true
	ws.mu.Unlock()
	defer func() {
		ws.mu.Lock()
		ws.running = false
		ws.mu.Unlock()
	}()

	cases := []struct {
		name string
		path string
		body any
	}{
		{"导入配置", "/api/config", map[string]any{
			"remoteInf":    []any{map[string]any{"IP": "1.1.1.1", "Port": 22, "Username": "u"}},
			"operationInf": []any{map[string]any{"name": "x", "type": 0, "commandStr": "date"}},
		}},
		{"载入预设", "/api/presets", map[string]any{"name": BuiltinPresets()[0]}},
		{"改设备", "/api/device", map[string]any{"action": "add",
			"device": map[string]any{"IP": "1.1.1.1", "Port": 22, "Username": "u"}}},
		{"改操作", "/api/op", map[string]any{"action": "remove", "index": 0}},
		{"改设置", "/api/settings", map[string]any{"maxParallel": 5}},
	}
	for _, c := range cases {
		resp, _ := postJSON(t, srv, c.path, c.body)
		if resp.StatusCode != http.StatusConflict {
			t.Errorf("%s: 状态码 = %d, 期望 409（执行期必须只读）", c.name, resp.StatusCode)
		}
	}
}

// 根目录与并行上限必须真的落到服务端——执行时读的是服务端的值。
// 早先这两个值只改前端 JS，界面显示新值、实际执行仍用旧值。
func TestWebSettingsPersist(t *testing.T) {
	ws, srv := newTestWeb(t)

	dir := t.TempDir()
	resp, body := postJSON(t, srv, "/api/settings", map[string]any{
		"rootDir": dir, "maxParallel": 7,
	})
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("设置状态码 = %d, body=%s", resp.StatusCode, body)
	}
	if ws.state.RootDir() != dir {
		t.Fatalf("根目录未保存: got %q want %q", ws.state.RootDir(), dir)
	}
	if ws.state.MaxParallel() != 7 {
		t.Fatalf("并行上限未保存: got %d", ws.state.MaxParallel())
	}

	// 不存在的目录必须拒绝（否则执行时才失败，且报错位置远离问题）
	resp, _ = postJSON(t, srv, "/api/settings", map[string]any{
		"rootDir": "/definitely/not/a/dir/xyz",
	})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("非法根目录状态码 = %d, 期望 400", resp.StatusCode)
	}
	if ws.state.RootDir() != dir {
		t.Fatal("被拒绝的设置不应改动已有值")
	}
}

// handleRun 的 running 抢占必须是原子的：并发 POST 只能有一个真正开跑，
// 否则两轮执行同时进行，cancel 只能杀掉其中一轮。
//
// 关键是要**真并发**地打进去，而不是等第一轮置位后再打——后者无论如何都过。
// 用「服务端收下命令后永不回应」让胜出的那轮保持在进行中，便于断言与清场。
func TestWebRunIsExclusive(t *testing.T) {
	srvSSH := newTestSSHServer(t)
	srvSSH.SetHangCommand(true)

	ws, srv := newTestWeb(t)
	postJSON(t, srv, "/api/config", map[string]any{
		"remoteInf": []any{map[string]any{
			"IP": "127.0.0.1", "Port": srvSSH.Port(), "Username": "u", "Password": "p"}},
		"operationInf": []any{map[string]any{"name": "c", "type": 0, "commandStr": "hang"}},
	})

	// 多轮并发，每轮都从"无人执行"状态起跑，放大竞争窗口。
	const rounds, perRound = 30, 8
	for r := 0; r < rounds; r++ {
		var wg sync.WaitGroup
		start := make(chan struct{})
		codes := make([]int, perRound)
		for i := 0; i < perRound; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				<-start // 同一个起跑线
				resp, _ := postJSON(t, srv, "/api/run", nil)
				codes[i] = resp.StatusCode
			}(i)
		}
		close(start)
		wg.Wait()

		ok, conflict := 0, 0
		for _, c := range codes {
			switch c {
			case http.StatusOK:
				ok++
			case http.StatusConflict:
				conflict++
			}
		}
		if ok != 1 || conflict != perRound-1 {
			t.Fatalf("第 %d 轮: 成功 %d 次、409 %d 次（期望 1 / %d），codes=%v",
				r+1, ok, conflict, perRound-1, codes)
		}

		// 清场：中止并等它退出，再进入下一轮
		postJSON(t, srv, "/api/cancel", nil)
		deadline := time.Now().Add(15 * time.Second)
		for ws.isRunning() && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
		if ws.isRunning() {
			t.Fatalf("第 %d 轮: 取消后仍未退出", r+1)
		}
	}
}

// 校验失败时 running 必须被放回去，否则界面永远卡在"执行中"。
func TestWebRunReleasesLockOnValidationFailure(t *testing.T) {
	ws, srv := newTestWeb(t)
	postJSON(t, srv, "/api/config", map[string]any{
		"remoteInf":    []any{map[string]any{"IP": "127.0.0.1", "Port": 1, "Username": "u"}},
		"operationInf": []any{map[string]any{"name": "空", "type": 0, "commandStr": "  "}},
	})
	resp, _ := postJSON(t, srv, "/api/run", nil)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("状态码 = %d, 期望 400", resp.StatusCode)
	}
	if ws.isRunning() {
		t.Fatal("校验失败后 running 必须复位，否则界面永久锁定")
	}
}

// 含明文 SSH 密码的响应不能被浏览器缓存。
func TestWebResponsesNotCached(t *testing.T) {
	_, srv := newTestWeb(t)
	for _, p := range []string{"/api/state", "/api/config"} {
		resp, err := http.Get(srv.URL + p)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if cc := resp.Header.Get("Cache-Control"); !strings.Contains(cc, "no-store") {
			t.Errorf("%s 的 Cache-Control = %q, 期望含 no-store", p, cc)
		}
	}
}

// 跨站请求与 DNS rebinding 必须被挡住（配置里有明文密码）。
func TestGuardLocalOrigin(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	h := guardLocalOrigin(next)

	cases := []struct {
		name   string
		host   string
		origin string
		want   int
	}{
		{"本机 Host", "127.0.0.1:8080", "", http.StatusOK},
		{"localhost Host", "localhost:8080", "", http.StatusOK},
		{"本机 Origin", "127.0.0.1:8080", "http://127.0.0.1:8080", http.StatusOK},
		{"外部 Host（DNS rebinding）", "evil.example.com", "", http.StatusForbidden},
		{"外部 Origin（跨站）", "127.0.0.1:8080", "http://evil.example.com", http.StatusForbidden},
		{"IPv6 回环", "[::1]:8080", "", http.StatusOK},
	}
	for _, c := range cases {
		req := httptest.NewRequest(http.MethodPost, "http://"+c.host+"/api/run", nil)
		req.Host = c.host
		if c.origin != "" {
			req.Header.Set("Origin", c.origin)
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != c.want {
			t.Errorf("%s: 状态码 = %d, 期望 %d", c.name, rec.Code, c.want)
		}
	}
}
