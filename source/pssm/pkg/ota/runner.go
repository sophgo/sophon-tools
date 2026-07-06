package ota

import (
	"os"
	"strings"
	"sync"
	"time"

	"github.com/jinzhu/gorm"

	"ssm/config"
	"ssm/database"
	"ssm/logger"
	"ssm/pkg/system"
)

// ---------------------------------------------------------------
// 可注入依赖（便于 TDD，不实刷设备）
// ---------------------------------------------------------------

// Runner 执行一条命令，签名对齐 system.RunCommandArgs。
type Runner func(name string, args ...string) (stdout, stderr string, err error)

// defaultRunner 委托 system.RunCommandArgs。
func defaultRunner(name string, args ...string) (string, string, error) {
	return system.RunCommandArgs(name, args...)
}

// FlagChecker 报告 SOC OTA 状态标志文件是否存在，并读取日志。
type FlagChecker interface {
	Exists(path string) bool
	ReadTail(path string, n int) string
	ReadPanicLine(path string) string
}

// osFlagChecker 真实文件系统实现。
type osFlagChecker struct{}

func (osFlagChecker) Exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func (osFlagChecker) ReadTail(path string, n int) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	s := string(data)
	if len(s) <= n {
		return s
	}
	return s[len(s)-n:]
}

func (osFlagChecker) ReadPanicLine(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return extractPanicLine(string(data))
}

// extractPanicLine 从日志中提取最后一个 [PANIC] 行，去掉前缀返回。
// 若无 [PANIC] 行，返回最后一个非空行（trim，限 200 字符）。
func extractPanicLine(content string) string {
	lines := strings.Split(content, "\n")
	var lastNonEmpty string
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed != "" {
			lastNonEmpty = trimmed
		}
	}
	// 找最后一个 [PANIC] 行
	var lastPanic string
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "[PANIC]") {
			msg := strings.TrimPrefix(trimmed, "[PANIC] ")
			msg = strings.TrimPrefix(msg, "[PANIC]")
			lastPanic = strings.TrimSpace(msg)
		}
	}
	if lastPanic != "" {
		return lastPanic
	}
	if len(lastNonEmpty) > 200 {
		lastNonEmpty = lastNonEmpty[:200]
	}
	return lastNonEmpty
}

// PathConfig 持有各路径，对齐 bmssm 目录布局，可注入便于测试。
type PathConfig struct {
	SOCOTADir       string // /data/ota —— SOC .tgz 上传目录
	SOCWorkRoot     string // /var/ssm/upgrade/soc —— SOC 解压工作目录根
	PCIEBackupDir   string // /var/ssm/upgrade/backup —— PCIE 回滚包目录
	PCIEBootromDir  string // /var/ssm/upgrade/bootrom —— PCIE a53 升级包目录
	PCIEFirmwareDir string // /firmware —— PCIE mcu 升级包目录
	CtrlOTADir      string // /data/ota —— 多节点 controller 包目录
	CoreTftpDir     string // /recovery/tftp —— 多节点 core 包目录
	DiskCheckPath   string // "/" —— 磁盘空间预检路径
	SuccessFlag     string // /dev/shm/ota_success_flag
	ErrorFlag       string // /dev/shm/ota_error_flag
	ShellLog        string // /dev/shm/ota_shell.sh.log
}

// DefaultPathConfig 返回对齐 bmssm 的默认路径配置。
func DefaultPathConfig() PathConfig {
	return PathConfig{
		SOCOTADir:       "/data/ota",
		SOCWorkRoot:     "/data/ssm/upgrade/soc",
		PCIEBackupDir:   "/data/ssm/upgrade/backup",
		PCIEBootromDir:  "/data/ssm/upgrade/bootrom",
		PCIEFirmwareDir: "/firmware",
		CtrlOTADir:      "/data/ota",
		CoreTftpDir:     "/recovery/tftp",
		DiskCheckPath:   "/",
		SuccessFlag:     "/dev/shm/ota_success_flag",
		ErrorFlag:       "/dev/shm/ota_error_flag",
		ShellLog:        "/dev/shm/ota_shell.sh.log",
	}
}

// dryRunFromConfig 从配置读取 ota.dryRun（默认 false）。
func dryRunFromConfig() bool {
	c := &config.Conf
	c.RLock()
	defer c.RUnlock()
	if c.GetViper() == nil {
		return false
	}
	return c.GetViper().GetBool("ota.dryRun")
}

// ---------------------------------------------------------------
// Engine
// ---------------------------------------------------------------

var (
	errDBUnavailable  = errDB("ota: database unavailable")
	errWorkerFull     = errDB("ota: worker queue full")
	errNotImplemented = errDB("ota: path not implemented yet")
)

type errDB string

func (e errDB) Error() string { return string(e) }

// Engine 驱动 OTA workflow：入队、分发、状态流转。
type Engine struct {
	db     *gorm.DB
	runner Runner
	flags  FlagChecker
	dryRun bool
	paths  PathConfig

	pollInterval time.Duration                                       // SOC 异步轮询间隔
	diskUsageFn  func(path string) (usedFraction float64, err error) // 磁盘空间预检（多节点 ctrl）

	worker  chan Workflow
	quit    chan struct{}
	done    chan struct{}
	once    sync.Once
	mu      sync.Mutex
	started bool
}

// NewEngine 构造可注入依赖的引擎（测试用）。
func NewEngine(db *gorm.DB, runner Runner, flags FlagChecker, dryRun bool, paths PathConfig) *Engine {
	return &Engine{
		db:           db,
		runner:       runner,
		flags:        flags,
		dryRun:       dryRun,
		paths:        paths,
		pollInterval: 5 * time.Second,
		diskUsageFn:  diskUsage,
		worker:       make(chan Workflow, 32),
		quit:         make(chan struct{}),
	}
}

// DefaultEngine 包级懒初始化单例，使用 database.DB()、system.RunCommandArgs、
// osFlagChecker 与配置中的 ota.dryRun。
var (
	defaultEngine *Engine
	defaultOnce   sync.Once
)

func DefaultEngine() *Engine {
	defaultOnce.Do(func() {
		defaultEngine = NewEngine(
			database.DB(),
			defaultRunner,
			osFlagChecker{},
			dryRunFromConfig(),
			DefaultPathConfig(),
		)
	})
	return defaultEngine
}

// Init 启动默认引擎的 worker goroutine。由 InitBase 调用。
func Init() {
	DefaultEngine().Start()
	logger.Info("ota engine started (dryRun=%v)", DefaultEngine().dryRun)
}

// ---------------------------------------------------------------
// 包级便捷函数（委托给 DefaultEngine）
// ---------------------------------------------------------------

// EnqueueFlow 提交 workflow 到默认引擎。
func EnqueueFlow(flow *Workflow) error { return DefaultEngine().EnqueueFlow(flow) }

// QueryAll 列出全部 workflow（默认引擎）。
func QueryAll() ([]Workflow, error) { return DefaultEngine().QueryAll() }

// Query 按 workflowId 查单个 workflow（默认引擎）。
func Query(id string) (*Workflow, error) { return DefaultEngine().Query(id) }

// OTAUpload 保存 OTA 刷机包到 module 对应目录（默认引擎）。
func OTAUpload(module, origName, srcPath string, size int64) (string, error) {
	return DefaultEngine().OTAUpload(module, origName, srcPath, size)
}

// Start 启动 worker goroutine（幂等）。
func (e *Engine) Start() {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.started {
		return
	}
	e.started = true
	e.done = make(chan struct{})
	go func() {
		defer close(e.done)
		e.startCmd()
	}()
}

// Stop 停止 worker goroutine（测试用；生产进程随主进程退出）。
// 阻塞至 worker 完全退出，避免 db.Close 与在途 processFlow 竞争。
func (e *Engine) Stop() {
	e.mu.Lock()
	if !e.started {
		e.mu.Unlock()
		return
	}
	e.started = false
	close(e.quit)
	e.mu.Unlock()
	<-e.done
}
