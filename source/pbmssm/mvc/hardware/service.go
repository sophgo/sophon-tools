package hardware

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"bmssm/global"
	"bmssm/pkg/system"
)

// CmdRunner 执行外部命令（可注入，便于测试）。
type CmdRunner interface {
	Run(name string, args ...string) (string, error)
}

// FileReader 读文件（可注入，便于 sysfs 夹具测试）。
type FileReader interface {
	ReadFile(path string) ([]byte, error)
}

// Rebooter 执行重启（可注入——测试绝不能真重启）。
type Rebooter interface {
	Reboot() error
}

// --- 生产实现 ---

type osCmdRunner struct{}

func (r *osCmdRunner) Run(name string, args ...string) (string, error) {
	out, errStr, err := system.RunCommandArgs(name, args...)
	if err != nil {
		return "", fmt.Errorf("%v: %s", err, errStr)
	}
	return strings.TrimSpace(out), nil
}

type osFileReader struct{}

func (r *osFileReader) ReadFile(path string) ([]byte, error) {
	return os.ReadFile(path)
}

type osRebooter struct{}

func (r *osRebooter) Reboot() error {
	_, errStr, err := system.RunCommandArgs("/sbin/reboot")
	if err != nil {
		return fmt.Errorf("reboot failed: %v: %s", err, errStr)
	}
	return nil
}

// HardwareService 硬件模块业务逻辑（无 gin 依赖，可单测）。
type HardwareService struct {
	cmdRunner  CmdRunner
	fileReader FileReader
	rebooter   Rebooter
}

// NewService 创建 HardwareService（依赖注入）。
func NewService(cmd CmdRunner, fr FileReader, rb Rebooter) *HardwareService {
	return &HardwareService{
		cmdRunner:  cmd,
		fileReader: fr,
		rebooter:   rb,
	}
}

// NewDefaultService 创建生产环境 HardwareService。
func NewDefaultService() *HardwareService {
	return NewService(&osCmdRunner{}, &osFileReader{}, &osRebooter{})
}

// GetHealth 从 sysfs 读取 CPU 温度 + 进程 uptime，返回健康状态。
// 温度读取失败不报错，字段留空（降级）。
func (s *HardwareService) GetHealth() HealthResponse {
	uptime := time.Since(global.Started).Truncate(time.Second).String()

	resp := HealthResponse{
		Uptime: uptime,
	}

	// 尝试从 thermal_zone 读取温度
	temp := s.readCPUTemp()
	if temp != "" {
		resp.CPUTemp = temp
	}

	return resp
}

// readCPUTemp 遍历 /sys/class/thermal/thermal_zone*/temp，返回第一个可读温度。
// sysfs temp 值单位是毫摄氏度。
func (s *HardwareService) readCPUTemp() string {
	for i := 0; i < 10; i++ {
		path := fmt.Sprintf("/sys/class/thermal/thermal_zone%d/temp", i)
		data, err := s.fileReader.ReadFile(path)
		if err != nil {
			continue
		}
		val, err := strconv.Atoi(strings.TrimSpace(string(data)))
		if err != nil {
			continue
		}
		return fmt.Sprintf("%.1fC", float64(val)/1000.0)
	}
	return ""
}

// Reboot 延迟（0-300 秒）后调用 rebooter 重启。
// delay==0 表示立即重启。校验 delay 范围，过大返回 error。
func (s *HardwareService) Reboot(delay int) error {
	if delay < 0 || delay > 300 {
		return fmt.Errorf("delay must be between 0 and 300 seconds, got %d", delay)
	}

	if delay > 0 {
		// 生产环境会真正 sleep + reboot；
		// 测试环境 rebooter 是 fake，sleep 无害。
		time.Sleep(time.Duration(delay) * time.Second)
	}

	return s.rebooter.Reboot()
}

// GetLED 返回 LED 状态。
// 无 bmlib 驱动时 LED 不可用，返回 available:false（200 降级）。
func (s *HardwareService) GetLED() LEDResponse {
	// BM1684 无 bmlib 时 LED 无法通过 sysfs/shell 控制，
	// 返回降级响应。
	return LEDResponse{
		Available: false,
		Reason:    "LED not supported without bmlib driver",
	}
}

// SetLED 设置 LED 状态（on/off/blink）。
// 参数白名单校验；无 bmlib 时返回降级错误。
func (s *HardwareService) SetLED(state string) error {
	validStates := map[string]bool{"on": true, "off": true, "blink": true}
	if !validStates[state] {
		return fmt.Errorf("invalid LED state: %s (must be on, off, or blink)", state)
	}

	// 无 bmlib 驱动时无法操作 LED
	return fmt.Errorf("LED control not available without bmlib driver")
}

// GetCard 返回 BM 卡信息（bmlib 占位）。
func (s *HardwareService) GetCard() CardResponse {
	return CardResponse{
		Available: false,
		Reason:    "bmlib not integrated",
	}
}
