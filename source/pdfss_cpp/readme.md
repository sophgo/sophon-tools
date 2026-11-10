# dfss cpp 重构

## 使用方式

dfss 只通过 SFTP 传输文件，**HTTP 下载能力已全部移除**（旧的 HTTP 开关参数和
内嵌的 HTTP 客户端库都已删除，再传该参数会得到明确的未知选项报错并以非 0
退出）。连接、握手、认证与 `sftp_init` 由统一的 RAII 连接层（`src/sftp_conn.h`）
负责，任一环节失败都会让本次下载返回失败，不会再出现「所有服务器都不可达却
报成功」的情况。

### dfss url

使用 --url=open@sophgo.com:/文件路径 可以从open账户中下载指定文件

### dfss dflag

使用 --dflag=文件标记 可以从open账户中下载指定文件（被标记的文件）

### dfss user

使用 --user=用户名 可以自动登陆SDK账号和HDK账号

### dfss insall

dfss的install功能可以方便地下载和安装软件包。

使用方式：`python3 -m dfss --install [package]`

例如：`python3 -m dfss --install sail`

目前支持的package：

- sail

### dfss list / force_server

1. 使用 --list 可以列出当前已经配置的服务器链路
2. 使用 --force_server ID 可以强制dfss从某个ID的服务器链路下载文件

### dfss probe

使用 `--probe` 可以对配置里的 SDK 和 HDK 两个服务器列表执行一遍完整探测
（并行连通性检查 + 测速），并打印排名表格：

```bash
dfss --probe
```

输出示例（ID、host:port、状态或失败原因、latency、speed、排名）：

```
[SDK] server probe result
rank id    host:port                status   latency    speed        error
1    3     172.26.166.163:32022     ok       90ms       38.89 MiB/s
2    0     172.26.175.10:32022      ok       92ms       -
3    4     106.38.208.114:32022     ok       114ms      -
-    1     172.24.12.75:32022       fail     -          -            connect timed out
```

至少有一台可达时退出码为 0，否则非 0。`--force_server ID` 对 `--probe`
同样生效，只探测指定的那台。

### 断点续传

下载过程中会写两个文件：

- `<文件名>.dfss.part`：已下载的内容
- `<文件名>.dfss.meta`：续传元数据，`{"v":1,"remote_path":...,"size":...,"mtime":...}`

下次运行时，如果 part 和 meta 都存在、`remote_path`/`size`/`mtime` 三项与远端
完全一致、且 part 不大于远端文件，就从 part 末尾继续下载（日志打印
`resume from <已下载>/<总大小>`）；其它情况一律从头开始。因为各镜像上同名
文件的 size 和 mtime 一致，这个判断同时支持**换服务器续传**——一台服务器
下载中断后会自动切到下一台候选，并从同一个偏移继续。

- 使用 `--no_resume` 忽略已有的 part/meta，强制从 0 开始。
- 下载完成前不会改动同名的最终文件：先校验大小，然后删 meta，最后把 part
  rename 成最终文件名（已存在则覆盖）。
- 失败或 Ctrl-C 中断时保留 part 和 meta，供下次或下一台服务器续传。
- `.dfss_flags` 这类读进内存的下载不做续传。

### 超时设置

`--connect_timeout=<秒>` 设置下载/上传会话的 libssh2 超时（握手、认证与后续
收发共用这个上限），默认值来自 `dfss-config.json` 的 `connect_timeout`（60 秒）。
该值不再与 HTTP 相关。

`--probe_timeout=<秒>` 设置**单台服务器**探测（TCP 连接 + 握手 + 认证 +
`sftp_init`）的时间上限，默认来自 `dfss-config.json` 的 `probe_timeout`（5 秒）。
探测是并行进行的，因此一轮探测的耗时上限接近 `probe_timeout`；不可达的地址
不会再像以前那样把整轮探测拖到 `connect_timeout`。测速另有自己的上限
（每台 2 秒或 8 MiB，先到者为准；某台达到 4 MiB/s 就提前结束剩余测速）。

### 多通道探测与失败切换

一次下载按下面的顺序选路：

1. **并行连通性检查**：对每台候选服务器起一个线程，完成连接、握手、认证和
   `sftp_init`，每台受 `probe_timeout` 约束，记录 latency。成功的连接保持
   打开，供测速和下载复用（整个流程只握手一次）。
2. **测速**（仅 SDK 下载路径）：按 latency 升序逐台读取 `/.sophgo_speed`，
   上限 2 秒或 8 MiB。某一台达到 4 MiB/s 即停止测速。
3. **排名**：测到速度的按速度降序在前；测速失败或未测速的按 latency 升序在
   后。**测速失败不淘汰服务器**（以前测速读文件失败会让整台服务器被丢弃）。
4. **下载与切换**：按排名依次尝试，任何错误（连接失败、读取出错、长度不符）
   都切到下一台并从已下载偏移续传。候选列表用尽后重新完整探测一轮，最多
   3 轮。`--url`、`--dflag` 和上传都走这套候选列表（上传不需要续传，只切换）。

`--user` 的 HDK/SDK 登录路径只按 latency 排序，不测速。

### 配置文件

程序启动时读取可执行文件同目录的 `dfss-config.json`；文件缺失、JSON 语法
错误或字段缺失都不会导致崩溃：缺失字段取默认值，整份文件解析失败时打印
warn 并回退到内置服务器列表。

与超时相关的两个键：

| 键 | 默认值 | 含义 |
|---|---|---|
| `connect_timeout` | 60 | 下载/上传会话的 libssh2 超时（秒） |
| `probe_timeout` | 5 | 单台服务器探测（连接+握手+认证+sftp_init）的时间上限（秒） |

两个键都可以用同名命令行参数覆盖（`--connect_timeout` / `--probe_timeout`）。

### 主机名支持

`host` 字段既可以是 IPv4/IPv6 字面量，也可以是主机名。主机名字面量按
`/etc/hosts` → DNS 的顺序解析（静态二进制不依赖目标机的 glibc NSS 模块）。

## 编译方式

1. host模式默认主机X86_64
2. 交叉编译要求主机必须X86_64
3. linux_release.sh参数两个，第一个是架构名，第二个是lib(标记库一起编译)
4. 最终生成的程序在output下，同目录的json文件是服务配置文件，需要和程序安装在同一目录下

### 支持架构

* amd64 linux
* amd64 win
* i686 win
* arm64 linux
* loongarch64 linux
* riscv64 linux
* armbi linux
* sw_64 linux
* x86_64 darwin (macOS Intel)
* arm64 darwin (macOS Apple Silicon)

### 示例

``` bash
./linux_release.sh host lib;
./linux_release.sh aarch64 lib;
./linux_release.sh loongarch64 lib;
./linux_release.sh sw_64 lib;
./linux_release.sh armbi lib;
./linux_release.sh riscv64 lib;
./linux_release.sh mingw lib;
./linux_release.sh mingw64 lib;
./linux_release.sh darwin lib;
```

### macOS 说明

* macOS 目标需在 Mac 本机上编译（交叉编译 darwin 需要 macOS SDK，Linux 环境下无法构建），`./linux_release.sh darwin lib` 会按当前 Mac 芯片生成对应架构产物
* Intel Mac (x86_64) 生成 `dfss-cpp-darwin-x86_64`，Apple Silicon (arm64) 生成 `dfss-cpp-darwin-arm64`
* 编译依赖 Xcode Command Line Tools（提供 clang/链接器等），依赖库 zlib/mbedtls/libssh2 会由 `libs/build_libs.sh` 自动构建静态版本
* 最低支持 macOS 10.15（`std::filesystem` 与 `clock_gettime` 依赖，构建时已显式指定 `-mmacosx-version-min=10.15`）

### 默认编译器版本

* amd64 linux gcc9.4(ubuntu20) static
* amd64 win gcc9.3(ubuntu20) static
* i686 win gcc9.3(ubuntu20) static
* arm64 linux gcc9.4(ubuntu20) static
* loongarch64 linux gcc14.2(ubuntu20) static
* riscv64 linux gcc9.4(ubuntu20) static
* armbi linux gcc9.4(ubuntu20)
* sw_64 linux gcc8.3(ubuntu20) static
* darwin clang(macOS Xcode CLT) 静态库 zlib/mbedtls/libssh2 + 动态系统库

### 编译期版本信息

二进制启动首行会打印 `dfss cpp tool, version: (<git describe>-<sha>)[<commit 日期>]`。
这两个值由 `src/Makefile` 在编译期通过 `-DGIT_COMMIT_HASH/-DGIT_COMMIT_DATE` 嵌入，取值优先级：

1. 环境变量 `GIT_COMMIT_HASH` / `GIT_COMMIT_DATE` —— 构建脚本在宿主机算好传入（容器内通常没有 `.git`，这是容器构建唯一可靠的来源）
2. 仓库内 git（开发者直接在仓库工作树里 `make`）
3. `git_version` 文件 —— 兜底，值会带 `-nogit` 后缀，避免把退化构建伪装成正常构建

三者都拿不到时 `make` 直接报错退出，不再静默编出 `version: (-)[]`。
`bash release.sh` 与 `docker/scripts/build-dfss-pip.sh` 都会自动在宿主机计算并传入，无需手工设置。

### 发布方式

使用当前目录的CPP源码编译出各个架构的运行程序，然后使用dfss_pip目录下的python工程将工具发布到pip上
