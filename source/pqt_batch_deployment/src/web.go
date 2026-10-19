package main

// Web 界面：给没有图形栈的 Linux 服务器用。
//
// 为什么要单独做（而不是让 Fyne 跑在 Xvfb 上）：
// Fyne 的 Linux 产物**动态链接** libX11/libGL/libwayland，在没有图形栈的服务器上
// 连启动都做不到（不是"看不到窗口"，是加载器直接报缺 so）。所以这里用
// `-tags headless` 编出一个不链接任何图形库的二进制，界面走 HTTP。
//
// 功能对齐桌面版，不是阉割版：
//   - 设备表 / 操作表的增删改查，克隆；
//   - 三段式操作配置（命令下发 / 文件上传 / 文件下载）+ 完整度实时提示；
//   - 根目录、并行上限、内置预设载入、配置保存/载入；
//   - 执行、逐设备实时状态与日志、中止；
//   - 「打开下载目录」在服务器上无意义，改为展示路径（见 /api/open 的说明）。
//
// 安全取向：配置里含**明文 SSH 密码**，因此默认只监听 127.0.0.1。
// 要对外提供必须显式 --listen 0.0.0.0:端口，并自行在前面加认证/反代。

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed webui/index.html
var webAssets embed.FS

// webOptions Web 启动参数。
type webOptions struct {
	// Listen 监听地址，默认 127.0.0.1:8080。
	Listen string
}

func parseWebArgs(args []string) (webOptions, error) {
	opts := webOptions{Listen: "127.0.0.1:8080"}
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--listen", "-l":
			if i+1 >= len(args) {
				return opts, errors.New("--listen 需要一个地址，例如 127.0.0.1:8080")
			}
			opts.Listen = args[i+1]
			i++
		default:
			return opts, fmt.Errorf("未知参数 %q", args[i])
		}
	}
	if _, _, err := net.SplitHostPort(opts.Listen); err != nil {
		return opts, fmt.Errorf("监听地址非法 %q（应形如 127.0.0.1:8080）: %w", opts.Listen, err)
	}
	return opts, nil
}

// webServer 把 GUIState/Executor 暴露成 HTTP 接口。
type webServer struct {
	state *GUIState

	mu      sync.Mutex
	running bool
	cancel  context.CancelFunc
	// gen 每次执行自增，用于让前端判断状态是否属于当前这轮。
	gen int
	// bus 全局唯一的事件广播器（见 web_events.go）。
	bus *eventBus
}

func newWebServer() *webServer {
	wd, err := os.Getwd()
	if err != nil {
		wd = "."
	}
	s := NewGUIState()
	s.SetRootDir(wd)
	return &webServer{state: s, bus: newEventBus()}
}

func runWeb(opts webOptions) int {
	ws := newWebServer()
	mux := http.NewServeMux()
	ws.routes(mux)

	ln, err := net.Listen("tcp", opts.Listen)
	if err != nil {
		fmt.Fprintf(os.Stderr, "错误: 无法监听 %s: %v\n", opts.Listen, err)
		return 2
	}

	fmt.Printf("批量部署工具 Web UI 已启动: http://%s\n", displayAddr(opts.Listen))
	if isLoopback(opts.Listen) {
		fmt.Println("提示: 仅监听本机。配置含明文 SSH 密码，对外提供请显式 --listen 0.0.0.0:端口 并自加访问控制。")
	} else {
		fmt.Println("警告: 正在对外监听，且配置中含明文 SSH 密码，请确保已有访问控制（反代认证/防火墙）。")
	}

	srv := &http.Server{
		Handler:           guardLocalOrigin(mux),
		ReadHeaderTimeout: 10 * time.Second,
	}
	if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintf(os.Stderr, "错误: %v\n", err)
		return 1
	}
	return 0
}

func displayAddr(listen string) string {
	host, port, err := net.SplitHostPort(listen)
	if err != nil {
		return listen
	}
	if host == "" || host == "0.0.0.0" || host == "::" {
		host = "127.0.0.1"
	}
	return net.JoinHostPort(host, port)
}

func isLoopback(listen string) bool {
	host, _, err := net.SplitHostPort(listen)
	if err != nil {
		return false
	}
	if host == "" {
		return false
	}
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// ---------- 路由 ----------

// guardLocalOrigin 挡住跨站请求与 DNS rebinding。
//
// 为什么需要：服务默认只监听 127.0.0.1，但**这挡不住浏览器**——
// 恶意页面可以直接 POST 到 http://127.0.0.1:8080，或用 DNS rebinding
// 把自己的域名解析到 127.0.0.1 从而被当作同源，读走 /api/config 里的
// 明文 SSH 密码。所以校验 Origin/Host 必须是本机名。
func guardLocalOrigin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !isLocalRequest(r) {
			writeErr(w, http.StatusForbidden,
				"只接受本机访问（Host/Origin 不是 localhost/127.0.0.1）。"+
					"远程请用 SSH 端口转发。")
			return
		}
		next.ServeHTTP(w, r)
	})
}

// isLocalRequest 判断请求是否来自本机页面。
func isLocalRequest(r *http.Request) bool {
	// Host 必须是本机名/回环地址，挡 DNS rebinding。
	host := r.Host
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	if !isLocalHostName(host) {
		return false
	}
	// 带 Origin 时（跨站 POST 一定带），必须也是本机。
	if origin := r.Header.Get("Origin"); origin != "" {
		u, err := url.Parse(origin)
		if err != nil {
			return false
		}
		if !isLocalHostName(u.Hostname()) {
			return false
		}
	}
	return true
}

func isLocalHostName(h string) bool {
	switch strings.ToLower(h) {
	case "localhost", "127.0.0.1", "::1", "[::1]":
		return true
	}
	ip := net.ParseIP(h)
	return ip != nil && ip.IsLoopback()
}

func (ws *webServer) routes(mux *http.ServeMux) {
	sub, err := fs.Sub(webAssets, "webui")
	if err != nil {
		panic(err) // 只可能在 embed 声明写错时发生
	}
	mux.Handle("/", http.FileServer(http.FS(sub)))
	// 品牌图片复用 assets/ 里已内嵌的同一份文件，不在 webui/ 再存一份。
	mux.HandleFunc("/logo.png", serveAsset("sophgo-logo-new2.png"))
	mux.HandleFunc("/favicon.png", serveAsset("ic_action_database.png"))

	mux.HandleFunc("/api/state", ws.handleState)
	mux.HandleFunc("/api/config", ws.handleConfig)     // GET 导出 / POST 覆盖
	mux.HandleFunc("/api/presets", ws.handlePresets)   // GET 列表 / POST 载入
	mux.HandleFunc("/api/settings", ws.handleSettings) // POST 根目录 / 并行上限
	mux.HandleFunc("/api/device", ws.handleDevice)     // POST 增删改克隆
	mux.HandleFunc("/api/op", ws.handleOp)             // POST 增删改克隆
	mux.HandleFunc("/api/run", ws.handleRun)           // POST 开始
	mux.HandleFunc("/api/cancel", ws.handleCancel)     // POST 中止
	mux.HandleFunc("/api/events", ws.handleEvents)     // GET SSE 事件流
	mux.HandleFunc("/api/log", ws.handleLog)           // GET 单设备日志
}

// serveAsset 输出一份内嵌 PNG 资源。
func serveAsset(name string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		data, err := ReadAsset(name)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Cache-Control", "max-age=86400")
		_, _ = w.Write(data)
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	// 响应里含明文 SSH 密码，禁止浏览器落盘缓存。
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

// stateDTO 前端需要的完整状态。
type stateDTO struct {
	RootDir     string      `json:"rootDir"`
	MaxParallel int         `json:"maxParallel"`
	Devices     []deviceDTO `json:"devices"`
	Ops         []opDTO     `json:"ops"`
	Running     bool        `json:"running"`
	Gen         int         `json:"gen"`
	Presets     []string    `json:"presets"`
	Version     string      `json:"version"`
}

type deviceDTO struct {
	IP       string `json:"IP"`
	Port     int    `json:"Port"`
	Username string `json:"Username"`
	Password string `json:"Password"`
	Status   string `json:"status"`
}

type opDTO struct {
	Name                        string `json:"name"`
	Type                        int    `json:"type"`
	CommandStr                  string `json:"commandStr"`
	CheckSuccessStr             string `json:"checkSuccessStr"`
	CheckErrorStr               string `json:"checkErrorStr"`
	TransferFileSourcePath      string `json:"transferFileSourcePath"`
	TransferFileDestinationPath string `json:"transferFileDestinationPath"`
	CheckFile                   int    `json:"checkFile"`
	Complete                    bool   `json:"complete"`
	IncompleteReason            string `json:"incompleteReason,omitempty"`
	TypeName                    string `json:"typeName"`
	CheckName                   string `json:"checkName"`
}

func (ws *webServer) snapshot() stateDTO {
	devs := ws.state.Devices()
	ops := ws.state.Ops()

	out := stateDTO{
		RootDir:     ws.state.RootDir(),
		MaxParallel: ws.state.MaxParallel(),
		Devices:     make([]deviceDTO, 0, len(devs)),
		Ops:         make([]opDTO, 0, len(ops)),
		Presets:     BuiltinPresets(),
		Version:     Version,
	}
	for _, d := range devs {
		out.Devices = append(out.Devices, deviceDTO{
			IP: d.Inf.IP, Port: d.Inf.Port, Username: d.Inf.Username,
			Password: d.Inf.Password, Status: d.Status,
		})
	}
	for _, o := range ops {
		op := o.Inf
		dto := opDTO{
			Name: op.Name, Type: op.Type, CommandStr: op.CommandStr,
			CheckSuccessStr: op.CheckSuccessStr, CheckErrorStr: op.CheckErrorStr,
			TransferFileSourcePath:      op.TransferFileSourcePath,
			TransferFileDestinationPath: op.TransferFileDestinationPath,
			CheckFile:                   op.CheckFile,
			Complete:                    op.IsComplete(),
			TypeName:                    op.TypeName(),
			CheckName:                   op.CheckName(),
		}
		if err := op.Validate(); err != nil {
			dto.IncompleteReason = err.Error()
		}
		out.Ops = append(out.Ops, dto)
	}

	ws.mu.Lock()
	out.Running = ws.running
	out.Gen = ws.gen
	ws.mu.Unlock()
	return out
}

func (ws *webServer) handleState(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 GET")
		return
	}
	writeJSON(w, http.StatusOK, ws.snapshot())
}

// ---------- 配置导入导出 ----------

func (ws *webServer) handleConfig(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		writeJSON(w, http.StatusOK, ws.state.ToConfig())

	case http.MethodPost:
		if ws.isRunning() {
			writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
			return
		}
		var cfg Config
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20)).Decode(&cfg); err != nil {
			writeErr(w, http.StatusBadRequest, "解析配置失败: "+err.Error())
			return
		}
		// 与 GUI/CLI 同一套语义：设备必须合法，至少一条完整操作。
		if err := cfg.ValidateDevices(); err != nil {
			writeErr(w, http.StatusBadRequest, "配置无效: "+err.Error())
			return
		}
		ws.state.LoadConfig(&cfg)
		writeJSON(w, http.StatusOK, ws.snapshot())

	default:
		writeErr(w, http.StatusMethodNotAllowed, "只支持 GET/POST")
	}
}

// handleSettings 保存根目录与并行上限。
//
// 这两个值必须落到服务端：早先只在前端 JS 里改，界面显示了新值但执行时
// 用的仍是旧值（根目录永远是启动 cwd、并行上限永远是 100），属于会让人
// 把文件传到错误目录的静默错误。
func (ws *webServer) handleSettings(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	if ws.isRunning() {
		writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
		return
	}
	var body struct {
		RootDir     *string `json:"rootDir"`
		MaxParallel *int    `json:"maxParallel"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}
	if body.RootDir != nil {
		root := strings.TrimSpace(*body.RootDir)
		if root == "" {
			writeErr(w, http.StatusBadRequest, "根目录不能为空")
			return
		}
		if st, err := os.Stat(root); err != nil || !st.IsDir() {
			writeErr(w, http.StatusBadRequest, "根目录不存在或不是目录: "+root)
			return
		}
		ws.state.SetRootDir(root)
	}
	if body.MaxParallel != nil {
		if *body.MaxParallel <= 0 {
			writeErr(w, http.StatusBadRequest, "并行上限必须大于 0")
			return
		}
		ws.state.SetMaxParallel(*body.MaxParallel)
	}
	writeJSON(w, http.StatusOK, ws.snapshot())
}

func (ws *webServer) handlePresets(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		writeJSON(w, http.StatusOK, BuiltinPresets())
		return
	}
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 GET/POST")
		return
	}
	if ws.isRunning() {
		writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
		return
	}
	var body struct {
		Name string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}
	cfg, err := LoadBuiltinPreset(body.Name)
	if err != nil {
		writeErr(w, http.StatusBadRequest, "载入预设失败: "+err.Error())
		return
	}
	ws.state.LoadConfig(cfg)
	writeJSON(w, http.StatusOK, ws.snapshot())
}

// ---------- 设备与操作编辑 ----------

func (ws *webServer) handleDevice(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	if ws.isRunning() {
		writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
		return
	}
	var body struct {
		Action string    `json:"action"` // add|update|remove|clone
		Index  int       `json:"index"`
		Device deviceDTO `json:"device"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}

	switch body.Action {
	case "add":
		inf := RemoteInf{IP: body.Device.IP, Port: body.Device.Port,
			Username: body.Device.Username, Password: body.Device.Password}
		if inf.Port <= 0 {
			inf.Port = 22
		}
		if strings.TrimSpace(inf.IP) == "" {
			writeErr(w, http.StatusBadRequest, "IP 不能为空")
			return
		}
		ws.state.AppendDevice(inf)

	case "update":
		inf := RemoteInf{IP: body.Device.IP, Port: body.Device.Port,
			Username: body.Device.Username, Password: body.Device.Password}
		if strings.TrimSpace(inf.IP) == "" {
			writeErr(w, http.StatusBadRequest, "IP 不能为空")
			return
		}
		if inf.Port <= 0 || inf.Port > 65535 {
			writeErr(w, http.StatusBadRequest, "端口必须是 1-65535")
			return
		}
		if !ws.state.UpdateDevice(body.Index, inf) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}

	case "remove":
		if !ws.state.RemoveDevice(body.Index) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}

	case "clone":
		if !ws.state.CloneDevice(body.Index) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}

	default:
		writeErr(w, http.StatusBadRequest, "未知 action: "+body.Action)
		return
	}
	writeJSON(w, http.StatusOK, ws.snapshot())
}

func (ws *webServer) handleOp(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	if ws.isRunning() {
		writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
		return
	}
	var body struct {
		Action string `json:"action"`
		Index  int    `json:"index"`
		Op     opDTO  `json:"op"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}

	toInf := func(d opDTO) OperationInf {
		return OperationInf{
			Name: d.Name, Type: d.Type, CommandStr: d.CommandStr,
			CheckSuccessStr: d.CheckSuccessStr, CheckErrorStr: d.CheckErrorStr,
			TransferFileSourcePath:      d.TransferFileSourcePath,
			TransferFileDestinationPath: d.TransferFileDestinationPath,
			CheckFile:                   d.CheckFile,
		}
	}

	switch body.Action {
	case "add":
		ws.state.AppendOp(toInf(body.Op))
	case "update":
		if !ws.state.UpdateOp(body.Index, toInf(body.Op)) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}
	case "remove":
		if !ws.state.RemoveOp(body.Index) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}
	case "clone":
		if !ws.state.CloneOp(body.Index) {
			writeErr(w, http.StatusBadRequest, "下标越界")
			return
		}
	default:
		writeErr(w, http.StatusBadRequest, "未知 action: "+body.Action)
		return
	}
	writeJSON(w, http.StatusOK, ws.snapshot())
}

// ---------- 执行 / 中止 / 事件 ----------

func (ws *webServer) isRunning() bool {
	ws.mu.Lock()
	defer ws.mu.Unlock()
	return ws.running
}

func (ws *webServer) handleRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}

	// 先抢占 running，避免两个并发 POST 都通过检查、起两轮执行
	// （那样 cancel 只能拿到后者，前者跑完前杀不掉）。
	ws.mu.Lock()
	if ws.running {
		ws.mu.Unlock()
		writeErr(w, http.StatusConflict, "已有任务在执行")
		return
	}
	ws.running = true
	ws.mu.Unlock()

	// 校验失败要把 running 放回去，否则界面永远处于"执行中"。
	release := func() {
		ws.mu.Lock()
		ws.running = false
		ws.mu.Unlock()
	}

	cfg := ws.state.ToConfig()
	if err := cfg.ValidateDevices(); err != nil {
		release()
		writeErr(w, http.StatusBadRequest, "配置无效: "+err.Error())
		return
	}
	if len(cfg.CompleteOperations()) == 0 {
		release()
		writeErr(w, http.StatusBadRequest, "没有配置完整的操作可执行")
		return
	}
	rootDir := ws.state.RootDir()
	if st, err := os.Stat(rootDir); err != nil || !st.IsDir() {
		release()
		writeErr(w, http.StatusBadRequest, "根目录不存在或不是目录: "+rootDir)
		return
	}

	ws.state.ClearLogs()
	for i := range cfg.RemoteInf {
		ws.state.SetDeviceStatus(i, "等待中")
	}

	ctx, cancel := context.WithCancel(context.Background())
	ws.mu.Lock()
	ws.cancel = cancel
	ws.gen++
	gen := ws.gen
	ws.mu.Unlock()

	cmdTimeout, xferTimeout := cfg.Timeouts()
	bus := ws.bus

	exec := &Executor{
		RootDir:         rootDir,
		MaxParallel:     ws.state.MaxParallel(),
		CommandTimeout:  cmdTimeout,
		TransferTimeout: xferTimeout,
		Emit:            func(ev StepEvent) { ws.applyEvent(gen, bus, ev) },
	}

	skipped := len(cfg.OperationInf) - len(cfg.CompleteOperations())
	start := eventDTO{Gen: gen, Kind: "start", Stage: fmt.Sprintf(
		"开始执行: %d 台设备 x %d 条操作，并行上限 %d",
		len(cfg.RemoteInf), len(cfg.CompleteOperations()), ws.state.MaxParallel())}
	if skipped > 0 {
		start.Stage += fmt.Sprintf("（%d 条不完整操作已跳过）", skipped)
	}
	bus.publish(start)

	go func() {
		results := exec.Run(ctx, cfg)
		ws.mu.Lock()
		ws.running = false
		ws.cancel = nil
		ws.mu.Unlock()

		ok, failed := 0, 0
		for _, res := range results {
			if res.OK {
				ok++
			} else {
				failed++
			}
		}
		summary := fmt.Sprintf("执行结束: 成功 %d，失败 %d", ok, failed)
		if ctx.Err() != nil {
			summary = fmt.Sprintf("执行已中止: 成功 %d，失败/未完成 %d", ok, failed)
		}
		bus.publish(eventDTO{Gen: gen, Kind: "done", OK: failed == 0,
			Success: ok, Failed: failed, Stage: summary})
	}()

	writeJSON(w, http.StatusOK, map[string]any{"gen": gen, "running": true})
}

func (ws *webServer) handleCancel(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	ws.mu.Lock()
	cancel := ws.cancel
	running := ws.running
	ws.mu.Unlock()
	if !running || cancel == nil {
		writeErr(w, http.StatusConflict, "当前没有正在执行的任务")
		return
	}
	cancel()
	writeJSON(w, http.StatusOK, map[string]string{"status": "正在中止"})
}

// eventDTO 推给前端的一条事件。
type eventDTO struct {
	Gen         int     `json:"gen"`
	Kind        string  `json:"kind"` // snapshot|stage|log|device|start|done
	DeviceIndex int     `json:"deviceIndex"`
	DeviceLabel string  `json:"deviceLabel"`
	Stage       string  `json:"stage,omitempty"`
	Log         string  `json:"log,omitempty"`
	Status      string  `json:"status,omitempty"`
	Err         string  `json:"err,omitempty"`
	Progress    float64 `json:"progress"`
	OK          bool    `json:"ok"`
	Success     int     `json:"success"`
	Failed      int     `json:"failed"`
}

// applyEvent 在服务端把事件落到 GUIState（与桌面版口径一致），再广播给前端。
func (ws *webServer) applyEvent(gen int, bus *eventBus, ev StepEvent) {
	if ev.Log != "" {
		ws.state.AppendLog(ev.DeviceIndex, ev.Log+"\n")
	}
	if ev.Err != nil {
		if ev.Log == "" {
			ws.state.AppendLog(ev.DeviceIndex, "错误: "+ev.Err.Error()+"\n")
		}
		ws.state.SetDeviceStatus(ev.DeviceIndex, "失败/"+ev.Err.Error())
	} else if ev.Done {
		if ev.OK {
			ws.state.SetDeviceStatus(ev.DeviceIndex, "成功")
		} else {
			ws.state.SetDeviceStatus(ev.DeviceIndex, "失败")
		}
	} else if ev.Stage != "" {
		ws.state.SetDeviceStatus(ev.DeviceIndex, ev.Stage)
	}

	dto := eventDTO{
		Gen: gen, Kind: "device", DeviceIndex: ev.DeviceIndex,
		DeviceLabel: ev.DeviceLabel, Stage: ev.Stage, Log: ev.Log,
		Progress: ev.Progress, OK: ev.OK,
	}
	if devs := ws.state.Devices(); ev.DeviceIndex >= 0 && ev.DeviceIndex < len(devs) {
		dto.Status = devs[ev.DeviceIndex].Status
	}
	if ev.Err != nil {
		dto.Err = ev.Err.Error()
	}
	bus.publish(dto)
}

func (ws *webServer) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, http.StatusInternalServerError, "当前服务器不支持流式响应")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // 反代下禁用缓冲，否则事件会攒着不发

	ws.mu.Lock()
	gen := ws.gen
	ws.mu.Unlock()

	// 全局唯一总线：订阅一次即可，后续每一轮执行的事件都会流过来。
	ch, unsub := ws.bus.subscribe()
	defer unsub()

	if data := marshalSSE(eventDTO{Gen: gen, Kind: "snapshot"}); data != nil {
		if _, err := w.Write(data); err == nil {
			flusher.Flush()
		}
	}

	tick := time.NewTicker(20 * time.Second)
	defer tick.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case ev, ok := <-ch:
			if !ok {
				// 本订阅者因积压被断开：告诉前端重连。
				if data := marshalSSE(eventDTO{Gen: gen, Kind: "eos"}); data != nil {
					_, _ = w.Write(data)
					flusher.Flush()
				}
				return
			}
			if data := marshalSSE(ev); data != nil {
				if _, err := w.Write(data); err != nil {
					return
				}
				flusher.Flush()
			}
		case <-tick.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func (ws *webServer) handleLog(w http.ResponseWriter, r *http.Request) {
	idx, err := strconv.Atoi(r.URL.Query().Get("index"))
	if err != nil {
		writeErr(w, http.StatusBadRequest, "index 参数非法")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"index": idx,
		"log":   ws.state.Log(idx),
	})
}
