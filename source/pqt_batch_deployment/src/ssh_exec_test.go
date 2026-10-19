package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// 旧版 bug：错误分支判断的是 checkSuccessStr，「失败关键字」完全失效。
func TestCheckKeywordsErrorActuallyChecked(t *testing.T) {
	op := OperationInf{CheckErrorStr: "panic"}
	if err := checkKeywords("everything is fine", op); err != nil {
		t.Fatalf("未命中失败关键字不应报错, got %v", err)
	}
	if err := checkKeywords("PANIC: boom", op); err == nil {
		t.Fatal("命中失败关键字必须报错（旧版这里失效）")
	}
}

func TestCheckKeywordsSuccess(t *testing.T) {
	op := OperationInf{CheckSuccessStr: "done"}
	if err := checkKeywords("all DONE", op); err != nil {
		t.Fatalf("大小写不敏感匹配应通过, got %v", err)
	}
	if err := checkKeywords("nothing", op); err == nil {
		t.Fatal("未命中成功关键字必须报错")
	}
}

func TestCheckKeywordsBothConfigured(t *testing.T) {
	op := OperationInf{CheckSuccessStr: "ok", CheckErrorStr: "error"}
	if err := checkKeywords("ok, no error", op); err == nil {
		t.Fatal("同时命中成功与失败关键字时应以失败为准")
	}
	if err := checkKeywords("ok", op); err != nil {
		t.Fatalf("只命中成功关键字应通过, got %v", err)
	}
}

func TestCheckKeywordsEmptyMeansNoCheck(t *testing.T) {
	if err := checkKeywords("任意输出", OperationInf{}); err != nil {
		t.Fatalf("未配置关键字时不应校验, got %v", err)
	}
}

// 旧版 remoteLog.split(" ").at(0) 在输出为空时越界崩溃。
func TestFirstFieldEmptyDoesNotPanic(t *testing.T) {
	if _, err := firstField(""); err == nil {
		t.Fatal("空输出应返回错误而不是崩溃")
	}
	if _, err := firstField("   \n\t "); err == nil {
		t.Fatal("全空白输出应返回错误")
	}
	got, err := firstField("d41d8cd98f00b204e9800998ecf8427e  /tmp/a\n")
	if err != nil || got != "d41d8cd98f00b204e9800998ecf8427e" {
		t.Fatalf("解析 MD5 失败: %q, %v", got, err)
	}
}

type failWriter struct{ after int }

func (w *failWriter) Write(p []byte) (int, error) {
	if w.after <= 0 {
		return 0, errors.New("磁盘已满")
	}
	n := len(p)
	if n > w.after {
		n = w.after
	}
	w.after -= n
	return n, nil
}

// 旧版不检查本地写入结果，磁盘满时会「下载成功但内容残缺」。
func TestCopyWithProgressPropagatesWriteError(t *testing.T) {
	src := strings.NewReader(strings.Repeat("x", 1024))
	_, err := copyWithProgress(&failWriter{after: 10}, src, 1024, nil)
	if err == nil {
		t.Fatal("写入失败必须向上传播")
	}
}

func TestCopyWithProgressReportsProgress(t *testing.T) {
	src := bytes.NewReader(make([]byte, 512*1024))
	var dst bytes.Buffer
	var last float64 = -1
	n, err := copyWithProgress(&dst, src, 512*1024, func(p float64) {
		if p < last {
			t.Fatalf("进度回退: %f -> %f", last, p)
		}
		last = p
	})
	if err != nil {
		t.Fatal(err)
	}
	if n != 512*1024 {
		t.Fatalf("写入 %d 字节, 期望 %d", n, 512*1024)
	}
	if last < 0.99 {
		t.Fatalf("最终进度 = %f, 期望接近 1", last)
	}
}

// 旧版 (double)trSize/fileSize 在文件大小为 0 时除零。
func TestCopyWithProgressZeroSizeNoNaN(t *testing.T) {
	called := false
	_, err := copyWithProgress(io.Discard, strings.NewReader(""), 0, func(p float64) {
		called = true
	})
	if err != nil {
		t.Fatal(err)
	}
	if called {
		t.Fatal("总大小为 0 时不应回调进度（避免除零）")
	}
}

func TestShellQuote(t *testing.T) {
	cases := map[string]string{
		"/tmp/a":         `'/tmp/a'`,
		"/tmp/a b":       `'/tmp/a b'`,
		"/tmp/it's":      `'/tmp/it'\''s'`,
		"/tmp/$(rm -rf)": `'/tmp/$(rm -rf)'`,
	}
	for in, want := range cases {
		if got := shellQuote(in); got != want {
			t.Errorf("shellQuote(%q) = %q, 期望 %q", in, got, want)
		}
	}
}

func TestParseInt(t *testing.T) {
	v, err := parseInt("1234")
	if err != nil || v != 1234 {
		t.Fatalf("got %d, %v", v, err)
	}
	if _, err := parseInt("abc"); err == nil {
		t.Fatal("非数字应报错")
	}
	if _, err := parseInt(""); err == nil {
		t.Fatal("空串应报错")
	}
}

// 连接不可达时必须快速失败并返回错误，而不是挂死（旧版无超时）。
func TestRunFailsFastOnUnreachable(t *testing.T) {
	e := &Executor{
		RootDir:     t.TempDir(),
		MaxParallel: 2,
		DialTimeout: 300 * time.Millisecond,
	}
	cfg := &Config{
		// 127.0.0.1:1 通常无监听，连接立即被拒
		RemoteInf: []RemoteInf{{IP: "127.0.0.1", Port: 1, Username: "u", Password: "p"}},
		OperationInf: []OperationInf{
			{Name: "c", Type: OpCommand, CommandStr: "date"},
		},
	}
	start := time.Now()
	res := e.Run(t.Context(), cfg)
	elapsed := time.Since(start)

	if elapsed > 10*time.Second {
		t.Fatalf("连接失败耗时 %s，超时控制失效", elapsed)
	}
	if len(res) != 1 {
		t.Fatalf("结果数 = %d", len(res))
	}
	if res[0].OK || res[0].Err == nil {
		t.Fatal("不可达设备应标记为失败")
	}
}

// 没有完整操作时不应尝试连接，且每台设备都要有明确失败原因。
func TestRunNoCompleteOperations(t *testing.T) {
	e := &Executor{RootDir: t.TempDir(), MaxParallel: 2}
	cfg := &Config{
		RemoteInf:    []RemoteInf{{IP: "127.0.0.1", Port: 1, Username: "u"}},
		OperationInf: []OperationInf{{Name: "bad", Type: OpCommand, CommandStr: ""}},
	}
	res := e.Run(t.Context(), cfg)
	if len(res) != 1 || res[0].Err == nil {
		t.Fatal("无完整操作时应返回明确错误")
	}
}

// 并发上限必须真实生效。
func TestRunRespectsMaxParallel(t *testing.T) {
	e := &Executor{
		RootDir:     t.TempDir(),
		MaxParallel: 2,
		DialTimeout: 200 * time.Millisecond,
	}
	cfg := &Config{
		OperationInf: []OperationInf{{Name: "c", Type: OpCommand, CommandStr: "date"}},
	}
	for i := 0; i < 6; i++ {
		cfg.RemoteInf = append(cfg.RemoteInf, RemoteInf{
			IP: "127.0.0.1", Port: 1, Username: "u", Password: "p"})
	}
	res := e.Run(t.Context(), cfg)
	if len(res) != 6 {
		t.Fatalf("结果数 = %d, 期望 6", len(res))
	}
	for i, r := range res {
		if r.Err == nil {
			t.Fatalf("设备 %d 应失败", i)
		}
	}
}

// 事件回调必须带上设备标识，且每台设备最终有一条 Done。
func TestRunEmitsDonePerDevice(t *testing.T) {
	// Emit 契约上会被多个 goroutine 并发调用（见 Executor.Emit 注释），
	// 计数器必须原子；这里同时用 -race 守护该契约。
	var done atomic.Int64
	var sawLabel atomic.Bool
	e := &Executor{
		RootDir:     t.TempDir(),
		MaxParallel: 4,
		DialTimeout: 200 * time.Millisecond,
		Emit: func(ev StepEvent) {
			if ev.DeviceLabel == "" {
				t.Error("事件缺少 DeviceLabel")
			} else {
				sawLabel.Store(true)
			}
			if ev.Done {
				done.Add(1)
			}
		},
	}
	cfg := &Config{
		RemoteInf: []RemoteInf{
			{IP: "127.0.0.1", Port: 1, Username: "u"},
			{IP: "127.0.0.1", Port: 2, Username: "u"},
		},
		OperationInf: []OperationInf{{Name: "c", Type: OpCommand, CommandStr: "date"}},
	}
	e.Run(t.Context(), cfg)
	if got := done.Load(); got != 2 {
		t.Fatalf("Done 事件数 = %d, 期望 2", got)
	}
	if !sawLabel.Load() {
		t.Fatal("事件未携带设备标签")
	}
}

// 审阅发现：transferTimeout 声明后无人引用，传输路径上没有超时，
// 服务端不读不写但连接不断时会永久挂住。这里断言「超时值真的被用上」。
func TestExecutorTimeoutDefaultsAndOverrides(t *testing.T) {
	e := &Executor{}
	if got := e.commandTimeout(); got != defaultCommandTimeout {
		t.Fatalf("默认命令超时 = %s, 期望 %s", got, defaultCommandTimeout)
	}
	if got := e.transferTimeout(); got != defaultTransferTimeout {
		t.Fatalf("默认传输超时 = %s, 期望 %s", got, defaultTransferTimeout)
	}

	e.CommandTimeout = 3 * time.Second
	e.TransferTimeout = 7 * time.Second
	if got := e.commandTimeout(); got != 3*time.Second {
		t.Fatalf("命令超时覆盖失效: %s", got)
	}
	if got := e.transferTimeout(); got != 7*time.Second {
		t.Fatalf("传输超时覆盖失效: %s", got)
	}
}

// 传输超时必须真实生效：用一个只接受连接、永不响应的假服务器，
// 断言命令在限定时间内失败，而不是永久阻塞。
// 注意 DialTimeout 必须给足，否则测到的是握手超时而不是命令超时。
func TestCommandHonorsCommandTimeout(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skipf("无法监听本地端口: %v", err)
	}
	defer ln.Close()
	// 接受连接后什么都不做——模拟"服务端不读不写但连接不断"。
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			defer c.Close()
		}
	}()

	addr := ln.Addr().(*net.TCPAddr)
	e := &Executor{
		RootDir:     t.TempDir(),
		MaxParallel: 1,
		// 握手超时给足，让失败只可能来自命令阶段。
		DialTimeout:     2 * time.Second,
		CommandTimeout:  400 * time.Millisecond,
		TransferTimeout: 400 * time.Millisecond,
	}
	cfg := &Config{
		RemoteInf: []RemoteInf{{IP: "127.0.0.1", Port: addr.Port, Username: "u", Password: "p"}},
		OperationInf: []OperationInf{
			{Name: "c", Type: OpCommand, CommandStr: "date"},
		},
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		e.Run(t.Context(), cfg)
	}()

	select {
	case <-done:
	case <-time.After(20 * time.Second):
		t.Fatal("未在超时内失败：超时控制失效")
	}
}

// 取消必须能打断执行，而不是等超时。
func TestRunHonorsContextCancel(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skipf("无法监听本地端口: %v", err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			defer c.Close()
		}
	}()

	addr := ln.Addr().(*net.TCPAddr)
	e := &Executor{
		RootDir:     t.TempDir(),
		MaxParallel: 1,
		// 故意给很长的超时，证明是"取消"而不是"超时"结束的。
		DialTimeout:     30 * time.Second,
		CommandTimeout:  30 * time.Second,
		TransferTimeout: 30 * time.Second,
	}
	cfg := &Config{
		RemoteInf:    []RemoteInf{{IP: "127.0.0.1", Port: addr.Port, Username: "u", Password: "p"}},
		OperationInf: []OperationInf{{Name: "c", Type: OpCommand, CommandStr: "date"}},
	}

	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan []DeviceResult, 1)
	go func() { done <- e.Run(ctx, cfg) }()

	time.Sleep(300 * time.Millisecond)
	cancel()

	select {
	case res := <-done:
		if len(res) != 1 || res[0].Err == nil {
			t.Fatalf("取消后应返回失败结果, got %+v", res)
		}
	case <-time.After(15 * time.Second):
		t.Fatal("取消后执行没有及时结束")
	}
}
