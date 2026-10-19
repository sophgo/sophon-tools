package main

// GUI 状态层：与 Fyne 控件解耦，便于无显示环境下单测。
//
// 设计取向（对应需求「UI 功能需要与原 UI 设计对齐，或选择人机功效更优的方案」）：
//   * 对齐：设备表 / 操作表 / 三段式操作配置（命令、上传、下载）/ 日志区 / 并行上限
//     / 内置预设 / 根目录 / 载入 / 保存 / 执行，一个不少。
//   * 改进：旧版必须先「储存该项」才会把编辑写回数据，容易忘按导致丢配置；
//     这里编辑即生效，并取消隐式状态。旧版"完整度"靠隐藏字段推断，这里显式展示。

import (
	"sync"
)

// DeviceRow 设备表一行。
type DeviceRow struct {
	Inf    RemoteInf
	Status string // 执行状态文本
}

// OpRow 操作表一行。
type OpRow struct {
	Inf OperationInf
}

// GUIState 界面数据模型。
type GUIState struct {
	mu             sync.RWMutex
	rootDir        string
	devices        []DeviceRow
	ops            []OpRow
	maxPar         int
	selectedDevice int // -1 表示未选中——旧版正是在未选中时读 currentRow()=-1 崩溃
	logs           map[int]string
}

// NewGUIState 构造初始状态（含一行示例设备，与旧版默认一致）。
func NewGUIState() *GUIState {
	return &GUIState{
		devices: []DeviceRow{{
			Inf: RemoteInf{IP: "192.168.150.1", Port: 22, Username: "linaro", Password: "linaro"},
		}},
		ops: []OpRow{{
			Inf: OperationInf{Name: "检查时间", Type: OpCommand, CommandStr: "date", CheckFile: CheckMD5},
		}},
		maxPar:         defaultMaxParallel,
		selectedDevice: -1,
		logs:           map[int]string{},
	}
}

func (s *GUIState) RootDir() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.rootDir
}

func (s *GUIState) SetRootDir(p string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.rootDir = p
}

func (s *GUIState) MaxParallel() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.maxPar
}

func (s *GUIState) SetMaxParallel(n int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n > 0 {
		s.maxPar = n
	}
}

func (s *GUIState) Devices() []DeviceRow {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]DeviceRow, len(s.devices))
	copy(out, s.devices)
	return out
}

func (s *GUIState) SetDevices(d []DeviceRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.devices = d
	s.selectedDevice = -1 // 列表被整体替换后，旧选中下标已失效
}

func (s *GUIState) DeviceCount() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.devices)
}

// UpdateDevice 更新单台设备；下标越界返回 false 而不是 panic
// （旧版多处直接 item(row,...) 未判界）。
func (s *GUIState) UpdateDevice(i int, inf RemoteInf) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.devices) {
		return false
	}
	s.devices[i].Inf = inf
	return true
}

func (s *GUIState) SetDeviceStatus(i int, st string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.devices) {
		return false
	}
	s.devices[i].Status = st
	return true
}

// RemoveDevice 删除设备；删空后 selectedDevice 归 -1，不允许再访问旧下标。
func (s *GUIState) RemoveDevice(i int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.devices) {
		return false
	}
	s.devices = append(s.devices[:i], s.devices[i+1:]...)
	s.selectedDevice = -1
	return true
}

// CloneDevice 在 i 之后插入一份副本。
func (s *GUIState) CloneDevice(i int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.devices) {
		return false
	}
	dup := s.devices[i]
	dup.Status = ""
	s.devices = append(s.devices[:i+1], append([]DeviceRow{dup}, s.devices[i+1:]...)...)
	return true
}

// SelectDevice 记录当前选中设备；-1 合法（表示无选中），调用方必须容忍。
func (s *GUIState) SelectDevice(i int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.selectedDevice = i
}

func (s *GUIState) SelectedDevice() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.selectedDevice
}

// SelectedDeviceInf 返回选中设备；无选中时 ok=false（旧版在此崩溃）。
func (s *GUIState) SelectedDeviceInf() (RemoteInf, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.selectedDevice < 0 || s.selectedDevice >= len(s.devices) {
		return RemoteInf{}, false
	}
	return s.devices[s.selectedDevice].Inf, true
}

func (s *GUIState) Ops() []OpRow {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]OpRow, len(s.ops))
	copy(out, s.ops)
	return out
}

func (s *GUIState) SetOps(o []OpRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ops = o
}

func (s *GUIState) UpdateOp(i int, inf OperationInf) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.ops) {
		return false
	}
	s.ops[i].Inf = inf
	return true
}

func (s *GUIState) RemoveOp(i int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.ops) {
		return false
	}
	s.ops = append(s.ops[:i], s.ops[i+1:]...)
	return true
}

func (s *GUIState) CloneOp(i int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if i < 0 || i >= len(s.ops) {
		return false
	}
	dup := s.ops[i]
	s.ops = append(s.ops[:i+1], append([]OpRow{dup}, s.ops[i+1:]...)...)
	return true
}

// AppendDevice / AppendOp 供"新增"按钮使用（旧版只能靠克隆再加行）。
func (s *GUIState) AppendDevice(d RemoteInf) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.devices = append(s.devices, DeviceRow{Inf: d})
}

func (s *GUIState) AppendOp(o OperationInf) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ops = append(s.ops, OpRow{Inf: o})
}

// ToConfig 导出为可保存/执行的配置。
func (s *GUIState) ToConfig() *Config {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c := &Config{
		RemoteInf:    make([]RemoteInf, 0, len(s.devices)),
		OperationInf: make([]OperationInf, 0, len(s.ops)),
	}
	for _, d := range s.devices {
		c.RemoteInf = append(c.RemoteInf, d.Inf)
	}
	for _, o := range s.ops {
		c.OperationInf = append(c.OperationInf, o.Inf)
	}
	return c
}

// LoadConfig 用配置整体替换状态。
//
// 注意：内置预设（inSE6conf/outSE6conf）只含设备清单、不含 operationInf。
// 这种情况下保留用户已配置的操作，否则「载入设备清单」会把操作表清空——
// 旧版 Qt 实现正是用同一个函数覆盖两张表，且因缺 operationInf 弹
// "Invalid JSON data in file" 警告，体验很差。
func (s *GUIState) LoadConfig(c *Config) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.devices = make([]DeviceRow, 0, len(c.RemoteInf))
	for _, d := range c.RemoteInf {
		s.devices = append(s.devices, DeviceRow{Inf: d})
	}
	if len(c.OperationInf) > 0 {
		s.ops = make([]OpRow, 0, len(c.OperationInf))
		for _, o := range c.OperationInf {
			s.ops = append(s.ops, OpRow{Inf: o})
		}
	}
	s.selectedDevice = -1
	s.logs = map[int]string{}
}

// Log 返回某台设备的日志。
func (s *GUIState) Log(i int) string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.logs[i]
}

func (s *GUIState) AppendLog(i int, text string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.logs[i] += text
}

func (s *GUIState) ClearLogs() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.logs = map[int]string{}
}

// CompleteOpCount 返回配置完整的操作数，供界面提示。
func (s *GUIState) CompleteOpCount() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	n := 0
	for _, o := range s.ops {
		if o.Inf.IsComplete() {
			n++
		}
	}
	return n
}
