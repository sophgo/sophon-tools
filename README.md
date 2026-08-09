# sophon-tools

## 简介

本工程用于存放算丰设备当前易用性工具源码，便于发版与使用者二次开发

## 目录结构

* `source` 目录下存放各个工具的源码
* `output` 目录下存放编译的最终结果

## 子项目介绍

| 子项目名称 | 源码路径 | 是否支持一键编译 | 简介 |
| --- | --- | --- | --- |
| [bmsec](./source/pbmsec) | source/pbmsec | 是 | 用于SE6/8高密度服务器的易用性命令行工具 |
| [socbak](./source/psocbak)   | source/psocbak | 是 | 用于BM1684/BM1684X/BM1688/CV186AH芯片刷机包打包 |
| [get_info](./source/pget_info) | source/pget_info | 是 | 用于获取BM1684/BM1684X/BM1688/CV186AH芯片的性能指标 |
| [memory_edit](./source/pmemory_edit) | source/pmemory_edit | 是 | 用于修改BM1684/BM1684X/BM1688/CV186AH的设备内存布局 |
| [qt_memory_edit](./source/pqt_memory_edit) | source/pqt_memory_edit | 否 | 图形化的远程修改设备内存布局的工具 |
| [qt_batch_deployment](./source/pqt_batch_deployment) | source/pqt_batch_deployment | 否 | 基于SSH的批量部署工具 |
| [dfss_cpp](./source/pdfss_cpp) | source/pdfss_cpp | 否 | DFSS工具CPP工程 |
| [spacc_efuse_demo](./source/pspacc_efuse_demo) | source/pspacc_efuse_demo | 否 | efuse+spacc加解密Demo |
| [SophUI](./source/pSophUI) | source/pSophUI | 否 | HDMI配网页面工程 |
| [ota_update](./source/pota_update) | source/pota_update | 是 | OTA远程刷机工具 |
| [mem_aging_test](./source/pmem_aging_test) | source/pmem_aging_test | 是 | DDR压测工具 |
| [autotelecomm](./source/pautotelecomm) | source/pautotelecomm | 是 | 4G/5G自动拨号工具 |
| [bm_set_ip](./source/pbm_set_ip) | source/pbm_set_ip | 否 | 配网工具 |
| [phytool](./source/psoph_phytool) | source/psoph_phytool | 是 | 网口 PHY 寄存器读写工具（纯脚本，无编译） |
| [bmssm](./source/pbmssm) | source/pbmssm | 否 | 设备端后端（:9779）：鉴权/硬件指标/systemd/端口/网络/OTA/文件。见 [API.md](./API.md) / [USAGE.md](./USAGE.md) / [BUILD.md](./BUILD.md) |
| [sophliteos](./source/psophliteos) | source/psophliteos | 否 | 算力设备管理 Web 平台（Go+Vue，:8080），反代 bmssm。见 [API.md](./API.md) / [USAGE.md](./USAGE.md) / [BUILD.md](./BUILD.md) |

## 编译方式

### 一键全量 release（推荐）

本仓库已接入统一构建工程（M1~M4）：16 个子项目全部提供统一接口 `release.sh`，由
Docker 统一镜像 `sophon-tools-build` 在容器内完成编译。**一条命令全量出包**：

```bash
# 前置：统一构建镜像（首次）
bash docker/build.sh --with-dfss-toolchains --with-qt-mingw --with-sophui-toolchain   # 完整镜像（含 dfss 私有 sw_64/loongarch64、Qt mingw 静态库、pSophUI 交叉 Qt 库）

# 一键全量 release（各子项目默认平台，Docker 内编译）
bash release.sh

# 常用变体
bash release.sh --project pbmssm            # 单项目快速构建
bash release.sh --version 2.1.0             # 全量 + 统一版本号
bash release.sh --project pqt_memory_edit   # 宿主执行（pqt 系列在统一镜像内直接构建，无需 docker-in-docker）
```

> **平台说明**：默认 `release.sh` 对每个子项目构建其**默认平台**（多数为单平台，
> 如 pbmssm/pbm_set_ip=arm64、pget_info/pdfss_cpp=amd64；仅 pbmsec/psoph_phytool 默认出全平台）。
> 需要跨平台出包时，对支持 `all` 的子项目在其源码目录执行 `bash release.sh all`
> （如 pdfss_cpp 可一次出 amd64/arm64/armbi/loongarch64/riscv64/sw_64/win-amd64/win-i686 8 平台），
> 或 `bash docker/build-all.sh --arch all` 对支持 `all` 的子项目统一驱动。

构建结束后：

- 全部产物汇聚到 `output/<子项目>/`（保持既有 output 约定）
- `output/MANIFEST.txt`：完整产物清单（子项目 / 文件名 / 架构 / 版本 / md5）
- `output/git_hash.txt`：构建时仓库 HEAD
- `output/.build-status.txt`：各子项目 PASS/FAIL/SKIP 状态

**失败隔离**：单个子项目失败不阻塞整体，其余照常出包；构建结束列出失败项，
`release.sh` 存在失败时以非零退出码结束（失败项见 `.build-status.txt` 与终端汇总）。

详细文档见 [`docker/README.md`](./docker/README.md)。

### 传统方式（单子项目）

1. 支持一键编译的子项目在本目录下执行 `release.sh` 后会将成果输出到 `output` 目录
2. 不支持一键编译的子项目请参考源码目录中的 `readme.md` 自行准备环境编译

## 一键编译的子项目的编译依赖

* 编译主机架构:amd64
* 7z/zip
* dpkg-deb
* pandoc
* docker（统一构建镜像 `sophon-tools-build:unified`）
