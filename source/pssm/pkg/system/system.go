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
// 注意：cmd 经 bash 解释，调用方必须确保不含用户可控输入（避免注入）。
// 对含用户输入的命令，改用 RunCommandArgs。
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

// RunCommandArgs 直接执行 name，args 作为独立参数传入（不经 shell）。
// 用于含用户输入的命令，避免 shell 注入。
func RunCommandArgs(name string, args ...string) (outStr, errStr string, err error) {
	c := exec.Command(name, args...)
	var outBuf, errBuf bytes.Buffer
	c.Stdout = &outBuf
	c.Stderr = &errBuf
	err = c.Run()
	outStr = outBuf.String()
	errStr = errBuf.String()
	return
}