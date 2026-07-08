# pssm 业务模块补全设计

- **日期**：2026-07-02
- **状态**：待评审→执行
- **基础**：地基子项目已落地（config/logger/global/device/devinfo/database/middleware/mvc/health/router/initialization/main，已合并 main）
- **目标**：基于地基补全 ssm 的 4 个业务模块（硬件/软件OTA/Docker/网络+用户认证），使 ssm 成为功能可用的 SSM 服务。

## 1. 架构决策

### 1.1 mvc 重写，不移植反射框架
bmssm 用自研 `resource`（IGettable/IPostable/...）+ 反射路由生成。pssm 改为 **mvc 分层 + 朴素 gin handler**，与已落地的 `mvc/health` + `router.Register` 一致，与 psophliteos 风格一致。

每个模块目录结构：
```
mvc/<module>/
├── controller.go   # gin handler 函数（接收 *gin.Context，调用 service，返回 JSON）
├── service.go      # 业务逻辑（无 gin 依赖，可单测）
└── types.go        # 请求/响应 struct
```
路由集中在 `router/router.go` 的 `Register` 内按模块注册。

### 1.2 路由分组与认证
- 公开：`GET /healthz`、`POST /api/v1/login`
- 受保护：`/api/v1/*` 其余，挂 `middleware.Auth`（JWT token 校验）
- 用 `r.Group("/api/v1")` + Auth 中间件

### 1.3 认证：JWT + sqlite 用户表
- `POST /api/v1/login`：校验用户名密码（用户存 sqlite，bcrypt 哈希），签发 JWT（HS256，secret 来自 config），有效期 12h。
- `middleware.Auth`：解析 `Authorization: Bearer <token>`，校验签名+过期，失败 401。
- 用 `github.com/golang-jwt/jwt/v5` + `golang.org/x/crypto/bcrypt`。
- 暴露 DB 句柄：`database` 包加 `DB()` 访问器（替代地基的 unexported globalDB）。

### 1.4 cgo 依赖取舍（bmlib）
- TPU/card/chip 级信息依赖 `bmlib`（cgo `.so`）。**本阶段不移植 bmlib_wrapper**，相关硬件 endpoint 先用 sysfs/`bm-smi` 等价命令或返回结构化占位，并在响应中标注 `available:false`。
- 硬件模块先实现：reboot、health（sysfs）、led（shell，若设备支持）、ip、nat。card/tpu/controller 留占位 endpoint。

### 1.5 Docker
用 `github.com/docker/docker` client（moby）或 `github.com/fsouza/go-dockerclient`。优先 go-dockerclient（轻、无 cgo）。容器/镜像的 list/inspect/start/stop/remove/logs + conf。

### 1.6 软件/OTA
软件包安装/升级（deb/tar 解包 + 落盘）、OTA 固件下载（HTTP 下载 + 进度）。VM/virtualization 子模块**不实现**（YAGNI，SE6 专属）。

## 2. 各模块 endpoint 范围

### 模块1 硬件 `mvc/hardware`
| 方法 | 路径 | 来源 | 说明 |
|---|---|---|---|
| GET | /api/v1/hardware/health | sysfs | 健康（温度/功耗，能取则取） |
| POST | /api/v1/hardware/reboot | shell | 重启，可选 delay |
| GET/PUT | /api/v1/hardware/led | shell | LED 状态 |
| GET | /api/v1/hardware/card | 占位 | BM 卡信息（bmlib 未接入，available:false） |
| GET/PUT | /api/v1/network/ip | shell | 网卡 IP |
| POST | /api/v1/network/nat | shell/iptables | NAT 规则 |

### 模块2 用户/认证/审计 `mvc/user` `mvc/audit`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/login | 登录签发 JWT |
| POST | /api/v1/logout | 注销（token 黑名单，可选） |
| GET | /api/v1/user | 用户列表（admin） |
| POST | /api/v1/user | 创建用户 |
| DELETE | /api/v1/user/:name | 删除用户 |
| GET | /api/v1/audit | 审计日志列表 |

### 模块3 Docker `mvc/docker`
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/docker/container | 容器列表 |
| POST | /api/v1/docker/container/:name/start | 启动 |
| POST | /api/v1/docker/container/:name/stop | 停止 |
| DELETE | /api/v1/docker/container/:name | 删除 |
| GET | /api/v1/docker/image | 镜像列表 |
| DELETE | /api/v1/docker/image/:id | 删除镜像 |
| GET | /api/v1/docker/logs/:name | 容器日志 |

### 模块4 软件/OTA `mvc/software`
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/software | 已装软件列表 |
| POST | /api/v1/software/install | 上传/安装软件包 |
| POST | /api/v1/software/upgrade | 升级 |
| GET | /api/v1/ota/download/:id | OTA 下载进度 |
| POST | /api/v1/ota/upload | 上传固件 |
| POST | /api/v1/ota/upgrade | 固件升级 |

## 3. 实施顺序
按「无 cgo 阻塞 + 价值高 + 体量小」排序：
1. 用户/认证/审计 + 网络（纯 Go，地基 DB 可用，解锁 Auth 中间件）
2. Docker（go-dockerclient，无 cgo）
3. 硬件（reboot/health/led/ip/nat，shell/sysfs；card/tpu 占位）
4. 软件/OTA（最大；下载/安装/升级）

每模块：spec 摘要（本文）+ 详细 plan（含从 bmssm 移植的代码）+ subagent 实现 + 评审 + 合并。

## 4. 降级与错误处理
- bmlib 相关：返回 `{available:false, reason:"bmlib not integrated"}`，不 500。
- docker 不可用（无 socket）：返回 `{available:false}`，不阻断服务。
- 认证失败：401 JSON。
- 所有错误统一 `{error:"...", code:"..."}` 格式。

## 5. 测试策略
- service 层单测（mock 依赖，TDD）。
- controller 层用 `httptest` 端到端（gin + middleware）。
- 真机验证：登录→拿 token→带 token 调各 endpoint。
