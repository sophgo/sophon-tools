# 构建输入与来源（build inputs & provenance）

本目录记录 `source/pcv84x6_llm_server` 的源码来源与固定构建输入，保证
`sophon-tools` 内的一键出包不依赖个人路径、私有仓库凭据或临时设备。

## 源码来源

| 项 | 值 |
| --- | --- |
| 来源仓库 | `zzttzzmyswy/cv84x6-llm-server`（私有） |
| 固定提交 | `fdd109c8b1f49d929fcc7d98f993bf95f4c88e1b`（= main，= release v0.6.37 tag） |
| 服务版本 | `0.6.37`（唯一版本源 `app/__init__.py`，与 `web/package.json` 同步） |
| 导出方式 | `git archive`（源树，不含 .git） |
| 导入适配 | 见下「与上游的必要适配差异」 |

## 与上游（原仓库 fdd109c8）的必要适配差异

全部为「接入 sophon-tools 出包流程」所需的适配，不改任何业务行为、UI、
服务名、包名、安装/数据目录与配置保留语义：

1. **排除项**（原始运行代码一律原样保留）：
   - `analysis/` — 实验测量数据与探针（非发布内容，README 亦如此声明）；
     原仓库 151 个 raw 证据文件不随本仓库分发。
   - `web/node_modules` — 源树里是指向个人路径的 symlink，本仓库由
     `npm ci` 现场构建（`scripts/build_web.sh`）。
   - `tools/e2e/d7_reserve_sweep.py` — D7 调研脚本，内嵌临时测试设备的
     sudo 密码明文（随机密码），凭据不能入库；其余 `tools/e2e/` 脚本的
     设备入口都是环境变量注入，原样保留。
2. **新增 `build/inputs/`** — 固定原生库与基础配置（见下），替代原打包
   流程要求调用者手工传递的 `--lib/--config` 外部输入。
3. **新增 `build/README.md`（本文件）与 `release.sh`** — 统一构建接口。
4. **`scripts/package_deb.sh` 适配** — `--lib/--config` 从必填外部参数
   改为默认取 `build/inputs/` 并校验 SHA256（显式传参仍可用）；其余逻辑
   （包结构、维护脚本、md5sums）逐字未动。

## 固定构建输入（build/inputs/）

原流程的 `--lib <libcv84x6_llm.so>` 与 `--config <qwen3_5 配置目录>` 是
外部输入。这里沿用 **官方 release v0.6.37 已验证的输入**，以明确版本 +
SHA256 固定在本目录（`SHA256SUMS`），构建时逐项校验：

| 输入 | 来源 | SHA256 |
| --- | --- | --- |
| `lib/libcv84x6_llm.so` | 官方 [v0.6.37 release](https://github.com/zzttzzmyswy/cv84x6-llm-server/releases/tag/v0.6.37) deb 内 `lib/libcv84x6_llm.so`（包资产 digest `sha256:1cd9dce7…` 整包校验一致后提取） | `b2363e3e3ca93a4914e9d1e46083c93973bf163add484670935d031016f61b32` |
| `qwen3_5-config/*` | sophon-demo Qwen3_5 `config.zip`（同 v0.6.37 deb 内 `model-config/qwen3_5/`，已验证与 MYS-2846/MYS-2754 发布输入逐字节一致） | 见 `SHA256SUMS` |

### 引擎库（libcv84x6_llm.so）

- 架构：ARM aarch64，ELF 共享库，`NEEDED: libbmrt.so.1.0 / libbmlib.so.0 /
  libjpeg.so.8 / libz.so.1`，`RUNPATH: /opt/sophon/libsophon-current/lib`。
- SDK/ABI：CV84X6 板端 libsophon（`/opt/sophon/libsophon-current`），
  与板上 `libjpeg-turbo8`（libjpeg.so.8）、zlib1g 链接；运行依赖与 deb 的
  `Depends:` 声明一致。
- 复现方式：源码在 `native/`，在 CV84X6 板上
  `cd native && mkdir -p build && cd build && cmake .. && make -j8`
  （需板端 libsophon，无法在 x86 交叉；见原仓库 README「开发与测试」）。
  重建后产物与固定输入不要求逐字节一致（编译非确定性），但 ABI 与行为
  由 `tests/native/run_tests.sh <libsophon>/include` 把关。
- 升级输入时：替换 `build/inputs/lib/libcv84x6_llm.so` 与
  `qwen3_5-config/`，重新生成 `SHA256SUMS`，并同步更新本表。

### 不得使用

- 旧版本库（如 0.6.34 的 lib）冒充；
- 浮动 latest 下载；
- 任何需要私有 token / 个人 SSH 的默认获取路径。
