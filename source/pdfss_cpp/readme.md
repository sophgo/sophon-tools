# dfss cpp 重构

## 使用方式

dfss 只通过 SFTP 传输文件，不再提供 HTTP 下载能力。连接、握手、认证与
`sftp_init` 由统一的 RAII 连接层（`src/sftp_conn.h`）负责，任一环节失败
都会让本次下载返回失败，不会再出现「所有服务器都不可达却报成功」的情况。

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

### 超时设置

`--connect_timeout=<秒>` 设置 SFTP 会话超时（TCP 连接、SSH 握手、认证与
后续收发共用这个上限），默认值来自 `dfss-config.json` 的 `connect_timeout`
（60 秒）。该值不再与 HTTP 相关。

### 配置文件

程序启动时读取可执行文件同目录的 `dfss-config.json`；文件缺失、JSON 语法
错误或字段缺失都不会导致崩溃：缺失字段取默认值，整份文件解析失败时打印
warn 并回退到内置服务器列表。

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
