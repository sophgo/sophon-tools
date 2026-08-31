# sophliteos

算力设备管理系统（SophLiteOS）—— Sophgo 算力设备的 Web 管理平台，提供设备资源监控、告警、日志、网络/IP、密码、OTA/SSM 升级、版本等设备运维功能。

> 本子工程自 `sophgo-liteos` 迁入并裁剪掉 algoliteos 算法业务集成。

## 目录结构
- `api`: 后端业务控制器（device-mgmt handlers）
- `router`: 路由定义
- `client/ssm`: 设备端 SSM(System Service Manager, 127.0.0.1:9779) 接口客户端
- `client/httpclient`: 通用 HTTP 封装
- `mvc`: 参数封装/验证/返回/i18n/异常
- `middleware`: 鉴权/熔断/超时中间件
- `database`: sqlite（User/Alarm/OptLog）
- `config`/`logger`/`global`/`initialization`: 配置/日志/全局/初始化
- `frontend`: Vue 前端（基于 vue-vben-admin），源码已在本目录下
- `build`/`scrip`/`release`: 构建脚本/部署脚本/产物落点

## 编译依赖
- go >= 1.19
- `gcc-aarch64-linux-gnu`（arm64 交叉编译）：`sudo apt-get install gcc-aarch64-linux-gnu`
- docker（前端在 node:16 容器中构建）

## 构建
前端源码已在本目录 `frontend/` 下，**无需 clone**。进入 build 目录执行：
```bash
cd build
./build_2_release.sh
```
（若 docker 需 root：`sudo ./build_2_release.sh`，且 root 的 PATH 需含 go）

## 产物
```
release/
├── sophliteos-linux_amd64.tgz
├── sophliteos-linux_arm64.tgz
├── sophliteos_pcie_1.1.2.deb
├── sophliteos_soc_1.1.2.deb
├── sophliteos_pcie_1.1.2_sdk.deb
└── sophliteos_soc_1.1.2_sdk.deb
```

## 安装运行
- x86: `tar -xvf sophliteos-linux_amd64.tgz && sudo ./install.sh` 或 `sudo dpkg -i sophliteos_pcie_1.1.2.deb`
- arm: `tar -xvf sophliteos-linux_arm64.tgz && sudo ./install.sh` 或 `sudo dpkg -i sophliteos_soc_1.1.2.deb`
