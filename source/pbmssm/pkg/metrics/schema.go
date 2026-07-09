// schema.go — 存档字段定义、版本常量、记录 struct。
package metrics

import "encoding/binary"

// CurrentVersion 每次 schema 变更 (新增/删除指标) +1，文件头记录此版本号。
// v2: 删除频率/每核/网卡/磁盘/内存绝对值/分路功耗电压/健康/核数等；
//     新增 TPU/VPU/VPP 内存使用率。
// v3: 删除 TPU 平均使用率、12V 功耗、eMMC 寿命/预寿命。
const CurrentVersion uint16 = 3

// 变长指标上限 (保留常量供旧版本兼容引用；v2 不再写入变长字段)。
const (
	MaxCPUCores  = 8
	MaxNICs      = 4
	MaxBlockDevs = 4
)

// ArchRecord 二进制 record layout（定长，所有字段 float32 LE，0 值表示不可用/不适用）。
// 注意：timestamp 单独以 uint32 LE 写入 record 前 4 字节，不在此 struct。
type ArchRecord struct {
	// 使用率 (0-100)
	CPUUsage    float32
	TPUUsage    float32
	VPUEncUsage float32
	VPUDecUsage float32
	VPUEncLinks float32
	VPUDecLinks float32
	VPPUsage    float32
	JPUUsage    float32
	// 内存使用率 (0-100)
	SystemMemUsagePct float32
	VppMemoryUsagePct float32
	VpuMemoryUsagePct float32
	TpuMemoryUsagePct float32
	// 温度 (℃)
	ChipTemp  float32
	BoardTemp float32
	// 风扇 (RPM)
	FanSpeedRPM float32
	// 功耗
	PowerUsage float32 // W，总功耗
	// 系统
	BootTime float32 // uptime 秒
}

// ArchFields 返回当前版本的字段名列表（按 struct 字段顺序，先 timestamp 后各 float32）。
// 用于文件头 field_names 写入 + API /fields 响应。
func ArchFields() []string {
	return []string{
		"timestamp",
		"cpu_usage_pct", "tpu_usage_pct",
		"vpu_enc_usage_pct", "vpu_dec_usage_pct", "vpu_enc_links", "vpu_dec_links",
		"vpp_usage_pct", "jpu_usage_pct",
		"system_mem_usage_pct",
		"vpp_memory_usage_pct", "vpu_memory_usage_pct", "tpu_memory_usage_pct",
		"chip_temp_c", "board_temp_c",
		"fan_speed_rpm",
		"power_usage_w",
		"boot_time_s",
	}
}

// ArchRecordSize 返回当前版本 record_size (timestamp 4B + ArchRecord binary 大小)。
func ArchRecordSize() int {
	return 4 + binary.Size(ArchRecord{})
}

// headerMagic 存档文件 magic 字节。
const headerMagic = "MTRC"

// headerSize 文件头固定大小 (4096 bytes)。
const headerSize = 4096

// HeaderSize 文件头固定大小 (4096 bytes)，公开导出供 controller 等用。
const HeaderSize = headerSize

// ArchFileHeader 文件头固定前缀 (偏移 0-17，共 18 字节)。
// field_names 从偏移 18 开始，最大 headerSize - 18 字节。
type ArchFileHeader struct {
	Magic          [4]byte // "MTRC"
	Version        uint16  // LE
	RecordSize     uint16  // LE
	FieldCount     uint16  // LE
	FieldNamesLen  uint16  // LE
	FirstTimestamp uint32  // LE
	Reserved       uint16  // LE，预留
}
