package main

// SSH 执行器。
//
// 与旧版 remotesshoperation.cpp 的关键差异（都是 REVIEW 里已确认的缺陷）：
//  1. 连接/命令/传输全部带超时，挂死设备不会永久占坑（旧版无超时）。
//  2. 不使用 `echo <明文密码> | sudo -S`——那会把密码暴露在 ps 命令行里；
//     改为不依赖 sudo 的只读校验（md5sum 直接执行）。
//  3. 传输后校验失败会明确返回错误，不会「下载成功但内容残缺」。
//  4. 全部错误路径关闭资源，不依赖 goto 清理。
//  5. 用 golang.org/x/crypto/ssh，天然并发安全，不存在旧版 libssh2
//     全局初始化非线程安全的数据竞争。

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

const (
	// 旧版把 10MB 读缓冲作为每个连接对象的成员，默认 200 并发时约 2GB；
	// 这里改为按需分配的中等缓冲，内存占用与并发数线性但系数小得多。
	copyBufSize = 256 * 1024

	// 命令与传输各自的硬上限。超时通过给底层 SSH 连接设 deadline 实现，
	// 因此远端「不读不写但连接不断」时也会被强制打断（仅靠 session 超时做不到）。
	defaultCommandTimeout  = 5 * time.Minute
	defaultTransferTimeout = 30 * time.Minute

	// SSH 连接保活间隔。旧版 libssh2 无 keepalive，链路被中间设备静默丢弃后
	// 读写会永久挂住；这里定期发 keepalive@openssh.com 探测。
	defaultKeepaliveInterval = 30 * time.Second
)

// StepEvent 一条执行进展/结果，UI 与 CLI 共用。
type StepEvent struct {
	DeviceIndex int     // 从 0 开始
	DeviceLabel string  // 例如 172.16.140.11:22
	Stage       string  // 正在做什么
	Log         string  // 输出
	Err         error   // 非空表示该设备本次执行失败
	Done        bool    // 该设备全部操作结束
	OK          bool    // 仅当 Done 为 true 时有效：该设备是否全部成功
	Progress    float64 // 0..1，仅传输类操作有效；负数表示无进度
}

// DeviceResult 单台设备的最终结果。
type DeviceResult struct {
	Remote RemoteInf
	OK     bool
	Log    strings.Builder
	Err    error
}

// Executor 执行一批设备 × 一批操作。
type Executor struct {
	RootDir     string // 相对路径基准目录
	MaxParallel int    // 并发上限

	// 以下三项都可覆盖，便于测试与按现场调整；零值取内置默认。
	DialTimeout     time.Duration
	CommandTimeout  time.Duration
	TransferTimeout time.Duration

	// Emit 若非空，每产生一个事件回调一次；回调可能来自多个 goroutine，
	// 调用方负责自身同步（GUI 侧会转到主线程）。
	Emit func(StepEvent)
}

func (e *Executor) emit(ev StepEvent) {
	if e.Emit != nil {
		e.Emit(ev)
	}
}

// Run 并发执行所有设备，返回按输入顺序排列的结果。
//
// 并发模型刻意用「信号量 + WaitGroup」而不是旧版的 startNum/closeNum 计数器：
// 旧版这两个计数器在第二轮执行时不清零，会串状态。
func (e *Executor) Run(ctx context.Context, cfg *Config) []DeviceResult {
	ops := cfg.CompleteOperations()
	results := make([]DeviceResult, len(cfg.RemoteInf))
	for i, r := range cfg.RemoteInf {
		results[i].Remote = r
	}
	if len(ops) == 0 {
		for i := range results {
			results[i].Err = errors.New("没有配置完整的操作可执行")
		}
		return results
	}

	max := e.MaxParallel
	if max <= 0 {
		max = defaultMaxParallel
	}
	if max > len(cfg.RemoteInf) {
		max = len(cfg.RemoteInf)
	}

	sem := make(chan struct{}, max)
	done := make(chan struct{}, len(cfg.RemoteInf))

	for i := range cfg.RemoteInf {
		i := i
		go func() {
			sem <- struct{}{}
			defer func() { <-sem; done <- struct{}{} }()

			res := &results[i]
			label := fmt.Sprintf("%s:%d", res.Remote.IP, res.Remote.Port)
			e.emit(StepEvent{DeviceIndex: i, DeviceLabel: label, Stage: "连接中", Progress: -1})

			err := e.runDevice(ctx, i, label, res.Remote, ops, res)
			res.OK = err == nil
			res.Err = err
			if err != nil {
				e.emit(StepEvent{DeviceIndex: i, DeviceLabel: label, Err: err, Log: err.Error()})
			}
			e.emit(StepEvent{DeviceIndex: i, DeviceLabel: label, Done: true,
				OK: err == nil, Stage: "结束", Progress: -1})
		}()
	}
	for range cfg.RemoteInf {
		<-done
	}
	return results
}

const defaultMaxParallel = 100

// runDevice 对单台设备依次执行所有操作；任一操作失败即停止该设备。
func (e *Executor) runDevice(ctx context.Context, idx int, label string,
	remote RemoteInf, ops []OperationInf, res *DeviceResult) error {

	dialTimeout := e.DialTimeout
	if dialTimeout <= 0 {
		dialTimeout = dialTimeoutDefault
	}

	cfg := &ssh.ClientConfig{
		User:            remote.Username,
		Auth:            []ssh.AuthMethod{ssh.Password(remote.Password)},
		HostKeyCallback: ssh.InsecureIgnoreHostKey(), // 与旧版行为一致：不做主机密钥校验
		Timeout:         dialTimeout,
	}
	addr := fmt.Sprintf("%s:%d", remote.IP, remote.Port)

	d := netDialer{dialTimeout}
	conn, err := d.DialContext(ctx, "tcp", addr)
	if err != nil {
		return fmt.Errorf("连接失败: %w", err)
	}
	defer conn.Close()

	// 握手也受超时约束，避免半开连接卡死。
	_ = conn.SetDeadline(time.Now().Add(dialTimeout))

	// 取消必须能打断「正在握手」的连接：ssh.NewClientConn 是阻塞调用，
	// 只有底层 conn 被关掉才会返回。这里把 ctx 接到 conn 上。
	hsDone := make(chan struct{})
	defer close(hsDone)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-hsDone:
		}
	}()

	c, chans, reqs, err := ssh.NewClientConn(conn, addr, cfg)
	if err != nil {
		if ctx.Err() != nil {
			return errors.New("已取消")
		}
		return fmt.Errorf("SSH 握手/认证失败: %w", err)
	}
	_ = conn.SetDeadline(time.Time{}) // 握手完成后取消整体 deadline，改由各操作自行限时
	client := ssh.NewClient(c, chans, reqs)
	defer client.Close()

	// 保活 + 取消。旧版既无 keepalive 也无取消入口：链路被中间设备静默丢弃时
	// 读写永久挂住，用户点不到任何能中断的东西。
	stop := make(chan struct{})
	defer close(stop)
	go keepaliveLoop(client, stop)

	go func() {
		select {
		case <-ctx.Done():
			// 关闭客户端会让所有阻塞中的 Read/Write 立即返回，命令与传输都能被打断。
			client.Close()
		case <-stop:
		}
	}()

	var sftpClient *sftp.Client
	getSFTP := func() (*sftp.Client, error) {
		if sftpClient != nil {
			return sftpClient, nil
		}
		s, err := sftp.NewClient(client)
		if err != nil {
			return nil, fmt.Errorf("打开 SFTP 失败: %w", err)
		}
		sftpClient = s
		return s, nil
	}
	defer func() {
		if sftpClient != nil {
			sftpClient.Close()
		}
	}()

	for _, op := range ops {
		e.emit(StepEvent{DeviceIndex: idx, DeviceLabel: label,
			Stage: "执行: " + op.Name, Progress: -1})

		// 每条操作独立限时：deadline 设在底层连接上，因此「服务端不读不写但连接
		// 不断」也能被打断——这正是旧版永久卡住的场景。
		timeout := e.commandTimeout()
		if op.Type != OpCommand {
			timeout = e.transferTimeout()
		}
		_ = conn.SetDeadline(time.Now().Add(timeout))

		out, err := e.runOperation(ctx, client, getSFTP, remote, op, idx, label, timeout)

		_ = conn.SetDeadline(time.Time{})
		if ctx.Err() != nil {
			return fmt.Errorf("%s: 已取消", op.Name)
		}
		if out != "" {
			res.Log.WriteString(out)
			if !strings.HasSuffix(out, "\n") {
				res.Log.WriteString("\n")
			}
			e.emit(StepEvent{DeviceIndex: idx, DeviceLabel: label, Log: out, Progress: -1})
		}
		if err != nil {
			return fmt.Errorf("%s: %w", op.Name, err)
		}
	}
	return nil
}

// keepaliveLoop 定期发 keepalive@openssh.com；连续失败说明链路已死，
// 关闭客户端让阻塞中的读写返回错误，而不是无限等待。
func keepaliveLoop(client *ssh.Client, stop <-chan struct{}) {
	t := time.NewTicker(defaultKeepaliveInterval)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			if _, _, err := client.SendRequest("keepalive@openssh.com", true, nil); err != nil {
				client.Close()
				return
			}
		}
	}
}

func (e *Executor) commandTimeout() time.Duration {
	if e.CommandTimeout > 0 {
		return e.CommandTimeout
	}
	return defaultCommandTimeout
}

func (e *Executor) transferTimeout() time.Duration {
	if e.TransferTimeout > 0 {
		return e.TransferTimeout
	}
	return defaultTransferTimeout
}

const dialTimeoutDefault = 15 * time.Second

// runOperation 执行单条操作，返回可展示的日志。
func (e *Executor) runOperation(ctx context.Context, client *ssh.Client,
	getSFTP func() (*sftp.Client, error), remote RemoteInf,
	op OperationInf, idx int, label string, timeout time.Duration) (string, error) {

	switch op.Type {
	case OpCommand:
		out, err := runCommand(ctx, client, op.CommandStr, timeout)
		if err != nil {
			return out, err
		}
		return out, checkKeywords(out, op)
	case OpUpFile:
		return e.doUpload(ctx, client, getSFTP, op, idx, label)
	case OpDownFile:
		return e.doDownload(ctx, client, getSFTP, remote, op, idx, label)
	}
	return "", fmt.Errorf("未知操作类型 %d", op.Type)
}

// checkKeywords 实现「成功/失败关键字」判定。
//
// 旧版此处有 bug：错误分支判断的是 checkSuccessStr，导致「失败关键字」完全失效。
// 新版按配置语义分别判断。
func checkKeywords(out string, op OperationInf) error {
	lower := strings.ToLower(out)
	if s := strings.TrimSpace(op.CheckErrorStr); s != "" {
		if strings.Contains(lower, strings.ToLower(s)) {
			return fmt.Errorf("命中失败关键字 %q", s)
		}
	}
	if s := strings.TrimSpace(op.CheckSuccessStr); s != "" {
		if !strings.Contains(lower, strings.ToLower(s)) {
			return fmt.Errorf("未命中成功关键字 %q", s)
		}
	}
	return nil
}

// runCommand 在远端执行一条命令，返回合并后的 stdout+stderr。
func runCommand(ctx context.Context, client *ssh.Client, cmd string, timeout time.Duration) (string, error) {
	if timeout <= 0 {
		timeout = defaultCommandTimeout
	}
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	session, err := client.NewSession()
	if err != nil {
		return "", fmt.Errorf("创建会话失败: %w", err)
	}
	defer session.Close()

	type res struct {
		out []byte
		err error
	}
	ch := make(chan res, 1)
	go func() {
		out, err := session.CombinedOutput(cmd)
		ch <- res{out, err}
	}()

	select {
	case <-cctx.Done():
		// 超时：关掉会话让远端进程结束
		session.Close()
		return "", fmt.Errorf("命令执行超时(%s)", timeout)
	case r := <-ch:
		s := string(r.out)
		// 与旧版一致：远端输出里的字面 "\n" 转成真换行
		s = strings.ReplaceAll(s, `\n`, "\n")
		if r.err != nil {
			return s, fmt.Errorf("命令返回非零: %w", r.err)
		}
		return s, nil
	}
}

// localAbs 解析相对路径（基准为 RootDir）。
func (e *Executor) localAbs(p string) string {
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(e.RootDir, p)
}

func (e *Executor) doUpload(ctx context.Context, client *ssh.Client,
	getSFTP func() (*sftp.Client, error), op OperationInf, idx int, label string) (string, error) {

	local := e.localAbs(op.TransferFileSourcePath)
	f, err := os.Open(local)
	if err != nil {
		return "", fmt.Errorf("打开本地文件失败: %w", err)
	}
	defer f.Close()

	st, err := f.Stat()
	if err != nil {
		return "", fmt.Errorf("读取本地文件信息失败: %w", err)
	}

	sc, err := getSFTP()
	if err != nil {
		return "", err
	}

	remotePath := op.TransferFileDestinationPath
	// 目标是目录时（以 / 结尾），拼上本地文件名。
	if strings.HasSuffix(remotePath, "/") {
		remotePath = path.Join(remotePath, filepath.Base(local))
	}

	dst, err := sc.Create(remotePath)
	if err != nil {
		return "", fmt.Errorf("创建远程文件失败: %w", err)
	}

	written, cpErr := copyWithProgress(dst, f, st.Size(), func(p float64) {
		e.emit(StepEvent{DeviceIndex: idx, DeviceLabel: label,
			Stage: "上传中", Progress: p})
	})
	closeErr := dst.Close()
	if cpErr != nil {
		return "", fmt.Errorf("上传失败: %w", cpErr)
	}
	if closeErr != nil {
		return "", fmt.Errorf("关闭远程文件失败: %w", closeErr)
	}

	logs := fmt.Sprintf("已上传 %s -> %s (%d 字节)", local, remotePath, written)

	if err := e.verifyUpload(ctx, client, op, local, remotePath); err != nil {
		return logs, err
	}
	return logs + "\n校验通过", nil
}

// verifyUpload 按配置的校验方式校验上传结果。
func (e *Executor) verifyUpload(ctx context.Context, client *ssh.Client,
	op OperationInf, localPath, remotePath string) error {

	switch op.CheckFile {
	case CheckNone:
		return nil
	case CheckSize:
		localSize, err := fileSize(localPath)
		if err != nil {
			return err
		}
		out, err := runCommand(ctx, client, "stat -c %s "+shellQuote(remotePath), defaultCommandTimeout)
		if err != nil {
			return fmt.Errorf("获取远程文件大小失败: %w", err)
		}
		remoteSize, err := parseInt(strings.TrimSpace(out))
		if err != nil {
			return fmt.Errorf("解析远程文件大小失败(%q): %w", strings.TrimSpace(out), err)
		}
		if localSize != remoteSize {
			return fmt.Errorf("大小校验失败: 本地 %d, 远程 %d", localSize, remoteSize)
		}
		return nil
	default: // CheckMD5
		localMD5, err := fileMD5(localPath)
		if err != nil {
			return err
		}
		out, err := runCommand(ctx, client, "md5sum "+shellQuote(remotePath), defaultCommandTimeout)
		if err != nil {
			return fmt.Errorf("远程 md5sum 失败: %w", err)
		}
		remoteMD5, err := firstField(out)
		if err != nil {
			return fmt.Errorf("解析远程 MD5 失败(%q): %w", strings.TrimSpace(out), err)
		}
		if !strings.EqualFold(remoteMD5, localMD5) {
			return fmt.Errorf("MD5 校验失败: 本地 %s, 远程 %s", localMD5, remoteMD5)
		}
		return nil
	}
}

func (e *Executor) doDownload(ctx context.Context, client *ssh.Client,
	getSFTP func() (*sftp.Client, error), remote RemoteInf, op OperationInf,
	idx int, label string) (string, error) {

	sc, err := getSFTP()
	if err != nil {
		return "", err
	}

	remotePath := op.TransferFileSourcePath
	src, err := sc.Open(remotePath)
	if err != nil {
		return "", fmt.Errorf("打开远程文件失败: %w", err)
	}
	defer src.Close()

	st, err := src.Stat()
	if err != nil {
		return "", fmt.Errorf("读取远程文件信息失败: %w", err)
	}

	dir := e.localAbs(op.TransferFileDestinationPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("创建本地目录失败: %w", err)
	}

	// 目标文件名带设备标识与时间戳，与旧版一致，避免多设备互相覆盖。
	base := fmt.Sprintf("%s_%d_%s_%s",
		remote.IP, remote.Port, time.Now().Format("2006_01_02_15_04_05"),
		filepath.Base(remotePath))
	localPath := filepath.Join(dir, base)

	f, err := os.Create(localPath)
	if err != nil {
		return "", fmt.Errorf("创建本地文件失败: %w", err)
	}

	written, cpErr := copyWithProgress(f, src, st.Size(), func(p float64) {
		e.emit(StepEvent{DeviceIndex: idx, DeviceLabel: label,
			Stage: "下载中", Progress: p})
	})
	// 旧版不检查本地写入是否成功，会在磁盘满时「下载成功但内容残缺」。
	syncErr := f.Sync()
	closeErr := f.Close()
	if cpErr != nil {
		os.Remove(localPath)
		return "", fmt.Errorf("下载失败: %w", cpErr)
	}
	if syncErr != nil {
		os.Remove(localPath)
		return "", fmt.Errorf("本地落盘失败: %w", syncErr)
	}
	if closeErr != nil {
		os.Remove(localPath)
		return "", fmt.Errorf("关闭本地文件失败: %w", closeErr)
	}

	logs := fmt.Sprintf("已下载 %s -> %s (%d 字节)", remotePath, localPath, written)
	if err := e.verifyDownload(ctx, client, op, localPath, remotePath); err != nil {
		return logs, err
	}
	return logs + "\n校验通过", nil
}

func (e *Executor) verifyDownload(ctx context.Context, client *ssh.Client,
	op OperationInf, localPath, remotePath string) error {

	switch op.CheckFile {
	case CheckNone:
		return nil
	case CheckSize:
		localSize, err := fileSize(localPath)
		if err != nil {
			return err
		}
		out, err := runCommand(ctx, client, "stat -c %s "+shellQuote(remotePath), defaultCommandTimeout)
		if err != nil {
			return fmt.Errorf("获取远程文件大小失败: %w", err)
		}
		remoteSize, err := parseInt(strings.TrimSpace(out))
		if err != nil {
			return fmt.Errorf("解析远程文件大小失败(%q): %w", strings.TrimSpace(out), err)
		}
		if localSize != remoteSize {
			return fmt.Errorf("大小校验失败: 本地 %d, 远程 %d", localSize, remoteSize)
		}
		return nil
	default:
		localMD5, err := fileMD5(localPath)
		if err != nil {
			return err
		}
		out, err := runCommand(ctx, client, "md5sum "+shellQuote(remotePath), defaultCommandTimeout)
		if err != nil {
			return fmt.Errorf("远程 md5sum 失败: %w", err)
		}
		remoteMD5, err := firstField(out)
		if err != nil {
			return fmt.Errorf("解析远程 MD5 失败(%q): %w", strings.TrimSpace(out), err)
		}
		if !strings.EqualFold(remoteMD5, localMD5) {
			return fmt.Errorf("MD5 校验失败: 本地 %s, 远程 %s", localMD5, remoteMD5)
		}
		return nil
	}
}

// copyWithProgress 复制并回调进度；总大小为 0 时不做除法（旧版会除零得到 NaN）。
func copyWithProgress(dst io.Writer, src io.Reader, total int64, onProgress func(float64)) (int64, error) {
	buf := make([]byte, copyBufSize)
	var written int64
	for {
		n, err := src.Read(buf)
		if n > 0 {
			w, werr := dst.Write(buf[:n])
			written += int64(w)
			if total > 0 && onProgress != nil {
				p := float64(written) / float64(total)
				if p > 1 {
					p = 1
				}
				onProgress(p)
			}
			if werr != nil {
				return written, werr
			}
			if w != n {
				return written, io.ErrShortWrite
			}
		}
		if err == io.EOF {
			return written, nil
		}
		if err != nil {
			return written, err
		}
	}
}

func fileMD5(p string) (string, error) {
	f, err := os.Open(p)
	if err != nil {
		return "", fmt.Errorf("打开文件计算 MD5 失败: %w", err)
	}
	defer f.Close()
	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", fmt.Errorf("计算 MD5 失败: %w", err)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func fileSize(p string) (int64, error) {
	st, err := os.Stat(p)
	if err != nil {
		return 0, fmt.Errorf("读取文件大小失败: %w", err)
	}
	return st.Size(), nil
}

// firstField 取代旧版 remoteLog.split(" ").at(0)——旧版在输出为空时越界。
func firstField(s string) (string, error) {
	fields := strings.Fields(s)
	if len(fields) == 0 {
		return "", errors.New("输出为空")
	}
	return fields[0], nil
}

func parseInt(s string) (int64, error) {
	var v int64
	_, err := fmt.Sscanf(s, "%d", &v)
	return v, err
}

// shellQuote 单引号包裹，避免路径里的空格/特殊字符破坏命令。
func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}
