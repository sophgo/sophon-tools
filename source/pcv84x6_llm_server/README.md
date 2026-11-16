# CV84X6 离线 LLM 推理服务

在 CV84X6（8×Cortex-A55 + Sophon NPU）上运行的**完全离线** LLM 推理服务：OpenAI 兼容 API +
Web 管理页 + VLM 图片输入 + 多会话并发 + 多模型/agent 进程管理。推理走自研的纯 bmrt C++ 引擎
（`native/`，不依赖 sail），数据流对齐 sophon-demo 官方 `sample/Qwen3_5/python/qwen3_5.py`。

- 模型：`Qwen3.5/3.6-35B-A3B`，32k 与 128k 两档上下文（四份自编译 bmodel，见下表）
- 板上只需要一个 Python 3.10 解释器：分词、图片解码与预处理都在引擎库里，不装 numpy/torch
- 每个模型一个 worker 进程，进程内多会话按时间片轮转；每模型并发硬上限 3，新装默认 2

设计取舍见 [`docs/DESIGN.md`](docs/DESIGN.md)，面向使用者的完整说明在服务内的「文档」页。

## 安装（arm64 deb）

```bash
sudo apt install ./cv84x6-llm-server_0.6.38_arm64.deb
```

一条命令完成解包、Python 检查、数据目录初始化、systemd enable 与启动。包内自带 Web 依赖与引擎库，
依赖只用板上已有的系统包，**不联网**；`libsophon` 是厂商运行时，postinst 会检查并明确提示。

| 操作 | 命令 | 数据 |
|---|---|---|
| 升级 | 装新包即可 | `etc/server.env`、数据目录、模型、API key、管理密码、agent 全部保留 |
| 卸载 | `apt remove cv84x6-llm-server` | 删程序、停服务，**保留** `etc/server.env` 与数据目录 |
| 彻底卸载 | `apt purge cv84x6-llm-server` | 连配置一起删，**默认仍保留数据目录**并打印删除命令 |
| 看状态 | `dpkg -l cv84x6-llm-server`、`systemctl status cv84x6-llm`、`journalctl -u cv84x6-llm -n 80` | |

程序与数据分开：`/opt/sophgo/cv84x6_llm_server/` 只放程序（升级整体替换），
`/data/cv84x6_llm_server/` 放全部可变数据（`models/ state/ agents/ downloads/`）。
数据目录可在「设置」页迁移，流程与回滚见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 首次使用

浏览器打开 `http://<板子IP>:8000`（默认管理密码 `admin`，请立即修改）→「模型」页一键下载或放入模型
→ 加载 →「API Key」页创建密钥。模型放在 `<数据目录>/models/<名字>/*.bmodel`。

| 模型 | 上下文 | md5 |
|---|---|---|
| Qwen3.6-35B-A3B 128k（mask128 优化版） | 131072 | `76b3795892a6debc1159630c879ed05b` |

「Agent」页可一键安装、配置、启停、重置、卸载 **PicoClaw / opencode / OpenClaw**，支持离线安装，
也可经本服务同源代理（`/agents/<id>/`）内嵌或外开。三个 agent 的端口、内存与默认配置见服务内「文档」页。

「推理记录」页保存每次推理的完整现场（请求、参数、输出、耗时、结束原因），成功 / 流式中断 / 异常
各一条，可导出 NDJSON 或按条数/天数自动清理。记录里是客户对话明文，位置、字段语义与隐私说明见
[`docs/inference-records.md`](docs/inference-records.md)。

## API

```bash
curl http://<板子IP>:8000/v1/chat/completions \
  -H "Authorization: Bearer $CV84X6_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model-id","messages":[{"role":"user","content":"你好"}],"max_tokens":256,"stream":true}'
```

`/v1/models`、`/v1/chat/completions`；字段按 OpenAI 格式，含 SSE、`stop`、`tools`/`tool_calls`、
`reasoning_content`，以及 `usage.prompt_tokens_details.cached_tokens`（前缀缓存命中的 token 数）。
任何接受「OpenAI 兼容 base URL」的客户端指过来即可用。

辅助模型另有三类接口，同一个模型会在 `/v1/models` 的 `kind` 里声明自己是哪一种：

| 接口 | `kind` | 文档 |
|---|---|---|
| `POST /v1/embeddings` | `embedding` | [`docs/aux-models.md`](docs/aux-models.md) |
| `POST /v1/rerank`（别名 `POST /rerank`） | `rerank` | [`docs/aux-models.md`](docs/aux-models.md) |
| `POST /v1/audio/transcriptions` | `asr` | [`docs/aux-models.md`](docs/aux-models.md) |
| `POST /v1/ocr` | `ocr` | [`docs/ocr.md`](docs/ocr.md) |

**就绪语义**（v0.6.14 起）：模型只有在权重、引擎、tokenizer/vision、缓存预算与调度器全部初始化完成后
才接受推理；加载中、卸载中、加载失败时 `/v1/chat/completions` 与 `/api/chat*` 一律返回 **409**，
不产生推理记录。`/healthz` 只表示**服务存活**（`loaded` 是计数，可为 0），
不代表模型已加载——客户端要判断能否推理请查 `/v1/models`（只列当前可推理的模型）或控制台「模型」页。
细节见 [`docs/DESIGN.md`](docs/DESIGN.md) §5.1.1。

## 开发与测试

```bash
./scripts/install_venv.sh                  # x86 开发 venv（mock 后端 + 测试）
./scripts/test.sh                          # pytest（等价 python3 -m pytest -q）
./scripts/build_web.sh                     # 构建控制台，只有构建时需要 node
.venv/bin/python -m app.main --backend mock --port 8000
cd native && mkdir -p build && cd build && cmake .. && make -j8   # 引擎，需在板上链接 libsophon
```

- 测试无需板卡：`MockBackend` 跑通调度、缓存、鉴权、OpenAI 协议全链路；原生行为检查
  `bash tests/native/run_tests.sh <libsophon>/include`。
- 控制台浏览器验收（布局、昼夜主题、对比度、图表）：[`web/acceptance/README.md`](web/acceptance/README.md)。
- 真机验收工具在 [`tools/`](tools/README.md)：服务接口、缓存、长上下文与并发、引擎直测。
- 打包：`scripts/package_deb.sh --lib <libcv84x6_llm.so> --config <qwen3_5 配置目录>`；
  版本号只来自 `app/__init__.py`。发布纪律见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## sophon-tools 统一构建（本仓库内出包）

本目录已接入 sophon-tools 统一 Docker 出包（在仓库根执行）：

```bash
bash release.sh --project pcv84x6_llm_server   # 单项目（推荐，约 2–7 分钟，首次较慢）
bash release.sh                                 # 全量（含本目录，失败隔离）
cd source/pcv84x6_llm_server && bash release.sh arm64   # 宿主直接调用（需 node/pip3/dpkg-deb）
```

- 产物：`output/pcv84x6_llm_server/cv84x6-llm-server_<ver>_arm64.deb` + `.sha256`，
  计入根 `output/MANIFEST.txt` 与 `.build-status.txt`。只支持 arm64；`all` 等同 arm64。
- 引擎库与 qwen3_5 基础配置是**固定输入**（`build/inputs/`，SHA256 校验，来源与重建方式见
  [`build/README.md`](build/README.md)）；Web 控制台从 `web/` 源码 + lockfile 现场构建；
  vendored Python 依赖按 `requirements-vendor-lock.txt` 锁定（= 官方 v0.6.38 实发版本）。
- **版本号唯一来源**：包版本来自 `app/__init__.py`（0.6.38），`release.sh` 只校验不修改。
- 源码来源：本目录自 v0.6.38 起就是**本仓库的源码**，不再是私有仓库的快照。
  `build/source-commit.txt` 记录构建所用提交（指向本仓库 `sophgo/sophon-tools`），
  包内 `COMMIT` 与之一致；历史上游导入来源见 [`build/README.md`](build/README.md)。

## 目录

```
app/          服务：main.py 组装、api/（OpenAI 兼容层与管理面）、core/（状态/鉴权/进程/下载/监控）、
              engine/（引擎抽象 + native ctypes + mock + 调度器 + worker 进程）、agents/
native/       纯 bmrt C++ 引擎、C ABI、分词器与图像预处理（替代 Python ML 依赖）
web/          React + TypeScript 控制台，dist/ 是提交在仓库里的构建产物；acceptance/ 浏览器验收
scripts/      install / uninstall / package / test / build_web
tests/        pytest 回归与原生行为检查，含分词与图像 golden
tools/        真机与端到端验证工具，见 tools/README.md
analysis/     decode / BMRT 队列的可复现研究探针与原始测量数据（不是发布包内容）
docs/         当前架构与契约；docs/research/ 是历史评测专题
deploy/       systemd unit 模板
```

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/README.md`](docs/README.md) | 文档索引：当前契约 / 研究专题 / 历史评测 |
| [`docs/DESIGN.md`](docs/DESIGN.md) | 当前架构与关键不变量 |
| [`docs/admin-api.md`](docs/admin-api.md) | 管理接口 `/api/*` 的对外契约（由代码生成）：admin key 认证、错误码表、每个接口的字段与 curl 示例；离线 Swagger 在 `/api/docs` |
| [`docs/session-state-contract.md`](docs/session-state-contract.md) | 会话快照/恢复/续算契约 |
| [`docs/console-design.md`](docs/console-design.md) | 控制台视觉规范 |
| [`docs/inference-records.md`](docs/inference-records.md) | 推理记录：记录时机、字段语义、保留与隐私 |
| [`docs/decode-submission.md`](docs/decode-submission.md) | decode 提交与线性状态处理 |
| [`tools/precision/README.md`](tools/precision/README.md) | 预填充 MoE 精度问题的证据与复现 |

## 已知边界

- **采样参数不生效**：bmodel 的 `lm_head` 内置 argmax，同一输入永远得到同一输出。
- **128k 是能装下的最长档**：KV 每 token 20 KB，128k 加载后占 NPU 22.8 GB / 23.75 GB，256k 放不下。
  一个 35B 模型占 20–23 GB，同一时刻只能加载一个。
- **冷启动长 prompt 首字慢**（127k 约 46 min），长文档靠前缀缓存；128k 版缓存空间约 1 GB，
  长文档反复提问用 32k 版更合适。
- **多 token 预填充的 MoE 有数值误差**（厂商算子，官方 bmodel 同样存在），已用「精确尾部」缓解；
  细节见 [`tools/precision/README.md`](tools/precision/README.md)。
- **不要在 NPU 进程执行中途强杀它**（`pkill`/`kill -9`），会卡死 TPU；停服务用 SIGTERM。
- **原始 PNG 间歇性驱动超时**未稳定复现、未定位，见
  [`docs/session-state-contract.md`](docs/session-state-contract.md) 末节。

版本变更看 [releases](https://github.com/zzttzzmyswy/cv84x6-llm-server/releases)。
