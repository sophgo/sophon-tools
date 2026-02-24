use crate::chip::{ChipType, DeviceDetector, DeviceInfo, RunMode};
use serde::{Deserialize, Serialize};
use std::fs;
use std::fs::File;
use std::io::{self, Read, Write};
use std::process::Command;
use std::str;
use tracing::{debug, error, info};
use sysinfo::{System};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareMetrics {
    // Device information
    pub device_info: DeviceInfo,

    // Memory metrics
    pub system_memory_total: Option<u64>, // B
    pub system_memory_used: Option<u64>,  // B
    pub system_memory_free: Option<u64>,  // B
    pub tpu_memory_total: Option<u64>,    // B
    pub tpu_memory_used: Option<u64>,     // B
    pub vpp_memory_total: Option<u64>,    // B
    pub vpp_memory_used: Option<u64>,     // B
    pub vpu_memory_total: Option<u64>,    // B
    pub vpu_memory_used: Option<u64>,     // B
    pub device_memory_total: Option<u64>, // B
    pub device_memory_used: Option<u64>,  // B

    // Performance metrics
    pub cpu_usage: Option<u64>,         // %
    pub tpu_usage: Option<u64>,         // %
    pub tpu_average_usage: Option<u64>, // %
    pub vpu_enc_usage: Option<u64>,     // %
    pub vpu_dec_usage: Option<u64>,     // %
    pub vpu_enc_links: Option<u64>,     //
    pub vpu_dec_links: Option<u64>,     //
    pub vpp_usage: Option<u64>,         // %
    pub jpu_usage: Option<u64>,         // %

    // Temperature metrics
    pub chip_temperature: Option<f64>,  // °C
    pub board_temperature: Option<f64>, // °C

    // Fan metrics
    pub fan_speed: Option<u64>, // RPM

    // Power metrics
    pub power_usage: Option<f64>, // W

    // Health status
    pub health_status: HealthStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HealthStatus {
    Healthy = 1,
    Unhealthy = 0,
}

#[derive(Debug)]
pub struct HardwareCollector {
    chip_type: ChipType,
    run_mode: RunMode,
    sys: System,
}

impl Clone for HardwareCollector {
    fn clone(&self) -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();
        Self {
            chip_type: self.chip_type.clone(),
            run_mode: self.run_mode.clone(),
            sys: sys,
        }
    }
}

impl HardwareCollector {
    pub fn new(chip_type: ChipType, run_mode: RunMode) -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();
        HardwareCollector {
            chip_type,
            run_mode,
            sys
        }
    }

    pub fn collect(&mut self, device_id: u32) -> Result<HardwareMetrics, Box<dyn std::error::Error>> {
        debug!(
            "Collecting hardware metrics for device {} (chip type: {:?})",
            device_id, self.chip_type
        );

        self.sys.refresh_cpu();
        self.sys.refresh_memory();

        // Get chip info
        let device_info = crate::chip::DeviceDetector::detect(0)?;

        // Collect system memory
        let (system_total, system_used, system_free) = match self.collect_system_memory() {
            Some((total, used, free)) => (Some(total), Some(used), Some(free)),
            None => (None, None, None),
        };

        // Collect VPP memory
        let (vpp_total, vpp_used) = match self.collect_vpp_memory() {
            Some((total, used)) => (Some(total), Some(used)),
            None => (None, None),
        };

        // Collect VPU memory
        let (vpu_total, vpu_used) = match self.collect_vpu_memory() {
            Some((total, used)) => (Some(total), Some(used)),
            None => (None, None),
        };

        // Collect TPU memory
        let (tpu_total, tpu_used) = match self.collect_tpu_memory() {
            Some((total, used)) => (Some(total), Some(used)),
            None => (None, None),
        };

        // Collect CPU usage
        let cpu_usage = self.collect_cpu_usage();

        // Collect TPU usage
        let (tpu_usage, tpu_avg_usage) = match self.collect_tpu_usage() {
            Some((usage, avg_usage)) => (Some(usage), Some(avg_usage)),
            None => (None, None),
        };

        // Collect VPU usage
        let (vpu_enc_usage, vpu_dec_usage, vpu_enc_links, vpu_dec_links) =
            match self.collect_vpu_usage() {
                Some((enc_usage, dec_usage, enc_links, dec_links)) => (
                    Some(enc_usage),
                    Some(dec_usage),
                    Some(enc_links),
                    Some(dec_links),
                ),
                None => (None, None, None, None),
            };

        let vpp_usage = self.collect_vpp_usage();

        let jpu_usage = self.collect_jpu_usage();

        // Collect temperatures
        let (chip_temp, board_temp) = self.collect_temperatures();

        // Collect fan speed
        let fan_speed = self.collect_fan_speed();

        // Collect power information if available
        let power_usage = self.collect_power_info();

        // Determine health status
        let health_status =
            self.determine_health_status(chip_temp.unwrap_or(0.0), board_temp.unwrap_or(0.0));

        Ok(HardwareMetrics {
            device_info: device_info,
            system_memory_total: system_total,
            system_memory_used: system_used,
            system_memory_free: system_free,
            vpp_memory_total: vpp_total,
            vpp_memory_used: vpp_used,
            vpu_memory_total: vpu_total,
            vpu_memory_used: vpu_used,
            tpu_memory_total: tpu_total,
            tpu_memory_used: tpu_used,
            device_memory_used: Some(
                vpp_used.unwrap_or(0) + vpu_used.unwrap_or(0) + tpu_used.unwrap_or(0),
            ),
            device_memory_total: Some(
                vpp_total.unwrap_or(0) + vpu_total.unwrap_or(0) + tpu_total.unwrap_or(0),
            ),
            cpu_usage: cpu_usage,
            tpu_usage: tpu_usage,
            tpu_average_usage: tpu_avg_usage,
            vpu_enc_usage: vpu_enc_usage, // %
            vpu_dec_usage: vpu_dec_usage, // %
            vpu_enc_links: vpu_enc_links, //
            vpu_dec_links: vpu_dec_links, //
            vpp_usage: vpp_usage,         // %
            jpu_usage: jpu_usage,
            chip_temperature: chip_temp,
            board_temperature: board_temp,
            fan_speed: fan_speed,
            power_usage: power_usage,
            health_status: health_status,
        })
    }

    fn collect_system_memory(&self) -> Option<(u64, u64, u64)> {
        let total = self.sys.total_memory();
        let used = self.sys.used_memory();
        let free = self.sys.free_memory();

        debug!(
            "System memory - Total: {}B, Used: {}B, Free: {}B",
            total, used, free
        );
        Some((total, used, free))
    }

    fn collect_vpp_memory(&self) -> Option<(u64, u64)> {
        // Collect VPP memory from sysfs
        let command = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X => {
                "cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary | awk '$1==\"[1]\" {printf \"%s %s\", $4,$6}'"
            }
            ChipType::BM1688 | ChipType::CV186AH => {
                "cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary | awk '$1==\"[1]\" {printf \"%s %s\", $4,$6}'"
            }
            _ => {
                // Default to 0 for unsupported chips
                return None;
            }
        };

        let vpp_mem = self.parse_memory_from_command(command);
        debug!(
            "VPP/VPSS memory - Total: {}B, Used: {}B",
            vpp_mem.unwrap_or((0, 0)).0,
            vpp_mem.unwrap_or((0, 0)).1
        );
        vpp_mem
    }

    fn collect_vpu_memory(&self) -> Option<(u64, u64)> {
        // Collect VPP memory from sysfs
        let command = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X => {
                "cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary | awk '$1==\"[1]\" {printf \"%s %s\", $4,$6}'"
            }
            ChipType::BM1688 | ChipType::CV186AH => {
                return None;
            }
            _ => {
                // Default to 0 for unsupported chips
                return None;
            }
        };

        let vpu_mem = self.parse_memory_from_command(command);
        debug!(
            "VPU memory - Total: {}B, Used: {}B",
            vpu_mem.unwrap_or((0, 0)).0,
            vpu_mem.unwrap_or((0, 0)).1
        );
        vpu_mem
    }

    fn collect_tpu_memory(&self) -> Option<(u64, u64)> {
        // Collect NPU memory from sysfs
        let command = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X => {
                "cat /sys/kernel/debug/ion/bm_npu_heap_dump/summary | awk '$1==\"[0]\" {printf \"%s %s\", $4,$6}'"
            }
            ChipType::BM1688 | ChipType::CV186AH => {
                "cat /sys/kernel/debug/ion/cvi_npu_heap_dump/summary | awk '$1==\"[0]\" {printf \"%s %s\", $4,$6}'"
            }
            _ => {
                // Default to 0 for unsupported chips
                return None;
            }
        };

        let tpu_mem = self.parse_memory_from_command(command);
        debug!(
            "TPU memory - Total: {}B, Used: {}B",
            tpu_mem.unwrap_or((0, 0)).0,
            tpu_mem.unwrap_or((0, 0)).1
        );
        tpu_mem
    }

    fn parse_memory_from_command(&self, command: &str) -> Option<(u64, u64)> {
        match std::process::Command::new("bash")
            .arg("-c")
            .arg(command)
            .output()
        {
            Ok(output) if output.status.success() => {
                let output_str = String::from_utf8_lossy(&output.stdout);
                let parts: Vec<&str> = output_str.split_whitespace().collect();

                if parts.len() >= 2 {
                    let total_str = parts[0];
                    let used_str = parts[1];

                    // Parse memory values
                    let parse_memory = |s: &str| -> Option<u64> {
                        if let Some(value_str) = s.split(':').nth(1) {
                            match value_str.parse::<u64>() {
                                Ok(value) => Some(value),
                                Err(_) => None,
                            }
                        } else {
                            None
                        }
                    };

                    let total = parse_memory(total_str);
                    let used = parse_memory(used_str);
                    match (total, used) {
                        (Some(v1), Some(v2)) => Some((v1, v2)),
                        _ => None,
                    }
                } else {
                    None
                }
            }
            Err(e) => {
                debug!("Failed to execute command: {} - {}", command, e);
                None
            }
            _ => None,
        }
    }

    fn collect_cpu_usage(&self) -> Option<u64> {
        Some(self.sys.global_cpu_info().cpu_usage() as u64)
    }

    fn collect_tpu_usage(&self) -> Option<(u64, u64)> {
        // Collect TPU usage from sysfs
        let path = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X => "/sys/class/bm-tpu/bm-tpu0/device/npu_usage",
            ChipType::BM1688 | ChipType::CV186AH => "/sys/class/bm-tpu/bm-tpu0/device/npu_usage",
            _ => return None,
        };

        match self.read_from_file(path) {
            Ok(content) => {
                let mut usages: Vec<u64> = Vec::new();
                let mut usages_avg: Vec<u64> = Vec::new();
                for line in content.lines() {
                    match line.find("usage:") {
                        Some(usage_start) => {
                            let usage_part = &line[usage_start + "usage:".len()..];
                            let usage_end = usage_part
                                .find(|c: char| c.is_whitespace())
                                .unwrap_or(usage_part.len());
                            let usage_str = &usage_part[..usage_end];

                            match usage_str.parse::<u64>() {
                                Ok(usage) => usages.push(usage),
                                Err(e) => {
                                    debug!("tpu_usage {} cannot parse to u64, e: {}", usage_str, e);
                                    usages.push(0);
                                }
                            }
                        }
                        None => {
                            usages.push(0);
                        }
                    };
                    match line.find("avusage:") {
                        Some(usage_start) => {
                            let usage_part = &line[usage_start + "avusage:".len()..];
                            let usage_end = usage_part
                                .find(|c: char| c.is_whitespace())
                                .unwrap_or(usage_part.len());
                            let usage_str = &usage_part[..usage_end];

                            match usage_str.parse::<u64>() {
                                Ok(usage) => usages_avg.push(usage),
                                Err(e) => {
                                    debug!(
                                        "tpu_usage_avg {} cannot parse to u64, e: {}",
                                        usage_str, e
                                    );
                                    usages_avg.push(0);
                                }
                            }
                        }
                        None => {
                            usages_avg.push(0);
                        }
                    };
                }
                let ret = Some((
                    (usages.clone().into_iter().sum::<u64>() as f64 / usages.len() as f64) as u64,
                    (usages_avg.clone().into_iter().sum::<u64>() as f64 / usages_avg.len() as f64)
                        as u64,
                ));
                debug!("get tpu usage {:?}", ret);
                ret
            }
            Err(e) => {
                error!("read file {} error, {}", path, e);
                None
            }
        }
    }

    fn collect_vpu_usage(&self) -> Option<(u64, u64, u64, u64)> {
        let ret: Option<(u64, u64, u64, u64)> = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X | ChipType::BM1688 | ChipType::CV186AH => {
                let path = match self.chip_type {
                    ChipType::BM1684 | ChipType::BM1684X => "/proc/vpuinfo",
                    ChipType::BM1688 | ChipType::CV186AH => "/proc/soph/vpuinfo",
                    _ => "",
                };
                match self.read_from_file(path) {
                    Ok(vpu_str) => {
                        let content_without_newlines: String =
                            vpu_str.chars().filter(|c| *c != '\n').collect();
                        let re_ues = regex::Regex::new(r":(\d+)%").unwrap();
                        let re_links = regex::Regex::new(r#""link_num":(\d+),"#).unwrap();
                        let mut percentages: Vec<u64> = Vec::new();
                        let mut linksages: Vec<u64> = Vec::new();
                        for cap in re_ues.captures_iter(&content_without_newlines) {
                            if let Some(matched) = cap.get(1) {
                                if let Ok(num) = matched.as_str().parse::<u64>() {
                                    percentages.push(num);
                                }
                            }
                        }
                        for cap in re_links.captures_iter(&content_without_newlines) {
                            if let Some(matched) = cap.get(1) {
                                if let Ok(num) = matched.as_str().parse::<u64>() {
                                    linksages.push(num);
                                }
                            }
                        }
                        match self.chip_type {
                            ChipType::BM1684 => {
                                if linksages.len() == percentages.len() && percentages.len() == 5
                                {
                                    Some((
                                        percentages[4],
                                        percentages[0..4].iter().sum::<u64>() / 4,
                                        linksages[4],
                                        linksages[0..4].iter().sum(),
                                    ))
                                } else {
                                    None
                                }
                            }
                            ChipType::BM1684X => {
                                if linksages.len() == percentages.len() && percentages.len() == 3
                                {
                                    Some((
                                        percentages[2],
                                        percentages[0..2].iter().sum::<u64>() / 2,
                                        linksages[2],
                                        linksages[0..2].iter().sum(),
                                    ))
                                } else {
                                    None
                                }
                            }
                            ChipType::BM1688 | ChipType::CV186AH => {
                                if linksages.len() == percentages.len() && percentages.len() == 3
                                {
                                    Some((
                                        percentages[0],
                                        percentages[1..3].iter().sum::<u64>() / 2,
                                        linksages[0],
                                        linksages[1..3].iter().sum(),
                                    ))
                                } else {
                                    None
                                }
                            }
                            _ => None,
                        }
                    }
                    Err(e) => {
                        error!("read file {} error, {}", path, e);
                        None
                    }
                }
            }
            _ => None,
        };
        debug!("get vpu info: {:?}", ret);
        return ret;
    }

    fn collect_vpp_usage(&self) -> Option<u64> {
        let ret: Option<u64> = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X | ChipType::BM1688 | ChipType::CV186AH => {
                let path = match self.chip_type {
                    ChipType::BM1684 | ChipType::BM1684X => "/proc/vppinfo",
                    ChipType::BM1688 | ChipType::CV186AH => "/proc/soph/vppinfo",
                    _ => "",
                };
                match self.read_from_file(path) {
                    Ok(vpu_str) => {
                        let content_without_newlines: String =
                            vpu_str.chars().filter(|c| *c != '\n').collect();
                        let re_ues = regex::Regex::new(r"(\d+)%\|").unwrap();
                        let mut percentages: Vec<u64> = Vec::new();
                        for cap in re_ues.captures_iter(&content_without_newlines) {
                            if let Some(matched) = cap.get(1) {
                                if let Ok(num) = matched.as_str().parse::<u64>() {
                                    percentages.push(num);
                                }
                            }
                        }
                        Some(percentages.iter().sum::<u64>() / (percentages.len() as u64))
                    }
                    Err(e) => {
                        error!("read file {} error, {}", path, e);
                        None
                    }
                }
            }
            _ => None,
        };
        debug!("get vpp info: {:?}", ret);
        return ret;
    }

    fn collect_jpu_usage(&self) -> Option<u64> {
        let ret: Option<u64> = match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X | ChipType::BM1688 | ChipType::CV186AH => {
                let path = match self.chip_type {
                    ChipType::BM1684 | ChipType::BM1684X => "/proc/jpuinfo",
                    ChipType::BM1688 | ChipType::CV186AH => "/proc/soph/jpuinfo",
                    _ => "",
                };
                match self.read_from_file(path) {
                    Ok(vpu_str) => {
                        let content_without_newlines: String =
                            vpu_str.chars().filter(|c| *c != '\n').collect();
                        let re_ues = regex::Regex::new(r"(\d+)%\|").unwrap();
                        let mut percentages: Vec<u64> = Vec::new();
                        for cap in re_ues.captures_iter(&content_without_newlines) {
                            if let Some(matched) = cap.get(1) {
                                if let Ok(num) = matched.as_str().parse::<u64>() {
                                    percentages.push(num);
                                }
                            }
                        }
                        Some(percentages.iter().sum::<u64>() / (percentages.len() as u64))
                    }
                    Err(e) => {
                        error!("read file {} error, {}", path, e);
                        None
                    }
                }
            }
            _ => None,
        };
        debug!("get jpu info: {:?}", ret);
        return ret;
    }

    fn collect_temperatures(&self) -> (Option<f64>, Option<f64>) {
        match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X | ChipType::BM1688 | ChipType::CV186AH => (
                self.read_temperature("/sys/class/thermal/thermal_zone0/temp"),
                self.read_temperature("/sys/class/thermal/thermal_zone1/temp"),
            ),
            _ => (None, None),
        }
    }

    fn read_temperature(&self, path: &str) -> Option<f64> {
        if let Ok(content) = std::fs::read_to_string(path) {
            Some(content.trim().parse::<f64>().unwrap_or(0.0) / 1000.0)
        } else {
            None
        }
    }

    fn collect_fan_speed(&self) -> Option<u64> {
        let mut fan_rpm: u64 = 0;
        match self.chip_type {
            ChipType::BM1684 | ChipType::BM1684X => {
                match self.write_to_file("/sys/class/bm-tach/bm-tach-0/enable", "1") {
                    Ok(_) => match fs::read_to_string("/sys/class/bm-tach/bm-tach-0/fan_speed") {
                        Ok(fan_speed_content) => {
                            let frequency_str = fan_speed_content.trim().replace("fan_speed:", "");
                            if let Ok(freq) = frequency_str.parse::<f64>() {
                                if freq != 0.0 {
                                    // 计算RPM: 60 / (1 / frequency * 2)
                                    fan_rpm = (60.0 / (1.0 / freq * 2.0)).round() as u64;
                                } else {
                                    return None;
                                }
                            }
                        }
                        Err(e) => {
                            error!("Failed to write to file: {}", e);
                            return None;
                        }
                    },
                    Err(e) => {
                        error!("Failed to write to file: {}", e);
                        return None;
                    }
                }
            }
            ChipType::BM1688 | ChipType::CV186AH => {
                return None;
            }
            _ => {
                return None;
            }
        }
        debug!("fan_rpm: {}", fan_rpm);
        Some(fan_rpm)
    }

    fn collect_power_info(&self) -> Option<f64> {
        match self.run_mode {
            RunMode::SOC => {
                match self.chip_type {
                    ChipType::BM1684 | ChipType::BM1684X => {
                        let i2cget_check = Command::new("which")
                            .arg("i2cget")
                            .output()
                            .ok()
                            .filter(|output| output.status.success());
                        if i2cget_check.is_none() {
                            return None;
                        }
                        // 读取高位寄存器 (0x25)
                        let pw_h_output = Command::new("i2cget")
                            .args(&["-f", "-y", "1", "0x17", "0x25"])
                            .output()
                            .ok()
                            .filter(|output| output.status.success())?;

                        // 读取低位寄存器 (0x24)
                        let pw_l_output = Command::new("i2cget")
                            .args(&["-f", "-y", "1", "0x17", "0x24"])
                            .output()
                            .ok()
                            .filter(|output| output.status.success())?;

                        // 解析高位值
                        let pw_h_str = str::from_utf8(&pw_h_output.stdout).ok()?.trim();
                        let pw_h =
                            u16::from_str_radix(pw_h_str.trim_start_matches("0x"), 16).ok()?;

                        // 解析低位值
                        let pw_l_str = str::from_utf8(&pw_l_output.stdout).ok()?.trim();
                        let pw_l =
                            u16::from_str_radix(pw_l_str.trim_start_matches("0x"), 16).ok()?;

                        // 计算功率值：高位值 * 256 + 低位值
                        let power_value = ((pw_h as u32) * 256 + (pw_l as u32)) as f64 / 1000.0;
                        debug!("get power 12V: {}W", power_value);

                        Some(power_value)
                    }
                    ChipType::BM1688 | ChipType::CV186AH => None,
                    _ => {
                        // Default to 0 for unsupported chips
                        None
                    }
                }
            }
            _ => None,
        }
    }

    fn determine_health_status(&self, chip_temp: f64, board_temp: f64) -> HealthStatus {
        // Basic health check
        let mut is_healthy = true;

        // Temperature checks
        if chip_temp > 85.0 || board_temp > 85.0 {
            error!(
                "Temperature too high - Chip: {}°C, Board: {}°C",
                chip_temp, board_temp
            );
            is_healthy = false;
        }

        if is_healthy {
            HealthStatus::Healthy
        } else {
            HealthStatus::Unhealthy
        }
    }

    fn write_to_file(&self, path: &str, value: &str) -> io::Result<()> {
        let mut file = fs::File::create(path)?;
        file.write_all(value.as_bytes())?;
        Ok(())
    }

    fn read_from_file(&self, path: &str) -> io::Result<String> {
        let mut file = File::open(path)?;
        let mut buffer = Vec::with_capacity(8192);
        file.read_to_end(&mut buffer)?;
        String::from_utf8(buffer).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }
}
