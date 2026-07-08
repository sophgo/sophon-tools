# bmssm

Sophon System Management 服务（由 bmssm 现代化重写）。

## 编译
- x86: `bash build/build-bmssm.sh`
- arm64: `bash build/build-bmssm-arm64.sh`（musl 工具链自动获取）

## 配置
默认读取 `/etc/bmssm/conf/bmssm.yaml`，本地开发回退 `./config/bmssm.yaml`。

## 端口
9779