use crate::Error::Hardware;
use serde::{Deserialize, Serialize};
use std::fs;
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::os::unix::fs::FileTypeExt;
use std::path::Path;
use tracing::{debug, info, warn};

#[derive(Debug, Serialize, Deserialize)]
struct BM1684DeviceInformation {
    #[serde(rename = "model")]
    model: String,
    #[serde(rename = "chip")]
    chip: String,
    #[serde(rename = "mcu")]
    mcu: String,
    #[serde(rename = "product sn")]
    product_sn: String,
    #[serde(rename = "board type")]
    board_type: String,
    #[serde(rename = "mcu version")]
    mcu_version: String,
    #[serde(rename = "pcb version")]
    pcb_version: String,
    #[serde(rename = "reset count")]
    reset_count: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ChipType {
    BM1684,
    BM1684X,
    BM1688,
    CV186AH,
    Unknown,
}

impl ChipType {
    pub fn name(&self) -> &'static str {
        match self {
            ChipType::BM1684 => "BM1684",
            ChipType::BM1684X => "BM1684X",
            ChipType::BM1688 => "BM1688",
            ChipType::CV186AH => "CV186AH",
            ChipType::Unknown => "Unknown Chip",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RunMode {
    SOC,
    PCIE,
    Unknown,
}

impl RunMode {
    pub fn name(&self) -> &'static str {
        match self {
            RunMode::SOC => "SoC Mode",
            RunMode::PCIE => "PCIE Mode",
            RunMode::Unknown => "Unknown Mode",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceInfo {
    pub device_id: u64,
    pub chip_type: ChipType,
    pub run_mode: RunMode,
    pub board_type: String,
    pub model: String,
    pub serial_number: String,
}

pub struct DeviceDetector;

impl DeviceDetector {
    /// 基于系统信息检测芯片类型
    pub fn detect(mut device_id: u64) -> Result<DeviceInfo, Box<dyn std::error::Error>> {
        let mut chip_type: ChipType = ChipType::Unknown;
        let mut run_mode: RunMode = RunMode::Unknown;
        let mut board_type: String = String::from("");
        let mut model: String = String::from("");
        let mut serial_number: String = String::from("");

        let cpuinfo_content = std::fs::read_to_string("/proc/cpuinfo")?;
        // 通过获取/proc/cpuinfo的“model name”项的值确定ChipType
        for line in cpuinfo_content.lines() {
            if line.to_lowercase().contains("model name") || line.to_lowercase().contains("model") {
                let line_lower = line.to_lowercase();
                if line_lower.contains("bm1684x") {
                    chip_type = ChipType::BM1684X;
                } else if line_lower.contains("bm1684") {
                    chip_type = ChipType::BM1684;
                } else if line_lower.contains("bm1688") {
                    chip_type = ChipType::BM1688;
                } else if line_lower.contains("cv186ah") {
                    chip_type = ChipType::CV186AH;
                } else {
                    return Err(Box::new(Hardware(String::from("not detect chip type"))));
                }
            }
        }

        // PCIE MODE: TODO
        run_mode = RunMode::SOC;
        device_id = 0;

        if run_mode == RunMode::SOC
            && (chip_type == ChipType::BM1684 || chip_type == ChipType::BM1684X)
        {
            let content = fs::read_to_string("/sys/bus/i2c/devices/1-0017/information")?;
            let info: BM1684DeviceInformation = serde_json::from_str(&content)
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.to_string()))?;
            board_type = info.board_type;
            model = info.model;
            serial_number =
                Self::od_read_char("/sys/bus/nvmem/devices/1-006a0/nvmem", 512, 32).unwrap();
            if serial_number == String::from("") {
                serial_number =
                    Self::od_read_char("/sys/bus/nvmem/devices/1-006a0/nvmem", 0, 32).unwrap();
            }
        } else if run_mode == RunMode::SOC
            && (chip_type == ChipType::BM1688 || chip_type == ChipType::CV186AH)
        {
            board_type = Self::od_read_char("/dev/mmcblk0boot1", 160, 32).unwrap();
            model = format!(
                "{} {}",
                Self::od_read_char("/dev/mmcblk0boot1", 208, 16).unwrap(),
                Self::od_read_char("/dev/mmcblk0boot1", 112, 16).unwrap()
            );
            serial_number = Self::od_read_char("/dev/mmcblk0boot1", 32, 32).unwrap();
            if serial_number == String::from("") {
                serial_number = Self::od_read_char("/dev/mmcblk0boot1", 0, 32).unwrap();
            }
        } else {
            return Err(Box::new(Hardware(String::from(
                "not support chip type for board type",
            ))));
        }

        let ret = DeviceInfo {
            device_id,
            chip_type,
            run_mode,
            board_type,
            model,
            serial_number,
        };
        return Ok(ret);
    }

    /// 从文件中读取字符串
    ///
    /// # 参数
    /// * `file_path` - 要读取的文件路径
    /// * `offset`    - 读取起始位置（字节偏移量）
    /// * `length`    - 最大读取长度
    fn od_read_char(file_path: &str, offset: u64, length: usize) -> io::Result<String> {
        // 打开文件（需要root权限）
        let mut file = File::open(file_path)?;
        let metadata = file.metadata()?;

        let is_special_file = {
            let path = Path::new(file_path);

            // 1. 检查是否是设备文件
            let is_device =
                metadata.file_type().is_block_device() || metadata.file_type().is_char_device();

            // 2. 检查是否是 sysfs 文件（包含 /sys/ 路径）
            let is_sysfs = path.starts_with("/sys/");

            // 3. 检查是否是 procfs 文件（包含 /proc/ 路径）
            let is_procfs = path.starts_with("/proc/");

            // 4. 检查是否是 devtmpfs 文件（包含 /dev/ 路径）
            let is_devtmpfs = path.starts_with("/dev/");

            is_device || is_sysfs || is_procfs || is_devtmpfs
        };

        // 检查文件大小
        if !is_special_file {
            let file_size = file.metadata()?.len();
            if offset >= file_size {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("Offset {} exceeds file size {}", offset, file_size),
                ));
            }
        }

        // 定位到偏移量
        file.seek(SeekFrom::Start(offset))?;

        // 读取数据
        let mut buffer = vec![0u8; length];
        let bytes_read = file.read(&mut buffer)?;

        if bytes_read == 0 {
            return Ok(String::new());
        }

        // 转换为字符串，处理可能的非UTF-8字符
        let result = String::from_utf8_lossy(&buffer[..bytes_read])
            .trim_end_matches('\0') // 移除末尾的空字符
            .trim() // 移除首尾空白字符
            .to_string();

        Ok(result)
    }
}
