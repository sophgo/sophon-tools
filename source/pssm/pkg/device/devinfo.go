// Package device 识别 Sophon 设备类型/角色/SN。
// SOC 设备读 /factory/OEMconfig.ini；PCIE 读 /sys/bus/i2c 设备信息。
package device

import (
	"encoding/json"
	"os"
	"strings"

	"ssm/pkg/system"
)

const (
	Mmcblk0Boot1Path = "/dev/mmcblk0boot1"
	NvmemSnPath      = "/sys/bus/nvmem/devices/1-006a0/nvmem"
	CpuInfoPath      = "/proc/cpuinfo"
)

const (
	PCIE_DEV    = "pcie"
	SOC_DEV     = "soc"
	UNKNOWN_DEV = "unknown"

	SE5      = "SE"
	SE6_CTRL = "SE-CTRL"
	SE6_CORE = "SE-CORE" // 预留：SE6 核心板角色，后续硬件子项目启用。

	OEMConfigPath = "/factory/OEMconfig.ini"
	DevInfoPath   = "/sys/bus/i2c/devices/1-0017/information"
	BoardIPPath   = "/sys/bus/i2c/devices/1-0017/board-ip" // 预留：i2c board-ip 文件，后续硬件子项目启用。
	CTRLShell     = "/root/se6_ctrl/se6ctr.sh"
	CTRLShell2    = "/root/se_ctrl/sectr.sh"
)

// 进程级状态（与 global 同步：GetDeviceInfo 会回写 global，见 initialization）。
var (
	DeviceType   string
	DeviceRole   string
	DeviceTypeEx string
	DeviceSnEx   string
	ChipSn       string
	ModuleType   string
	ModuleTypeEx string // MODULE_TYPE 键（如 "16-BP1-11"），用于拼接 DEVICE_MODEL；与 ModuleType(CHIP) 区分
)

// ParseOEMConfig 纯函数：解析 OEMconfig.ini 文本，返回
// (typeEx, chipSn, deviceSn, moduleType, moduleTypeEx)。
// 兼容两种格式：
//
//	旧式（两条 SN 行）：
//	  PRODUCT = SE8
//	  SN = <chipSn>
//	  SN = <deviceSn>
//	  CHIP = <moduleType>
//	新式（SN + DEVICE_SN 独立键，如 SE9）：
//	  PRODUCT = SE9
//	  SN = <chipSn>
//	  DEVICE_SN = <deviceSn>
//	  MODULE_TYPE = 16-BP1-11
//	  CHIP = BM1688
//
// moduleType = CHIP 键（BM1688，供 metrics.ChipCapacity 查算力）；
// moduleTypeEx = MODULE_TYPE 键（16-BP1-11，供拼接 DEVICE_MODEL，对齐 get_info
// "PRODUCT MODULE_TYPE" 格式）。DeviceSn 优先 DEVICE_SN 键，无则回退第二条 SN。
func ParseOEMConfig(content string) (typeEx, chipSn, deviceSn, moduleType, moduleTypeEx string) {
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
		case "DEVICE_SN":
			if deviceSn == "" {
				deviceSn = val
			}
		case "CHIP":
			if moduleType == "" {
				moduleType = val
			}
		case "MODULE_TYPE":
			if moduleTypeEx == "" {
				moduleTypeEx = val
			}
		}
	}
	// ChipSn：第一条 SN（bmssm 兼容：两条 SN 时第一条为 ChipSn）
	if len(snLines) > 0 && chipSn == "" {
		chipSn = snLines[0]
	}
	// DeviceSn：优先 DEVICE_SN 独立键（SE9 格式）；无则回退第二条 SN（旧式）
	if deviceSn == "" && len(snLines) > 1 {
		deviceSn = snLines[1]
	}
	return
}

// LoadFromOEM 从 OEMconfig.ini 文件加载并填充包级状态（SOC 路径）。
// 对齐 get_info.sh：bm1688/cv186ah 的 SN 优先从 /dev/mmcblk0boot1 读（offset 0=CHIP_SN，
// offset 32=DEVICE_SN），bm1684x/bm1684 优先从 nvmem 读（offset 0/512）；读不到再回退 OEMconfig。
func LoadFromOEM(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	DeviceType = SOC_DEV
	DeviceRole = SE5
	DeviceTypeEx, ChipSn, DeviceSnEx, ModuleType, ModuleTypeEx = ParseOEMConfig(string(data))
	// SN 优先走 get_info 的原始设备路径（mmcblk0boot1 / nvmem），OEMconfig 作回退
	readSnFromRaw()
}

// readSnFromRaw 按 CPU 型号从原始设备路径读 SN，覆盖 OEMconfig 解析值（仅成功覆盖）。
// 与 get_info.sh 的 SN 分支一致：
//
//	bm1688/cv186ah → /dev/mmcblk0boot1 offset 0/32
//	bm1684x/bm1684 → nvmem offset 0/512
func readSnFromRaw() {
	cm := ReadCpuModel(CpuInfoPath)
	switch {
	case cm == "bm1688" || cm == "cv186ah":
		if chip, dev := readSnFromMmcblkBoot1(Mmcblk0Boot1Path); chip != "" || dev != "" {
			if chip != "" {
				ChipSn = chip
			}
			if dev != "" {
				DeviceSnEx = dev
			}
		}
	case cm == "bm1684x" || cm == "bm1684":
		if chip, dev := readSnFromNvmem(NvmemSnPath); chip != "" || dev != "" {
			if chip != "" {
				ChipSn = chip
			}
			if dev != "" {
				DeviceSnEx = dev
			}
		}
	}
}

// ReadCpuModel 从 /proc/cpuinfo 读 "model name" 字段（小写），对齐 get_info.sh CPU_MODEL。
func ReadCpuModel(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "model name") {
			eq := strings.Index(line, ":")
			if eq < 0 {
				continue
			}
			return strings.ToLower(strings.TrimSpace(line[eq+1:]))
		}
	}
	return ""
}

// readSnFromMmcblkBoot1 从 /dev/mmcblk0boot1 读 CHIP_SN(offset 0) 和 DEVICE_SN(offset 32)，
// 各 32 字节，去掉 \0 与首尾空白。对齐 get_info.sh od_read_char 0/32 32。
func readSnFromMmcblkBoot1(path string) (chipSn, deviceSn string) {
	return readSnAtOffsets(path, 0, 32)
}

// readSnFromNvmem 从 nvmem 读 CHIP_SN(offset 0) 和 DEVICE_SN(offset 512)，各 32 字节。
// 对齐 get_info.sh od_read_char 0/512 32。
func readSnFromNvmem(path string) (chipSn, deviceSn string) {
	return readSnAtOffsets(path, 0, 512)
}

// readSnAtOffsets 打开 path，分别从 chipOff/devOff 各读 32 字节，去 \0 与空白。
func readSnAtOffsets(path string, chipOff, devOff int64) (chipSn, deviceSn string) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	chipSn = readFixedString(f, chipOff, 32)
	deviceSn = readFixedString(f, devOff, 32)
	return
}

// readFixedString 在 f 的 offset 处读 n 字节，去掉 \0 与首尾空白。
// ReadAt 在读到部分字节后也可能返回 io.EOF/ErrUnexpectedEOF，只要 read>0 即视为成功，
// 避免短文件（如 nvmem DEVICE_SN 偏移接近 EOF）丢弃已读到的有效字节。
func readFixedString(f *os.File, offset int64, n int) string {
	buf := make([]byte, n)
	read, _ := f.ReadAt(buf, offset)
	if read == 0 {
		return ""
	}
	s := strings.TrimRight(string(buf[:read]), "\x00")
	return strings.TrimSpace(s)
}

// GetDeviceInfo 探测设备信息并填充包级状态。失败降级为 UNKNOWN_DEV，不返回错误阻断启动。
func GetDeviceInfo() {
	getDeviceInfo(DevInfoPath, OEMConfigPath, BoardIPPath)
}

// getDeviceInfo 接受路径参数，供测试注入临时路径。
func getDeviceInfo(i2cPath, oemPath, boardIPPath string) {
	// 清旧值，避免二次调用（重检测/测试）时上一分支残留污染本次结果
	DeviceType = UNKNOWN_DEV
	DeviceRole = ""
	DeviceTypeEx = ""
	DeviceSnEx = ""
	ChipSn = ""
	ModuleType = ""
	ModuleTypeEx = ""

	// 1) I2C device information 优先（与 bmssm 顺序一致）
	if ok, _ := system.PathExists(i2cPath); ok {
		DeviceType = SOC_DEV
		loadFromI2C(i2cPath, boardIPPath)
		// i2c 分支确定角色后，SE5/SE6_CTRL 补充 DEVICE_SN（SE6_CORE 不读 DEVICE_SN，保持 DeviceSnEx=ChipSn）
		if DeviceRole == SE5 || DeviceRole == SE6_CTRL {
			if sn := readDeviceSnFromOEM(oemPath); sn != "" {
				DeviceSnEx = sn
			}
		}
		return
	}

	// 2) SOC fallback：OEMconfig.ini
	if ok, _ := system.PathExists(oemPath); ok {
		LoadFromOEM(oemPath)
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

// loadFromI2C 读取 i2c information（JSON），按 model 推断角色，并提取 chip/product sn。
// boardIPPath 用于默认分支检测 SE6 核心板（与 bmssm 对齐）。
func loadFromI2C(i2cPath, boardIPPath string) {
	data, err := os.ReadFile(i2cPath)
	if err != nil {
		return
	}
	var info map[string]string
	if err := parseJSONLoose(data, &info); err != nil {
		return
	}
	// 先提取 product sn 和 chip（bmssm 顺序：先取 ChipSn，后续 board-ip 分支可能需要用它赋值 DeviceSnEx）
	if sn, ok := info["product sn"]; ok && sn != "" {
		ChipSn = sn
	}
	if chip, ok := info["chip"]; ok && chip != "" {
		ModuleType = chip
	}
	if model, ok := info["model"]; ok && model != "" {
		DeviceTypeEx = model
		switch {
		case model == "SE6-CTRL" || model == "SE6 CTRL" || model == "SE8-CTRL" || model == "SE8 CTRL":
			DeviceRole = SE6_CTRL
		case strings.Contains(model, "SE7"):
			DeviceRole = SE5
		default:
			// 默认分支：看 board-ip 文件（与 bmssm 完全对齐）
			isExist, err := system.PathExists(boardIPPath)
			if err != nil || !isExist {
				DeviceRole = SE5
			} else {
				ipData, err := os.ReadFile(boardIPPath)
				if err != nil {
					DeviceRole = SE5
				} else if string(ipData) != "" {
					DeviceRole = SE6_CORE
					if ChipSn != "" {
						DeviceSnEx = ChipSn
					}
				} else {
					DeviceRole = SE5
				}
			}
		}
	}
}

// readDeviceSnFromOEM 从 OEMconfig.ini 读取 DEVICE_SN 字段。
// 仅读单字段，不复用 ParseOEMConfig（后者取 SN 行语义不同）。
func readDeviceSnFromOEM(oemPath string) string {
	data, err := os.ReadFile(oemPath)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		eq := strings.Index(line, "=")
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		if key == "DEVICE_SN" {
			return strings.TrimSpace(line[eq+1:])
		}
	}
	return ""
}

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
