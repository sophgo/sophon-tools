# bm_set_ip 参数解析需求 (cmd_note)

## 目标

兼容旧 IP-only 语法 + 支持多实例(多地址/多路由/多策略),沿用组模式匹配思路。

## 双模式

- **IP-only**:旧语法(family1 尾部可省 + 可选 family2),完全向后兼容。
- **IP + 其它**(路由/策略/额外地址):强制 **4 元组**(每组 4 token,空槽 `''`;dhcp 单 token)。
- 检测:旧模式解析若有剩余 token → 切 4 元组。

## 4 元组组顺序

```
<网卡> [family1] [额外地址]* [路由]* [策略]* [family2]
```

## 组类型识别(family1 之后,peek pos3/pos4)

| pos3 | pos4 | 类型 |
|---|---|---|
| `''` | `''` | 额外地址 `addr mask '' ''` |
| IPv4 | 点分掩码 | 策略 `from from_mask to to_mask [table]`(5 元组,table 可省) |
| IPv4 | 数字/名字/`''` | 路由 `to to_mask via table` |
| IPv4 | 其它 | ERROR 无法区分 |

- family1(首组)恒地址族:pos1=dhcp→dhcp 族;含`:`→IPv6 族;否则 IPv4。
- family2:组首含`:`或 dhcp(且 family1 为 v4)→IPv6 族。
- **策略 `to_mask` 强制点分**(消歧);前缀数字作策略 to_mask 会被当路由 table(用法错误)。
- 策略第 5 token(table)可选:省略(4-token)时仅在**恰好 1 条路由**时共享该路由的 table(该路由须有 table);0 路由或多路由 → ERROR,须显式第 5 token。多条策略各自独立。
- family1 不足 4 token 又有路由/策略 → ERROR(补 `''`)。

## 边界

- 不需要 `default` 恢复。
- 兼容仓库 Rust 版现有 IPv6 地址/网关/DNS 配置(IP-only)。
- 路由/策略仅 IPv4;table 数字 id,不自动写 rt_tables。
- 无新依赖;单文件 `src/main.rs`。

## 无实施模式(--dry-run / -n)

只解析 + 按固定 `key=value` 格式打印分析配置(列表化:`v4.addrs=`、`routes[N].to=`、`policies[N].from=`),不应用、不需 root。测试融入 `cargo test`(`tests/parse_cases.rs`,69 项);`tests/parse_cases.sh` 为薄包装。

## 输入校验(解析层直接报错)

前缀越界(v4>32/v6>128)、非连续/非法点分掩码、畸形 IP(段越界/不足/含 `/`)、空网卡、DHCP 族加静态额外地址。表名允许 `_`/`-`,含点号报错。边界合法:前缀 0、全 0/全 1 掩码。路由 via 可空(直连路由)。

## DNS(逗号分隔多地址,MYS-436)

- 单个 DNS 槽(`dns` 参数)支持逗号分隔多地址:`"8.8.8.8,114.114.114.114"` → 数组逐项校验后存储(`Family.dns: Vec<String>`)。
- 校验:逐项 trim;空项(连续/首尾逗号、纯空白)、非法项、含 `/` 项直接报错;**必须与地址族一致**(v4 族只收 IPv4,v6 族只收 IPv6,不可混族——各后端 nmcli `ipv4.dns`/`ipv6.dns` 按族隔离,混族运行时失败,故解析层拦截)。
- 渲染:netplan `nameservers.addresses` 数组逐项;networkd `DNS=` 空格分隔;nmcli `ipv4.dns`/`ipv6.dns` 逗号串(原生);ip 兜底逐项 `nameserver`。
- 旧模式 v4 family 的 dns 槽含 `:` 的串会触发 family2(v6 族)跳转——混族/纯 v6 DNS 串不做 v4 family 的 DNS,仅 v4 DNS 列表可放该槽。

## 后端

netplan(需 yaml;apply 检测 stderr Error/Conflicting;写入前清除旧 gateway4/gateway6;routes/routing-policy 表名须数字或 rt_tables 已注册)→ nmcli(routes 用 `table=N`,routing-rules 逗号+固定 priority+数字 table;缺席 family 显式 method=disabled)→ networkd(`networkctl reload`+`reconfigure <dev>`,不波及其他网口)→ ip 兜底(DHCP 不支持报错退出;支持 v6 默认路由与 DNS(resolvconf/resolvectl/resolv.conf))。

**错误契约**:关键命令失败一律非零退出且无成功文案——nmcli `con add`/`con up`、`ip addr flush`/`link set`/`addr add`/显式请求的 `route add`/`rule add`、DNS 写入(resolvconf/resolvectl/文件回退)、`netplan apply`、`networkctl reconfigure`、备份失败。非致命项仅限:`nmcli` 新连接激活后清旧 profile 失败、表名映射回写失败、`networkctl reload` 失败(随后 reconfigure 会重读配置)、多默认网关提示。

**NM 新旧 profile 按 UUID 区分**:`con add` 前后各查一次 `nmcli -t -f UUID,NAME,TYPE con show`,差集即新建连接;用该 UUID `con up`;激活成功后才按 UUID 删除本工具旧连接(名称恰为 `static-<dev>` 且 `connection.interface-name` 确为本设备)。add 失败直接返回(不动旧配置);up 失败删除本次新连接并尝试 `con up` 旧连接恢复激活。不按同名/前缀模糊删除,不碰其它接口或非托管连接。`con show` 查询失败则拒绝修改。

**DNS**:`resolvconf -a <dev>` 的 stdin 写入完整 `nameserver` 列表并等待退出码;`resolvectl dns <dev> <dns...>` 用**真实接口名**且**一次传全部** DNS(逐条调用会互相覆盖);两者都不可用时回退直写 `/etc/resolv.conf`(写前快照,失败传播)。子进程一律回收。DNS 写入发生在管理口保护之后。

**快照与回滚**:写前区分原文件存在(内容入内存快照)/ 不存在;读不到原文即拒绝修改;`.bak` 写失败即拒绝修改。应用失败只按本次快照回滚(存在则写回原文,不存在则删除新文件),不读取遗留 `.bak`。

## 策略 from+to 语义

`Policy { from, to, table }` 中 from 与 to 同时存在时,生成**单条**规则(源且目的同时匹配),而非拆成两条。四后端一致:netplan 单个 `routing-policy` 项含 from+to;networkd 单个 `[RoutingPolicyRule]` 段含 From=/To=;nmcli 单条 `priority P from X to Y table N`;ip 单条 `ip rule add from X to Y table N`。

## --force

仅长选项 `--force`。ip 兜底后端默认拒绝 flush「当前默认路由所在设备」(通常是管理口,避免断 SSH);`--force` 覆盖该保护。

## netplan 文件选择与合并

- 目标文件:环境变量 `BM_SET_IP_NETPLAN_FILE` 优先;否则取 `/etc/netplan/` 下字典序最后一个 `*.yaml`;都没有则回退 `01-netcfg.yaml` 并告警。
- 写前快照并备份为 `<file>.bm_set_ip.bak`;`netplan apply` 失败(退出码非 0 或 stderr 含 Error/Conflicting)按本次快照回滚后退出(不读遗留 `.bak`)。
- 设备已存在时**合并**:更新本工具管理的键(dhcp4/dhcp6/addresses/routes/routing-policy/nameservers/optional),保留其余(mtu/match/set-name/receive-checksum-offload 等)。

## nmcli 表名解析

routes 与 routing-rules 的 table 表名统一解析为数字 id:直接数字 → 用之;`/etc/iproute2/rt_tables` 已有名 → 查表;未知名 → 从 100 起自动分配空闲 id 并追加写回 `/etc/iproute2/rt_tables`。同一次运行内多个未知名分到不同 id。
