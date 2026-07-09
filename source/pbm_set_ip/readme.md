# 配网工具

## 简介

简易的配网工具,支持的后端(顺序为工具尝试顺序): netplan network-manager systemd-networkd ip

配置netplan时需要确保文件`/etc/netplan/01-netcfg.yaml`存在并且格式正确

## 预编译版本获取方式

可以从本仓库的Release页面下载：[https://github.com/sophgo/sophon-tools/releases](https://github.com/sophgo/sophon-tools/releases)

## 编译方式

需要准备rust交叉编译环境和upx工具,然后执行如下命令即可在target目录下生成编译后的二进制文件

``` bash
bash build.sh
```

## 使用方式

参数采用**组模式匹配**:按 token 格式特征(冒号=IPv6、`dhcp`/`auto`=dhcp、点分=IPv4/掩码)识别参数组,自动适配以下 7 种配置模式。可选参数用空串 `''` 占位跳过,尾部可省。

``` bash
Examples:
  # 1. 仅 IPv4
  bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8
  # 2. 仅 IPv6(新增)
  bm_set_ip eth0 2001:db8::1 64 fe80::1 2001:4860:4860::8888
  # 3. IPv4 + IPv6
  bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1
  # 4. IPv4 + IPv6 + 静态路由+策略
  bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.2.0 24 192.168.1.1 100 10.0.0.0 24 192.168.3.0 24 2001:db8::1 64
  # 5. 仅 IPv4 + 静态路由(gw/dns 用 '' 跳过)
  bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100
  # 6. DHCP IPv4
  bm_set_ip eth0 dhcp ''
  # 7. DHCP IPv4 + IPv6
  bm_set_ip eth0 dhcp '' '' '' dhcp

Arguments(组顺序):
  <NET_DEVICE>    网卡名
  # IP 配置组1(addr1 形状决定 v4/v6/dhcp)
  <IP>            IPv4 地址 / dhcp / (含冒号时为 IPv6 地址)
  <NETMASK>       掩码或前缀长度
  [GATEWAY]       默认网关(netplan 以 routes 形式写入,不再用已废弃的 gateway4/gateway6)
  [DNS]           DNS
  # IPv4 静态路由组(可选)
  [TO]            目标网络
  [TO_NETMASK]    目标掩码/前缀
  [VIA]           下一跳
  [TABLE]         路由表 id(数字,如 100;策略路由用)
  # IPv4 路由策略组(可选,需配合 TABLE)
  [RULE_FROM]           源地址/网络
  [RULE_FROM_NETMASK]   源掩码/前缀(可空)
  [RULE_TO]             目的地址/网络
  [RULE_TO_NETMASK]     目的掩码/前缀(可空)
  # IP 配置组2(IPv6,仅当组1为 IPv4 时;token 为 IPv6 形状或 dhcp 触发)
  [IPV6]          IPv6 地址 / dhcp
  [IPV6_PREFIX]   IPv6 前缀长度
  [IPV6_GATEWAY]  IPv6 网关
  [IPV6_DNS]      IPv6 DNS
```

### 7 种配置模式

| 模式 | 说明 |
|---|---|
| 1 | 仅 IPv4,无 IPv6,无高级路由 |
| 2 | 仅 IPv6,无 IPv4(新增,按 IPv6 格式特征识别) |
| 3 | IPv4 + IPv6,无高级路由 |
| 4 | IPv4 + IPv6 + IPv4 高级路由 |
| 5 | 仅 IPv4 + IPv4 高级路由 |
| 6 | 单 dhcp → IPv4 为 dhcp |
| 7 | 双 dhcp → IPv4 + IPv6 均为 dhcp |

### 后端

按优先级自动探测:`netplan` → `NetworkManager(nmcli)` → `systemd-networkd` → `ip` 兜底。静态路由与路由策略在四个后端均已实现(仅 IPv4)。

### 路由表命名

`TABLE` 为数字 id,netplan/nmcli/networkd/ip 均直接识别。如需命名(如 `100 lan_table`),可手工执行 `echo "100 lan_table" | sudo tee -a /etc/iproute2/rt_tables`,工具不自动写入。

