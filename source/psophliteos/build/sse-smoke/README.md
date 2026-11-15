# sophliteos SSO/SSE 并发冒烟（MYS-2885）

会话/连接类改动发布前的回归要求：至少 4 个独立客户端/进程高频并发 register + SSE 建连，
持续 ≥ 30 秒，记录请求数、最大连接数、旧流关闭情况、结束后零残留，并检查数据竞争。

## 怎么跑

```bash
cd source/psophliteos

# 默认：4 个独立客户端进程 / 35s / 每会话 8 条并发连接（模拟多标签页）
bash build/sse-smoke.sh

# 显式指定 时长 客户端数 每客户端并发连接数
bash build/sse-smoke.sh 35 4 8
```

脚本退出码 0 表示全部通过；非 0 时会在 stderr 指出失败原因（残留连接、data race、
panic、网络指纹变化、结构断言不满足等）。

## 它做了什么

1. 用 `go build -race` 构建 `build/sse-smoke`——它链接**真实的** `middleware.SSOEvents /
   SSORegister / SSOLogout`，因此在带 `-race` 的构建下数据竞争会直接报出来。
2. 起一个隔离测试服务：只监听 `127.0.0.1` 随机端口，不读 `/data` 配置、不连 bmssm、
   不接触设备上任何现有会话。
3. 拉起 N 个**独立 OS 进程**客户端，每个进程：
   - 反复注册会话（多数轮次换新 token 模拟重新登录/多端登录，每 5 轮复用同一 token
     覆盖幂等保护）；
   - 并发建立多条 SSE 长连接并持有约 1.5s（模拟多标签页）；
   - 偶尔主动 logout。
   每个客户端独占一段 `127.0.0.x` 源地址（回环整段可用，仅本机生效），
   既模拟不同来源，也把"同 IP 每分钟 10 次建连"这条独立限流的干扰降到最低。
4. 运行期间每秒采样 `/stats`（真实连接数/峰值/各类拒绝计数）。
5. 收尾：注册一个清理会话把残留长连接顶掉、注销，轮询确认 `activeConnections` 归零。
6. 检查：服务端/客户端日志无 `DATA RACE`、无 panic；宿主 `ip addr`/`ip route` 指纹前后一致。

## 观测口径

- **连接数**由 handler 包裹层统计（`SSOEvents` 阻塞到流结束），统计的是真实 HTTP 连接，
  不依赖内部 map 实现。
- 平台是单会话（同一时刻只有一个活跃 token），所以峰值连接的**上限来自"单 token 8"**；
  "全局 32"是旧连接未回收时的兜底，它在单元测试里通过把上限调低到 3 精确验证
  （`middleware/sso_events_test.go: TestSSOEventsGlobalCapCountsConnections`）。
- 冒烟判定要求：峰值 ≥ 每会话并发数（证明连接真的建立起来了）、峰值 ≤ 32、
  至少投递过一次终止事件、结束时零残留。

## 结果样例（2026-11-15，13.24 x86_64 宿主）

```
client-1 src=127.0.0.2   注册=2099 建连尝试=60 成功=43 拒绝=17 离线事件=43 服务端关闭=43
client-2 src=127.0.0.10  注册=1431 建连尝试=60 成功=46 拒绝=14 离线事件=46 服务端关闭=46
client-3 src=127.0.0.18  注册=1089 建连尝试=60 成功=59 拒绝=1  离线事件=59 服务端关闭=59
client-4 src=127.0.0.26  注册=2863 建连尝试=60 成功=53 拒绝=7  离线事件=53 服务端关闭=53
服务端: requests=10217 sseAccepted=201 activeConnections=0 maxConnections=10 offlineEventsSent=201
PASS（4 客户端 / 32s / 峰值 10 / 零残留 / 无 race）
```

## 相关文件

- `build/sse-smoke/main.go` — 冒烟工具（server / client 两种模式）
- `build/sse-smoke.sh` — 驱动脚本（构建、编排、采样、判定）
- `build/verify-deb-isolated.sh` — 在测试机上隔离验证 deb 产物（旧升级接口拒绝、SSE 回收、
  服务目录不被改动；不安装、不重启、不写真实 `/data`）

## 隔离验收脚本的防护（`build/verify-deb-isolated.sh`）

首次验收时该脚本有一个**真实事故**：`unshare -m` 的包装层没有生效，bind mount 落到了
宿主的真实挂载表上（覆盖了 `/opt/sophon/sophliteos/config`、`/var/log/sophliteos`、
`/var/lib/sophliteos/db`、`/var/lib/bmssm`、`/data`），事后才发现并 umount 恢复。
**"出错后再卸载恢复"不是隔离**，因此脚本已改为事前隔离 + 逐项核验：

1. **工作目录**：`mktemp -d /tmp/mys2885-verify-XXXXXXXX` 创建专属目录；退出时只删
   这一个带固定前缀的目录（前缀不匹配则拒绝清理）。不再对用户可控的 `WORKDIR` 直接 `rm -rf`。
2. **宿主路径只读**：所有 bind 目标（含 `/var/lib/sophliteos`、`/var/lib/bmssm`）必须
   已存在且是目录，否则**直接 fail-closed 退出**；namespace 内**绝不在宿主路径上
   `mkdir`**（改为 bind `/var/lib/sophliteos` 整目录，其下 db 也落在临时目录里）。
3. **dependent 工具 fail-closed**：`dpkg-deb/unshare/mount/findmnt/ip/ss/curl/python3/
   sha256sum/md5sum` 与 `pyjwt` 逐个检查，root 也检查。
4. **私有 mount + network namespace**：`unshare -m -n --propagation private`。
   network namespace 自带独立回环，因此不与设备上 `:8080`/`:18080` 的任何既有服务冲突。
5. **动态端口 + PID 归属核验**：端口在 namespace 内动态选取，启动后用 `ss -ltnpH`
   核验「该端口的监听者 PID == 本次启动的 PID」，杜绝"新进程没起来、curl 验到旧进程"。
6. **功能性隔离自检**：每个 bind 完成后，往挂载后的目标路径写一个随机哨兵文件，
   确认它出现在本次临时目录里 —— 不再比较 `findmnt` 源字符串（overlay/tmpfs 表示法
   因机器而异，容易误判）。
7. **事后核验**：比对运行前后宿主的 `ip addr`/`ip route` 指纹与 `/proc/self/mountinfo`
   挂载表，任一不同即 FAIL，并检查挂载表中不得出现本脚本的临时挂载。

