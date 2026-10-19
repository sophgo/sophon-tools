# 功能验证记录

本文记录 v2.1.0 各功能的验证方式与实测结果。**每条都能被第三方复现**：
命令、输入、期望输出、实际输出。

- 验证环境：13.24 构建机（x86_64）+ SE7 真机 172.26.166.185（BM1684X, aarch64）
- 构建产物：`qt_batch_deployment_V2.1.0_linux_amd64`
- 验证日期：2026-10-19

## 0. 自动化测试

```bash
cd src
go test ./...          # 52 项通过
go test -race ./...    # 并发契约无告警
go vet ./...           # 干净
```

两层覆盖：

| 层 | 文件 | 覆盖内容 |
| --- | --- | --- |
| 单元 | `config_test.go` `state_test.go` `ssh_exec_test.go` `preset_test.go` | JSON 双向兼容、校验语义、关键字判定、并发上限、目录/路径拼接、旧版三个崩溃场景回归 |
| 协议 | `testsrv_test.go` `testsrv_sftp_test.go` `e2e_test.go` | 真实 SSH/SFTP 会话：命令下发、上传+MD5、下载+MD5、多操作短路、传输超时、取消 |

协议层用仓库自带的最小 SSH/SFTP 服务端，**不需要任何外部设备**即可跑；
真机验证见下文。

## 1. 命令行模式（SE7 真机）

### 1.1 命令下发 + 成功关键字

输入 `cfg_cmd.json`：

```json
{"remoteInf":[{"IP":"172.26.166.185","Port":22,"Username":"linaro","Password":"linaro"}],
 "operationInf":[{"name":"命令-成功关键字","type":0,"commandStr":"echo SE7_OK",
                  "checkSuccessStr":"SE7_OK","checkErrorStr":"","checkFile":0}]}
```

```bash
./qt_batch_deployment_V2.1.0_linux_amd64 /tmp/qbdtest /tmp/qbdtest/cfg_cmd.json 4
```

实际输出（退出码 0）：

```
[172.26.166.185:22] 连接中
[172.26.166.185:22] 执行: 命令-成功关键字
[172.26.166.185:22] SE7_OK
设备[1] 172.26.166.185:22  执行状态: 成功
共 1 台，成功 1，失败 0
```

### 1.2 失败关键字（旧版此功能从未生效）

```json
{"name":"失败关键字","type":0,"commandStr":"echo 'FATAL_ERROR happened'",
 "checkErrorStr":"FATAL_ERROR"}
```

实际输出（退出码 1）：

```
[172.26.166.185:22] FATAL_ERROR happened
[172.26.166.185:22] 失败关键字: 命中失败关键字 "FATAL_ERROR"
设备[1] 172.26.166.185:22  执行状态: 失败
```

### 1.3 上传 1MB + MD5 双向一致

```json
{"name":"上传","type":1,"transferFileSourcePath":"payload.bin",
 "transferFileDestinationPath":"/tmp/qbd_upload_payload.bin","checkFile":0}
```

```
[172.26.166.185:22] 已上传 /tmp/qbdtest/payload.bin -> /tmp/qbd_upload_payload.bin (1048576 字节)
[172.26.166.185:22] 校验通过
```

远端独立复核：

```
$ ssh linaro@172.26.166.185 md5sum /tmp/qbd_upload_payload.bin
b9e59df2331dfeccbf33a59cbed1d75b  /tmp/qbd_upload_payload.bin
$ md5sum payload.bin
b9e59df2331dfeccbf33a59cbed1d75b  payload.bin
```

### 1.4 下载 + MD5 双向一致

```json
{"name":"下载","type":2,"transferFileSourcePath":"/tmp/qbd_upload_payload.bin",
 "transferFileDestinationPath":"downloaded","checkFile":0}
```

```
[172.26.166.185:22] 已下载 /tmp/qbd_upload_payload.bin -> downloaded/172.26.166.185_22_2026_10_18_23_23_02_qbd_upload_payload.bin (1048576 字节)
[172.26.166.185:22] 校验通过
```

本地复核 MD5 = `b9e59df2331dfeccbf33a59cbed1d75b`，与源文件一致。
文件名符合旧版规则 `<IP>_<端口>_<时间戳>_<原名>`，多设备不会互相覆盖。

### 1.5 不完整操作：警告 + 跳过，不静默

```bash
./qt_batch_deployment_V2.1.0_linux_amd64 /tmp/qbdtest /tmp/qbdtest/cfg_skip.json 4
```

```
警告: 2 条操作配置不完整，将被跳过:
  第 2 条: 操作 "缺命令":命令为空
  第 3 条: 操作 "缺路径":源路径为空
[172.26.166.185:22] 执行: 好操作
[172.26.166.185:22] fine
共 1 台，成功 1，失败 0     （退出码 0）
```

### 1.6 并发 + 不可达设备快速失败

4 台真机 + 4 台不可达（`10.255.255.0/24`），并行上限 8：

```
共 8 台，成功 4，失败 4
```

不可达设备在拨号超时（15s）内返回明确错误，不挂死；成功与失败隔离正确。

## 2. 参数与退出码

| 场景 | 期望 | 实测 |
| --- | --- | --- |
| 无参数 | 启动图形界面 | 是 |
| 根目录不存在 | 退出码 2 + 错误信息 | 是 |
| 配置 JSON 非法 | 退出码 2 + 错误信息 | 是 |
| 全部设备成功 | 退出码 0 | 是 |
| 任一设备失败 | 退出码 1 | 是 |

（旧版参数错误时 `exit(0)`，脚本无法判断失败；本版已修正。）

## 3. 图形界面（Xvfb 实拍）

截图见 PR 附件。逐项核对：

| 功能 | 验证方式 | 结果 |
| --- | --- | --- |
| 启动与渲染 | Xvfb 启动后截图 | 中文用内嵌思源黑体正常显示，无方块 |
| 执行期间禁用配置区 | 点「执行配置」后截图 | 根目录/预设/载入/保存/并行上限/设备与操作工具栏/操作表单全部置灰；主按钮变为「执行中…」并置灰，「中止」启用，顶栏出现「执行中」标记 |
| 状态语义色 | 执行中截图 | 状态列为色块：蓝色「连接中 / 执行: xxx」；成功后绿色、失败红色、等待中橙色；概览统计与比例条同步 |
| 中止执行 | 点「中止」→ 确认 | 弹出中文确认框；确认后立即结束，状态栏显示「执行已中止:成功 0，失败/未完成 1」，控件恢复 |
| 未选中即删除设备 | 不选中直接点「删除」 | 弹出「请先在表格中选中一台设备」，进程存活 |
| 未选中即删除操作 | 不选中直接点操作序列的「删除」 | 弹出「请先在操作表中选中一行」，进程存活 |
| 删到空表 | 删除唯一设备后再点删除 | 同上提示，无 SIGSEGV |
| 完整度提示 | 编辑操作名称/命令 | 实时显示绿色徽标「配置完整，可以执行」或橙色徽标「不完整，执行时将跳过 - 原因」 |
| 中文对话框 | 触发确认/提示框 | 按钮为「确认 / 取消 / 知道了」 |

## 4. 已知限制

- Linux 产物是**单个可执行文件、免安装**，但依赖系统图形栈（X11/Wayland/OpenGL/
  glibc）；不是纯静态。已与需求方确认接受，`release.sh` 同时产出 `.deps.txt`。
- Windows 产物为真正的单二进制，仅依赖系统 DLL；交叉编译产物未在 Windows 实机
  上做过 GUI 交互验证（构建与依赖检查已完成）。

## 5. Web 模式（无图形栈服务器）

### 5.1 headless 产物形态

```bash
CGO_ENABLED=0 go build -tags headless -trimpath -ldflags "-s -w" -o qbd_headless .
file qbd_headless     # statically linked
ldd  qbd_headless     # not a dynamic executable
```

对比：桌面版 `ldd` 里有 `libX11`/`libGL`/`libwayland-client` 等 7 个图形库。
这就是为什么无图形栈机器必须用 headless 产物——桌面版在那里连加载都过不去。

桌面版也无法交叉编译到 arm64（宿主没有 aarch64 图形工具链，`runtime/cgo` 直接报
`no such instruction`），headless 版可以：

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -tags headless ...
```

### 5.2 SE7 真机（aarch64，无图形栈）

SE7 上 `DISPLAY` 与 `WAYLAND_DISPLAY` 均为空，属典型无图形栈服务器：

```
$ ssh linaro@172.26.166.185 'echo "DISPLAY=[$DISPLAY] WAYLAND=[$WAYLAND_DISPLAY]"'
DISPLAY=[] WAYLAND=[]
$ /tmp/qbd_headless_arm64 --web --listen 127.0.0.1:8090
批量部署工具 Web UI 已启动: http://127.0.0.1:8090
提示: 仅监听本机。配置含明文 SSH 密码，对外提供请显式 --listen 0.0.0.0:端口 并自加访问控制。
```

经 Web API 下发命令并按成功关键字判定：

```
$ curl -X POST http://127.0.0.1:8090/api/run
$ curl http://127.0.0.1:8090/api/state | ... 执行状态: ['成功']
$ curl "http://127.0.0.1:8090/api/log?index=0"
aarch64
SE7_HEADLESS_OK
```

### 5.3 Web 界面（Chromium 实拍）

截图见 PR 附件。逐项核对：

| 功能 | 验证方式 | 结果 |
| --- | --- | --- |
| 界面渲染 | Chromium 1500x980 截图 | 布局与桌面版一致，中文正常 |
| 设备表 | 导入 3 台设备 | IPv4/端口/用户名/密码掩码/状态 五列齐全 |
| 操作表 | 导入 3 条操作（含 1 条不完整） | 不完整项显示「⚠ …（不完整）」且内容列提示不会执行 |
| 三段式配置 | 选中「上传文件」操作 | 自动切到上传页，字段与校验方式下拉回显正确 |
| 完整度实时提示 | 选中完整项 | 显示「该项当前完整度: 完整 ✓」（绿色） |
| 执行与实时状态 | 点「执行配置」 | 状态列显示蓝色「执行: 慢命令」，逐设备实时更新 |
| 执行期锁定 | 执行中观察 | 预设/根目录/并行上限/设备与操作按钮/表单全部置灰 |
| 中止按钮 | 执行中 | 「执行配置」置灰、「中止执行」变红可点 |
| 完成后解锁 | 等 done 事件 | 控件全部恢复，状态栏「执行结束: 成功 1，失败 0」 |
| 事件流 | SSE | 先连流后执行也能收到 start + 11 条 device + done，3 台设备事件齐全 |
| 浏览器控制台 | 全程监听 | 无 error |

### 5.4 Web 端到端（含真实设备）

经 Web API 对 SE7 做完整三类操作，与命令行模式结果一致：

- 命令下发 + 成功关键字 → 成功，日志含 `SE7_OK`
- 上传 1MB → `校验通过`，远端独立 `md5sum` 与本地一致
- 下载 → `校验通过`，文件名符合 `IP_端口_时间戳_原名`

### 5.5 自查发现并修掉的问题

| 问题 | 处理 |
| --- | --- |
| 执行锁只覆盖 device/op，**config 与 presets 没锁**，且「载入」按钮不在前端的禁用清单里 | 五个改配置的入口全部加 409 守卫；前端禁用范围补上 `.bar button` |
| **根目录与并行上限只改前端 JS**，界面显示新值、执行时仍用旧值（根目录永远是启动 cwd、并行上限永远是 100） | 新增 `/api/settings`，落到服务端并校验目录存在；有回归用例 |
| `handleRun` 的 running 是 check-then-set，并发 POST 可能起两轮（cancel 只能杀一轮） | 改成原子抢占；用例用 30 轮 x 8 并发验证，退回旧写法必失败 |
| 无 Origin/Host 校验：恶意页面可跨站 POST，DNS rebinding 还能读走明文密码 | 加 `guardLocalOrigin`，Host/Origin 必须是本机名；响应加 `Cache-Control: no-store` |
| SSE 订阅被重置或 done 被丢弃后，前端永远停在「执行中」 | 前端处理 `snapshot`/`eos` 时重新拉状态；`start` 事件重绑 gen（多标签页也能跟上） |
| `syncOp` 把服务端回显写回表单，会吞掉请求在途时用户继续输入的字 | 只合并列表与状态，不回填表单；并把 update 串行化 |
| `--open` 是解析了但从未使用的死参数 | 删除 |

### 5.6 安全取向

配置文件含明文 SSH 密码，因此默认 `127.0.0.1:8080`；指定 `0.0.0.0` 时启动日志会
打印醒目警告。测试覆盖了默认必须为回环地址这条约束。

## 6. 2.2.0 UI 重做后的回归验证

本节记录在 2.2.0（桌面 GUI 与 Web UI 视觉重做）上重跑的验证。

### 6.1 自动化

```
go test ./...                      # 78 项通过
go test -tags headless ./...       # headless 构建同样通过
go test -race ./...                # 无告警
go vet ./... / gofmt -l .          # 干净
```

新增 2 项：

- `TestEmbeddedFontCoversPrintableASCII` —— 内嵌字体必须覆盖可打印 ASCII。
  2.0.1 的字体子集丢了 U+0020，导致桌面版**所有空格显示成全角空白**。
- `TestLogViewThrottleKeepsFinalContent` —— 日志高频更新要合并，但最终内容不能被吞掉
  （见 6.3）。

### 6.2 字体修复的独立核验

2.2.0 换掉了内嵌字体（955088 -> 955092 字节）。逐字形比对结果：

```
old 码点数: 3919  new 码点数: 3921
新增码点: ['0x20', '0xa0']      丢失码点: []
共有码点中字形名/宽度有变化的: 0
新增码点 U+0020 -> advanceWidth=224
```

对照系统里的 Noto Sans CJK SC，空格 advanceWidth 也是 **224**，与官方一致。
即：只补了空格与不换行空格，原有 3919 个码点一字未动。

### 6.3 日志渲染节流（本轮修）

改版后的日志区用 `widget.RichText` 按行着色，每行一个 `TextSegment`。
每次 `SetText` 都要重建全部段并触发布局，实测：

| 行数 | 重建一次耗时 |
| --- | --- |
| 100 | 0.87 ms |
| 500 | 4.1 ms |
| 2000 | 18.1 ms |

而传输过程中进度事件每 200ms 一次，且每次都会走到 `refreshDeviceLog`，
选中设备看日志时 UI 线程几乎被占满。改为**最多每 300ms 重建一次**，
高频更新只记原文，执行结束时 `Flush` 保证最终内容一定呈现。

修复后同样基准：2000 行 **37.6 ns/op，0 次分配**（被合并的调用不再重建）。

用例不只测耗时，而是直接数 `renderNow` 的调用次数——按间隔判断会在
测试跑得快时产生假阳性（这一点我在写用例时踩到过，已改）。

### 6.4 界面实测

| 项 | 桌面版 | Web 版 |
| --- | --- | --- |
| 渲染（含空格、中文） | ✓ | ✓ |
| 执行中：配置锁定 / 中止可点 / 顶栏「执行中」 | ✓ | ✓ |
| 状态标签语义色（成功绿 / 失败红 / 进行中蓝） | ✓ | ✓ |
| 概览统计与成功失败比例条 | ✓ | ✓ |
| 日志按行着色（失败行红） | ✓ | ✓ |
| 结束后解锁 + 结果提示 | ✓ | ✓（toast 分色） |
| 浏览器控制台报错 | — | 无 |

### 6.5 产物与真机

```
V2.2.0 linux_amd64            27M
V2.2.0 linux_amd64_headless   8.2M   静态链接，ldd: not a dynamic executable
V2.2.0 windows_amd64.exe      27M    仅依赖系统 DLL
```

- **SE7 真机（aarch64，无 DISPLAY/WAYLAND）**：headless arm64 产物直接运行，
  经 Web 完成命令下发 + 30 万字节上传，MD5 双向一致。
- **桌面版**：Xvfb 下跑完整执行（1 成功 / 1 失败），日志着色、统计、解锁均正常。
- **Windows**：Wine 下 GUI 与 Linux 渲染一致，空格正常；Web 模式 API 可用。

> 仍未覆盖：真 Windows 机器上的人工操作；100+ 台真机并发压测。
