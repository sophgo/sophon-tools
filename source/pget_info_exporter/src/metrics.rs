use crate::hardware::{HardwareMetrics, HealthStatus};
use lazy_static::lazy_static;
use num::cast::AsPrimitive;
use prometheus::{
    core::Collector, register_gauge_vec, register_int_gauge_vec, GaugeVec, IntGaugeVec,
};
use std::sync::Mutex;
use tracing::{debug, error, Level};

// 使用 lazy_static 宏创建静态的指标注册表
// 这是一个线程安全的单例模式，确保在整个应用中只有一个 MetricsRegistry 实例
lazy_static! {
    pub static ref METRICS_REGISTRY: Mutex<MetricsRegistry> = Mutex::new(MetricsRegistry::new());
}

/// 指标注册表结构体
/// 负责管理和维护所有的 Prometheus 指标
/// 包含多种硬件指标，如内存、性能、温度、风扇、功耗等
pub struct MetricsRegistry {
    // 设备数量指标
    // 使用 IntGaugeVec 表示整数类型的指标向量
    pub num_devices: IntGaugeVec,

    // 内存指标
    pub system_memory_total: IntGaugeVec,
    pub system_memory_used: IntGaugeVec,
    pub system_memory_free: IntGaugeVec,
    pub vpp_memory_total: IntGaugeVec,
    pub vpp_memory_used: IntGaugeVec,
    pub vpu_memory_total: IntGaugeVec,
    pub vpu_memory_used: IntGaugeVec,
    pub tpu_memory_total: IntGaugeVec,
    pub tpu_memory_used: IntGaugeVec,
    pub device_memory_total: IntGaugeVec,
    pub device_memory_used: IntGaugeVec,

    // 性能指标
    pub cpu_usage: IntGaugeVec,
    pub tpu_usage: IntGaugeVec,
    pub tpu_average_usage: IntGaugeVec,
    pub vpu_enc_usage: IntGaugeVec,
    pub vpu_dec_usage: IntGaugeVec,
    pub vpu_enc_links: IntGaugeVec,
    pub vpu_dec_links: IntGaugeVec,
    pub vpp_usage: IntGaugeVec,
    pub jpu_usage: IntGaugeVec,

    // 温度指标（单位：摄氏度）
    // chip_temperature: 芯片温度
    // board_temperature: 主板温度
    pub chip_temperature: GaugeVec,
    pub board_temperature: GaugeVec,

    // 风扇指标（单位：RPM - 转每分钟）
    // fan_speed: 风扇转速
    pub fan_speed: IntGaugeVec,

    // 功耗指标
    // power_usage: 当前功耗
    pub power_usage: GaugeVec,

    // 健康状态指标
    // health_status: 设备健康状态（1=健康，0=不健康）
    pub health_status: IntGaugeVec,

    // 芯片信息指标
    // chip_info: 芯片信息，使用多维标签存储设备详细信息
    pub chip_info: GaugeVec,
}

impl MetricsRegistry {
    /// 创建新的 MetricsRegistry 实例
    /// 初始化所有的 Prometheus 指标
    pub fn new() -> Self {
        // 定义所有指标共用的标签
        // 这些标签用于区分不同的设备实例
        let labels = vec!["device_id", "model", "serial", "chip_type", "board_type"];

        MetricsRegistry {
            // 注册设备数量指标
            // 这是一个全局指标，没有标签
            num_devices: register_int_gauge_vec!(
                "sophon_num_devices",    // 指标名称
                "Number of TPU devices", // 指标描述
                &[]                      // 标签列表（空表示无标签）
            )
            .unwrap(),

            // 注册系统内存总容量指标
            system_memory_total: register_int_gauge_vec!(
                "sophon_system_memory_total_bytes",
                "Total system memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册已使用系统内存指标
            system_memory_used: register_int_gauge_vec!(
                "sophon_system_memory_used_bytes",
                "Used system memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册空闲系统内存指标
            system_memory_free: register_int_gauge_vec!(
                "sophon_system_memory_free_bytes",
                "Free system memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册 VPP 内存总容量指标
            vpp_memory_total: register_int_gauge_vec!(
                "sophon_vpp_memory_total_bytes",
                "Total VPP memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册已使用 VPP 内存指标
            vpp_memory_used: register_int_gauge_vec!(
                "sophon_vpp_memory_used_bytes",
                "Used VPP memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册 VPU 内存总容量指标
            vpu_memory_total: register_int_gauge_vec!(
                "sophon_vpu_memory_total_bytes",
                "Total VPU memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册已使用 VPU 内存指标
            vpu_memory_used: register_int_gauge_vec!(
                "sophon_vpu_memory_used_bytes",
                "Used VPU memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册 TPU 内存总容量指标
            tpu_memory_total: register_int_gauge_vec!(
                "sophon_tpu_memory_total_bytes",
                "Total TPU memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册已使用 TPU 内存指标
            tpu_memory_used: register_int_gauge_vec!(
                "sophon_tpu_memory_used_bytes",
                "Used TPU memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册设备内存总容量指标
            device_memory_total: register_int_gauge_vec!(
                "sophon_device_memory_total_bytes",
                "Total device memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册已使用设备内存指标
            device_memory_used: register_int_gauge_vec!(
                "sophon_device_memory_used_bytes",
                "Used device memory in bytes",
                &labels
            )
            .unwrap(),

            // 注册当前 CPU 使用率指标
            cpu_usage: register_int_gauge_vec!(
                "sophon_cpu_usage_percent",
                "Current CPU usage percentage",
                &labels
            )
            .unwrap(),

            // 注册当前 TPU 使用率指标
            tpu_usage: register_int_gauge_vec!(
                "sophon_tpu_usage_percent",
                "Current TPU usage percentage",
                &labels
            )
            .unwrap(),

            // 注册平均 TPU 使用率指标
            tpu_average_usage: register_int_gauge_vec!(
                "sophon_tpu_average_usage_percent",
                "Average TPU usage percentage",
                &labels
            )
            .unwrap(),

            vpu_enc_usage: register_int_gauge_vec!(
                "sophon_vpu_enc_usage_percent",
                "Current VPU encoder usage percentage",
                &labels
            )
            .unwrap(),

            vpu_dec_usage: register_int_gauge_vec!(
                "sophon_vpu_dec_usage_percent",
                "Current VPU decoder usage percentage",
                &labels
            )
            .unwrap(),

            vpu_enc_links: register_int_gauge_vec!(
                "sophon_vpu_enc_links_percent",
                "Current VPU decoder links percentage",
                &labels
            )
            .unwrap(),

            vpu_dec_links: register_int_gauge_vec!(
                "sophon_vpu_dec_links_percent",
                "Current VPU decoder links percentage",
                &labels
            )
            .unwrap(),

            vpp_usage: register_int_gauge_vec!(
                "sophon_vpp_usage_percent",
                "Current VPP USAGE links percentage",
                &labels
            )
            .unwrap(),

            jpu_usage: register_int_gauge_vec!(
                "sophon_jpu_usage_percent",
                "Current JPU USAGE links percentage",
                &labels
            )
            .unwrap(),

            // 注册芯片温度指标
            chip_temperature: register_gauge_vec!(
                "sophon_chip_temperature_celsius",
                "Chip temperature in Celsius",
                &labels
            )
            .unwrap(),

            // 注册主板温度指标
            board_temperature: register_gauge_vec!(
                "sophon_board_temperature_celsius",
                "Board temperature in Celsius",
                &labels
            )
            .unwrap(),

            // 注册风扇转速指标
            fan_speed: register_int_gauge_vec!("sophon_fan_speed_rpm", "Fan speed in RPM", &labels)
                .unwrap(),

            // 注册当前功耗指标
            power_usage: register_gauge_vec!(
                "sophon_power_usage_watts",
                "Power usage in watts",
                &labels
            )
            .unwrap(),

            // 注册健康状态指标
            health_status: register_int_gauge_vec!(
                "sophon_health_status",
                "Device health status (1=healthy, 0=unhealthy)",
                &labels
            )
            .unwrap(),

            // 注册芯片信息指标
            chip_info: register_gauge_vec!("sophon_chip_info", "Chip information", &labels)
                .unwrap(),
        }
    }

    pub fn update_metric<T: AsPrimitive<f64> + AsPrimitive<i64> + Copy>(
        &self,
        gauge: &dyn std::any::Any,
        labels: &[&str],
        value: Option<T>,
    ) {
        if let Some(v) = value {
            if let Some(g) = gauge.downcast_ref::<GaugeVec>() {
                let value: f64 = v.as_();
                if tracing::enabled!(Level::DEBUG) {
                    let name = match g.desc().first() {
                        Some(v) => v.fq_name.as_str(),
                        None => "None Name",
                    };
                    debug!("update metric {:?}:{} -> {}", labels, name, value);
                }
                g.with_label_values(labels).set(value);
            } else if let Some(g) = gauge.downcast_ref::<IntGaugeVec>() {
                let value: i64 = v.as_();
                if tracing::enabled!(Level::DEBUG) {
                    let name = match g.desc().first() {
                        Some(v) => v.fq_name.as_str(),
                        None => "None Name",
                    };
                    debug!("update metric {:?}:{} -> {}", labels, name, value);
                }
                g.with_label_values(labels).set(value);
            }
        }
    }

    /// 更新硬件指标
    ///
    /// # 参数
    /// - `metrics`: 包含所有硬件指标的 HardwareMetrics 结构体
    ///
    /// # 功能
    /// 1. 将硬件监控数据转换为 Prometheus 指标
    /// 2. 为每个指标设置对应的标签值
    /// 3. 处理可选字段（如功耗指标）
    pub fn update_metrics(&self, metrics: &HardwareMetrics) {
        // 构建标签值列表，用于标识具体的设备
        let label_refs = vec![
            metrics.device_info.device_id.to_string().clone(), // 插槽/设备ID
            metrics.device_info.model.clone(),                 // 设备型号
            metrics.device_info.serial_number.clone(),         // 序列号
            String::from(metrics.device_info.chip_type.name()).clone(), // 芯片类型名称
            metrics.device_info.board_type.clone(),            // 板类型/设备树名称
        ];

        let labels: Vec<&str> = label_refs.iter().map(|s| s.as_str()).collect();

        // 更新系统内存指标
        self.update_metric(
            &self.system_memory_total,
            &labels,
            metrics.system_memory_total,
        );
        self.update_metric(
            &self.system_memory_used,
            &labels,
            metrics.system_memory_used,
        );
        self.update_metric(
            &self.system_memory_free,
            &labels,
            metrics.system_memory_free,
        );

        // 更新内存指标
        self.update_metric(&self.vpp_memory_total, &labels, metrics.vpp_memory_total);
        self.update_metric(&self.vpp_memory_used, &labels, metrics.vpp_memory_used);
        self.update_metric(&self.vpu_memory_total, &labels, metrics.vpu_memory_total);
        self.update_metric(&self.vpu_memory_used, &labels, metrics.vpu_memory_used);
        self.update_metric(&self.tpu_memory_total, &labels, metrics.tpu_memory_total);
        self.update_metric(&self.tpu_memory_used, &labels, metrics.tpu_memory_used);
        self.update_metric(
            &self.device_memory_total,
            &labels,
            metrics.device_memory_total,
        );
        self.update_metric(
            &self.device_memory_used,
            &labels,
            metrics.device_memory_used,
        );

        // 更新性能指标（直接设置百分比值）
        self.update_metric(&self.cpu_usage, &labels, metrics.cpu_usage);
        self.update_metric(&self.tpu_usage, &labels, metrics.tpu_usage);
        self.update_metric(&self.tpu_average_usage, &labels, metrics.tpu_average_usage);
        self.update_metric(&self.vpu_enc_usage, &labels, metrics.vpu_enc_usage);
        self.update_metric(&self.vpu_dec_usage, &labels, metrics.vpu_dec_usage);
        self.update_metric(&self.vpu_enc_links, &labels, metrics.vpu_enc_links);
        self.update_metric(&self.vpu_dec_links, &labels, metrics.vpu_dec_links);
        self.update_metric(&self.vpp_usage, &labels, metrics.vpp_usage);
        self.update_metric(&self.jpu_usage, &labels, metrics.jpu_usage);

        // 更新温度指标
        self.update_metric(&self.chip_temperature, &labels, metrics.chip_temperature);
        self.update_metric(&self.board_temperature, &labels, metrics.board_temperature);

        // 更新风扇转速
        self.update_metric(&self.fan_speed, &labels, metrics.fan_speed);

        // 更新功耗指标（这些字段是 Option 类型，需要检查是否有值）
        self.update_metric(&self.power_usage, &labels, metrics.power_usage);

        // 更新健康状态指标
        // 将 HealthStatus 枚举转换为 i64（1=健康，0=不健康）
        self.update_metric(
            &self.health_status,
            &labels,
            match metrics.health_status {
                HealthStatus::Healthy => Some(1),
                HealthStatus::Unhealthy => Some(0),
            },
        );

        // 设置 chip_info 指标的值为 1.0，表示这个设备存在
        // 在 Prometheus 中，这通常用于记录设备的元数据
        self.update_metric(&self.chip_info, &labels, Some(1.0));

        // 记录调试日志
        debug!(
            "Updated metrics for device {}",
            metrics.device_info.device_id
        );
    }

    /// 设置设备数量
    ///
    /// # 参数
    /// - `count`: 当前检测到的设备总数
    ///
    /// # 说明
    /// 这个指标没有标签，表示整个系统中的设备数量
    pub fn set_device_count(&self, count: u32) {
        self.num_devices.with_label_values(&[]).set(count as i64);
    }

    /// 重置所有指标
    ///
    /// # 功能
    /// 1. 清除所有指标的值
    /// 2. 用于设备断开连接或系统重置时清理状态
    /// 3. 确保不会显示过时的监控数据
    pub fn reset_metrics(&self) {
        // 重置所有指标向量
        // 这会清除所有标签组合对应的指标值
        self.system_memory_total.reset();
        self.system_memory_used.reset();
        self.system_memory_free.reset();
        self.vpp_memory_total.reset();
        self.vpp_memory_used.reset();
        self.vpu_memory_total.reset();
        self.vpu_memory_used.reset();
        self.tpu_memory_total.reset();
        self.tpu_memory_used.reset();
        self.device_memory_total.reset();
        self.device_memory_used.reset();
        self.cpu_usage.reset();
        self.tpu_usage.reset();
        self.tpu_average_usage.reset();
        self.vpu_enc_usage.reset();
        self.vpu_dec_usage.reset();
        self.vpu_enc_links.reset();
        self.vpu_dec_links.reset();
        self.vpp_usage.reset();
        self.jpu_usage.reset();
        self.chip_temperature.reset();
        self.board_temperature.reset();
        self.fan_speed.reset();
        self.power_usage.reset();
        self.health_status.reset();
        self.chip_info.reset();

        // 记录调试日志
        debug!("All metrics have been reset");
    }
}

// 定义枚举类型来支持通用更新方法
pub enum MetricType<'a> {
    Gauge(&'a GaugeVec),
    IntGauge(&'a IntGaugeVec),
}

pub enum MetricValue {
    Float(f64),
    Integer(u64),
}
