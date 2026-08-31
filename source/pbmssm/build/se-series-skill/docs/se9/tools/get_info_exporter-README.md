# get-info-exporter

一个用于SE5/SE7/SE9的exporter实现

## 支持的硬件

- SE5
- SE7
- SE9

## 项目介绍

### 文件结构

``` bash
get-info-exporter/
├── Cargo.toml              # 项目配置和依赖
├── README.md               # 项目说明文档
├── src/
│   ├── main.rs             # 程序入口点
│   ├── lib.rs              # 库模块声明和错误定义
│   ├── config.rs           # 配置管理
│   ├── chip.rs             # 芯片类型检测
│   ├── hardware.rs         # 硬件指标收集
│   ├── metrics.rs          # Prometheus 指标定义和管理
│   └── exporter.rs         # 指标导出服务
└── target/                 # 编译输出目录
```

### 编译方式

1. 安装rust编译环境和其aarch64交叉编译工具链
2. 执行 `cargo build --target aarch64-unknown-linux-musl --release` 或 `cargo build --target aarch64-unknown-linux-gnu --release` 完成编译

> rust编译环境的安装、配置等请参考rust官方文档

## 使用方式

### 命令行选项

```bash
# 使用默认配置
get-info-exporter

# 指定自定义配置文件
get-info-exporter --config /path/to/config.yaml

# 显示帮助
get-info-exporter --help
```

### 访问指标

```bash
# 默认端点
curl http://localhost:9100/metrics

# 健康检查
curl http://localhost:9100/health

# 根端点
curl http://localhost:9100/
```

### Prometheus 配置

添加到 `prometheus.yml`：

```yaml
scrape_configs:
  - job_name: 'get-info-exporter'
    static_configs:
      - targets: ['<device-ip>:9100']
    scrape_interval: 15s
    metrics_path: /metrics
```

## 指标

### 导出的关键指标

- `sophon_num_devices`：检测到的TPU设备数量
- `sophon_system_memory_*`：系统内存使用情况(总计、已用、空闲)
- `sophon_vpp_memory_*`：VPP内存使用情况
- `sophon_vpu_memory_*`：VPU内存使用情况
- `sophon_tpu_memory_*`：TPU内存使用情况
- `sophon_device_memory_*`：设备内存使用情况(TPU+VPU+VPP)
- `sophon_cpu_usage_percent`：当前CPU使用率
- `sophon_tpu_usage_percent`：当前TPU利用率
- `sophon_tpu_average_usage_percent`：平均TPU利用率
- `sophon_vpu_enc_usage_percent`：当前VPU编码器使用率
- `sophon_vpu_dec_usage_percent`：当前VPU解码器使用率
- `sophon_vpu_enc_links_percent`：当前VPU编码器链接数
- `sophon_vpu_dec_links_percent`：当前VPU解码器链接数
- `sophon_vpp_usage_percent`：当前VPP使用率
- `sophon_jpu_usage_percent`：当前JPU使用率
- `sophon_chip_temperature_celsius`：芯片温度
- `sophon_board_temperature_celsius`：板卡温度(SE9没有该项)
- `sophon_fan_speed_rpm`：风扇速度(部分没有风扇的设备该项无效)
- `sophon_power_usage_watts`：功耗(部分设备硬件不支持,该项无效)
- `sophon_health_status`：设备健康状态（1=健康，0=不健康）
- `sophon_chip_info`：芯片信息（作为带标签的仪表）

### 指标标签

所有指标都包含以下标签：
"device_id", "model", "serial", "chip_type", "board_type"
- `device_id`: 设备ID
- `model`: 硬件型号
- `serial`: 序列号
- `chip_type`: 芯片类型（BM1684,BM1684X,BM1688等）
- `board_type`: 板类型,对于SE5/7设备来说是一个十六进制数字,对于SE9设备来说是设备树名称

## Grafana配置

本工程提供一个Grafana的参考配置文件，在grafana目录下。其效果如下图

![img](./imgs/grafana.png)
