# API 说明

bmssm(:9779)为后端,sophliteos(:8080)反代 `/api/v1/*` 到 bmssm 并补充少量本地端点。两者同机部署。

## 统一响应信封

```jsonc
// 成功
{ "code":0, "msg":"请求成功", "result":<data>, "deviceSn":"..." }
// 失败
{ "code":1, "msg":"请求失败", "error_code":N, "error_message":"..." }
```
`code==0` 成功,`code==1` 失败。

## 鉴权

- bmssm:JWT Bearer,HS256,12h TTL。除公开端点外,所有 `/api/v1/*` 需 `Authorization: Bearer <token>`。
- 登录:`POST /api/v1/login` body `{username,password}` → `result.token`。首次用默认密码登录发的是 temp token,只能调 `POST /api/v1/password` 改密,改完发正式 token。
- sophliteos 侧 SSO:单会话,新登录踢旧会话(旧会话后续请求返 401 `SESSION_OFFLINE`)。

---

## bmssm 路由表

### 公开(无 Auth)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` `/health` | 存活/健康(JSON) |
| GET | `/metrics` | Prometheus 抓取(无 Auth,Prometheus 加不了头) |
| POST | `/api/v1/login` | 登录(限流 5/12s/IP) |
| GET | `/api/v1/hardware/terminal` | WebSocket 终端(用 `?token=` 鉴权,浏览器加不了头) |
| GET | `/api/v1/files/download` | 文件下载(`?token=` 或 Authorization) |

### 受保护(`/api/v1`,需 Auth)

**用户/鉴权**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/logout` | 注销 |
| POST | `/password` | 改密 body `{oldPassword,newPassword}`(temp token 可用) |
| GET/POST | `/user` | 列/建用户 |
| DELETE | `/user/:name` | 删用户 |

**日志/告警**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/audit` | 审计日志 |
| GET | `/logs/download` | 流式 tar.gz 打包整个 `/var/log` 目录 |
| GET | `/alarms` | 告警历史 |

**性能指标历史存档**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/metrics/fields` | 字段目录 |
| GET | `/metrics/history?from=&to=&fields=` | 历史查询(unix 秒,fields 逗号分隔,首列 timestamp) |
| GET | `/metrics/export?from=&to=&format=csv` | CSV 导出(只认 Authorization 头) |

**服务管理 / 端口状态**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/systemd/services` | 列所有 .service(含 protected 标记) |
| GET | `/systemd/services/:name` | 服务详情(status+unit 文件+日志) |
| POST | `/systemd/services/:name/action` | body `{action}`:start/stop/restart/reload/enable/disable。关键服务返 403 |
| POST | `/systemd/daemon-reload` | 全局 daemon-reload |
| GET | `/systemd/boot-report` | 本次启动分析(total/kernel/userspace + blame + critical-chain) |
| GET | `/systemd/boot-report/export?format=text\|svg` | 文本/SVG 导出 |
| GET | `/ports/listening?proto=tcp\|udp` | 监听套接字 + 归属进程(pid/comm/cmdline) |

**网络**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/PUT | `/network/ip` | 查/配网卡 IP |
| GET/POST/DELETE | `/network/nat[/:num]` | NAT 规则 |

**Docker**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/docker/container` `/docker/image` | 列容器/镜像 |
| POST | `/docker/container/:name/start\|stop` | 启停容器 |
| DELETE | `/docker/container/:name` `/docker/image/:id` | 删容器/镜像 |
| GET | `/docker/logs/:name` | 容器日志 |

**软件 / OTA**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/software` `/software/install` `/software/upgrade` | 软件列表/安装/升级 |
| POST | `/ota/upload` `/ota/upgrade` `/ota/rollback` | OTA 上传/执行/回滚 |
| GET | `/ota/workflow[/:id]` | OTA 工作流列表/详情 |
| GET | `/ota/download/:id` | OTA 下载(旧) |

**硬件 / 设备信息**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/hardware/health` `/hardware/card` `/hardware/led` | 健康/网卡/LED |
| POST | `/hardware/reboot` `/hardware/shutdown` | 重启/关机 |
| PUT | `/hardware/led` | 配 LED |
| POST | `/hardware/exec` `/hardware/scp` | 远程命令/拷贝 |
| GET/POST | `/device/basic` `/device/resource` `/device/configure/basic` | 设备信息/资源/配置 |
| GET/POST | `/device/configure/alarm` | 告警阈值配置 |
| POST | `/software/notify/subscribe\|unsubscribe` | 告警订阅 |
| GET | `/software/notify/subscribe/:name` | 订阅详情 |

**文件管理**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/files` `/files/content` | 列文件/读内容 |
| POST | `/files/upload` `/files/chmod` `/files/chown` `/files/mkdir` `/files/rename` | 上传/改权限/改主/建目录/改名 |
| DELETE | `/files` | 删文件 |

---

## sophliteos 路由

**反代**:`/api/v1/*any` → `127.0.0.1:9779`(bmssm),前置 SSO 单会话校验。鉴权由 bmssm 完成。

**SSO 本地端点**(不反代):

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sso/active` | 当前活跃会话 `{active,username}` |
| POST | `/api/sso/register` | body `{username,token}` 注册新会话(踢旧) |
| POST | `/api/sso/logout` | 注销当前会话 |
| GET | `/api/sso/events?token=` | SSE 长连接,被踢时推 `SESSION_OFFLINE`,25s ping |

**`/api/device/*` 本地端点**(不反代,TimeoutMiddleware):

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/device/ota/list` | OTA 文件列表 |
| POST | `/api/device/ota/chunked` `/api/device/ota/file` | OTA 分块/整包上传 |
| GET | `/api/device/version` | 版本信息 |
| POST | `/api/upgrade` | 升级执行 |
| GET/PUT | `/api/device/metrics-selection` | 性能历史指标选择持久化 |

**静态**:sophliteos 从 `server.www`(默认 `/opt/sophon/sophliteos/dist`)服务前端(`/`、`/assets`、`/resource`、`/_app.config.js`)。

> 浏览器实际访问 `:8080`。nginx `:80` 在测试机上是 stock 配置,不转发 `/api`,不走它。
