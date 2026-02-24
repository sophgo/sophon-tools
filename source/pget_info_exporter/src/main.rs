use clap::Parser;
use get_info_exporter::{config::Config, exporter::Exporter, metrics::MetricsRegistry};
use get_info_exporter::chip::{self, DeviceInfo};
use tokio::signal;
use tracing::{debug, error, info};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// 配置文件路径
    #[arg(short, long, default_value = "config.yaml")]
    config: String,

    /// 监听端口
    #[arg(short, long, default_value_t = 9090)]
    port: u16,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 初始化 tracing
    tracing_subscriber::fmt::init();

    // 解析命令行参数
    let args = Args::parse();
    info!("启动 exporter v{}", env!("CARGO_PKG_VERSION"));

    let device_info: DeviceInfo = chip::DeviceDetector::detect(0).unwrap();
    info!("Device info: {:?}", device_info);

    // 加载配置
    let config = Config::load(&args.config).await?;
    debug!("配置文件已加载: {}", args.config);

    // 初始化指标注册表
    let metrics_registry = MetricsRegistry::new();

    // 创建并启动导出器
    let exporter = Exporter::new(config, metrics_registry, args.port).await?;

    // 运行导出器
    if let Err(e) = exporter.run().await {
        error!("导出器运行失败: {:?}", e);
        return Err(e);
    }

    // 等待关机信号
    signal::ctrl_c().await?;
    info!("正在关闭...");

    Ok(())
}
