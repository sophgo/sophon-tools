// Package metrics 提供设备指标采集（纯 Go，无 cgo/bmlib）。
//
// 所有读取通过可注入的 FileReader / CmdRunner 接口进行，便于 TDD 夹具测试。
// 每个采集函数失败降级返零值/空串，不 panic、不阻断调用方。
package metrics

import (
	"os"
	"strings"
	"time"

	"bmssm/pkg/system"
)

// FileReader 读文件（可注入，便于 sysfs 夹具测试）。
type FileReader interface {
	ReadFile(path string) ([]byte, error)
}

// CmdRunner 执行外部命令（可注入，便于测试）。
type CmdRunner interface {
	Run(name string, args ...string) (string, error)
}

// Sleeeper 用于 CPU 利用率双采样间隔（可注入，测试时无延迟）。
type Sleeeper interface {
	Sleep(d time.Duration)
}

// Collector 设备指标采集器。所有方法均降级安全（失败返零值）。
type Collector struct {
	fr    FileReader
	cmd   CmdRunner
	sleep Sleeeper
}

// NewCollector 创建 Collector（依赖注入，便于测试）。
func NewCollector(fr FileReader, cmd CmdRunner) *Collector {
	return &Collector{
		fr:    fr,
		cmd:   cmd,
		sleep: realSleeper{},
	}
}

// NewCollectorWithSleep 创建带可注入 sleep 的 Collector（CPU 利用率测试用）。
func NewCollectorWithSleep(fr FileReader, cmd CmdRunner, s Sleeeper) *Collector {
	return &Collector{fr: fr, cmd: cmd, sleep: s}
}

// NewDefaultCollector 创建生产环境 Collector（os 实现）。
func NewDefaultCollector() *Collector {
	return NewCollector(&osFileReader{}, &osCmdRunner{})
}

// --- 生产实现 ---

type osFileReader struct{}

func (r *osFileReader) ReadFile(path string) ([]byte, error) {
	return os.ReadFile(path)
}

// osCmdRunner 复用 pkg/system 的参数化执行（不经 shell，防注入）。
type osCmdRunner struct{}

func (r *osCmdRunner) Run(name string, args ...string) (string, error) {
	out, _, err := system.RunCommandArgs(name, args...)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}
// realSleeper 调用 time.Sleep。
type realSleeper struct{}

func (realSleeper) Sleep(d time.Duration) { time.Sleep(d) }

// noopSleeper 测试用，立即返回。
type noopSleeper struct{}

func (noopSleeper) Sleep(time.Duration) {}

// --- 内部辅助 ---

// readStr 读文件并 TrimSpace；失败返空串。
func (c *Collector) readStr(path string) string {
	if c.fr == nil {
		return ""
	}
	data, err := c.fr.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}
