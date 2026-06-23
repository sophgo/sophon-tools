# arm64 改为 musl 静态链接 设计文档

- 日期: 2026-06-23
- 范围: `psophliteos` 后端 arm64 (SoC) 产物
- 状态: 已批准设计,待实现

## 1. 背景与问题

`sophliteos` 二进制部署到 sophon SoC (aarch64) 设备时报错:

```
/bin/sophliteos: /lib/aarch64-linux-gnu/libc.so.6: version `GLIBC_2.x' not found
```

### 根因

项目后端为 Go,因依赖 `github.com/mattn/go-sqlite3` 必须 `CGO_ENABLED=1`。
当前 arm64 构建使用交叉编译器 `aarch64-linux-gnu-gcc`,**动态链接 glibc**:

```bash
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 CC=aarch64-linux-gnu-gcc go build -trimpath -ldflags '-s -w'
```

报错的真正来源不是构建宿主机的 glibc,而是 **交叉工具链 `aarch64-linux-gnu-gcc` 自带的 sysroot glibc 太新**。构建宿主 Ubuntu 越新,`gcc-aarch64-linux-gnu` 包带的 arm64 glibc sysroot 就越新(约 2.35~2.39),产物引用了 `GLIBC_2.32`~`GLIBC_2.35` 范围的符号版本;而目标 sophon 设备 glibc 仅 2.31,缺少这些符号,故报错。

glibc 只向前兼容(在旧 glibc 上编出来的能跑在新系统),不向后兼容,因此必须让产物的 glibc 符号版本 ≤ 目标设备的 glibc 版本。

### 目标设备

- glibc 版本: 2.31 或更新
- 架构: aarch64 (SoC)
- 本次修复范围: 仅 arm64 SoC;amd64 (PCIE) 构建保持不变

## 2. 方案选择

在「旧 glibc 构建容器」「musl 静态链接」「glibc 静态链接」三者中,选定 **musl 静态链接**。

理由:

- 产物完全静态,无任何 glibc 依赖,在任何 Linux 上均可运行,彻底告别 glibc 版本碎片化问题。
- 项目唯一 CGO 依赖为 `go-sqlite3`(纯 C),与 musl 兼容,迁移风险低。
- glibc 静态链接存在 NSS/DNS/dlopen 警告且 `go-sqlite3` 易踩坑,不采用。
- 旧 glibc 容器方案虽改动更小,但产物仍动态依赖 glibc,未来遇到更旧设备需再次降级;musl 一次性收益最大。

## 3. 现状确认(已核对代码)

- 全项目**无 `import "C"`** 直接使用,CGO 仅来自 `go-sqlite3`。
- `database/dbconnect.go` 通过 `sql.Register` 注册 `sqlite3.SQLiteDriver`,在 `ConnectHook` 中用 `c.RegisterFunc("regexp", regexp.MatchString, true)` 注册一个 Go 侧的 `regexp` 函数。
  - `RegisterFunc` 是 Go 回调,与 C 扩展加载(`load_extension`)无关,因此 `sqlite_omit_load_extension` 构建标签安全。
  - 项目未使用 sqlite 的 C 扩展加载。
- 未发现 `netgo`/`osusergo`/`sqlite_omit_load_extension` 现有构建标签。

## 4. 工具链来源

仅 arm64 新增;amd64 不受影响。

### 主选:musl.cc 预构建工具链 `aarch64-linux-musl-cross`

- 是 `aarch64-linux-gnu-gcc` 的直接对应物,`CC=aarch64-linux-musl-gcc`。
- Go + CGO + gcc 风格 musl 工具链最成熟、最可预测。
- 构建脚本中下载并**固定版本**,缓存到本地目录避免每次重复下载。
- 下载地址: `https://musl.cc/aarch64-linux-musl-cross.tgz`(在脚本中以变量形式给出,版本可固定)。

### 备选:`zig cc -target aarch64-linux-musl`

- 单二进制自带 musl,更现代,无需单独维护工具链下载。
- 与 Go 外部链接器偶有兼容性小坑,作为环境无法获取 musl.cc 工具链或团队偏好单工具链时的备选。
- 用法: `CC="zig cc -target aarch64-linux-musl" CXX="zig c++ -target aarch64-linux-musl"`。

设计默认走主选;脚本中保留切换为备选的说明。

## 5. 构建脚本改动

### 5.1 `scrip/package.sh`

只改 arm64 段(amd64 段原样保留)。

原:

```bash
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 CC=aarch64-linux-gnu-gcc go build -trimpath -ldflags '-s -w'  && tar -zcvf sophliteos-linux_arm64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh
```

改为:

```bash
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 \
  CC=aarch64-linux-musl-gcc \
  CXX=aarch64-linux-musl-g++ \
  go build -trimpath \
  -tags 'netgo osusergo sqlite_omit_load_extension' \
  -ldflags '-s -w -linkmode external -extldflags "-static"' \
  && tar -zcvf sophliteos-linux_arm64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh
```

### 5.2 工具链获取

在构建脚本中(或在 `build/build_2_release.sh` 调用 `package.sh` 前)增加:

- 检测 `aarch64-linux-musl-gcc` 是否已在 PATH;若否,从 musl.cc 下载固定版本工具链,解压到 `build/toolchain/aarch64-linux-musl-cross/` 并将其 `bin` 加入 PATH。
- 下载做缓存(存在则跳过),避免每次构建重下。
- 具体版本号与校验在实现阶段固定。

### 5.3 不变项

- 前端构建(node:16 docker)不变。
- amd64 Go 构建不变(仍动态链接 glibc)。
- `build/package-deb.sh`、`build/package-deb-sdk.sh`、DEBIAN/control、`install.sh`、`sophliteos.service` 全部不变。
- deb 包架构仍为 arm64,只是其中 `sophliteos` 二进制从动态变为静态。

## 6. 构建标签与 ldflags 说明

- `-linkmode external -extldflags "-static"`:强制走外部链接器(musl-gcc)并完全静态链接,产物无任何动态依赖。
- `netgo`:静态二进制下使用纯 Go DNS 解析器,避免依赖 musl 的 NSS(静态链接无法满足动态 NSS 模块)。
- `osusergo`:纯 Go 用户/组查询,同理避免 NSS 依赖。
- `sqlite_omit_load_extension`:移除 sqlite 的 `load_extension` 与 `dlopen` 依赖,静态二进制不应动态加载扩展。
- `-s -w`:沿用,去除符号表与 DWARF,缩减体积。

## 7. 验证步骤

构建流程中加入:

1. `file sophliteos` → 应输出 `statically linked`(对照 amd64 仍为动态可执行)。
2. `ldd sophliteos` → `not a dynamic executable` 或 `statically linked`。
3. (可选)若构建机有 `qemu-aarch64-static`,执行 `qemu-aarch64-static ./sophliteos --version` 本地冒烟;否则直接部署验证。
4. 部署到 sophon 设备后,确认以下最可能暴露 musl/静态化差异的功能正常:
   - sqlite 表读写(用户表、告警表、操作日志表自动建表)
   - `regexp` SQL 函数(登录/查询用到)
   - cron 定时清理任务(每日 0 点清理过期告警与操作日志)
   - 登录流程(用户表查询、admin 初始化、密码校验)
   - 外部 HTTP 调用(验证 `netgo` 纯 Go DNS 解析在设备网络环境下可用)

## 8. 风险与回滚

### 风险

- musl 与 glibc 在 locale/数值格式化等行为上存在细微差异,本项目未使用相关特性,风险低。
- `netgo` 改变 DNS 解析路径,需在目标设备网络环境下验证外部 HTTP 调用(代理、DNS 解析)。
- `go-sqlite3` 在 musl 下编译偶有警告,通常无碍;若出现编译错误,排查 `CGO_CFLAGS`/`CGO_LDFLAGS`。
- musl.cc 预构建工具链更新不频繁(稳定即可,Go 对 musl 1.2.x 支持良好);若不可用,切备选 zig cc。

### 回滚

改动集中在 `scrip/package.sh` 的 arm64 段与一处工具链获取步骤,`git revert` 即可恢复原 `aarch64-linux-gnu-gcc` 动态构建,无破坏性副作用。

## 9. 非目标 (YAGNI)

- 不改 amd64 (PCIE) 构建链路。
- 不替换前端构建方式。
- 不调整 deb 打包、安装脚本、systemd 服务。
- 不引入 CI 流水线改动(超出本次范围)。
