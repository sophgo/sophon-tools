# 构建输入与来源（build inputs & provenance）

本目录记录 `source/pcv84x6_llm_server` 的源码来源与固定构建输入，保证
`sophon-tools` 内的一键出包不依赖个人路径、私有仓库凭据或临时设备。

## 源码来源

自 v0.6.38 起，本目录**就是源码**：构建所用的 C++ 引擎、Python 服务、Web 控制台
全部在本仓库的 `source/pcv84x6_llm_server/` 下，与固定输入一起提交。构建不依赖任何
私有仓库、个人路径或外部快照。

| 项 | 值 |
| --- | --- |
| 源码仓库 | `sophgo/sophon-tools`（本仓库），子目录 `source/pcv84x6_llm_server` |
| 源码提交 | 见 `build/source-commit.txt`（**源码提交 A**，即引擎与服务的可追溯来源） |
| 固定产物提交 | **产物提交 B**：在 A 之上提交 `build/inputs/lib/libcv84x6_llm.so` 与 `build/inputs/SHA256SUMS` |
| 服务版本 | `0.6.38`（唯一版本源 `app/__init__.py`，与 `web/package.json` / `package-lock.json` 同步） |
| 构建方式 | `bash release.sh --project pcv84x6_llm_server`（见仓库根 `docker/`） |

`build/source-commit.txt` 指向的是**真实构建源码**：从该提交在 CV84X6 板端执行
`cmake -S native -B <独立目录> && cmake --build <独立目录>` 即可逐字重建
`build/inputs/lib/libcv84x6_llm.so` 的 ABI 与行为（编译非确定性，不要求逐字节相同）。
包内 `COMMIT` 与该文件一致，`tests/test_sophon_tools_build.py` 校验两者不会漂移。

### 历史上游导入来源（仅供追溯，不再是构建来源）

v0.6.37 及更早的包由私有仓库 `zzttzzmyswy/cv84x6-llm-server` 的源码快照导入：

| 版本 | 上游提交 | 说明 |
| --- | --- | --- |
| v0.6.37 及更早 | `fdd109c8b1f49d929fcc7d98f993bf95f4c88e1b` | 导入时的私有仓库快照；其后的适配差异见下节 |

这段历史**不描述当前构建**：v0.6.38 的引擎库来自本仓库源码，`source-commit.txt`
不再宣称新库来自 `fdd109c8`。

## 与上游导入版本的适配差异（历史）

v0.6.37 及更早的导入需要以下适配，**不改任何业务行为、UI、服务名、包名、
安装/数据目录与配置保留语义**。v0.6.38 起这些适配已成为源码本身的一部分，保留在此
仅为追溯：

1. **导入范围**（原始运行代码原样保留；实验原始输出与板端日志不随本仓库分发）：
   - `analysis/` 探针代码保留（decode/队列可复现研究脚本），`analysis/raw/`
     只保留被 `docs/research/*`「复现」一节与单测引用的**测量数据锚点**
     （prefill/queue/embed sweep、prof CSV、model_info、queue_depth 表、
     driver-evidence 摘录、mys2474/2477/2510-supplement/2702 数据）；原仓库
     的板端原始日志与运行记录（dmesg/journal/栈 dump/SSE 流/recent-inference
     等，mys2498/2501/2502 整目录、mys2702 的 hang trace、顶层
     `dmesg_wedged_tpu.txt`/`hang_prof.csv`）与 `docs/research/d7/` 下 9 个
     卡死现场采集目录（每个 run 的 dmesg/内核栈/kernel_fifo/请求记录）不在
     本仓库——结论已整理进 `docs/research/d7-tpu-hang.md`、`d7/step1`、
     `d7/step2-3`、各篇研究文档与各自 README，原始件留在原私有仓库。
   - `web/node_modules` — 源树里是指向个人路径的 symlink，本仓库由
     `npm ci` 现场构建（`scripts/build_web.sh`，lockfile 已入库）。
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
外部输入。这里把**本仓库源码构建出的引擎库**与已验证的基础配置以明确版本 +
SHA256 固定在本目录（`SHA256SUMS`），构建时逐项校验：

| 输入 | 来源 | SHA256 |
| --- | --- | --- |
| `lib/libcv84x6_llm.so` | 从 `build/source-commit.txt` 指向的**源码提交 A** 在 CV84X6 板端完整 CMake 构建（`native/`，全量目标，非诊断子集）；构建记录见 `build/native-build.md` | 见 `SHA256SUMS`（v0.6.38：`26bd2702cf903bd69a1e413be16f93d327f04a0d99679c6408ea46a8694eee09`） |
| `qwen3_5-config/*` | sophon-demo Qwen3_5 `config.zip`（官方 v0.6.37 deb 内 `model-config/qwen3_5/`，已验证与 MYS-2846/MYS-2754 发布输入逐字节一致；v0.6.38 未改动） | 见 `SHA256SUMS` |

### 引擎库（libcv84x6_llm.so）

- 架构：ARM aarch64，ELF 共享库，`NEEDED: libbmrt.so.1.0 / libbmlib.so.0 /
  libjpeg.so.8 / libz.so.1`，`RUNPATH: /opt/sophon/libsophon-current/lib`。
- SDK/ABI：CV84X6 板端 libsophon（`/opt/sophon/libsophon-current`），
  与板上 `libjpeg-turbo8`（libjpeg.so.8）、zlib1g 链接；运行依赖与 deb 的
  `Depends:` 声明一致。
- **v0.6.38 的库来自修复源码**：包含 `native/src/vl_embed_engine.cpp` 里设备
  拷贝完成序的修复（每个 d2d/zero/upload 之后等待 SDK 同步完成），并保留
  zero/non-finite/fault 锁存保护。它不是 0.6.37 的库，也不是只含诊断代码的子集库。
- 复现方式：源码在 `native/`，在 CV84X6 板上用独立构建目录全量构建：

  ```bash
  cmake -S native -B /tmp/cv84x6-native-build -DCMAKE_BUILD_TYPE=Release
  cmake --build /tmp/cv84x6-native-build -j"$(nproc)"
  ```

  （需板端 libsophon，无法在 x86 交叉。）重建后产物与固定输入不要求逐字节一致
  （编译非确定性），但 ABI 与行为由 `tests/native/run_tests.sh <libsophon>/include`
  与 `readelf -d` 的入口/依赖清单把关。
- 升级输入时：替换 `build/inputs/lib/libcv84x6_llm.so` 与
  `qwen3_5-config/`，重新生成 `SHA256SUMS`，更新本表与 `build/native-build.md`。

### 文本格式（git diff --check）

本目录/子项目自有文本（脚本、文档、测试）保持 `git diff --check` 干净。以下
导入的第三方原文与测量数据**保留原样、不改写**，其行尾空白/文件尾空行属原文
特征，逐项列为例外：
- `build/inputs/qwen3_5-config/README.md`（HuggingFace 模型卡片原文）
- `model-config/wemm_embedding/LICENSE`、`app/static/docs/LICENSE-redoc.txt`、
  `app/static/docs/redoc.standalone.js`（第三方许可证与库文件原文）
- `analysis/raw/` 测量数据（prof/表/model_info/driver-evidence/rounds 等原始
  探针输出，mys2521-report.html 为交付报告原文）

## 不得使用

- 旧版本库（如 0.6.34 的 lib）冒充；
- 浮动 latest 下载；
- 任何需要私有 token / 个人 SSH 的默认获取路径。
