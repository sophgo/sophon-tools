use crate::{
    chip::{ChipType, DeviceDetector, DeviceInfo, RunMode},
    config::Config,
    hardware::{HardwareCollector, HardwareMetrics},
    metrics::MetricsRegistry,
};
use prometheus::{Encoder, TextEncoder};
use std::{convert::Infallible, net::SocketAddr, sync::Arc, time::Duration};
use tokio::{sync::Mutex, time};
use tracing::{debug, error, info, warn};
use warp::{Filter, Reply};

/// Prometheus指标导出器
///
/// 负责收集TPU硬件指标并通过HTTP服务暴露给Prometheus
pub struct Exporter {
    /// 配置信息
    config: Config,
    /// 指标注册表，存储所有Prometheus指标
    metrics_registry: Arc<MetricsRegistry>,
    /// HTTP服务端口号
    port: u16,
    /// 硬件收集器，用于获取TPU硬件指标
    hardware_collector: Option<HardwareCollector>,
    /// 检测到的芯片类型（Google TPU, ASIC等）
    device_info: Option<DeviceInfo>,
}

impl Exporter {
    /// 创建新的Exporter实例
    ///
    /// # 参数
    /// - `config`: 应用配置
    /// - `metrics_registry`: 指标注册表
    /// - `port`: HTTP服务端口号
    ///
    /// # 返回值
    /// - `Ok(Self)`: 成功创建的Exporter实例
    /// - `Err(Box<dyn std::error::Error>)`: 创建失败的错误
    pub async fn new(
        config: Config,
        metrics_registry: MetricsRegistry,
        port: u16,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        // 验证配置的完整性和正确性
        config.validate()?;

        // 检测硬件芯片类型
        let device_info_detect = DeviceDetector::detect(0).ok();
        // 根据芯片类型创建对应的硬件收集器
        let hardware_collector = device_info_detect
            .clone()
            .map(|ct| HardwareCollector::new(ct.chip_type, ct.run_mode));

        info!(
            "Exporter initialized with chip type: {:?}",
            device_info_detect.clone().unwrap()
        );

        Ok(Exporter {
            config,
            metrics_registry: Arc::new(metrics_registry),
            port,
            hardware_collector,
            device_info: device_info_detect,
        })
    }

    /// 启动指标导出器
    ///
    /// 开启HTTP服务并启动后台指标收集任务
    ///
    /// # 返回值
    /// - `Ok(())`: 服务启动成功
    /// - `Err(Box<dyn std::error::Error>)`: 启动失败的错误
    pub async fn run(&self) -> Result<(), Box<dyn std::error::Error>> {
        // 构建Socket地址
        let addr: SocketAddr = format!("{}:{}", self.config.exporter.host, self.port).parse()?;

        info!("Starting exporter on http://{}", addr);

        // 提取需要的字段
        let metrics_path: String = self.config.exporter.metrics_path.clone();
        let health_path: String = self.config.exporter.health_path.clone();

        // 添加调试信息
        info!("Metrics path: '{}'", metrics_path);
        info!("Health path: '{}'", health_path);

        // 启动后台指标收集任务，返回异步任务句柄
        let metrics_handle = self.start_metrics_collection();

        // 创建HTTP路由端点
        // 1. /metrics 端点：提供Prometheus格式的指标数据
        let metrics_route = warp::path(metrics_path.clone())
            .and(warp::get())
            .and_then(Self::handle_metrics);

        // 2. /health 端点：提供健康检查信息
        let health_route = warp::path(health_path.clone())
            .and(warp::get())
            .and_then(Self::handle_health);

        // 3. / 根端点：提供简单的说明信息
        let root_route = warp::path::end()
            .and(warp::get())
            .map(|| "TPU Info Exporter - Use /metrics endpoint");

        // 合并所有路由，支持多个端点
        let routes = metrics_route.or(health_route).or(root_route);

        // 启动Warp HTTP服务器，开始监听请求
        warp::serve(routes).run(addr).await;

        // 等待后台指标收集任务结束（通常不会结束，除非发生错误）
        metrics_handle.await?;

        Ok(())
    }

    /// 启动后台指标收集任务
    ///
    /// 创建异步任务，定期从硬件收集指标并更新Prometheus注册表
    ///
    /// # 返回值
    /// - `tokio::task::JoinHandle<()>`: 异步任务句柄，可以等待任务完成
    fn start_metrics_collection(&self) -> tokio::task::JoinHandle<()> {
        // 克隆需要的配置和数据，以便在异步任务中使用
        let config = self.config.clone();
        let registry = Arc::clone(&self.metrics_registry);
        let hardware_collector = self.hardware_collector.clone();
        let device_info = self.device_info.clone();

        // 创建异步任务
        tokio::spawn(async move {
            // 根据配置获取指标收集间隔时间
            let interval = Duration::from_secs(config.exporter.update_interval_seconds);
            // 创建定时器，每隔指定时间触发一次
            let mut interval_timer = time::interval(interval);

            info!("Starting metrics collection with interval: {:?}", interval);

            // 如果有可用的硬件收集器，执行指标收集
            if let Some(ref mut collector) = hardware_collector.clone() {
                // 无限循环，持续收集指标
                loop {
                    // 等待下一个收集周期
                    interval_timer.tick().await;

                    match Self::collect_and_update_metrics(
                        collector,
                        &registry,
                        Some(device_info.clone().unwrap().chip_type),
                    )
                    .await
                    {
                        Ok(_) => {
                            // 成功收集指标后，更新设备数量统计
                            // PCIE: TODO
                            registry.set_device_count(1);
                        }
                        Err(e) => {
                            // 收集失败时记录错误日志
                            error!("Failed to collect metrics: {:?}", e);
                            // 出错时重置所有指标，防止展示过时或错误的数据
                            registry.reset_metrics();
                        }
                    }
                }
            } else {
                // 如果没有硬件收集器，记录警告日志并跳过
                warn!("No hardware collector available, skipping metrics collection");
            }
        })
    }

    /// 收集硬件指标并更新Prometheus注册表
    ///
    /// # 参数
    /// - `collector`: 硬件收集器实例
    /// - `registry`: Prometheus指标注册表
    /// - `chip_type`: 芯片类型信息
    ///
    /// # 返回值
    /// - `Ok(())`: 指标收集和更新成功
    /// - `Err(Box<dyn std::error::Error>)`: 收集或更新失败的错误
    async fn collect_and_update_metrics(
        collector: &mut HardwareCollector,
        registry: &MetricsRegistry,
        chip_type: Option<ChipType>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        debug!("Collecting hardware metrics...");

        // 目前只支持单个设备，使用设备ID 0
        // 未来可以扩展为支持多设备，通过循环处理不同设备ID
        let device_id = 0;

        // 调用硬件收集器获取当前硬件指标
        let metrics = collector.collect(device_id)?;

        // 将收集到的硬件指标更新到Prometheus指标注册表中
        registry.update_metrics(&metrics);

        // 记录收集成功日志，包含关键指标信息
        debug!(
            "Metrics updated - Chip: {}, Temp: {}°C, TPU Usage: {}%",
            metrics.device_info.chip_type.name(),
            metrics.chip_temperature.unwrap_or(0.0),
            metrics.tpu_usage.unwrap_or(0)
        );

        Ok(())
    }

    /// 处理/metrics端点的HTTP请求
    ///
    /// # 参数
    /// - `registry`: Prometheus指标注册表
    ///
    /// # 返回值
    /// - `Ok(impl Reply)`: HTTP响应，包含Prometheus格式的指标数据
    /// - `Err(Infallible)`: 由于Infallible类型，实际上不会返回错误
    async fn handle_metrics() -> Result<impl Reply, Infallible> {
        // 创建Prometheus文本编码器，用于将指标编码为Prometheus格式
        let encoder = TextEncoder::new();
        let mut buffer = Vec::new();

        // 从全局Prometheus注册表收集所有指标族
        let metric_families = prometheus::gather();

        match encoder.encode(&metric_families, &mut buffer) {
            Ok(_) => {
                let response = String::from_utf8_lossy(&buffer).to_string();
                let reply: warp::reply::WithHeader<String> =
                    warp::reply::with_header(response, "Content-Type", encoder.format_type());
                Ok(warp::reply::with_status(reply, warp::http::StatusCode::OK))
            }
            Err(e) => {
                error!("Failed to encode metrics: {:?}", e);
                let reply: warp::reply::WithHeader<String> = warp::reply::with_header(
                    String::from("Internal Server Error"),
                    "Content-Type",
                    "text/plain; charset=utf-8",
                );
                Ok(warp::reply::with_status(
                    reply,
                    warp::http::StatusCode::INTERNAL_SERVER_ERROR,
                ))
            }
        }
    }

    /// 处理/health端点的HTTP请求
    ///
    /// 提供简单的健康检查信息，可用于监控系统是否正常运行
    ///
    /// # 返回值
    /// - `Ok(impl Reply)`: HTTP响应，包含JSON格式的健康状态信息
    /// - `Err(Infallible)`: 由于Infallible类型，实际上不会返回错误
    async fn handle_health() -> Result<impl Reply, Infallible> {
        // 简单的健康检查，返回当前状态和时间戳
        // TODO: 未来可以添加更复杂的健康检查逻辑，如：
        // 1. 检查硬件连接状态
        // 2. 验证最近一次指标收集是否成功
        // 3. 检查系统资源使用情况
        Ok(warp::reply::json(&serde_json::json!({
            "status": "healthy",
            "timestamp": chrono::Utc::now().to_rfc3339(),
        })))
    }
}
