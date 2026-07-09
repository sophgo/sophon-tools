# bm_set_ip 参数解析需求 (cmd_note)

## 目标

兼容双方配置参数模式(仓库 Rust 版 + 设备旧 bash 脚本版),并新加高级路由功能。
采用 **组模式匹配** 解析:把位置参数切成若干"组",按组判定 v4/v6、是 IP 配置还是路由配置还是路由+策略。

## 7 种配置模式

1. 只配 IPv4,无 IPv6,无高级路由
2. 只配 IPv6,无 IPv4(新增,通过 IPv6 格式特征识别)
3. 配 IPv4 + IPv6,无高级路由
4. 配 IPv4 + IPv6,且配 IPv4 高级路由
5. 只配 IPv4,无 IPv6,配 IPv4 高级路由
6. 只有一个 dhcp/auto → IPv4 为 dhcp(对齐仓库版)
7. 有两个 dhcp/auto → IPv4 + IPv6 都为 dhcp(对齐仓库版)

## 组定义与识别

位置参数在 `<net_device>` 之后,按以下组的顺序出现:

```
f1: [addr1] [mask1] [gw1] [dns1]          # IP 配置组1
rt: [to] [to_mask] [via] [table]          # 路由组(IPv4,不含默认网关)
pl: [rule_from] [rule_from_mask] [rule_to] [rule_to_mask]   # 策略组(IPv4)
f2: [addr2] [mask2] [gw2] [dns2]          # IP 配置组2(IPv6)
```

**组识别规则(按组首 token 形状判定)**:
- 组首含 `:` → 该 IP 配置组为 **IPv6** 静态
- 组首为 `dhcp`/`auto` → 该 IP 配置组为 dhcp 族(第 1 个=dhcp→IPv4-dhcp;第 2 个=dhcp→IPv6-dhcp)
- 组首为 IPv4 点分地址 → IPv4 静态 IP 配置组
- 路由组首(`to`)是 IPv4 形状(网络地址)
- 策略组首(`rule_from`)是 IPv4 形状

**组边界判定(何时进入下一组)**:
- 在 IP 配置组内,已取 addr(+mask+gw+dns)后,看下一非 `''` token:
  - `:` 或 dhcp/auto → 进入 f2(IPv6 组),跳过中间的路由组/策略组
  - IPv4 形状 → 进入路由组 `to`
- 路由组之后:下一 token `:`/dhcp → 进 f2(跳过策略);IPv4 → 进策略组
- 策略组之后:下一 token `:`/dhcp → 进 f2

**槽内规则**:每槽取到 `''` → 该槽 None 并前进;无更多参数 → 停(尾部可省);中间跳过必须用 `''`。

> 路由组放在 IPv6 组**之前**(用户要求:IPv4 路由放到 IPv6 前面)。

## 高级路由功能(设备脚本 13 参数)

| $ | 含义 | 组 |
|---|---|---|
| 4 | 默认网关 → **改用 routes**(to:0.0.0.0/0 via:gw),不再用已废弃的 gateway4 | f1 |
| 6 | 目标地址 to | rt |
| 7 | 目标掩码 to_mask | rt |
| 8 | via 下一跳 | rt |
| 9 | 路由表 id(数字,如 100) | rt |
| 10 | 策略 from(源) | pl |
| 11 | from 子网掩码(可空) | pl |
| 12 | 策略 to(目的) | pl |
| 13 | to 子网掩码(可空) | pl |

- table 仅数字 id;rt_tables 命名(如 `100 lan_table`)是可选手工前置步骤,工具不自动写(无 name 参数)。
- 路由+策略**仅 IPv4**(对齐旧脚本,不做 IPv6 路由/策略)。
- DHCP 时不写静态路由/策略(与旧脚本一致)。
- table 缺省 main(254);策略缺 table → 该条规则无意义,WARNING 并跳过。

## 四后端落地

| 后端 | 默认网关(gw1) | 高级路由 | 策略 |
|---|---|---|---|
| netplan | `routes:[{to:0.0.0.0/0, via:gw}]` | `routes:[{to,via,table}]` | `routing-policy:[{from/to,table}]` |
| nmcli | `ipv4.gateway` | `ipv4.routes "<to/prefix> <via> <table>"` | `ipv4.routing-rules "priority n from <src/prefix> table <t>"` |
| networkd | `[Network] Gateway=` | `[Route] Destination/Gateway/Table` | `[RoutingPolicyRule] From/To/Table` |
| ip 兜底 | `ip route add default via` | `ip route add <to/prefix> via <via> dev <dev> table <table>` | `ip rule add from/to <net/prefix> table <t>` |

## 其它边界

- 不需要 `default` 恢复功能。
- 必须兼容仓库 Rust 版现有的 IPv6 地址/网关/DNS 配置方案(不破坏)。
- 无新依赖;单文件 `src/main.rs`。
