# pssm 地基子项目设计

- **日期**：2026-07-02
- **状态**：待评审
- **作者**：zetao.zhang
- **关联项目**：`sophon-tools/source/pssm`（由 `bmssm` 重构而来）

## 1. 背景与目标

`bmssm`（`/home/zzt/workspace/bmssm`）是 Sophon 系统管理服务（System Management），Go 1.20 + gin 的 REST API，监听 9779，跑在 Sophon BM/SE 系列 SOC 设备上。原项目 339 个 Go 文件，依赖 k8s 全家桶、kubeedge、cadvisor、docker engine 等，并附带 C 子项目 `bm_snmp_service`。

本系列子项目将 `bmssm` **现代化重写 + 瘦身**为 `pssm`，目录位于 `sophon-tools/source/pssm/`，Go module 名 `ssm`（`p` 前缀仅为子目录命名惯例，与 `psophliteos`→module `sophliteos` 一致）。重写遵循 `psophliteos` 的现代 Go 布局。**丢弃** kubeadapter、pierce-edge、bm_snmp_service 三个子系统。**保留** 设备信息+硬件、软件/OTA、Docker、网络+用户/认证 四大功能模块。

`psophliteos` 的 `client/ssm`（配置 `server: '127.0.0.1:9779'`）是 SSM 服务的客户端，pssm 即为其服务端，端口必须保持 9779。

### 1.1 分解策略（方案 A：垂直切片，地基先行）

整个 pssm 重写分解为 5 个子项目，各自走 spec→plan→实现 周期：

1. **pssm 地基**（本 spec）——骨架/配置/日志/设备信息/健康端点
2. 硬件管理——卡片/健康/LED/重启
3. 软件/OTA——软件包安装升级 + 固件 OTA
4. Docker 管理——容器/镜像
5. 网络 + 用户/认证/审计——网卡 IP/NAT + 登录/token/审计

### 1.2 本子项目边界

**包含**：现代 Go 骨架（config/global/logger/initialization/middleware/router）、SOC 设备信息识别、`/healthz` 端点、aarch64 交叉编译与真机部署验证。

**不包含**：硬件/软件/Docker/网络/用户等任何业务模块。但骨架需为它们留好扩展位（router 注册点、mvc 目录、middleware auth 占位、DB 抽象层）。

## 2. 目录布局

镜像 `psophliteos` 惯例：

```
pssm/
├── main.go              # initialization.InitBase() → Routers() → InitServer() → 优雅退出
├── go.mod               # module ssm
├── config/              # viper 加载 ssm.yaml + 热加载
├── global/              # 进程级状态：DeviceType/Role/Sn/Version...
├── logger/              # zap 封装
├── initialization/      # InitBase / Routers / InitServer
├── middleware/          # recovery / 访问日志 / 限流 / auth占位
├── router/              # 路由注册（/healthz + 后续模块扩展位）
├── mvc/                 # 业务模块位置（地基阶段只放 health）
│   └── health/
├── pkg/device/          # devinfo：设备信息识别
├── build/               # build-ssm.sh(x86) / build-ssm-arm64.sh(aarch64)
└── release/             # 产物输出
```

## 3. 组件设计

### 3.1 config

- viper 加载 `/etc/ssm/conf/ssm.yaml`，本地开发回退 `./ssm.yaml`（与 bmssm 原路径一致，便于真机平滑替代）。
- 字段精简：`server.{listenIP, port, auth}`、`log.{level, path}`、`db.driver`。
- 保留 `SyncConfig` 读写锁（`sync.RWMutex`）+ fsnotify 热加载。
- **砍掉** bmssm 的 kubeadapter/pierce-edge/k8s 配置块。

### 3.2 logger

- 采用 `go.uber.org/zap`，替代 bmssm 自研 beego-logs 风格包。
- 封装统一接口：`logger.Info/Warn/Error/Debug`。
- console + file 双输出，file 按大小 rotate（`lumberjack`），级别可配。

### 3.3 global

进程级单例状态，由 devinfo 在 InitBase 阶段填充：

```go
var (
    DeviceType   string  // pcie / soc / unknown
    DeviceRole   string  // SE / SE-CTRL / SE-CORE
    DeviceTypeEx string  // 如 SE8
    DeviceSnEx   string
    ChipSn       string
    ModuleType   string
    Version      BuildInfo  // 本地定义：{Version, GitCommit, BuildTime}
)
```

### 3.4 pkg/device (devinfo)

保留 bmssm 的 SOC 分支逻辑，迁移到 `pkg/device`：

- 检测 `/factory/OEMconfig.ini` 存在 → `DeviceType=soc`, `DeviceRole=SE`。
- 解析 OEMconfig.ini：`PRODUCT` → `DeviceTypeEx`；`SN` → `ChipSn`/`DeviceSnEx`；`CHIP` → `ModuleType`。
- PCIE 分支（`/sys/bus/i2c/devices/1-0017/information`）保留但非本设备重点。
- 读取失败降级为 `UNKNOWN_DEV`，不阻断启动。

### 3.5 initialization

- `InitBase()`：LoadConfig → InitLogging → GetDeviceInfo 填 global → InitDB（建库 + migration 框架，空表）。
- `Routers()`：`gin.New()` + 中间件链（recovery、访问日志、tokenBucket 限流）→ 注册 `/healthz`。
- `InitServer(r)`：`&http.Server{Addr, Handler}`，返回供 main 调用 `ListenAndServe`。

### 3.6 router + mvc/health

地基阶段唯一端点：

```
GET /healthz → 200
{
  "status": "ok",
  "deviceType": "soc",
  "role": "SE",
  "deviceTypeEx": "SE8",
  "sn": "<DeviceSnEx>",
  "version": "<Version>",
  "uptime": "<秒>"
}
```

后续业务模块路由在 `Routers()` 内注册扩展。

### 3.7 middleware

- `Recovery`：gin Recovery + panic 日志。
- `AccessLog`：请求方法/路径/状态/耗时。
- `RateLimit`：移植 bmssm 的 tokenBucket（`golang.org/x/time/rate`，默认 100 token，10ms 补充）。
- `Auth`（占位）：定义接口，地基阶段不启用；用户/认证子项目填充。

### 3.8 main.go

- 调 `initialization.InitBase()` → `Routers()` → `InitServer(r)`。
- `go s.ListenAndServe()`，主 goroutine 监听 `SIGHUP/SIGINT/SIGTERM/SIGQUIT`。
- 收信号 → `ctx` cancel → `s.Shutdown(ctx)` 优雅退出，10s 超时。

## 4. 错误处理

- **配置缺失**：用默认值（port=9779、log.level=info）+ 告警日志，不中断启动。
- **devinfo 读取失败**：降级 `UNKNOWN_DEV`，告警，服务正常启动。
- **DB 初始化失败**：告警，服务仍起（地基阶段无业务依赖 DB）。
- **端口占用**：启动失败，日志明确报错并退出。

## 5. 测试策略

- **单元测试**：
  - `config`：ssm.yaml 解析、默认值、热加载回调触发。
  - `pkg/device`：OEMconfig.ini 解析（测试夹具文件，不依赖真机），覆盖 PRODUCT/SN/CHIP 各字段与缺失分支。
- **真机验证**（`linaro@172.26.166.185` / `linaro`，SOC 设备）：
  1. `build/build-ssm-arm64.sh` 交叉编译。
  2. scp 产物到真机。
  3. 部署 ssm.yaml 到 `/etc/ssm/conf/`，运行二进制。
  4. `curl http://127.0.0.1:9779/healthz`，校验返回的 deviceType=soc、role=SE 及 SN 与真机一致。
  5. 发送 SIGTERM，确认优雅退出。

## 6. 构建

- `build/build-ssm.sh`：x86，`CGO_ENABLED=1 go build`（sqlite cgo）。
- `build/build-ssm-arm64.sh`：aarch64 交叉编译，`CGO_ENABLED=1 CC=aarch64-linux-gnu-gcc`，参考 bmssm 的 `build-ssm-arm64.sh` 与 psophliteos 的 arm 构建脚本。
- 产物输出到 `release/`。

## 7. 关键决策

| 决策项 | 选择 | 理由 |
|---|---|---|
| module 名 | `ssm` | 子目录 `pssm` 带 p 前缀仅为仓库命名惯例 |
| 端口 | 9779 | 沿用 bmssm，兼容 psophliteos client/ssm |
| 配置路径 | `/etc/ssm/conf/ssm.yaml` | 与 bmssm 一致，真机平滑替代 |
| 日志库 | zap | 现代化、高性能、结构化 |
| DB 时机 | 地基阶段引入 sqlite | 建好抽象层与 migration 框架，用户/审计子项目直接填表 |
| 重写范围 | 仅核心 SSM | 丢弃 kubeadapter/pierce-edge/snmp |

## 8. 后续子项目（占位，非本 spec 范围）

地基完成后，依次：硬件管理 → 软件/OTA → Docker → 网络+用户/认证。各自再开一轮 brainstorm 产出独立 spec。
