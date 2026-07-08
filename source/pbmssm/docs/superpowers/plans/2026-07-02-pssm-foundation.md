# pssm 地基子项目 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `sophon-tools/source/pssm/` 下建立 `ssm` Go 服务的现代骨架，跑起监听 9779 的 gin 服务，识别 SOC 设备信息，暴露 `/healthz`，可 aarch64 交叉编译并部署到真机验证。

**Architecture:** 镜像 `psophliteos` 的现代 Go 分层布局（config/global/logger/initialization/middleware/router/mvc）。从 `bmssm` 移植并纯函数化 `devinfo`（OEMconfig.ini 解析改为可测纯函数）。地基阶段引入 sqlite(gorm) 建好 DB 抽象层与 migration 框架（空表）。日志用 zap+lumberjack。丢弃 kubeadapter/pierce-edge/bm_snmp_service/bmlib_wrapper（bmlib 属硬件子项目）。

**Tech Stack:** Go 1.21、gin v1.9、viper v1.7+fsnotify、go.uber.org/zap、gopkg.in/natefinch/lumberjack、gorm v1.9 + mattn/go-sqlite3、golang.org/x/time/rate。交叉编译 aarch64 用 `aarch64-linux-gnu-gcc`。

**源参考：**
- `bmssm`：`/home/zzt/workspace/bmssm`（`pkg/config`、`pkg/devinfo`、`pkg/common/system`、`build/build-ssm*.sh`、`main.go`）
- `psophliteos`：`/home/zzt/workspace/sophon-tools/source/psophliteos`（`config/`、`logger/`、`initialization/`、`go.mod`）
- spec：`source/pssm/docs/superpowers/specs/2026-07-02-pssm-foundation-design.md`

**真机验证环境：** `linaro@172.26.166.185` 密码 `linaro`（SOC 设备，devinfo 走 `/factory/OEMconfig.ini`）

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `pssm/go.mod` | module `ssm`，依赖声明 |
| `pssm/main.go` | 入口：InitBase→Routers→InitServer→信号优雅退出 |
| `pssm/config/ssm.yaml` | 默认配置文件 |
| `pssm/config/config.go` | viper 加载 + SyncConfig 读写锁 + 热加载 |
| `pssm/logger/logger.go` | zap 封装：Info/Warn/Error/Debug + file rotate |
| `pssm/global/global.go` | 进程级状态：DeviceType/Role/Sn/Version + BuildInfo |
| `pssm/global/version.go` | 版本信息注入（ldflags） |
| `pssm/pkg/system/system.go` | PathExists / RunCommand 工具 |
| `pssm/pkg/device/devinfo.go` | GetDeviceInfo + 纯函数 ParseOEMConfig |
| `pssm/database/db.go` | gorm sqlite InitDB + Migrate 框架 |
| `pssm/middleware/middleware.go` | Recovery / AccessLog / RateLimit |
| `pssm/mvc/health/health.go` | health 控制器 |
| `pssm/router/router.go` | 路由注册 |
| `pssm/initialization/init.go` | InitBase |
| `pssm/initialization/router.go` | Routers |
| `pssm/initialization/server.go` | InitServer |
| `pssm/build/build-ssm.sh` | x86 构建 |
| `pssm/build/build-ssm-arm64.sh` | aarch64 交叉编译 |
| `pssm/build/version.sh` | 版本号生成 |
| 各 `*_test.go` | 单元测试 |

---

## Task 1: 工程骨架与 go.mod

**Files:**
- Create: `pssm/go.mod`
- Create: `pssm/.gitignore`
- Create: `pssm/main.go`（临时最小 stub，后续 Task 11 替换）
- Create: `pssm/README.md`

- [ ] **Step 1: 创建 go.mod**

```bash
mkdir -p /home/zzt/workspace/sophon-tools/source/pssm
cd /home/zzt/workspace/sophon-tools/source/pssm
go mod init ssm
go mod edit -go=1.21
```

- [ ] **Step 2: 写 .gitignore**

`pssm/.gitignore`:
```
release/
install/
ssm
ssm-arm64
*.db
*.out
```

- [ ] **Step 3: 写临时 main.go stub**

`pssm/main.go`:
```go
package main

import "fmt"

func main() { fmt.Println("ssm skeleton") }
```

- [ ] **Step 4: 写 README**

`pssm/README.md`:
```markdown
# ssm

Sophon System Management 服务（由 bmssm 现代化重写）。

## 编译
- x86: `bash build/build-ssm.sh`
- arm64: `bash build/build-ssm-arm64.sh`（需 `gcc-aarch64-linux-gnu`）

## 配置
默认读取 `/etc/ssm/conf/ssm.yaml`，本地开发回退 `./config/ssm.yaml`。

## 端口
9779
```

- [ ] **Step 5: 验证编译**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go build ./...
```
Expected: 无错误输出。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm
git commit -m "feat(pssm): 工程骨架与 go.mod"
```

---

## Task 2: logger 包（zap + lumberjack）

**Files:**
- Create: `pssm/logger/logger.go`
- Test: `pssm/logger/logger_test.go`

- [ ] **Step 1: 添加依赖**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go get go.uber.org/zap@v1.26.0
go get gopkg.in/natefinch/lumberjack.v2@v2.2.1
```

- [ ] **Step 2: 写失败测试**

`pssm/logger/logger_test.go`:
```go
package logger

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestInitLoggingCreatesFile(t *testing.T) {
	dir := t.TempDir()
	InitLogging(dir, "ssm.log", "debug")
	Info("hello %s", "world")
	_sync()

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read dir: %v", err)
	}
	if len(entries) == 0 {
		t.Fatal("expected log file created")
	}
	data, _ := os.ReadFile(filepath.Join(dir, "ssm.log"))
	if !strings.Contains(string(data), "hello world") {
		t.Fatalf("log missing message, got: %s", string(data))
	}
}

func TestParseLevel(t *testing.T) {
	if parseLevel("error") != zapErrorLevel {
		t.Fatal("error level mismatch")
	}
	if parseLevel("nonsense") != zapInfoLevel {
		t.Fatal("default should be info")
	}
}
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go test ./logger/ -v
```
Expected: FAIL，`InitLogging`/`Info`/`_sync`/`parseLevel` 等未定义。

- [ ] **Step 4: 实现 logger**

`pssm/logger/logger.go`:
```go
// Package logger 封装 zap，提供全局 Info/Warn/Error/Debug。
// console + file（lumberjack 按大小 rotate）双输出。
package logger

import (
	"os"
	"sync"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
	"gopkg.in/natefinch/lumberjack.v2"
)

const (
	zapDebugLevel = zapcore.DebugLevel
	zapInfoLevel  = zapcore.InfoLevel
	zapWarnLevel  = zapcore.WarnLevel
	zapErrorLevel = zapcore.ErrorLevel
)

var (
	mu      sync.Mutex
	logging *zap.Logger
)

// InitLogging 初始化全局日志：dir=日志目录，filename=文件名，level=debug/info/warn/error。
func InitLogging(dir, filename, level string) {
	mu.Lock()
	defer mu.Unlock()

	if err := os.MkdirAll(dir, 0o755); err != nil {
		panic(err)
	}

	lvl := parseLevel(level)
	encoderCfg := zapcore.EncoderConfig{
		TimeKey:        "ts",
		LevelKey:       "level",
		NameKey:        "logger",
		CallerKey:      "caller",
		MessageKey:     "msg",
		StacktraceKey:  "stacktrace",
		LineEnding:     zapcore.LineEndingUnix,
		EncodeLevel:    zapcore.CapitalLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.StringDurationEncoder,
		EncodeCaller:   zapcore.ShortCallerEncoder,
	}

	fileWriter := zapcore.AddSync(&lumberjack.Logger{
		Filename:   dir + "/" + filename,
		MaxSize:    100, // MB
		MaxBackups: 10,
		MaxAge:     30,
	})
	consoleWriter := zapcore.Lock(os.Stdout)

	core := zapcore.NewTee(
		zapcore.NewCore(zapcore.NewConsoleEncoder(encoderCfg), consoleWriter, lvl),
		zapcore.NewCore(zapcore.NewConsoleEncoder(encoderCfg), fileWriter, lvl),
	)
	logging = zap.New(core, zap.AddCaller(), zap.AddCallerSkip(1))
}

func parseLevel(level string) zapcore.Level {
	switch strings.ToLower(level) {
	case "debug":
		return zapDebugLevel
	case "info":
		return zapInfoLevel
	case "warn", "warning":
		return zapWarnLevel
	case "error":
		return zapErrorLevel
	default:
		return zapInfoLevel
	}
}

func _sync() {
	if logging != nil {
		_ = logging.Sync()
	}
}

// Debug/Info/Warn/Error 全局快捷函数。
func Debug(format string, args ...interface{}) {
	if logging == nil {
		return
	}
	logging.Sugar().Debugf(format, args...)
}

func Info(format string, args ...interface{}) {
	if logging == nil {
		return
	}
	logging.Sugar().Infof(format, args...)
}

func Warn(format string, args ...interface{}) {
	if logging == nil {
		return
	}
	logging.Sugar().Warnf(format, args...)
}

func Error(format string, args ...interface{}) {
	if logging == nil {
		return
	}
	logging.Sugar().Errorf(format, args...)
}

// Sync 刷新缓冲，进程退出前调用。
func Sync() { _sync() }
```

注意：文件顶部需补 `"strings"` import（`parseLevel` 用到）。

- [ ] **Step 5: 补 strings import 并运行测试**

编辑 `logger.go`，在 import 块加入 `"strings"`。

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go test ./logger/ -v
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/logger source/pssm/go.mod source/pssm/go.sum
git commit -m "feat(pssm): logger 包（zap+lumberjack）"
```

---

## Task 3: pkg/system 工具（PathExists / RunCommand）

**Files:**
- Create: `pssm/pkg/system/system.go`
- Test: `pssm/pkg/system/system_test.go`

- [ ] **Step 1: 写失败测试**

`pssm/pkg/system/system_test.go`:
```go
package system

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPathExistsTrue(t *testing.T) {
	f, _ := os.CreateTemp("", "ex")
	defer os.Remove(f.Name())
	ok, err := PathExists(f.Name())
	if err != nil || !ok {
		t.Fatalf("expected exist, ok=%v err=%v", ok, err)
	}
}

func TestPathExistsFalse(t *testing.T) {
	ok, err := PathExists("/no/such/path/zzz")
	if err != nil || ok {
		t.Fatalf("expected not exist, ok=%v err=%v", ok, err)
	}
}

func TestRunCommand(t *testing.T) {
	out, errStr, err := RunCommand("echo hello")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if out != "hello\n" {
		t.Fatalf("unexpected out: %q", out)
	}
	if errStr != "" {
		t.Fatalf("unexpected errStr: %q", errStr)
	}
	_ = filepath.Separator
}
```

- [ ] **Step 2: 运行确认失败**

```bash
go test ./pkg/system/ -v
```
Expected: FAIL，`PathExists`/`RunCommand` 未定义。

- [ ] **Step 3: 实现**

`pssm/pkg/system/system.go`:
```go
// Package system 提供基础 OS 工具：文件存在检查与 shell 命令执行。
package system

import (
	"bytes"
	"os"
	"os/exec"
)

// PathExists 返回路径是否存在（不存在且无其他错误时返回 false,nil）。
func PathExists(path string) (bool, error) {
	_, err := os.Stat(path)
	if err == nil {
		return true, nil
	}
	if os.IsNotExist(err) {
		return false, nil
	}
	return false, err
}

// RunCommand 以 /bin/bash -c 执行 cmd，返回 stdout/stderr。
func RunCommand(cmd string) (outStr, errStr string, err error) {
	c := exec.Command("/bin/bash", "-c", cmd)
	var outBuf, errBuf bytes.Buffer
	c.Stdout = &outBuf
	c.Stderr = &errBuf
	err = c.Run()
	outStr = outBuf.String()
	errStr = errBuf.String()
	return
}
```

- [ ] **Step 4: 运行测试**

```bash
go test ./pkg/system/ -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/pkg/system
git commit -m "feat(pssm): pkg/system 工具"
```

---

## Task 4: config 包（viper + 热加载）

**Files:**
- Create: `pssm/config/ssm.yaml`
- Create: `pssm/config/config.go`
- Test: `pssm/config/config_test.go`

- [ ] **Step 1: 添加依赖**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go get github.com/spf13/viper@v1.18.2
go get github.com/fsnotify/fsnotify@v1.7.0
```

- [ ] **Step 2: 写默认配置文件**

`pssm/config/ssm.yaml`:
```yaml
server:
  listenIP: ""
  port: 9779
  auth: true
log:
  level: info
  path: /var/log/ssm
db:
  driver: sqlite3
  path: /var/lib/ssm/ssm.db
```

- [ ] **Step 3: 写失败测试**

`pssm/config/config_test.go`:
```go
package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigFromDir(t *testing.T) {
	dir := t.TempDir()
	yaml := []byte("server:\n  port: 9999\n  auth: false\nlog:\n  level: debug\n  path: /tmp/log\ndb:\n  driver: sqlite3\n  path: /tmp/x.db\n")
	if err := os.WriteFile(filepath.Join(dir, "ssm.yaml"), yaml, 0o644); err != nil {
		t.Fatal(err)
	}
	LoadFromDir(dir)

	v := Conf.GetViper()
	if v.GetString("server.port") != "9999" {
		t.Fatalf("port=%s", v.GetString("server.port"))
	}
	if v.GetBool("server.auth") != false {
		t.Fatal("auth should be false")
	}
	if v.GetString("log.level") != "debug" {
		t.Fatalf("level=%s", v.GetString("log.level"))
	}
}

func TestDefaultsWhenMissing(t *testing.T) {
	dir := t.TempDir() // 空目录，无 ssm.yaml
	LoadFromDir(dir)
	v := Conf.GetViper()
	if v.GetString("server.port") != "9779" {
		t.Fatalf("default port expected, got %s", v.GetString("server.port"))
	}
	if v.GetBool("server.auth") != true {
		t.Fatal("default auth should be true")
	}
}
```

- [ ] **Step 4: 运行确认失败**

```bash
go test ./config/ -v
```
Expected: FAIL，`LoadFromDir`/`Conf` 未定义。

- [ ] **Step 5: 实现 config**

`pssm/config/config.go`:
```go
// Package config 用 viper 加载 ssm.yaml，提供带读写锁的全局配置与热加载。
package config

import (
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"

	"ssm/logger"
)

const DefaultConfigPath = "/etc/ssm/conf"

var Conf Config

// Config 包装 viper，带 RWMutex 供并发安全访问。
type Config struct {
	name string
	v    *viper.Viper
	mu   sync.RWMutex
}

func (c *Config) GetName() string    { return c.name }
func (c *Config) GetViper() *viper.Viper { return c.v }
func (c *Config) RLock()             { c.mu.RLock() }
func (c *Config) RUnlock()           { c.mu.RUnlock() }
func (c *Config) Lock()              { c.mu.Lock() }
func (c *Config) Unlock()            { c.mu.Unlock() }

// LoadConfig 从默认路径 /etc/ssm/conf 加载；失败回退 ./config。
func LoadConfig() {
	LoadFromDir(DefaultConfigPath)
}

// LoadFromDir 从指定目录加载 ssm.yaml（测试与本地开发用）。
func LoadFromDir(dir string) {
	Conf = Config{name: "ssm", v: viper.New()}
	v := Conf.v

	v.SetDefault("server.port", "9779")
	v.SetDefault("server.auth", true)
	v.SetDefault("server.listenIP", "")
	v.SetDefault("log.level", "info")
	v.SetDefault("log.path", "/var/log/ssm")
	v.SetDefault("db.driver", "sqlite3")
	v.SetDefault("db.path", "/var/lib/ssm/ssm.db")

	v.AddConfigPath(dir)
	v.AddConfigPath("./config")
	v.SetConfigName("ssm")
	v.SetConfigType("yaml")

	if err := v.ReadInConfig(); err != nil {
		logger.Warn("load config from %s failed: %v (using defaults)", dir, err)
		return
	}
	logger.Info("loaded config from %s, port=%s", dir, v.GetString("server.port"))

	v.OnConfigChange(func(in fsnotify.Event) {
		logger.Info("config file changed: %s", in.Name)
	})
	v.WatchConfig()
}
```

- [ ] **Step 6: 运行测试**

```bash
go test ./config/ -v
```
Expected: PASS。注意 `logger.Warn`/`Info` 在 logging 未初始化时为 no-op，测试不受影响。

- [ ] **Step 7: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/config source/pssm/go.mod source/pssm/go.sum
git commit -m "feat(pssm): config 包（viper+热加载）"
```

---

## Task 5: global 包（状态 + BuildInfo）

**Files:**
- Create: `pssm/global/global.go`
- Create: `pssm/global/version.go`
- Test: `pssm/global/version_test.go`

- [ ] **Step 1: 写失败测试**

`pssm/global/version_test.go`:
```go
package global

import "testing"

func TestVersionString(t *testing.T) {
	bi := BuildInfo{Version: "1.0.0", GitCommit: "abc", BuildTime: "2026-01-01"}
	got := bi.String()
	if got != "1.0.0 (abc @ 2026-01-01)" {
		t.Fatalf("got %q", got)
	}
}

func TestVersionDefaults(t *testing.T) {
	if Version.Version != "dev" {
		t.Fatalf("expected dev, got %q", Version.Version)
	}
}
```

- [ ] **Step 2: 运行确认失败**

```bash
go test ./global/ -v
```
Expected: FAIL，`BuildInfo`/`Version` 未定义。

- [ ] **Step 3: 实现 global**

`pssm/global/global.go`:
```go
// Package global 存放进程级单例状态，由 initialization 在启动阶段填充。
package global

import "time"

var (
	// 设备信息，由 pkg/device.GetDeviceInfo 填充
	DeviceType   string // pcie / soc / unknown
	DeviceRole   string // SE / SE-CTRL / SE-CORE
	DeviceTypeEx string
	DeviceSnEx   string
	ChipSn       string
	ModuleType   string

	// 服务信息
	Version  BuildInfo
	Started  time.Time
)

// BuildInfo 由 ldflags 注入。
type BuildInfo struct {
	Version   string
	GitCommit string
	BuildTime string
}

func (b BuildInfo) String() string {
	return b.Version + " (" + b.GitCommit + " @ " + b.BuildTime + ")"
}
```

`pssm/global/version.go`:
```go
package global

// Version 默认值，构建时由 ldflags 覆盖：
//   -X global.Version.Version=... -X global.Version.GitCommit=... -X global.Version.BuildTime=...
var Version = BuildInfo{
	Version:   "dev",
	GitCommit: "unknown",
	BuildTime: "unknown",
}
```

- [ ] **Step 4: 运行测试**

```bash
go test ./global/ -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/global
git commit -m "feat(pssm): global 包与 BuildInfo"
```

---

## Task 6: pkg/device（devinfo，纯函数化 OEMconfig 解析）

**Files:**
- Create: `pssm/pkg/device/devinfo.go`
- Create: `pssm/pkg/device/testdata/OEMconfig.ini`
- Test: `pssm/pkg/device/devinfo_test.go`

- [ ] **Step 1: 准备测试夹具**

`pssm/pkg/device/testdata/OEMconfig.ini`:
```ini
PRODUCT = SE8
SN = CHIPSN123
SN = DEVSN456
CHIP = BM1684
```

- [ ] **Step 2: 写失败测试**

`pssm/pkg/device/devinfo_test.go`:
```go
package device

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseOEMConfig(t *testing.T) {
	data, _ := os.ReadFile(filepath.Join("testdata", "OEMconfig.ini"))
	ti, cs, ds, mt := ParseOEMConfig(string(data))
	if ti != "SE8" {
		t.Fatalf("typeEx=%q", ti)
	}
	if cs != "CHIPSN123" {
		t.Fatalf("chipSn=%q", cs)
	}
	if ds != "DEVSN456" {
		t.Fatalf("deviceSn=%q", ds)
	}
	if mt != "BM1684" {
		t.Fatalf("moduleType=%q", mt)
	}
}

func TestParseOEMConfigEmpty(t *testing.T) {
	ti, cs, ds, mt := ParseOEMConfig("")
	if ti != "" || cs != "" || ds != "" || mt != "" {
		t.Fatalf("expected all empty: %q %q %q %q", ti, cs, ds, mt)
	}
}

func TestLoadFromOEMSetsGlobals(t *testing.T) {
	LoadFromOEM(filepath.Join("testdata", "OEMconfig.ini"))
	if DeviceType != "soc" {
		t.Fatalf("DeviceType=%q", DeviceType)
	}
	if DeviceRole != "SE" {
		t.Fatalf("DeviceRole=%q", DeviceRole)
	}
	if DeviceTypeEx != "SE8" {
		t.Fatalf("DeviceTypeEx=%q", DeviceTypeEx)
	}
	if ChipSn != "CHIPSN123" {
		t.Fatalf("ChipSn=%q", ChipSn)
	}
}
```

- [ ] **Step 3: 运行确认失败**

```bash
go test ./pkg/device/ -v
```
Expected: FAIL，`ParseOEMConfig`/`LoadFromOEM`/`DeviceType` 等未定义。

- [ ] **Step 4: 实现 devinfo**

`pssm/pkg/device/devinfo.go`:
```go
// Package device 识别 Sophon 设备类型/角色/SN。
// SOC 设备读 /factory/OEMconfig.ini；PCIE 读 /sys/bus/i2c 设备信息。
package device

import (
	"os"
	"strings"

	"ssm/pkg/system"
)

const (
	PCIE_DEV    = "pcie"
	SOC_DEV     = "soc"
	UNKNOWN_DEV = "unknown"

	SE5      = "SE"
	SE6_CTRL = "SE-CTRL"
	SE6_CORE = "SE-CORE"

	OEMConfigPath   = "/factory/OEMconfig.ini"
	DevInfoPath     = "/sys/bus/i2c/devices/1-0017/information"
	BoardIPPath     = "/sys/bus/i2c/devices/1-0017/board-ip"
	CTRLShell       = "/root/se6_ctrl/se6ctr.sh"
	CTRLShell2      = "/root/se_ctrl/sectr.sh"
)

// 进程级状态（与 global 同步：GetDeviceInfo 会回写 global，见 initialization）。
var (
	DeviceType   string
	DeviceRole   string
	DeviceTypeEx string
	DeviceSnEx   string
	ChipSn       string
	ModuleType   string
)

// ParseOEMConfig 纯函数：解析 OEMconfig.ini 文本，返回 (typeEx, chipSn, deviceSn, moduleType)。
// 文件格式示例：
//   PRODUCT = SE8
//   SN = <chipSn>
//   SN = <deviceSn>
//   CHIP = <moduleType>
// 第一条 SN 视为 ChipSn，第二条视为 DeviceSn（与 bmssm 行为一致）。
func ParseOEMConfig(content string) (typeEx, chipSn, deviceSn, moduleType string) {
	var snLines []string
	for _, line := range strings.Split(content, "\n") {
		// 形如 "KEY = VALUE"，去掉 KEY 与 '=' 后剩余作为值
		eq := strings.Index(line, "=")
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		val := strings.TrimSpace(line[eq+1:])
		if val == "" {
			continue
		}
		switch key {
		case "PRODUCT":
			if typeEx == "" {
				typeEx = val
			}
		case "SN":
			snLines = append(snLines, val)
		case "CHIP":
			if moduleType == "" {
				moduleType = val
			}
		}
	}
	if len(snLines) > 0 {
		chipSn = snLines[0]
	}
	if len(snLines) > 1 {
		deviceSn = snLines[1]
	}
	return
}

// LoadFromOEM 从 OEMconfig.ini 文件加载并填充包级状态（SOC 路径）。
func LoadFromOEM(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	DeviceType = SOC_DEV
	DeviceRole = SE5
	DeviceTypeEx, ChipSn, DeviceSnEx, ModuleType = ParseOEMConfig(string(data))
}

// GetDeviceInfo 探测设备信息并填充包级状态。失败降级为 UNKNOWN_DEV，不返回错误阻断启动。
func GetDeviceInfo() {
	DeviceType = UNKNOWN_DEV

	// 1) SOC：OEMconfig.ini 存在
	if ok, _ := system.PathExists(OEMConfigPath); ok {
		LoadFromOEM(OEMConfigPath)
		return
	}

	// 2) PCIE：i2c 设备信息
	if ok, _ := system.PathExists(DevInfoPath); ok {
		DeviceType = PCIE_DEV
		loadFromI2C()
		return
	}

	// 3) 无 i2c 也无 OEM：可能是 SE6 控制器裸板
	DeviceType = PCIE_DEV
	DeviceTypeEx = "PCIE"
	if ok1, _ := system.PathExists(CTRLShell); ok1 {
		DeviceRole = SE6_CTRL
		DeviceTypeEx = "SE8"
	} else if ok2, _ := system.PathExists(CTRLShell2); ok2 {
		DeviceRole = SE6_CTRL
		DeviceTypeEx = "SE8"
	}
}

// loadFromI2C 读 /sys/bus/i2c/.../information（JSON），按 model 推断角色。
// 地基阶段仅做最小实现，覆盖 SE5/SE6-CTRL；其余分支后续硬件子项目完善。
func loadFromI2C() {
	data, err := os.ReadFile(DevInfoPath)
	if err != nil {
		return
	}
	// 简化：information 为 JSON，含 model / "product sn" 字段
	var info map[string]string
	if err := parseJSONLoose(data, &info); err != nil {
		return
	}
	if model, ok := info["model"]; ok && model != "" {
		DeviceTypeEx = model
		switch {
		case strings.Contains(model, "SE6-CTRL"), strings.Contains(model, "SE6 CTRL"),
			strings.Contains(model, "SE8-CTRL"), strings.Contains(model, "SE8 CTRL"):
			DeviceRole = SE6_CTRL
		case strings.Contains(model, "SE7"):
			DeviceRole = SE5
		default:
			DeviceRole = SE5
		}
	}
	if sn, ok := info["product sn"]; ok && sn != "" {
		ChipSn = sn
	}
}
```

注意：`loadFromI2C` 用到一个 `parseJSONLoose` 辅助函数。补到同文件：

```go
import "encoding/json"

// parseJSONLoose 用 encoding/json 解析，值为 string 时直接装入 map[string]string；
// 非字符串值被跳过（地基阶段够用）。
func parseJSONLoose(data []byte, out *map[string]string) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	m := map[string]string{}
	for k, v := range raw {
		if s, ok := v.(string); ok {
			m[k] = s
		}
	}
	*out = m
	return nil
}
```
（将 `"encoding/json"` 加入文件顶部 import 块。）

- [ ] **Step 5: 运行测试**

```bash
go test ./pkg/device/ -v
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/pkg/device
git commit -m "feat(pssm): pkg/device devinfo（纯函数化 OEM 解析）"
```

---

## Task 7: database 包（gorm sqlite + migration 框架）

**Files:**
- Create: `pssm/database/db.go`
- Test: `pssm/database/db_test.go`

- [ ] **Step 1: 添加依赖**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go get github.com/jinzhu/gorm@v1.9.16
go get github.com/mattn/go-sqlite3@v1.14.16
```

- [ ] **Step 2: 写失败测试**

`pssm/database/db_test.go`:
```go
package database

import (
	"path/filepath"
	"testing"
)

func TestInitDB(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "ssm.db")
	db, err := InitDB(dbPath)
	if err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	defer db.Close()

	if err := db.DB().Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}
	// migration 框架可调用，无模型时不报错
	if err := Migrate(db); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
}
```

- [ ] **Step 3: 运行确认失败**

```bash
go test ./database/ -v
```
Expected: FAIL，`InitDB`/`Migrate` 未定义（cgo 编译需 gcc，本机 x86 有 gcc 即可）。

- [ ] **Step 4: 实现 database**

`pssm/database/db.go`:
```go
// Package database 提供 sqlite(gorm) 初始化与 migration 框架。
// 地基阶段无业务模型；用户/审计子项目在 models 中注册并调用 Migrate。
package database

import (
	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
	_ "github.com/mattn/go-sqlite3"

	"ssm/logger"
)

// models 注册表：各业务子项目在 init() 中 append 自身的 gorm 模型指针。
var models []interface{}

// RegisterModel 注册一个待 AutoMigrate 的模型（线程安全由 init 阶段单线程保证）。
func RegisterModel(m ...interface{}) { models = append(models, m...) }

// InitDB 打开/创建 sqlite 文件并返回 *gorm.DB。
func InitDB(path string) (*gorm.DB, error) {
	db, err := gorm.Open("sqlite3", path)
	if err != nil {
		logger.Error("open sqlite %s failed: %v", path, err)
		return nil, err
	}
	return db, nil
}

// Migrate 对所有已注册模型执行 AutoMigrate。地基阶段 models 为空，等价 no-op。
func Migrate(db *gorm.DB) error {
	if len(models) == 0 {
		return nil
	}
	if err := db.AutoMigrate(models...).Error; err != nil {
		logger.Error("automigrate failed: %v", err)
		return err
	}
	return nil
}
```

注意：`github.com/jinzhu/gorm/dialects/sqlite` 在 gorm v1.9 中提供 sqlite 方言；若该路径在所选版本不存在，则去掉该 import 并直接用 `gorm.Open("sqlite3", path)`（mattn 驱动已注册 `"sqlite3"` driverName）。先按 Step 5 编译结果确认。

- [ ] **Step 5: 运行测试（按需修正 dialect import）**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go test ./database/ -v
```
若报 `sqlite dialect` 找不到，删除 `dialects/sqlite` 那行 import 再跑。Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/database source/pssm/go.mod source/pssm/go.sum
git commit -m "feat(pssm): database 包（gorm sqlite + migration 框架）"
```

---

## Task 8: middleware（recovery / accesslog / ratelimit）

**Files:**
- Create: `pssm/middleware/middleware.go`
- Test: `pssm/middleware/middleware_test.go`

- [ ] **Step 1: 添加依赖**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go get github.com/gin-gonic/gin@v1.9.1
go get golang.org/x/time@v0.5.0
```

- [ ] **Step 2: 写失败测试**

`pssm/middleware/middleware_test.go`:
```go
package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestRecoveryCatchesPanic(t *testing.T) {
	r := gin.New()
	r.Use(Recovery())
	r.GET("/boom", func(c *gin.Context) { panic("x") })
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/boom", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", w.Code)
	}
}

func TestRateLimitAllowsBurst(t *testing.T) {
	r := gin.New()
	r.Use(RateLimit(100, 10))
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ok", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestAccessLogNoPanic(t *testing.T) {
	r := gin.New()
	r.Use(AccessLog())
	r.GET("/ok", func(c *gin.Context) { c.Status(http.StatusOK) })
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ok", nil)
	r.ServeHTTP(w, req) // 不 panic 即通过
}
```

- [ ] **Step 3: 运行确认失败**

```bash
go test ./middleware/ -v
```
Expected: FAIL，`Recovery`/`RateLimit`/`AccessLog` 未定义。

- [ ] **Step 4: 实现 middleware**

`pssm/middleware/middleware.go`:
```go
// Package middleware 提供 gin 中间件：Recovery / AccessLog / RateLimit。
package middleware

import (
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"ssm/logger"
)

// Recovery 捕获 panic，返回 500 并记录日志。
func Recovery() gin.HandlerFunc {
	return gin.CustomRecoveryWithWriter(nil, func(c *gin.Context, rec any) {
		logger.Error("panic recovered: %v", rec)
		c.AbortWithStatus(http.StatusInternalServerError)
	})
}

// AccessLog 记录每个请求的方法/路径/状态/耗时。
func AccessLog() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		logger.Info("%s %s %d %v", c.Request.Method, c.Request.URL.Path, c.Writer.Status(), time.Since(start))
	}
}

// RateLimit 令牌桶限流：burst 突发上限，refill 每 refillEvery 补 1 token。
func RateLimit(burst int, refillEvery time.Duration) gin.HandlerFunc {
	limiter := rate.NewLimiter(rate.Every(refillEvery), burst)
	return func(c *gin.Context) {
		if limiter.Allow() {
			c.Next()
			return
		}
		c.JSON(http.StatusServiceUnavailable, "Request too frequently, please try it later")
		c.Abort()
	}
}
```

注意：顶部需补 `"net/http"` import。

- [ ] **Step 5: 补 net/http import 并运行测试**

编辑 `middleware.go`，import 块加入 `"net/http"`。

```bash
go test ./middleware/ -v
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/middleware source/pssm/go.mod source/pssm/go.sum
git commit -m "feat(pssm): middleware（recovery/accesslog/ratelimit）"
```

---

## Task 9: mvc/health + router（GET /healthz）

**Files:**
- Create: `pssm/mvc/health/health.go`
- Create: `pssm/router/router.go`
- Test: `pssm/router/router_test.go`

- [ ] **Step 1: 写失败测试**

`pssm/router/router_test.go`:
```go
package router

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"ssm/global"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestHealthz(t *testing.T) {
	global.DeviceType = "soc"
	global.DeviceRole = "SE"
	global.DeviceTypeEx = "SE8"
	global.DeviceSnEx = "DEVSN456"
	global.Version = global.BuildInfo{Version: "1.0.0", GitCommit: "abc", BuildTime: "2026-01-01"}

	r := gin.New()
	Register(r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if body["status"] != "ok" {
		t.Fatalf("status=%s", body["status"])
	}
	if body["deviceType"] != "soc" {
		t.Fatalf("deviceType=%s", body["deviceType"])
	}
	if body["sn"] != "DEVSN456" {
		t.Fatalf("sn=%s", body["sn"])
	}
	if body["version"] != "1.0.0" {
		t.Fatalf("version=%s", body["version"])
	}
}
```

- [ ] **Step 2: 运行确认失败**

```bash
go test ./router/ -v
```
Expected: FAIL，`Register` 未定义。

- [ ] **Step 3: 实现 health 控制器**

`pssm/mvc/health/health.go`:
```go
// Package health 提供 /healthz 端点。
package health

import (
	"time"

	"github.com/gin-gonic/gin"

	"ssm/global"
)

type response struct {
	Status       string `json:"status"`
	DeviceType   string `json:"deviceType"`
	Role         string `json:"role"`
	DeviceTypeEx string `json:"deviceTypeEx,omitempty"`
	SN           string `json:"sn"`
	Version      string `json:"version"`
	Uptime       string `json:"uptime"`
}

// Health 处理 GET /healthz。
func Health(c *gin.Context) {
	uptime := time.Since(global.Started).Truncate(time.Second).String()
	c.JSON(200, response{
		Status:       "ok",
		DeviceType:   global.DeviceType,
		Role:         global.DeviceRole,
		DeviceTypeEx: global.DeviceTypeEx,
		SN:           global.DeviceSnEx,
		Version:      global.Version.Version,
		Uptime:       uptime,
	})
}
```

- [ ] **Step 4: 实现 router**

`pssm/router/router.go`:
```go
// Package router 注册全部路由。地基阶段仅 /healthz；后续模块在此扩展。
package router

import (
	"github.com/gin-gonic/gin"

	"ssm/mvc/health"
)

// Register 在 engine 上注册所有路由。
func Register(r *gin.Engine) {
	r.GET("/healthz", health.Health)
}
```

- [ ] **Step 5: 运行测试**

```bash
go test ./router/ -v
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/mvc source/pssm/router
git commit -m "feat(pssm): mvc/health + router（/healthz）"
```

---

## Task 10: initialization（InitBase / Routers / InitServer）

**Files:**
- Create: `pssm/initialization/init.go`
- Create: `pssm/initialization/router.go`
- Create: `pssm/initialization/server.go`

- [ ] **Step 1: 实现 InitBase**

`pssm/initialization/init.go`:
```go
// Package initialization 串联启动流程：配置→日志→设备信息→DB。
package initialization

import (
	"time"

	"ssm/config"
	"ssm/database"
	"ssm/global"
	"ssm/logger"
	"ssm/pkg/device"
)

// InitBase 启动阶段基础初始化。
func InitBase() {
	config.LoadConfig()

	conf := &config.Conf
	conf.RLock()
	logLevel := conf.GetViper().GetString("log.level")
	logPath := conf.GetViper().GetString("log.path")
	dbPath := conf.GetViper().GetString("db.path")
	conf.RUnlock()

	logger.InitLogging(logPath, "ssm.log", logLevel)
	logger.Info("ssm starting, version=%s", global.Version.String())

	global.Started = time.Now()

	device.GetDeviceInfo()
	global.DeviceType = device.DeviceType
	global.DeviceRole = device.DeviceRole
	global.DeviceTypeEx = device.DeviceTypeEx
	global.DeviceSnEx = device.DeviceSnEx
	global.ChipSn = device.ChipSn
	global.ModuleType = device.ModuleType
	logger.Info("device: type=%s role=%s typeEx=%s sn=%s",
		global.DeviceType, global.DeviceRole, global.DeviceTypeEx, global.DeviceSnEx)

	// DB：地基阶段失败不阻断启动（无业务依赖）
	if db, err := database.InitDB(dbPath); err == nil {
		if err := database.Migrate(db); err != nil {
			logger.Warn("migrate failed: %v", err)
		}
		globalDB = db
	} else {
		logger.Warn("db init failed (non-fatal): %v", err)
	}
}

// globalDB 保留 db 句柄供后续模块使用（地基阶段仅占位）。
var globalDB interface{ Close() error }
```

注意：`globalDB` 用 `interface{ Close() error }` 以避免在 initialization 包里直接 import gorm 形成循环；后续若需可改为 `*gorm.DB`。`database.InitDB` 返回 `*gorm.DB` 满足该接口。

- [ ] **Step 2: 实现 Routers**

`pssm/initialization/router.go`:
```go
package initialization

import (
	"time"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/middleware"
	"ssm/router"
)

// Routers 构建 gin engine 并挂载中间件与路由。
func Routers() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(middleware.Recovery())
	r.Use(middleware.AccessLog())
	r.Use(middleware.RateLimit(100, 10*time.Millisecond))
	router.Register(r)
	return r
}

// listenAddr 从配置读取监听地址。
func listenAddr() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	v := conf.GetViper()
	ip := v.GetString("server.listenIP")
	port := v.GetString("server.port")
	if port == "" {
		port = "9779"
	}
	return ip + ":" + port
}
```

- [ ] **Step 3: 实现 InitServer**

`pssm/initialization/server.go`:
```go
package initialization

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"ssm/logger"
)

// InitServer 构造 *http.Server。
func InitServer(r *gin.Engine) *http.Server {
	addr := listenAddr()
	logger.Info("HTTP listen on %s", addr)
	return &http.Server{
		Addr:         addr,
		Handler:      r,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
	}
}
```

- [ ] **Step 4: 编译验证**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go build ./...
```
Expected: 无错误。

- [ ] **Step 5: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/initialization
git commit -m "feat(pssm): initialization（InitBase/Routers/InitServer）"
```

---

## Task 11: main.go（信号 + 优雅退出）

**Files:**
- Modify: `pssm/main.go`（替换 Task 1 的 stub）
- Test: `pssm/main_test.go`

- [ ] **Step 1: 写失败测试（验证 Routers+health 端到端可用）**

`pssm/main_test.go`:
```go
package main

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"ssm/initialization"
)

func TestServerHealthzEndToEnd(t *testing.T) {
	r := initialization.Routers()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}
```

- [ ] **Step 2: 运行确认失败（main stub 还在）**

```bash
go test ./... -v
```
Expected: `TestServerHealthzEndToEnd` 可能因 main.go stub 无 initialization 引用而编译失败——这正是驱动我们写真正 main.go 的信号。

- [ ] **Step 3: 替换 main.go**

`pssm/main.go`:
```go
package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ssm/initialization"
	"ssm/logger"
)

func main() {
	initialization.InitBase()
	r := initialization.Routers()
	s := initialization.InitServer(r)

	go func() {
		if err := s.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("listen failed: %v", err)
			os.Exit(1)
		}
	}()

	logger.Info("ssm ready")

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGHUP, syscall.SIGINT, syscall.SIGTERM, syscall.SIGQUIT)
	sg := <-sig
	logger.Info("signal %v received, shutting down", sg)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		logger.Error("graceful shutdown failed: %v", err)
	}
	logger.Sync()
}
```

- [ ] **Step 4: 运行全部测试**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
go test ./... -v
```
Expected: 全部 PASS。

- [ ] **Step 5: 本地冒烟（手动）**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
mkdir -p /tmp/ssm-log
# 用本地配置覆盖日志/db 路径，避免写到 /var
cat > /tmp/ssm-conf/ssm.yaml 2>/dev/null <<'EOF' || mkdir -p /tmp/ssm-conf && cat > /tmp/ssm-conf/ssm.yaml <<'EOF'
server:
  port: 9779
log:
  level: info
  path: /tmp/ssm-log
db:
  path: /tmp/ssm/ssm.db
EOF
mkdir -p /tmp/ssm
SSM_CONF=/tmp/ssm-conf go run . &
sleep 1
curl -s http://127.0.0.1:9779/healthz
kill %1
```
注意：`config.LoadConfig` 当前固定读 `/etc/ssm/conf`；本地冒烟时可临时 `sudo mkdir -p /etc/ssm/conf && sudo cp config/ssm.yaml /etc/ssm/conf/`，或在此步先加一个 `SSM_CONF` 环境变量回退路径（推荐，便于测试）。若加环境回退，修改 `config.LoadConfig`：
```go
func LoadConfig() {
	if env := os.Getenv("SSM_CONF"); env != "" {
		LoadFromDir(env)
		return
	}
	LoadFromDir(DefaultConfigPath)
}
```
（需在 config.go import `"os"`。）采用此修改后，本步 `SSM_CONF=/tmp/ssm-conf go run .` 即可。Expected: `curl` 返回 `{"status":"ok",...}`。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm
git commit -m "feat(pssm): main.go 信号处理与优雅退出"
```

---

## Task 12: 构建脚本

**Files:**
- Create: `pssm/build/version.sh`
- Create: `pssm/build/build-ssm.sh`
- Create: `pssm/build/build-ssm-arm64.sh`

- [ ] **Step 1: version.sh**

`pssm/build/version.sh`:
```bash
#!/bin/bash
# 生成版本头信息，写入 build/version.txt 供 ldflags 读取
set -e
VERSION="${1:-1.0.0}"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILDTIME="$(date '+%Y-%m-%d_%H:%M:%S')"
cat > "$(dirname "$0")/version.txt" <<EOF
${VERSION}|${COMMIT}|${BUILDTIME}
EOF
cat "$(dirname "$0")/version.txt"
```

- [ ] **Step 2: build-ssm.sh（x86）**

`pssm/build/build-ssm.sh`:
```bash
#!/bin/bash
# x86 构建
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-1.0.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

LDFLAGS="-s -w -X global.Version.Version=${VERSION} -X global.Version.GitCommit=${COMMIT} -X global.Version.BuildTime=${BUILDTIME}"

CGO_ENABLED=1 go build -trimpath -ldflags "${LDFLAGS}" -o ssm .

mkdir -p release
cp ssm release/
cp config/ssm.yaml release/
echo "built release/ssm (x86)"
```

- [ ] **Step 3: build-ssm-arm64.sh（aarch64 交叉编译）**

`pssm/build/build-ssm-arm64.sh`:
```bash
#!/bin/bash
# aarch64 交叉编译（需 gcc-aarch64-linux-gnu）
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-1.0.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

LDFLAGS="-s -w -X global.Version.Version=${VERSION} -X global.Version.GitCommit=${COMMIT} -X global.Version.BuildTime=${BUILDTIME}"

CGO_ENABLED=1 GOOS=linux GOARCH=arm64 CC=aarch64-linux-gnu-gcc \
  go build -trimpath -ldflags "${LDFLAGS}" -o ssm-arm64 .

mkdir -p release
cp ssm-arm64 release/ssm
cp config/ssm.yaml release/
echo "built release/ssm (arm64)"
```

- [ ] **Step 4: 加可执行权限并本地验证 x86 构建**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
chmod +x build/*.sh
bash build/build-ssm.sh
./release/ssm &
sleep 1
curl -s http://127.0.0.1:9779/healthz
kill %1
```
Expected: `curl` 返回含 `"status":"ok"` 的 JSON。

- [ ] **Step 5: 验证 arm64 交叉编译产物**

```bash
cd /home/zzt/workspace/sophon-tools/source/pssm
bash build/build-ssm-arm64.sh
file release/ssm
```
Expected: `file` 输出含 `ELF 64-bit LSB executable, ARM aarch64`。

- [ ] **Step 6: Commit**

```bash
cd /home/zzt/workspace/sophon-tools
git add source/pssm/build
git commit -m "build(pssm): x86 与 arm64 构建脚本"
```

---

## Task 13: 真机部署验证（172.26.166.185）

**Files:** 无（验证任务）

- [ ] **Step 1: 确认 arm64 产物已生成**

```bash
ls -la /home/zzt/workspace/sophon-tools/source/pssm/release/
```
Expected: 存在 `ssm`（arm64 ELF）与 `ssm.yaml`。

- [ ] **Step 2: scp 产物到真机**

```bash
sshpass -p linaro scp -o StrictHostKeyChecking=no \
  /home/zzt/workspace/sophon-tools/source/pssm/release/ssm \
  /home/zzt/workspace/sophon-tools/source/pssm/release/ssm.yaml \
  linaro@172.26.166.185:/tmp/
```
若本机无 `sshpass`：`sudo apt-get install -y sshpass`。

- [ ] **Step 3: 部署配置并运行**

```bash
sshpass -p linaro ssh -o StrictHostKeyChecking=no linaro@172.26.166.185 \
  'mkdir -p /tmp/ssm-log /tmp/ssm-conf /tmp/ssm && \
   cp /tmp/ssm.yaml /tmp/ssm-conf/ && \
   sed -i "s#/var/log/ssm#/tmp/ssm-log#; s#/var/lib/ssm/ssm.db#/tmp/ssm/ssm.db#" /tmp/ssm-conf/ssm.yaml && \
   SSM_CONF=/tmp/ssm-conf nohup /tmp/ssm > /tmp/ssm/ssm.out 2>&1 & \
   sleep 1 && curl -s http://127.0.0.1:9779/healthz'
```
Expected: 返回 JSON，`deviceType` 为 `"soc"`，`role` 为 `"SE"`，`sn` 非空（与真机 OEM 一致）。

- [ ] **Step 4: 校验设备信息与真机一致**

```bash
sshpass -p linaro ssh -o StrictHostKeyChecking=no linaro@172.26.166.185 \
  'echo "--- OEM ---"; cat /factory/OEMconfig.ini 2>/dev/null; echo "--- healthz ---"; curl -s http://127.0.0.1:9779/healthz'
```
Expected: `/healthz` 的 `sn`/`deviceTypeEx` 与 `OEMconfig.ini` 中的 `SN`/`PRODUCT` 对应一致。

- [ ] **Step 5: 验证优雅退出**

```bash
sshpass -p linaro ssh -o StrictHostKeyChecking=no linaro@172.26.166.185 \
  'pid=$(pgrep -f /tmp/ssm); kill -TERM $pid; sleep 1; pgrep -f /tmp/ssm || echo "stopped cleanly"'
```
Expected: 输出 `stopped cleanly`。

- [ ] **Step 6: 清理真机**

```bash
sshpass -p linaro ssh -o StrictHostKeyChecking=no linaro@172.26.166.185 \
  'pkill -f /tmp/ssm 2>/dev/null; rm -rf /tmp/ssm* /tmp/ssm-conf /tmp/ssm-log'
```

- [ ] **Step 7: 记录验证结果到 commit message**

```bash
cd /home/zzt/workspace/sophon-tools
git commit --allow-empty -m "test(pssm): 地基子项目真机验证通过（172.26.166.185 SOC）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自查（writing-plans skill self-review）

**1. Spec 覆盖：**
- 目录布局（spec §2）→ Task 1–11 逐一建出
- config（§3.1）→ Task 4
- logger zap（§3.2）→ Task 2
- global（§3.3）→ Task 5
- pkg/device devinfo SOC 分支（§3.4）→ Task 6
- initialization InitBase/Routers/InitServer（§3.5）→ Task 10
- router + mvc/health GET /healthz（§3.6）→ Task 9
- middleware recovery/accesslog/ratelimit/auth 占位（§3.7）→ Task 8（auth 占位：spec 说"地基阶段不启用"，本计划未建 auth 中间件，符合"不启用"——但留扩展位：后续在 middleware 包新增即可，无需地基代码。✓）
- main.go 信号优雅退出（§3.8）→ Task 11
- 错误处理降级（§4）→ Task 6（devinfo 降级）、Task 10（DB 失败不阻断）、Task 4（配置默认值）
- 单元测试（§5）→ Task 2–9 各有测试
- 真机验证（§5）→ Task 13
- 构建脚本（§6）→ Task 12
- 关键决策（§7）→ 全程一致

**2. 占位符扫描：** 无 TBD/TODO；所有代码步骤均含完整代码。Task 7 的 dialect import 有条件分支说明（已给出两种情况的处置），非占位。

**3. 类型一致性：**
- `BuildInfo.String()` → Task 5 定义，Task 11（main）用 `global.Version.String()` ✓
- `device.DeviceType` 等包级变量 → Task 6 定义，Task 10 `initialization` 读取并回写 global ✓
- `config.Conf.GetViper()` → Task 4 定义，Task 10/11 使用 ✓
- `database.InitDB/`Migrate` → Task 7 定义，Task 10 调用 ✓
- `middleware.Recovery/AccessLog/RateLimit` 签名 → Task 8 定义，Task 10 使用，参数 `(100, 10*time.Millisecond)` 与测试一致 ✓
- `router.Register(r)` → Task 9 定义，Task 10 使用 ✓
- `RateLimit(burst int, refillEvery time.Duration)` → Task 8 定义，Task 10 `RateLimit(100, 10*time.Millisecond)` ✓
- `logger.InitLogging(dir, filename, level)` → Task 2 定义，Task 10 调用 `(logPath, "ssm.log", logLevel)` ✓

无类型/签名漂移。

---

## Execution Handoff

Plan complete and saved to `source/pssm/docs/superpowers/plans/2026-07-02-pssm-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 每个 Task 派一个全新 subagent，Task 间两阶段评审，迭代快
2. **Inline Execution** - 在当前会话用 executing-plans 批量执行，带检查点评审

Which approach?
