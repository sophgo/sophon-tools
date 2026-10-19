package main

// 配置模型：字段与现有 JSON 完全兼容（REQUIREMENTS §7「不改 JSON 格式」）。
//
// 现有格式由 mainwindow.cpp:writeTableDataToJson 写出：
//
//	{"remoteInf":[{"IP","Port","Username","Password"}],
//	 "operationInf":[{"name","type","commandStr","checkSuccessStr","checkErrorStr",
//	                  "transferFileSourcePath","transferFileDestinationPath","checkFile"}]}
//
// 这里刻意保持字段名一字不差，使旧配置文件无需任何迁移即可被新版读取。

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

// 操作类型，取值与旧版 OperationInfData::operationType 一致。
const (
	OpCommand  = 0 // 下发命令
	OpUpFile   = 1 // 上传文件
	OpDownFile = 2 // 下载文件
)

// 校验方式，取值与旧版 checkFileMethods 一致。
const (
	CheckMD5  = 0
	CheckSize = 1
	CheckNone = 2
)

// RemoteInf 一台目标设备。
type RemoteInf struct {
	IP       string `json:"IP"`
	Port     int    `json:"Port"`
	Username string `json:"Username"`
	Password string `json:"Password"`
}

// OperationInf 一条对每台设备执行的批量操作。
type OperationInf struct {
	Name                        string `json:"name"`
	Type                        int    `json:"type"`
	CommandStr                  string `json:"commandStr"`
	CheckSuccessStr             string `json:"checkSuccessStr"`
	CheckErrorStr               string `json:"checkErrorStr"`
	TransferFileSourcePath      string `json:"transferFileSourcePath"`
	TransferFileDestinationPath string `json:"transferFileDestinationPath"`
	CheckFile                   int    `json:"checkFile"`
}

// Config 顶层配置文件。
//
// 超时字段是**可选新增**：旧配置没有它们，取零值时使用内置默认，
// 因此对旧文件完全向后兼容（encoding/json 对缺失字段就是零值）。
type Config struct {
	RemoteInf    []RemoteInf    `json:"remoteInf"`
	OperationInf []OperationInf `json:"operationInf"`

	// 单条命令的超时秒数；0 或省略 = 默认 5 分钟。
	// 刷机、升级等长任务需要放宽时在此配置。
	CommandTimeoutSec int `json:"commandTimeoutSec,omitempty"`
	// 单次文件传输的超时秒数；0 或省略 = 默认 30 分钟。
	TransferTimeoutSec int `json:"transferTimeoutSec,omitempty"`
}

// Timeouts 把配置里的秒数换算成 time.Duration，零值保持 0（由执行器取默认）。
func (c *Config) Timeouts() (command, transfer time.Duration) {
	if c.CommandTimeoutSec > 0 {
		command = time.Duration(c.CommandTimeoutSec) * time.Second
	}
	if c.TransferTimeoutSec > 0 {
		transfer = time.Duration(c.TransferTimeoutSec) * time.Second
	}
	return command, transfer
}

// TypeName 返回操作类型的中文名，与旧版 operationTypeStrList 一致。
func (o OperationInf) TypeName() string {
	switch o.Type {
	case OpCommand:
		return "下发命令"
	case OpUpFile:
		return "上传文件"
	case OpDownFile:
		return "下载文件"
	}
	return "未知"
}

// CheckName 返回校验方式中文名，与旧版 checkFileStrList 一致。
func (o OperationInf) CheckName() string {
	switch o.CheckFile {
	case CheckMD5:
		return "MD5校验值"
	case CheckSize:
		return "文件大小校验"
	case CheckNone:
		return "不进行校验"
	}
	return "未知"
}

// Validate 判断该操作配置是否完整（对应旧版 checkStatus）。
// 不完整的操作不会被执行，而不是让程序崩溃或静默跳过。
func (o OperationInf) Validate() error {
	if strings.TrimSpace(o.Name) == "" {
		return errors.New("操作名称为空")
	}
	switch o.Type {
	case OpCommand:
		if strings.TrimSpace(o.CommandStr) == "" {
			return fmt.Errorf("操作 %q:命令为空", o.Name)
		}
	case OpUpFile, OpDownFile:
		if strings.TrimSpace(o.TransferFileSourcePath) == "" {
			return fmt.Errorf("操作 %q:源路径为空", o.Name)
		}
		if strings.TrimSpace(o.TransferFileDestinationPath) == "" {
			return fmt.Errorf("操作 %q:目标路径为空", o.Name)
		}
	default:
		return fmt.Errorf("操作 %q:未知类型 %d", o.Name, o.Type)
	}
	return nil
}

// IsComplete 供 UI 显示「完整/不完整」。
func (o OperationInf) IsComplete() bool { return o.Validate() == nil }

// Validate 校验整份配置是否可执行。
//
// 语义（GUI 与 CLI 完全一致）：设备必须全部合法，且至少有一条配置完整的操作。
// 不完整的操作**不算错误**——它们会在执行时被跳过并在界面/终端上明确列出，
// 这与旧版「标记不完整」的交互一致；旧版 argsparse.cpp 在缺少 remoteInf/
// operationInf 或数组为空时既不报错也不退出，会静默跑空或走到空指针崩溃路径，
// 这里显式报错。
func (c *Config) Validate() error {
	if err := c.ValidateDevices(); err != nil {
		return err
	}
	if len(c.CompleteOperations()) == 0 {
		return errors.New("没有配置完整的操作可执行")
	}
	return nil
}

// ValidateDevices 只校验设备表。
func (c *Config) ValidateDevices() error {
	if len(c.RemoteInf) == 0 {
		return errors.New("配置中没有设备（remoteInf 为空）")
	}
	if len(c.OperationInf) == 0 {
		return errors.New("配置中没有操作（operationInf 为空）")
	}
	for i, r := range c.RemoteInf {
		if strings.TrimSpace(r.IP) == "" {
			return fmt.Errorf("第 %d 台设备:IP 为空", i+1)
		}
		if r.Port <= 0 || r.Port > 65535 {
			return fmt.Errorf("第 %d 台设备（%s）:端口 %d 非法", i+1, r.IP, r.Port)
		}
		if strings.TrimSpace(r.Username) == "" {
			return fmt.Errorf("第 %d 台设备（%s）:用户名为空", i+1, r.IP)
		}
	}
	return nil
}

// IncompleteOperations 返回不会被执行的操作及其原因，供界面/CLI 明确提示。
// 旧版只是把表格文字换成「该项配置不完整，将不会执行」，不说明缺了什么。
func (c *Config) IncompleteOperations() map[int]error {
	out := map[int]error{}
	for i, o := range c.OperationInf {
		if err := o.Validate(); err != nil {
			out[i] = err
		}
	}
	return out
}

// CompleteOperations 只返回配置完整的操作（旧版语义：不完整的跳过不执行）。
func (c *Config) CompleteOperations() []OperationInf {
	out := make([]OperationInf, 0, len(c.OperationInf))
	for _, o := range c.OperationInf {
		if o.IsComplete() {
			out = append(out, o)
		}
	}
	return out
}

// LoadConfig 从文件读取配置。
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取配置文件失败: %w", err)
	}
	return ParseConfig(data)
}

// ParseConfig 从字节解析配置（文件与内置预设共用）。
func ParseConfig(data []byte) (*Config, error) {
	var c Config
	if err := json.Unmarshal(data, &c); err != nil {
		return nil, fmt.Errorf("解析配置文件失败: %w", err)
	}
	return &c, nil
}

// unmarshalConfig 供 assets.go 复用。
func unmarshalConfig(data []byte, c *Config) error {
	return json.Unmarshal(data, c)
}

// SaveConfig 写出配置，格式与旧版一致（两空格缩进，便于人工查看与 diff）。
func SaveConfig(path string, c *Config) error {
	if c.RemoteInf == nil {
		c.RemoteInf = []RemoteInf{}
	}
	if c.OperationInf == nil {
		c.OperationInf = []OperationInf{}
	}
	data, err := json.MarshalIndent(c, "", "    ")
	if err != nil {
		return fmt.Errorf("序列化配置失败: %w", err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("写入配置文件失败: %w", err)
	}
	return nil
}

// checkFileOptions 返回校验方式下拉的选项，顺序与 CheckName 一致。
func checkFileOptions() []string {
	return []string{
		(OperationInf{CheckFile: CheckMD5}).CheckName(),
		(OperationInf{CheckFile: CheckSize}).CheckName(),
		(OperationInf{CheckFile: CheckNone}).CheckName(),
	}
}

// parseCheckFile 把下拉选项还原成 checkFile 取值；无法识别时保守取 MD5。
func parseCheckFile(name string) int {
	switch name {
	case (OperationInf{CheckFile: CheckSize}).CheckName():
		return CheckSize
	case (OperationInf{CheckFile: CheckNone}).CheckName():
		return CheckNone
	}
	return CheckMD5
}
