# ssm

Sophon System Management 服务（由 bmssm 现代化重写）。

## 编译
- x86: `bash build/build-ssm.sh`
- arm64: `bash build/build-ssm-arm64.sh`（musl 工具链自动获取）

## 配置
默认读取 `/etc/ssm/conf/ssm.yaml`，本地开发回退 `./config/ssm.yaml`。

## 端口
9779