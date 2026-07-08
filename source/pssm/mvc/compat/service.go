package compat

import (
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"sync"
	"time"

	"ssm/config"
	"ssm/global"
	"ssm/pkg/metrics"
	"ssm/pkg/network"
	"ssm/pkg/system"
)

// ---------------------------------------------------------------
// CompatService 组合复用现有 service 能力
// ---------------------------------------------------------------

// MetricProvider 设备指标采集接口（*metrics.Collector 实现之）。
// 抽象为接口便于 compat 测试注入 fake，无需依赖 metrics 内部 fake。
type MetricProvider interface {
	OSVersion() string
	Runtime() string
	SdkVersion() string
	CPUInfo() metrics.CPU
	Memory() metrics.Memory
	Disks() []metrics.Disk
	NetCards() []metrics.NetCard
	ChipTemp() int
	BoardTemp() int
	TPUUsage() int
	TPUMem() float64
}

// CompatService 提供 bmssm 旧路径兼容所需的业务逻辑。
// 组合复用现有 pkg/network、mvc/hardware（rebooter）、mvc/software 等能力，
// 自身维护一个订阅内存 map，并通过 MetricProvider 采集设备指标。
type CompatService struct {
	subscriptions map[string]SubscribeRequest // platform name -> subscription
	metrics       MetricProvider
	mu            sync.RWMutex
}

// DefaultService 包级懒初始化单例。
var (
	defaultService     *CompatService
	defaultServiceOnce sync.Once
)

// NewCompatService 创建 CompatService（生产环境，使用默认 metrics 采集器）。
func NewCompatService() *CompatService {
	return NewCompatServiceWith(metrics.NewDefaultCollector())
}

// NewCompatServiceWith 创建 CompatService，注入指定 MetricProvider（测试用）。
func NewCompatServiceWith(mp MetricProvider) *CompatService {
	return &CompatService{
		subscriptions: make(map[string]SubscribeRequest),
		metrics:       mp,
	}
}

// DefaultCompatService 返回懒初始化的包级单例。
func DefaultCompatService() *CompatService {
	defaultServiceOnce.Do(func() {
		defaultService = NewCompatService()
	})
	return defaultService
}

// ---------------------------------------------------------------
// Login
// ---------------------------------------------------------------

// LoginResult 登录返回结果（token + role）。
type LoginResult struct {
	Token string `json:"token"`
	Role  string `json:"role"`
}

// ---------------------------------------------------------------
// CtrlBasic 装配
// ---------------------------------------------------------------

// displayDeviceType 去掉型号后缀，仅保留型号主体用于前端展示。
// "SE7 V1" → "SE7"，"se9 v02" → "SE9"。空串返空。
func displayDeviceType(s string) string {
	fields := strings.Fields(s)
	if len(fields) == 0 {
		return strings.ToUpper(strings.TrimSpace(s))
	}
	return strings.ToUpper(fields[0])
}

// buildDeviceModel 拼接 DEVICE_MODEL = "PRODUCT MODULE_TYPE"（对齐 get_info.sh）。
// moduleTypeEx 为空时回退 typeEx（i2c 分支已有完整 model 如 "SE7 V1"）。
func buildDeviceModel(typeEx, moduleTypeEx string) string {
	typeEx = strings.TrimSpace(typeEx)
	moduleTypeEx = strings.TrimSpace(moduleTypeEx)
	if typeEx == "" {
		return ""
	}
	if moduleTypeEx == "" {
		return typeEx
	}
	return typeEx + " " + moduleTypeEx
}

// BuildCtrlBasic 从全局设备信息和网卡信息装配 CtrlBasic。
// bmlib 依赖字段（agencyModule、serviceAddress、chipSn 详细）返空/零值。
// alarmThreshold 从配置读取，对齐 bmssm 的 deviceConf.json alarmthreshold。
func (s *CompatService) BuildCtrlBasic() (CtrlBasic, error) {
	cards, err := network.GetNetCards()
	if err != nil {
		return CtrlBasic{}, fmt.Errorf("get net cards: %w", err)
	}

	// 从 NetCard 转换为 IPInfo（bmssm 格式：只有 IP 字段）
	ipList := make([]IPInfo, 0, len(cards))
	for _, card := range cards {
		if card.IsLoopback {
			continue
		}
		for _, ip := range card.IPs {
			// 去掉 CIDR 后缀只保留 IP 地址
			if idx := strings.Index(ip, "/"); idx >= 0 {
				ip = ip[:idx]
			}
			ipList = append(ipList, IPInfo{IP: ip})
		}
	}

	chipSn := global.ChipSn
	if chipSn == "" {
		chipSn = global.DeviceSnEx
	}

	deviceTypeEx := global.DeviceTypeEx
	if deviceTypeEx == "" {
		deviceTypeEx = "unknown"
	}

	deviceType := global.DeviceType
	if deviceType == "" {
		deviceType = "unknown"
	}

	// deviceName 和 alarmThreshold 从配置读取
	config.Conf.RLock()
	v := config.Conf.GetViper()
	deviceName := v.GetString("server.deviceName")
	at := AlarmThreshold{
		BoardTemperature:     int(v.GetFloat64("alarmThreshold.boardTemperature")),
		CoreTemperature:      int(v.GetFloat64("alarmThreshold.coreTemperature")),
		CpuRate:              v.GetFloat64("alarmThreshold.cpuRate"),
		DiskRate:             v.GetFloat64("alarmThreshold.diskRate"),
		ExternalHardDiskRate: v.GetFloat64("alarmThreshold.externalHardDiskRate"),
		FanSpeed:             v.GetInt("alarmThreshold.fanSpeed"),
		SystemScale:          v.GetFloat64("alarmThreshold.systemScale"),
		TotalMemoryScale:     v.GetFloat64("alarmThreshold.totalMemoryScale"),
		TpuRate:              v.GetFloat64("alarmThreshold.tpuRate"),
		TpuScale:             v.GetFloat64("alarmThreshold.tpuScale"),
		VideoScale:           v.GetFloat64("alarmThreshold.videoScale"),
	}
	config.Conf.RUnlock()
	if deviceName == "" {
		deviceName = "device_1"
	}

	// System 字段：OS/Runtime/SDK 来自 metrics 采集，BmssmVersion/BuildTime 来自 ldflags 注入
	osVer := s.metrics.OSVersion()
	if osVer == "" {
		osVer = "linux" // 降级值
	}

	return CtrlBasic{
		ChipSn: chipSn,
		Configure: CtrlBasicConfigure{
			AgencyModule:   []AgencyModuleItem{}, // bmlib 依赖，返空
			AlarmThreshold: at,                   // 从配置读取，对齐 bmssm alarmthreshold
			Basic: BasicInfo{
				DeviceName: deviceName,
				DeviceType: displayDeviceType(deviceTypeEx), // 展示用型号主体（"SE7 V1"→"SE7"），完整型号在 System.DeviceTypeEx
			},
			ServiceAddress: ServiceAddressConfig{}, // bmlib 依赖，返空
		},
		IpList: ipList,
		System: CtrlBasicSystem{
			AgencyServiceRunTime: "",                       // 无 bmlib 无法获取
			OperatingSystem:      osVer,                    // /etc/os-release PRETTY_NAME
			Runtime:              s.metrics.Runtime(),      // /proc/uptime → "H:MM:SS"
			BmssmVersion:         global.Version.String(),  // ldflags 注入
			BuildTime:            global.Version.BuildTime, // ldflags 注入
			SdkVersion:           s.metrics.SdkVersion(),   // bm_version / libsophon
			DeviceType:           deviceType,               // "soc"
			DeviceTypeEx:         deviceTypeEx,             // "SE7 V1"
		},
	}, nil
}

// ---------------------------------------------------------------
// CtrlResource 装配（用 metrics 真值填充 CPU/内存/磁盘/网卡/TPU）
// ---------------------------------------------------------------

// BuildCtrlResource 构造 CtrlResource 列表（单元素，sophliteos 取 [0]）。
// CPU/Memory/Disk/NetCard/温度/TPU 来自 MetricProvider；
// bmlib 依赖字段（chipType/calculationCapacity/slot/fan/power 等）降级零值。
func (s *CompatService) BuildCtrlResource() []CtrlResource {
	m := s.metrics

	// metrics.CPU → compat.CPU（字段名一致，逐字段拷贝避免跨包转换）
	mcpu := m.CPUInfo()
	cpu := CPU{
		Frequency:       mcpu.Frequency,
		Cores:           mcpu.Cores,
		UtilizationRate: mcpu.UtilizationRate,
		Type:            mcpu.Type,
		Arch:            mcpu.Arch,
	}

	// metrics.Memory → compat.Memory
	mmem := m.Memory()
	mem := Memory{
		Total:     mmem.Total,
		Free:      mmem.Free,
		Available: mmem.Available,
	}

	// metrics.Disk → compat.Disk（compat.Disk 无 ReadOnly 字段，契约不携带）
	mdisks := m.Disks()
	disks := make([]Disk, 0, len(mdisks))
	for _, d := range mdisks {
		disks = append(disks, Disk{
			DiskName: d.DiskName,
			DiskSn:   d.DiskSn,
			Total:    d.Total,
			Free:     d.Free,
			IoRate:   d.IoRate,
			MountOn:  d.MountOn,
		})
	}

	// metrics.NetCard → compat.NetCard
	mnets := m.NetCards()
	netCards := make([]NetCard, 0, len(mnets))
	for _, n := range mnets {
		netCards = append(netCards, NetCard{
			IP:          n.IP,
			Mask:        n.Mask,
			Mac:         n.Mac,
			Dns:         []string{}, // netplan 解析降级，留空
			Gateway:     "",         // 同上
			Bandwidth:   n.Bandwidth,
			Dynamic:     0, // 同上
			NetRx:       n.NetRx,
			NetTx:       n.NetTx,
			Rate:        0,
			NetCardName: n.Name,
		})
	}

	// TPU 显存：仅 total 可从 ion debugfs 获取，free/used 降级 0
	tpuMem := Memory{Total: m.TPUMem()}

	chipSn := global.ChipSn
	if chipSn == "" {
		chipSn = global.DeviceSnEx
	}

	// 按 chip 型号查表得到算力，对齐 bmssm bmlib Chipid 表
	calcCapacity, chipType := metrics.ChipCapacity(global.ModuleType)

	// deviceType 对齐 pget_info DEVICE_MODEL：i2c 路径（bm1684x/bm1684）即 model 字段
	// （"SE7 V1"），OEM 路径即 PRODUCT。sophliteos overview store 从 resource 解构
	// deviceType 用于"基础信息/设备概览"展示，缺字段会显示 undefined，故在此补齐。
	// 展示用截取后的型号主体（"SE7 V1" → "SE7"），完整型号保留在 DeviceModel。
	deviceType := displayDeviceType(global.DeviceTypeEx)
	if deviceType == "" {
		deviceType = "unknown"
	}

	return []CtrlResource{
		{
			DeviceSn:        global.DeviceSnEx,
			DeviceType:      deviceType,
			// DEVICE_MODEL 对齐 get_info.sh "PRODUCT MODULE_TYPE"（如 "SE9 16-BP1-11"）。
			// i2c 分支 ModuleTypeEx 为空 → 保持 DeviceTypeEx（如 "SE7 V1"）不变。
			DeviceModel:     buildDeviceModel(global.DeviceTypeEx, global.ModuleTypeEx),
			CollectDateTime: time.Now().Format("2006-01-02 15:04:05"),
			Sslots:          []interface{}{},
			CentralProcessingUnit: CentralProcessingUnit{
				BmssmVersion: global.Version.String(),
				BuildTime:    global.Version.BuildTime,
				Cpu:          cpu,
				Memory:       mem,
				Disk:         disks,
				NetCard:      netCards,
			},
			CoreComputingUnit: CoreComputingUnit{Board: []CoreBoard{
				{
					BoardSn:     chipSn, // bmssm boardSn 来自 BmGetSn；pssm 用 ChipSn 兜底
					SdkVersion:  m.SdkVersion(),
					BoardType:   "", // bmlib BmGetBoardName 依赖，降级留空
					Temperature: m.BoardTemp(),
					Chip: []ChipInfo{
						{
							ChipSn:                  chipSn,
							Temperature:             m.ChipTemp(),
							UtilizationRate:         m.TPUUsage(),
							Memory:                  tpuMem,
							CalculationCapacity:     calcCapacity,
							CalculationCapacityInt8: calcCapacity,
							CalculationCapacityFp16: calcCapacity / 4,
							CalculationCapacityFp32: calcCapacity / 8,
							ChipType:                chipType,
						},
					},
				},
			}},
		},
	}
}

// ---------------------------------------------------------------
// IP 列表映射
// ---------------------------------------------------------------

// BuildIPList 从网卡信息构造 bmssm 格式的 Ip 列表。
func (s *CompatService) BuildIPList() ([]Ip, error) {
	cards, err := network.GetNetCards()
	if err != nil {
		return nil, fmt.Errorf("get net cards: %w", err)
	}

	ipList := make([]Ip, 0, len(cards))
	for _, card := range cards {
		if card.IsLoopback {
			continue
		}
		var ipAddr, netMask string
		for _, ipStr := range card.IPs {
			// 跳过 IPv6
			if strings.Contains(ipStr, ":") {
				continue
			}
			if idx := strings.Index(ipStr, "/"); idx >= 0 {
				ipAddr = ipStr[:idx]
				// 将 CIDR 前缀长度转换为网络掩码
				netMask = cidrToMask(ipStr[idx+1:])
			} else {
				ipAddr = ipStr
			}
			break // 只取第一个 IPv4
		}

		ipList = append(ipList, Ip{
			NetCardName: card.Name,
			Name:        card.Name,
			IP:          ipAddr,
			NetMask:     netMask,
			Mac:         card.MAC,
			DNS:         []string{},
			Gateway:     "",
			Bandwidth:   0,
			Dynamic:     0,
			NetRx:       0,
			NetTx:       0,
			DeltaRx:     0,
			DeltaTx:     0,
			Rate:        0,
		})
	}
	return ipList, nil
}

// cidrToMask 将 CIDR 前缀长度转换为点分十进制掩码。
func cidrToMask(cidr string) string {
	var bits int
	n, err := fmt.Sscanf(cidr, "%d", &bits)
	if n != 1 || err != nil {
		return ""
	}
	if bits < 0 || bits > 32 {
		return ""
	}
	mask := uint32(0xffffffff) << (32 - bits)
	return fmt.Sprintf("%d.%d.%d.%d", byte(mask>>24), byte(mask>>16), byte(mask>>8), byte(mask))
}

// ---------------------------------------------------------------
// 订阅管理
// ---------------------------------------------------------------

// Subscribe 记录告警订阅。
func (s *CompatService) Subscribe(req SubscribeRequest) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.subscriptions[req.Platform] = req
}

// Unsubscribe 取消告警订阅。
func (s *CompatService) Unsubscribe(platform string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.subscriptions, platform)
}

// GetSubscription 查询订阅。
func (s *CompatService) GetSubscription(platform string) (SubscribeRequest, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	req, ok := s.subscriptions[platform]
	return req, ok
}

// ListSubscriptions 列出所有订阅。
func (s *CompatService) ListSubscriptions() []SubscribeRequest {
	s.mu.RLock()
	defer s.mu.RUnlock()
	list := make([]SubscribeRequest, 0, len(s.subscriptions))
	for _, v := range s.subscriptions {
		list = append(list, v)
	}
	return list
}

// ---------------------------------------------------------------
// NAT 规则删除
// ---------------------------------------------------------------

// DeleteNATRule 按 PREROUTING 规则编号删除 iptables NAT 规则。
// num 必须为合法正整数。
func DeleteNATRule(num string) error {
	if num == "" {
		return errors.New("missing rule number")
	}
	// 校验 num 为纯数字
	for _, c := range num {
		if c < '0' || c > '9' {
			return errors.New("invalid rule number: must be numeric")
		}
	}
	if num == "0" {
		return errors.New("invalid rule number: must be positive")
	}
	// 参数化执行，防注入
	_, errStr, err := system.RunCommandArgs("iptables", "-t", "nat", "-D", "PREROUTING", num)
	if err != nil {
		if errStr != "" {
			return errors.New(errStr)
		}
		return err
	}
	return nil
}

// ---------------------------------------------------------------
// 关机 / 重启
// ---------------------------------------------------------------

// Shutdown 执行关机（/sbin/poweroff）。
func Shutdown() error {
	_, errStr, err := system.RunCommandArgs("/sbin/poweroff")
	if err != nil {
		return fmt.Errorf("shutdown failed: %v: %s", err, errStr)
	}
	return nil
}

// RunReboot 执行重启，复用硬件模块的 osRebooter。
func RunReboot() error {
	cmd := exec.Command("/sbin/reboot")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("reboot failed: %v: %s", err, string(out))
	}
	return nil
}
