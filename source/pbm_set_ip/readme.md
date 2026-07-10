# bm_set_ip 配网工具

命令行配网工具,为网卡配置 IPv4/IPv6 地址、默认网关、DNS,以及 IPv4 静态路由与路由策略。自动探测后端:`netplan` → `NetworkManager(nmcli)` → `systemd-networkd` → `ip` 兜底。

## 获取与编译

- 预编译二进制:[Releases](https://github.com/sophgo/sophon-tools/releases)
- 自行编译:需 Rust + [`cross`](https://github.com/cross-rs/cross) + `upx`,执行 `bash build.sh`(产出在 `target/`)。
- netplan 后端依赖 `/etc/netplan/01-netcfg.yaml` 存在且格式正确。

## 用法

```bash
bm_set_ip <网卡> <IP|dhcp> <掩码> [网关] [DNS] \
  [目标网] [目标掩码] [下一跳] [路由表] \
  [策略源] [策略源掩码] [策略目的] [策略目的掩码] \
  [IPv6|dhcp] [IPv6前缀] [IPv6网关] [IPv6-DNS]
```

参数按**特征自动分组**:`dhcp`/`auto` 为 DHCP,含 `:` 为 IPv6,其余为 IPv4。因此同一套位置参数能覆盖以下场景。可选参数用空串 `''` 占位跳过,尾部可省。

```bash
# DHCP IPv4
bm_set_ip eth0 dhcp ''
# DHCP IPv4 + IPv6
bm_set_ip eth0 dhcp '' '' '' dhcp

# 静态 IPv4  地址 掩码 网关 DNS
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8
# 静态 IPv6(掩码槽写前缀)
bm_set_ip eth0 2001:db8::1 64 fe80::1 2001:4860:4860::8888
# 静态 IPv4 + IPv6
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1

# IPv4 + 静态路由(网关/DNS 用 '' 跳过):到 192.168.2.0/24 经 192.168.1.1 入 table 100
bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100
# IPv4 + 静态路由 + 策略(源 10.0.0.0/24、目的 192.168.3.0/24 走 table 100)+ IPv6
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 \
  192.168.2.0 24 192.168.1.1 100 \
  10.0.0.0 24 192.168.3.0 24 \
  2001:db8::1 64
```

| 参数 | 含义 |
|---|---|
| `<网卡>` | 网卡名 |
| `<IP\|dhcp>` | IPv4 地址、`dhcp`/`auto`、或 IPv6 地址(含 `:`) |
| `<掩码>` | 前缀长度(`24`)或点分(`255.255.255.0`),IPv6 用前缀 |
| `[网关]` | 默认网关(netplan 以 `routes` 写入,不用已废弃的 `gateway4`/`gateway6`) |
| `[DNS]` | DNS |
| `[目标网][目标掩码][下一跳][路由表]` | IPv4 静态路由 |
| `[策略源][策略源掩码][策略目的][策略目的掩码]` | IPv4 路由策略,需配合上面的路由表 |
| `[IPv6\|dhcp][IPv6前缀][IPv6网关][IPv6-DNS]` | 第二地址族(IPv6) |

> 路由表为数字 id(如 `100`),四后端直接识别;如需命名,手工 `echo "100 lan_table" | sudo tee -a /etc/iproute2/rt_tables`。路由与策略仅 IPv4。

## 预览(不应用)

`--dry-run` / `-n`:只解析并打印分析出的配置(`key=value`),不修改网络、不需要 root。用于核对参数或自动化测试。

```bash
bm_set_ip --dry-run eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.2.0 24 192.168.1.1 100
```

## 测试

```bash
cargo test --test parse_cases   # 71 项,覆盖 7 模式 + 边缘/异常输入
bash tests/parse_cases.sh        # 等价包装
```
