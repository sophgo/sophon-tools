# sophon-tools-build —— sophon-tools 统一编译镜像（M5 单镜像合并）

`docker/` 目录是 sophon-tools 各子项目的统一构建镜像交付物。镜像预装全部子项目所需工具链，
子项目构建只需基于此镜像，不再依赖构建机预装环境。

**M5 起为单镜像方案**：三个镜像（`sophon-tools-build:m2` ubuntu:22.04 主镜像、
`sophon-tools-build-pqt` ubuntu:20.04 pqt 专用、`cross_build_sophon_u20:v1` ubuntu:20.04 pSophUI 专用）
合并为**一个 ubuntu:20.04 基座镜像** `sophon-tools-build:unified`，全部 16 个子项目在单镜像内构建，
不再按子项目切换镜像。

**镜像体积**：完整镜像（内置 dfss sw_64/loongarch64、Qt mingw 静态库、pSophUI aarch64 Qt 库）
约 **8.9GB**（v1.1.0，`docker images` 显示 ~8.88GB）。体积增大是单镜像方案的预期取舍
——换取构建期零镜像切换、一键全量。v1.1.0 起去掉 Linaro GCC 6.3（改用系统 apt aarch64
工具链），较 v1.0.0（~10.1GB）省约 1.2GB。

**镜像版本**：镜像 tag 由 `docker/versions.env` 的 `IMAGE_TAG` 控制（默认 `unified-v1.1.0`），
`release.sh` / `build-all.sh` 默认使用 `sophon-tools-build:${IMAGE_TAG}`。发布到 dfss 服务器后，
通过 `docker load` 加载的镜像即为该 tag。

## 获取镜像（`build.sh` 默认自动三级回退）

`docker/build.sh` **默认行为**（无需任何参数）：

1. **本地已有** `sophon-tools-build:<tag>` 镜像 → 直接使用
2. **本地没有** → 从 dfss 服务器拉取已构建镜像并 `docker load`
3. **dfss 拉取失败** → 回退本地从源码构建

```bash
# 一行命令，自动完成 本地检查 → dfss 拉取 → 本地构建
bash docker/build.sh

# 强制从 dfss 拉取（跳过本地检查）
bash docker/build.sh --from-dfss

# 跳过 dfss 下载，直接本地构建
bash docker/build.sh --no-dfss

# 本地构建时内置私有工具链
bash docker/build.sh --with-dfss-toolchains --with-qt-mingw --with-sophui-toolchain
```

dfss 下载细节：

- dfss 文件名约定 `<镜像名>-<tag>.tar.zst`（冒号不适合文件路径，用 `-` 分隔）
- 默认 dfss 路径前缀 `open@sophgo.com:/`，可用环境变量 `DFSS_IMAGE_BASE` 覆盖：
  `DFSS_IMAGE_BASE=open@sophgo.com:/some/path bash docker/build.sh --from-dfss`
- 依赖 `python3 -m dfss`（dfss-cpp 客户端），从 sophgo sftp 服务器下载

### 手动拉取（等价命令）

```bash
python3 -m dfss --url=open@sophgo.com:/sophon-tools-build-unified-v1.1.0.tar.zst
docker load -i sophon-tools-build-unified-v1.1.0.tar.zst
# 加载后镜像 tag: sophon-tools-build:unified-v1.1.0
```

### 本地构建（可选）

完整镜像也可从仓库 Dockerfile 现场构建（需私有工具链归档，见下文"私有工具链"章节），
构建时间约 30-60 分钟（Go/Node/Rust 下载 + apt + 工具链解压）：

```bash
# 基础镜像（不含 dfss 私有工具链 sw_64/loongarch64、Qt mingw 静态库、pSophUI 交叉工具链）
bash docker/build.sh --no-dfss

# 完整镜像（内置 dfss 私有工具链 + Qt mingw 静态库 + pSophUI 交叉工具链）
bash docker/build.sh --no-dfss --with-dfss-toolchains --with-qt-mingw --with-sophui-toolchain

# 只内置 dfss / 只内置 Qt mingw / 只内置 pSophUI / 指定标签 / 禁用缓存
bash docker/build.sh --with-dfss-toolchains
bash docker/build.sh --with-qt-mingw
bash docker/build.sh --with-sophui-toolchain
bash docker/build.sh --tag v1.0 --no-cache
```

构建依赖：
- docker（≥20.10，BuildKit 默认开启），网络可访问 go.dev / nodejs.org / musl.cc
- pSophUI / dfss 私有工具链：以 `toolchains/` 归档内置（`--with-sophui-toolchain` / `--with-dfss-toolchains`），
  不再依赖 `cross_build_sophon_u20:v1` 独立镜像（导出归档见下文）
- Qt mingw 静态库：见下文

### 版本锁定（可复现）

- 唯一版本源：`docker/versions.env` —— 全部工具链版本 + 校验和统一在此维护，含镜像版本号 `IMAGE_TAG`。
- 基础镜像 `ubuntu:20.04` 用 **digest**（不可变引用）锁定，不用 tag。
- Go / Node 下载后做 **SHA256 校验**（校验失败即中止构建）。
- Rust 用 rustup 锁定稳定版 `1.97.1`；musl 工具链来自 musl.cc。
- 想固定 musl 工具链内容：把首次构建打印的实际 SHA256 填入 `versions.env` 的 `MUSL_*_SHA256`。
- 发布新镜像版本：改 `versions.env` 的 `IMAGE_TAG`，重建并导出（`docker save`）后上传 dfss。

## 为什么基座是 ubuntu:20.04（硬约束）

pqt 系列打 AppImage 依赖 linuxdeployqt，它**强制宿主 glibc ≤ 2.31**（保证产物兼容旧发行版）。
ubuntu:20.04 的 glibc 是 2.31（22.04 是 2.35）。M5 决定以 20.04 为唯一基座，同时满足：

| 需求 | 原独立镜像 | M5 单镜像内如何满足 |
|------|-----------|---------------------|
| pqt AppImage（glibc≤2.31） | `sophon-tools-build-pqt`（20.04） | 基座即 20.04，Qt5 + libgl1-mesa-dev + fuse + patchelf 内置 |
| pqt windows exe（Qt mingw 静态库） | `sophon-tools-build:m2` + 宿主 `/opt/qt-mingw` | `--with-qt-mingw` 内置 `/opt/qt-mingw` |
| pSophUI（aarch64 Qt 5.12.8 交叉） | `cross_build_sophon_u20:v1`（20.04） | `--with-sophui-toolchain` 内置 `/env/qt_5.12.8_nosysroot`（编译用系统 apt aarch64-linux-gnu-gcc 9.4） |
| dfss sw_64 / loongarch64 | `sophon-tools-build:m2` 内置 | `--with-dfss-toolchains` 内置（不变） |
| 其余 13 子项目 | `sophon-tools-build:m2` | 直接满足 |

## 镜像内工具链（对照 M1 盘点清单）

| 子项目 | 工具链 | 版本 |
|--------|--------|------|
| pbmssm / psophliteos | Go | 1.25.5（含 arm64/amd64 交叉） |
| pbm_set_ip | Rust + cargo | 1.97.1（aarch64/x86_64 musl + aarch64 gnu target） |
| psophliteos 前端 | Node + pnpm + yarn | Node 20.19.0 / pnpm 9.15.9 / yarn 1.22.22 |
| pbmssm / pbm_set_ip | musl 交叉工具链 | aarch64 + x86_64（musl.cc 静态） |
| pdfss_cpp | glibc 交叉工具链 | aarch64 / armel / riscv64（apt 精确版本） |
| pdfss_cpp (windows) | mingw-w64 | x86_64-w64-mingw32 + i686-w64-mingw32 |
| pdfss_cpp (私有) | sw_64 + loongarch64 | SWREACH GCC 8.3.0 / LoongArch 8.3.0（dfss 私有源） |
| pqt 系列 (linux AppImage) | Qt 5 + qmake | qtbase5-dev = Qt 5.12.8（20.04 仓库）+ libgl1-mesa-dev + fuse + patchelf |
| pqt 系列 (windows exe) | Qt 5.15.2 mingw 静态 | `/opt/qt-mingw`（build-qt-mingw.sh 编译，`--with-qt-mingw` 内置） |
| pSophUI | aarch64 Qt 5.12.8 交叉库 + apt aarch64-linux-gnu-gcc 9.4 | `/env/qt_5.12.8_nosysroot`（13.24 同款 Qt）+ 系统工具链（Linaro GCC 6.3 已移除） |
| 打包/文档 | dpkg-deb / 7z / zip / upx / patchelf / pandoc | apt 精确版本 |
| 跨架构验证 | qemu-user-static | aarch64 / loongarch64 等 |

## dfss 私有工具链（sw_64 / loongarch64）

sw_64 和 loongarch64 工具链来自 dfss 私有源，**默认不内置**（体积大、需从 13.24 服务器容器导出）。
两种获取方式：

### 方式 1：从 13.24 服务器容器导出（推荐）

在 13.24 服务器上（`cross_build_sophon_u20:v1` 容器，名 `bm1684_zzt`），执行：

```bash
bash docker/scripts/export-dfss-toolchains.sh
# 产物: docker/toolchains/swgcc830_cross_tools.tar.zst
#        docker/toolchains/loongarch64-cross-tools.tar.zst
```

然后构建：

```bash
bash docker/build.sh --with-dfss-toolchains
```

### 方式 2：从 dfss 私有服务器在线拉取

网络可达 dfss 服务器时，可参考 `source/pdfss_cpp/build_docker/Dockerfile` 的方式：

```bash
python3 -m dfss --url=open@sophgo.com:/toolchains/swgcc830-*.tar.gz
```

## Qt mingw 静态库（pqt windows exe）

pqt 系列 windows 端依赖 Qt 5.15 mingw **静态库**（仓库 `libs/win_amd64` 只含 libssh2/openssl，不含 Qt）。
**默认不内置**，获取方式：

```bash
# 在 20.04 基座内从源码交叉编译（约 20-40 分钟）—— 唯一可靠方式
bash docker/pqt/build-qt-mingw.sh
# 产物: /opt/qt-mingw（宿主工具 uic/moc 已与 20.04 glibc 兼容）
tar -C /opt/qt-mingw -cf - . | zstd -q -T0 > docker/toolchains/qt-mingw.tar.zst

# 然后构建镜像
bash docker/build.sh --with-qt-mingw
```

> **为什么不能复用 13.24 的 /opt/qt-mingw**：13.24 上的 Qt mingw 是 22.04 基座编译的，
> 其宿主工具（uic/moc/rcc 等）链接 glibc ≥ 2.33，在 20.04 基座（glibc 2.31）内无法运行。
> `build.sh --with-qt-mingw` 会先校验/触发从源码重建，保证宿主工具与 20.04 兼容。

## pSophUI 交叉 Qt 库（aarch64 Qt 5.12.8）

与 13.24 `cross_build_sophon_u20:v1` 的 Qt 库一致，**默认不内置**（约 42MB 归档 / 180MB 解压，私有源）。
**只含 aarch64 Qt 库，不含交叉编译器**——pSophUI 编译用系统 apt 的 `aarch64-linux-gnu-gcc 9.4`
（`source/pSophUI/release.sh` 默认 `CROSS_PREFIX=/usr`），替代原 Linaro GCC 6.3（已移除，省约 700MB）。
两种获取方式：

### 方式 1：从 13.24 服务器镜像导出（推荐）

在 13.24 服务器上执行：

```bash
bash docker/scripts/export-sophui-toolchains.sh
# 产物: docker/toolchains/sophui-cross-toolchains.tar.zst (约 42MB, 已剔除 examples/qml 冗余)
```

然后构建：

```bash
bash docker/build.sh --with-sophui-toolchain
```

归档内置后，构建期不再依赖 `cross_build_sophon_u20:v1` 独立镜像（与 M2 处理 dfss 工具链的方式一致）。
qmake / mkspecs 硬编码 `/env` 绝对路径，解压到 `/env` 原始路径，绝对引用全部有效。

## 挂载源码跑构建

```bash
# 挂载 sophon-tools 源码到 /workspace，进入容器交互式构建
docker run -it --rm \
  -v "$(pwd)":/workspace/sophon-tools \
  sophon-tools-build:unified \
  bash

# 进入后，按各子项目方式构建，例如:
cd /workspace/sophon-tools/source/pbmssm
bash build/build-deb-bmssm.sh   # 需以非 root 用户运行，或改输出目录为可写路径
```

## 统一构建入口（M3/M4/M5）：全部子项目一键全量多平台编译

每个子项目都提供统一接口的 `release.sh`（M1 规范 v0.1）：

```bash
bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64 | amd64 | all（默认按子项目）
#   VERSION: 显式版本号（缺省用子项目版本来源）
#   env OUTPUT_DIR: 覆盖产物目录（默认 <repo>/output/<子项目>/）
```

`docker/build-all.sh` 在镜像内依次驱动全部子项目的 `release.sh`，产物汇聚到仓库根 `output/<子项目>/`：

```bash
# 构建全部子项目（默认平台；失败隔离：单项目失败不影响整体）
bash docker/build-all.sh

# 只构建指定子项目 / 架构 / 版本
bash docker/build-all.sh --project pbmssm
bash docker/build-all.sh --arch arm64
bash docker/build-all.sh --version 2.1.0

# 查看构建清单（子项目 + 平台 + 使用镜像）
bash docker/build-all.sh --list

# 生成产物清单（文件名/架构/版本/md5）
bash docker/gen-manifest.sh          # -> output/MANIFEST.txt
```

### M5 单镜像说明

- **不再按子项目切换镜像**：pqt 系列（AppImage + exe）与 pSophUI 全部在统一镜像内构建。
- pqt 系列通过 `PQT_INPLACE=1` 让 `build-pqt.sh` 直接在容器内执行（不嵌套 docker）。
- pqt 系列 linux AppImage 基座即 20.04（glibc 2.31），linuxdeployqt 约束已满足。
- pqt 系列 windows exe 依赖 `/opt/qt-mingw`（`--with-qt-mingw` 内置）。

### M4：一条命令全量 release（推荐入口）

仓库根 `release.sh` 是 M4 的一键全量入口，内部依次完成：镜像前置检查 → 驱动
`build-all.sh` 全量构建 → 生成 `MANIFEST.txt` + `git_hash.txt` + `.build-status.txt`。

```bash
bash release.sh                      # 一键全量多平台 release
bash release.sh --project pbmssm     # 单项目
bash release.sh --version 2.1.0      # 统一版本号
```

**失败隔离语义**：单子项目失败（如某平台工具链缺失）不阻塞其他项目，其余照常出包。
结束时打印汇总表并写 `output/.build-status.txt`（每行 `<子项目> PASS|FAIL:<rc>|SKIP`）；
存在失败项时 `release.sh` 以退出码 1 结束，失败项在终端与状态文件中明确列出。

**产物清单**：`output/MANIFEST.txt` 为固定格式文本：

```
子项目                | 文件名                                            | 架构           | 版本      | md5
pbmssm               | bmssm_2.1.0_arm64.deb                             | arm64          | 2.1.0     | db83...
pdfss_cpp            | dfss-cpp-linux-loongarch64                        | loongarch64    | 1.10.5    | ...
```

架构判定优先级：文件名关键字 → `.deb` 包 `Architecture` 字段 → `file` ELF/PE 探测。

## 镜像自检

```bash
# 基础自检（工具链存在性，含基座 glibc 版本 + pqt/pSophUI 工具链）
bash docker/verify.sh --image sophon-tools-build:unified

# 完整自检（含交叉编译实测：arm64 musl 静态 / windows / sw_64 / loongarch64 / pqt Qt5 / pqt mingw / pSophUI）
bash docker/verify.sh --image sophon-tools-build:unified --cross
```

## pqt 系列（Qt GUI 工具）专用构建

`docker/pqt/` 提供 pqt 系列（`pqt_memory_edit` 图形化内存修改工具、`pqt_batch_deployment` 批量部署工具）的专用构建。

> **M5 变更**：pqt 不再用独立镜像。统一镜像基座即 20.04（glibc 2.31），满足 linuxdeployqt 的
> glibc≤2.31 硬约束；windows exe 的 Qt mingw 静态库由 `--with-qt-mingw` 内置。

```bash
# linux AppImage 一键编译（自动生成 memory_edit.tar.xz 前置依赖）
bash docker/pqt/build-pqt.sh --project pqt_memory_edit --linux
bash docker/pqt/build-pqt.sh --project pqt_batch_deployment --linux

# windows exe（需先内置 Qt mingw 静态库，见上文）
bash docker/pqt/build-qt-mingw.sh          # 交叉编译 Qt 5.15.2 mingw 静态（一次约 20-40 分钟）
bash docker/pqt/build-pqt.sh --project pqt_memory_edit --windows

# 两端一起
bash docker/pqt/build-pqt.sh --project pqt_memory_edit --all

# 在统一镜像内直接执行（inplace 模式，不嵌套 docker）
docker run --rm -v "$(pwd)":/workspace/sophon-tools sophon-tools-build:unified bash -c \
  'cd /workspace/sophon-tools/source/pqt_memory_edit && PQT_INPLACE=1 bash release.sh amd64'
```

已实测：`qt_mem_edit_V2.12.1-x86_64.AppImage`（25.9MB）在 20.04 镜像内一键产出，
AppImage 可正常解包运行。

## 交叉编译示例

`docker/examples/cross-test/` 提供 C / Rust / Windows 的交叉编译最小示例：

```bash
bash docker/examples/cross-test/run.sh --image sophon-tools-build:unified
```

## 已知边界

1. **pqt 系列 AppImage** 在统一镜像（20.04，glibc 2.31）内构建，产物兼容 glibc ≥ 2.27 的系统。
2. **pqt 系列 windows exe** 依赖 Qt 5.15 mingw 静态库（`build-qt-mingw.sh` 交叉编译，20-40 分钟）；
   `--with-qt-mingw` 后内置 `/opt/qt-mingw`，全部在统一镜像内完成，无需宿主 `/opt/qt-mingw`。
3. **pSophUI** 在统一镜像内交叉编译（aarch64 Qt 5.12.8 库 `--with-sophui-toolchain` 内置，
   编译器用系统 apt `aarch64-linux-gnu-gcc 9.4`，Linaro GCC 6.3 已移除；
   `sophui-cross-toolchains.tar.zst` 归档导出自 cross_build_sophon_u20:v1），
   产出 `sophgo-hdmi_<ver>_arm64.deb` + `SophUI_arm64`（尾部 upx 缺失仅告警，不影响产物）。
4. **pmulti_video_qt** 已按 MYSWY 决定从统一构建范围排除（不需要做），不再参与构建。
5. **dfss 私有工具链**默认不内置；需要时按上文方式导出（`--with-dfss-toolchains`）。
6. 容器内构建涉及 `sudo` 的脚本（根 `release.sh`）需以 root 运行（镜像默认 root）或调整输出目录权限。
7. 基座由 22.04 降为 20.04 后，宿主 gcc 从 11.x 变为 9.4、Qt 从 5.15.3 变为 5.12.8；
   各子项目构建回归结果见 M5 交付矩阵（16/16 全绿）。

## 目录结构

```
docker/
├── Dockerfile                # 多阶段构建（Stage1 下载校验 → Stage2 运行镜像；工具链归档内置）
├── versions.env              # 唯一版本源（版本 + 校验和）
├── build.sh                  # 一条命令构建镜像
├── build-all.sh              # 统一构建入口（M3/M4/M5，驱动全部子项目 release.sh）
├── gen-manifest.sh           # 生成产物清单 MANIFEST.txt（文件名/架构/版本/md5）
├── verify.sh                 # 镜像自检（对照 M1 清单 + pqt/pSophUI 工具链）
├── README.md                 # 本文件
├── scripts/
│   ├── export-dfss-toolchains.sh     # 从 13.24 容器导出 sw_64/loongarch64 工具链
│   └── export-sophui-toolchains.sh   # 从 13.24 镜像导出 pSophUI 交叉工具链
├── pqt/
│   ├── Dockerfile            # [废弃] pqt 专用镜像（M5 已并入统一镜像，保留兼容）
│   ├── build-pqt.sh          # pqt linux/windows 一键编译（支持 inplace 模式）
│   └── build-qt-mingw.sh     # Qt 5.15.2 mingw 静态库交叉编译
├── examples/
│   └── cross-test/           # 交叉编译示例（C/Rust/Windows）
└── toolchains/               # 导出的私有工具链归档（构建时由 --with-dfss-toolchains / --with-qt-mingw / --with-sophui-toolchain 使用）
```
