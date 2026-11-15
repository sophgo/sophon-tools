# bm_set_ip 配网工具

命令行配网工具,为网卡配置 IPv4/IPv6 地址、默认网关、DNS,以及 IPv4 静态路由与路由策略。自动探测后端:`netplan` → `NetworkManager(nmcli)` → `systemd-networkd` → `ip` 兜底。

## 获取与编译

- 预编译二进制:[Releases](https://github.com/sophgo/sophon-tools/releases)
- 自行编译:需 Rust + [`cross`](https://github.com/cross-rs/cross),执行 `bash build.sh`(产出在 `target/`)。
- netplan 后端依赖 `/etc/netplan/01-netcfg.yaml` 存在且格式正确。

## 用法

**双模式**:只配 IP 时用旧语法(尾部可省,向后兼容);配 IP + 路由/策略/额外地址时强制 **4 元组**(每个组 4 个参数,空槽 `''`)。工具自动按"旧模式解析若有剩余 token 则切 4 元组"判定。

### 示例详解

由简到繁,逐个讲解。`''` 表示该槽留空(4 元组模式下作占位)。

**1. DHCP(自动获取)**
```bash
bm_set_ip eth0 dhcp
```
`dhcp` → IPv4 走 DHCP,无需地址/掩码/网关/DNS。等价 netplan `dhcp4: true`。

**2. 静态 IPv4(地址 + 网关 + DNS)**
```bash
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8
```
- `192.168.1.100` IPv4 地址
- `24` 前缀(等价 `255.255.255.0`)
- `192.168.1.1` 默认网关
- `8.8.8.8` DNS
→ eth0 = 192.168.1.100/24,默认路由 via 192.168.1.1。

DNS 支持逗号分隔多地址,各后端渲染为数组/列表(netplan `nameservers` 数组、systemd-networkd `DNS=8.8.8.8 114.114.114.114`、nmcli `ipv4.dns` 逗号串、ip 兜底逐行 `nameserver`):
```bash
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 "8.8.8.8,114.114.114.114"
```
校验规则:每项 trim 后校验;空项(连续/首尾逗号)、非法项、含 `/` 项直接报错;DNS 必须与地址族一致(IPv4 族只收 IPv4 DNS,IPv6 族只收 IPv6 DNS,不可混族——各后端按族隔离,混族会在 nmcli 等后端运行时失败)。

**3. 只设地址(无网关/DNS)**
```bash
bm_set_ip eth0 192.168.1.100 24
```
IP-only 模式尾部可省。仅设地址,不配默认路由。

**4. 静态 IPv6**
```bash
bm_set_ip eth0 2001:db8::1 64 fe80::1 2001:4860:4860::8888
```
`2001:db8::1` 含冒号 → 识别为 IPv6 族;`64` 前缀;`fe80::1` IPv6 网关;末尾 IPv6 DNS。

**5. IPv4 + IPv6 双栈**
```bash
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1
```
前 4 个 token 是 IPv4 族;接着 `2001:db8::1`(IPv6)触发第二地址族:地址/前缀/网关。

**6. IPv4 + 一条静态路由(策略路由入门)**
```bash
bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100
```
- family1 = `192.168.1.100 24 '' ''`(地址/掩码,gw/dns 空)
- 路由组 `192.168.2.0 24 192.168.1.1 100` → 到 `192.168.2.0/24` 经 `192.168.1.1`,入 table `100`
→ `ip route show table 100` 可见该路由。

**7. IPv4 + 多条静态路由(不同表)**
```bash
bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100 192.168.3.0 24 192.168.1.1 200
```
两条路由组:`192.168.2.0/24`→table 100,`192.168.3.0/24`→table 200。

**8. IPv4 + 路由 + 策略(完整源/目的分流)**
```bash
bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100 10.0.0.0 24 192.168.3.0 255.255.255.0
```
- 路由组:到 `192.168.2.0/24` 经 `192.168.1.1` 入 table 100
- 策略组 `10.0.0.0 24 192.168.3.0 255.255.255.0`:`from 10.0.0.0/24`、`to 192.168.3.0/24` → 查 table 100
- 策略是 4-token(省略 table),恰好 1 条路由 → 共享该路由的 table 100;若写成 5-token `... 255.255.255.0 100` 则显式指定 table
- 策略 `to_mask` 必须**点分**(`255.255.255.0`)以与路由 table 区分
→ 源 `10.0.0.0/24` 访问 `192.168.3.0/24` 时走 table 100 的路由,其余走 main。

**9. 多个 IPv4 地址**
```bash
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.1.101 24 '' ''
```
- family1:`192.168.1.100/24` + 网关 + DNS
- 额外地址组 `192.168.1.101 24 '' ''`:第 2 个地址(pos3=`''` 标识为额外地址,非路由)
→ eth0 同时拥有 192.168.1.100 与 192.168.1.101。

**10. DHCP + 静态路由**
```bash
bm_set_ip eth0 dhcp 192.168.2.0 24 192.168.1.1 100
```
`dhcp` 是单 token family1(无地址/掩码/网关/DNS 槽);其后直接接路由组。地址由 DHCP 获取,静态路由照常生效。

**11. 多个 IPv4 + 多条路由 + 1 个策略(综合)**
```bash
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.1.101 24 '' '' 192.168.2.0 24 192.168.1.1 100 192.168.3.0 24 192.168.1.1 200 10.0.0.0 24 192.168.4.0 255.255.255.0 200
```
- family1:`192.168.1.100/24` + 网关 + DNS
- 额外地址 `192.168.1.101 24 '' ''`:第 2 个 IPv4 地址
- 路由1 `192.168.2.0 24 192.168.1.1 100` → table 100
- 路由2 `192.168.3.0 24 192.168.1.1 200` → table 200
- 策略 `10.0.0.0 24 192.168.4.0 255.255.255.0 200`:`from 10.0.0.0/24`、`to 192.168.4.0/24` → 查 table 200(5-token 显式 table;此处有 2 条路由,4-token 省略 table 会报错)
→ eth0 有 2 个地址;源 `10.0.0.0/24` 访问 `192.168.4.0/24` 走 table 200 的路由。

**12. 多条路由策略(分流到不同表)**
```bash
bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100 192.168.3.0 24 192.168.1.1 200 10.0.0.0 24 192.168.4.0 255.255.255.0 100 10.1.0.0 24 192.168.5.0 255.255.255.0 200
```
- 路由1 → table 100,路由2 → table 200
- 策略1 `10.0.0.0 24 192.168.4.0 255.255.255.0 100` → 源 `10.0.0.0/24` 访问 `192.168.4.0/24` 走 table 100
- 策略2 `10.1.0.0 24 192.168.5.0 255.255.255.0 200` → 源 `10.1.0.0/24` 访问 `192.168.5.0/24` 走 table 200
→ 每条策略自带 table(5-token),多条策略各自分流;省略 table 仅在恰好 1 条路由时允许(共享该路由 table)。

### IP-only(旧语法,兼容)

```bash
# DHCP
bm_set_ip eth0 dhcp
# 静态 IPv4  地址 掩码 [网关] [DNS]
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8
bm_set_ip eth0 192.168.1.100 24                 # 只设地址
# 静态 IPv6
bm_set_ip eth0 2001:db8::1 64 fe80::1 2001:4860:4860::8888
# IPv4 + IPv6
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1
# DHCP IPv4 + IPv6
bm_set_ip eth0 dhcp '' '' '' dhcp
```

### IP + 其它(4 元组,family1 须满 4 参数,空槽 `''`)

组顺序:`<网卡> [family1] [额外地址]* [路由]* [策略]* [family2]`。每个组 4 token;`dhcp` 单 token;策略可 4 或 5 token(第 5 为 table)。

```bash
# 2 个 IPv4 地址(第 2 个 gw/dns 空)+ 1 条路由
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8  192.168.1.101 24 '' ''  192.168.2.0 24 192.168.1.1 100
# 2 条路由(不同表)
bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  192.168.3.0 24 192.168.1.1 200
# 1 路由 + 1 策略(策略 to_mask 必须点分;4-token 共享该路由 table)
bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0
# 2 路由 + 2 策略(策略 5-token 各带 table)
bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  192.168.3.0 24 192.168.1.1 200  10.0.0.0 24 192.168.4.0 255.255.255.0 100  10.1.0.0 24 192.168.5.0 255.255.255.0 200
# 多地址 + 路由 + IPv6
bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8  192.168.1.101 24 '' ''  192.168.2.0 24 192.168.1.1 100  2001:db8::1 64 fe80::1 ''
```

### 4 元组组类型(按 pos3/pos4 形状识别)

| 组 | 4 元组 | pos3 | pos4 |
|---|---|---|---|
| 额外地址 | `addr mask '' ''` | `''` | `''` |
| 路由 | `to to_mask via table` | IPv4 | 数字/名字/`''` |
| 策略 | `from from_mask to to_mask [table]` | IPv4 | 点分掩码 |

- family1(首组)恒地址族:pos1=dhcp→dhcp 族,含`:`→IPv6 族,否则 IPv4。
- family2:组首含`:`或 dhcp(且 family1 为 v4)→IPv6 族(4 token,或 dhcp 单 token)。
- **策略 `to_mask` 强制点分**(消歧);前缀数字会被当路由 table。
- 策略第 5 token(table)可选:省略时仅在**恰好 1 条路由**时共享该路由的 table(该路由须有 table);否则须显式给出第 5 token。多条策略各自独立。
- family1 不足 4 参数又有路由/策略 → 报错(补 `''`)。

> 路由表为数字 id(如 `100`),四后端直接识别;如需命名,手工 `echo "100 lan_table" | sudo tee -a /etc/iproute2/rt_tables`。netplan 后端只接受数字表 id(表名须已在 rt_tables 注册);nmcli 后端对未知名自动分配 id 并写回。路由与策略仅 IPv4。

## 为啥需要路由表(策略路由原理)

普通 Linux 默认只有一张 **main** 表,所有路由堆在一起,做不到按"源/目的"分流,也容不下两条默认网关(会报 `Conflicting default route`)。策略路由用**多张表**解决:

- **路由表(table)**:独立容器,可放自己的路由和默认网关,与 main 互不干扰——多套默认网关得以并存。
- **静态路由 `[to][via][table]`**:把"到 `to` 经 `via`"这条路由写进**指定表**;不指定 `table` 则进 main。
- **路由策略 `[from][to][table]`**:规则——**源/目的匹配的包,去查哪张表**(`from`=按源,`to`=按目的)。

转发流程:内核按 `ip rule` 链匹配 → 命中规则 → 查对应表 → 在该表内查路由 → 决定出口。例:`from 10.0.0.0/24 lookup 100` 让源 10.0.0.0/24 的流量走 table 100 里的路由,其余仍走 main。

**一句话**:路由表承载多套路由,策略决定哪个包用哪套——二者配合才能按源/目的选出口,这是单张 main 表做不到的。所以工具里静态路由与策略都需配合 `table`。

## 预览(不应用)

`--dry-run` / `-n`:只解析并打印分析出的配置(`key=value`),不修改网络、不需要 root。用于核对参数或自动化测试。

```bash
bm_set_ip --dry-run eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.2.0 24 192.168.1.1 100
```

## 测试

```bash
cargo test                       # 118 项:92 项解析用例 + 26 项后端单元测试(stateful fake）
bash tests/parse_cases.sh        # 解析用例包装(等价 cargo test --test parse_cases)
bash tests/backend_contract.sh   # 54 项后端行为契约(真实二进制 + 有状态 fake 命令)
```

`tests/backend_contract.sh` 用有状态的 fake `nmcli`/`ip`/`resolvconf`/`resolvectl`/`netplan`/`networkctl`
(全部放在临时 PATH 前缀,被测程序只能看到 fake)驱动**真实可执行文件**,断言退出码、成功文案与调用序列;
默认在 `unshare -rmn` 中用 tmpfs 覆盖 `/etc` 后运行,不在宿主产生任何网络或文件副作用。

## 输入校验

解析层对以下非法输入**直接报错**(不生成非法网络配置):

- 前缀越界:IPv4 前缀 `>32`、IPv6 前缀 `>128`(如 `33`、`200`)。
- 非连续/非法点分掩码:`255.255.0.255`(非连续)、`256.0.0.0`(段越界)、`255.255.255`(段数不足)。
- 畸形 IP 地址:`999.1.1.1`、`1.1.1`(段不足)、`1.1.1.1/24`(含 `/`)、`2001:db8::g`(非法 v6)。
- 空网卡名:`bm_set_ip "" 1.1.1.1 24`。
- DHCP 族加静态额外地址:`bm_set_ip eth0 dhcp 1.1.1.2 24 '' ''`(后端会静默丢弃,故解析层拒绝)。
- 路由表名允许字母/数字/下划线/连字符(如 `lan_table`、`lan-table`);含点号会被当点分掩码误判,报错。

合法边界:前缀 `0`、全 `0` 掩码 `0.0.0.0`(→ `/0`)、全 `1` 掩码 `255.255.255.255`(→ `/32`)均接受。路由 `via` 可空(直连路由进指定表):`to to_mask '' table`。

## 后端

自动探测:`netplan`(需 `/etc/netplan/*.yaml` 存在)→ `NetworkManager(nmcli)` → `systemd-networkd` → `ip` 兜底。

**错误契约**:任何关键命令失败(nmcli add/up、ip flush/link/地址/显式请求的路由与规则、DNS 写入、netplan apply、networkctl reconfigure、备份失败)都以**非零退出**结束,且不打印成功文案。只有明确标注理由的情形保留为非致命告警(见下)。

- **netplan**:写 `addresses`/`routes`/`routing-policy` 到 yaml 后 `netplan apply`。默认网关用 `routes: to:0.0.0.0/0`(避开 deprecated `gateway4` 的冲突检测);写入前清除设备上旧的 `gateway4`/`gateway6` 键,避免与新 routes 默认路由冲突。apply 退出码 0 但 stderr 含 `Error`/`Conflicting` 时报失败。路由/策略的表名须为数字或已在 `/etc/iproute2/rt_tables` 注册(netplan 的 `table` 只接受数字),否则报错。只更新已存在的 netplan 文件,不会凭空新建 yaml。
- **nmcli**:`ipv4.routes` 用 `table=N` 语法;`ipv4.routing-rules` 逗号分隔、固定 priority、table 仅数字 id。未指定的 family 显式 `method=disabled`(避免默认 auto 意外启用 DHCP)。新旧 profile **按 UUID 区分**:先 `con add` 新连接 → 用新建的 UUID `con up` → 激活成功后才按 UUID 删除本工具的旧连接(名称为 `static-<dev>` **且**接口名确为本设备);add/up 失败保留旧配置并恢复旧连接激活状态,up 失败还会撤销本次新建的半成品。绑定在其它接口的同名连接、非本工具创建的连接一律不动。
- **systemd-networkd**:写 `/etc/systemd/network/10-<dev>.network`,`networkctl reload` + `reconfigure <dev>`(仅重载该设备,不波及其他网口)。`networkctl` 不可用时回退 `systemctl restart systemd-networkd`。
- **ip**(兜底):先做管理口保护(目标接口承载默认路由且未加 `--force` 时**直接拒绝,不做任何写入,含 DNS**),再逐条 `ip addr/route/rule add`。flush/link 失败立即中止;地址/路由/规则失败会跑完全部命令后统一非零退出,并报出每一条失败命令。地址配置自身有失败时不改动 DNS。DHCP 不支持,报错退出。支持 IPv6 默认路由(`-6 route add default`)与 DNS(优先 `resolvconf`/`resolvectl`,否则直写 `/etc/resolv.conf`)。

### 配置快照与回滚

三个写文件的后端(netplan / networkd / DNS 文件回退)统一使用**本次运行的内存快照**:

- 写入前先明确原文件**存在**(读到内容)还是**不存在**;读不到原文件即拒绝修改。
- 备份失败(`<file>.bm_set_ip.bak` 写不进去)则**拒绝修改**,不会出现“备份失败仍覆盖原配置”。
- 应用失败时**只按本次快照回滚**:原文件存在则写回原文,原文件不存在则删除本次新建的文件。**绝不读取历史遗留的 `.bak`**,不会恢复陈旧内容。
- `.bak` 仅供人工恢复参考,不参与自动回滚。

### 有意保留的非致命告警

| 情形 | 为何不致命 |
| --- | --- |
| nmcli 新连接已激活后,删除旧 profile 失败 | 新配置已生效;残留旧 profile 只影响后续同名解析,已提示 `nmcli con delete <uuid>` 手工清理 |
| nmcli 新连接已激活后,rt_tables 表名映射回写失败 | 连接已按数字 id 生效;回写只影响后续复用同一表名 |
| `networkctl reload` 失败 | 紧接的 `reconfigure` 会重新读取配置文件,reload 失败不影响最终生效 |
| 系统上存在其它设备的默认路由 | 纯提示,配置本身仍完整写入并生效 |

> 切换后端时注意:networkd 后端写的 `/etc/systemd/network/10-<dev>.network` 不会被 `netplan apply` 清除,切回 netplan 前应 `rm` 该文件,否则与 netplan 生成的配置竞争。

## 2026-07-13 review 修复

- **策略 from+to 单条语义**:策略同时指定源(`from`)和目的(`to`)时,生成单条规则(源且目的同时匹配),四后端一致:netplan `routing-policy` 项含两者;networkd `[RoutingPolicyRule]` 段含 From=/To=;nmcli 单条带 `from X to Y`;ip 单条 `from X to Y`。
- **--force 标志**:仅长选项。ip 兜底后端默认保护当前默认路由所在设备(通常管理口,避免 SSH 断连);`--force` 覆盖该保护。
- **环境变量 BM_SET_IP_NETPLAN_FILE**:netplan 后端优先使用此变量指定配置文件;未设则在 `/etc/netplan/` 取字典序最后一个 `*.yaml`;都无则回退 `01-netcfg.yaml` 并告警。
- **netplan 合并与备份**:设备已存在时更新本工具管理的键(dhcp4/dhcp6/addresses/routes/routing-policy/nameservers/optional),保留其余(mtu/match/set-name 等);写前自动备份为 `<file>.bm_set_ip.bak`,apply 失败则按本次快照回滚(不读遗留 `.bak`)。
- **nmcli 表名解析**:路由与策略的 table 参数统一解析为数字:直接数字用之;`/etc/iproute2/rt_tables` 已有的名字查表;未知名自动从 100 起分配空闲 id 并写回 rt_tables。

## 2026-11-15 review 修复(后端配置丢失 / 失败退出 / DNS / 回滚)

- **NM 不再删掉自己刚建的连接**:原实现 `con add static-<dev>` 后 `con delete static-<dev>` 会按同名删掉新建连接,首次配置即失效。现改为前后两次 `nmcli -t -f UUID,NAME,TYPE con show` 求 UUID 差集定位新连接,`con up <新UUID>` 成功后才按 UUID 清理本工具旧连接;add/up 失败保留(或恢复)旧配置,up 失败还撤销半成品。按名称模糊删除、删除其它接口/非托管连接的行为一并去除。
- **失败不再返回成功**:`nmcli con add`/`con up` 失败、`ip` 关键命令失败(flush/link/全部地址失败/显式请求的 route 与 rule)、DNS 写入失败、备份失败、`netplan apply`/`networkctl reconfigure` 失败,一律非零退出且不打印成功文案(原来这些路径 `main` 仍返回 0,上层 bmssm 因此误报配置成功)。
- **DNS 真正生效且顺序正确**:`resolvconf -a <真实设备>` 写入完整 stdin 并检查退出码(原来既不写 stdin 也不 wait);`resolvectl dns <真实设备> <全部DNS>` 一次传完(原来用不存在的 `bm_set_ip` 当接口且逐条覆盖);文件回退传播写失败。管理口保护移到所有写入之前,拒绝时 DNS 与全部修改命令调用次数为 0。
- **回滚不再用陈旧备份**:写前在内存中区分“原文件存在(捕获内容)/不存在”,备份失败即拒绝修改;失败时只按本次快照回滚——原本不存在的文件会被删除,而不是恢复出一个假的原文件;历史遗留 `.bak` 不参与自动回滚。
- **可测试性**:外部命令与文件系统访问收敛到 `Env` trait(生产实现 `OsEnv`),使 `cargo test` 可用 stateful fake 覆盖上述四类问题;`tests/backend_contract.sh` 用真实二进制 + fake 命令做端到端契约验证。
