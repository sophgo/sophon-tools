package firewall

import "bmssm/pkg/system"

// CommandRunner 抽象外部命令执行，便于测试注入 fake。
type CommandRunner interface {
	Run(name string, args ...string) (stdout, stderr string, err error)
}

// SystemRunner 生产实现，委托 system.RunCommandArgs（参数化，不经 shell）。
type SystemRunner struct{}

func (SystemRunner) Run(name string, args ...string) (string, string, error) {
	return system.RunCommandArgs(name, args...)
}

// DefaultRunner 全模块默认使用；测试可临时替换后恢复。
var DefaultRunner CommandRunner = SystemRunner{}
