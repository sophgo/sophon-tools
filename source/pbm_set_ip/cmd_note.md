# bm_set_ip 参数解析需求 (cmd_note)

## 目标

兼容旧 IP-only 语法 + 支持多实例(多地址/多路由/单策略),沿用组模式匹配思路。

## 双模式

- **IP-only**:旧语法(family1 尾部可省 + 可选 family2),完全向后兼容。
- **IP + 其它**(路由/策略/额外地址):强制 **4 元组**(每组 4 token,空槽 `''`;dhcp 单 token)。
- 检测:旧模式解析若有剩余 token → 切 4 元组。

## 4 元组组顺序

```
<网卡> [family1] [额外地址]* [路由]* [策略] [family2]
```

## 组类型识别(family1 之后,peek pos3/pos4)

| pos3 | pos4 | 类型 |
|---|---|---|
| `''` | `''` | 额外地址 `addr mask '' ''` |
| IPv4 | 点分掩码 | 策略 `from from_mask to to_mask`(单) |
| IPv4 | 数字/名字/`''` | 路由 `to to_mask via table` |
| IPv4 | 其它 | ERROR 无法区分 |

- family1(首组)恒地址族:pos1=dhcp→dhcp 族;含`:`→IPv6 族;否则 IPv4。
- family2:组首含`:`或 dhcp(且 family1 为 v4)→IPv6 族。
- **策略 `to_mask` 强制点分**(消歧);前缀数字作策略 to_mask 会被当路由 table(用法错误)。
- 策略 table 取**最后一条路由的 table**;无路由配策略 → ERROR。
- family1 不足 4 token 又有路由/策略 → ERROR(补 `''`)。

## 边界

- 不需要 `default` 恢复。
- 兼容仓库 Rust 版现有 IPv6 地址/网关/DNS 配置(IP-only)。
- 路由/策略仅 IPv4;table 数字 id,不自动写 rt_tables。
- 无新依赖;单文件 `src/main.rs`。

## 无实施模式(--dry-run / -n)

只解析 + 按固定 `key=value` 格式打印分析配置(列表化:`v4.addrs=`、`routes[N].to=`、`policy.from=`),不应用、不需 root。测试融入 `cargo test`(`tests/parse_cases.rs`,30 项);`tests/parse_cases.sh` 为薄包装。
