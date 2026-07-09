# 使用说明

## 1. 是什么

| 组件 | 角色 | 端口 | 技术栈 |
|---|---|---|---|
| **bmssm** | 设备端后端:鉴权/硬件指标/systemd/端口/网络/OTA/文件/docker | :9779 | Go (Gin), 静态 musl |
| **sophliteos** | Web 平台:前端 + 反代 bmssm + SSO + OTA/指标选择 | :8080 | Go (Gin) + Vue3 (vben) |

同机部署。浏览器访问 `http://<设备IP>:8080`。

```
浏览器 :8080 (sophliteos)
   ├── 静态前端 dist
   ├── /api/v1/* ──反代──▶ bmssm :9779 (JWT 鉴权)
   └── /api/device/* /api/sso/* (sophliteos 本地)
```

## 2. 登录

- 浏览器开 `http://<设备IP>:8080`,用户名 `admin`。
- 默认密码见 bmssm 配置 `server.defaultPassword`(默认 `admin`)。首次用默认密码登录后**强制改密**,改完才能用其它功能。
- 登录流程:前端 `POST /api/v1/login` 拿 token → `POST /api/sso/register` 注册会话(SSO 单会话,新登录踢旧会话,旧端弹"会话已下线"并退回登录页)。

## 3. Web 页面

| 菜单 | 页面 | 功能 |
|---|---|---|
| 基础信息 | 设备概览 / 板卡详情 / **性能历史** | 性能历史:每指标独立 echarts,恒定值显示静态文字;指标选择 Modal 分类勾选,保存到后端 |
| 设备运维 | 系统升级 / 网络设置 / 告警阈值 / 实时终端 / 文件管理 / **服务管理** / **端口状态** | |
| └ | 服务管理 | 列所有 systemd 服务;**关键服务**按钮置灰(后端 403 兜底);可启停/重启/重载/开机自启;详情 Drawer 看 unit 文件;导出本次启动时间分析(文本 + SVG) |
| └ | 端口状态 | 监听套接字表(TCP/UDP,IPv4/6),含归属进程(pid/进程名/命令行);协议过滤 |
| 日志管理 | 告警日志 / 操作日志 | |

## 4. 关键服务保护

服务管理页对**关键服务**禁止启停/禁用/重载(后端 403 是真实闸门,前端置灰仅为体验)。默认保护名单(`bmssm.yaml` 可覆盖 `systemd.protected`):

- 管理/网络/shell 锁出核心:`bmssm` `sophliteos` `nginx` `ssh`/`sshd` `networking` `systemd-networkd` `systemd-resolved` `networkd-dispatcher` `dbus` `systemd-journald` `systemd-logind` `systemd-udevd` `systemd-timesyncd` `getty@*` `serial-getty@*`
- Sophon 厂商硬件/运行时:`bm*.service`(通配,含 `bmrt_*`/`bmDeviceDetect`/`bmSysMonitor`/`bm-se7-*` 等)
- 功能关键:`docker` `containerd` `upd72020x-fwload`(USB3) `apparmor` `ubuntu-fan`

> 禁用所有**未保护**服务不会导致系统无法启动(boot target 硬依赖只有 systemd 核心 + 根挂载,都受保护)。详见服务管理页 + 启动报告。

## 5. 性能指标存档

- 采样 20s/轮,定长二进制 record + gzip 分段(每小时一个 `.mtrc.gz`),`/var/lib/bmssm/metrics/`。
- 淘汰策略:**仅按空间**(默认 100MB),超限 FIFO 删最旧分段,无时间淘汰。
- 容量(v3 schema 18 字段,20s 采样):实测约 **5 KiB/小时 → 100MB ≈ 2 年**。设备指标越恒定压缩越好(可达 ~7 年)。
- 普罗米修斯实时指标(`/metrics`,27 个 `sophon_*` gauge)与存档**共用一轮采集**,不重复采。

## 6. 配置调整

配置文件 `/opt/sophon/bmssm/config/bmssm.yaml`(改完 `systemctl restart bmssm`):

```yaml
metrics:
  updateIntervalSeconds: 20      # 采样间隔(秒)
  archive:
    enabled: true                # 存档开关
    path: /var/lib/bmssm/metrics # 存档目录
    maxSizeMB: 100              # 空间淘汰上限(MB)
    channelBufferSize: 16       # 异步写入通道
systemd:
  protected: [bmssm.service, ...]  # 覆盖关键服务名单
```

sophliteos 配置 `/opt/sophon/sophliteos/config/sophliteos.yaml`:`bmssm.server`(默认 `127.0.0.1:9779`)、`server.www`(dist 路径)、`server.timeout`。

## 7. 服务管理

```bash
systemctl {status,restart,start,stop} {bmssm,sophliteos}
journalctl -u bmssm -f        # 看日志
```

## 8. 路径速查

| | 二进制 | 配置 | 数据 |
|---|---|---|---|
| bmssm | `/opt/sophon/bmssm/bin/bmssm` | `/opt/sophon/bmssm/config/bmssm.yaml` | `/var/lib/bmssm/{bmssm.db,metrics/}` `/var/log/bmssm` |
| sophliteos | `/opt/sophon/sophliteos/bin/sophliteos` | `/opt/sophon/sophliteos/config/sophliteos.yaml` | `/var/lib/sophliteos/db` `/var/log/sophliteos` `/opt/sophon/sophliteos/dist` |

API 细节见 [API.md](./API.md);编译部署见 [BUILD.md](./BUILD.md)。
