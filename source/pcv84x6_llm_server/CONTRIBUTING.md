# 贡献指南

## 开发环境

x86 工作站即可，不需要板卡和 NPU：

```bash
./scripts/install_venv.sh
./scripts/test.sh                              # 等价 .venv/bin/python -m pytest -q
.venv/bin/python -m app.main --backend mock --port 8000
```

`MockBackend` 是完整的假推理后端（确定性输出 + 模拟延迟 + 内存账本），所以调度器、前缀缓存、
OpenAI 协议、鉴权、统计、Web UI 全部能在 x86 上跑测试。真机上只需要验与 NPU 打交道的那部分。

改了控制台：

```bash
./scripts/build_web.sh       # 需要 node，只有构建时需要；dist/ 要一起提交
```

`web/dist` 是**提交在仓库里**的构建产物，因为板上没有 node 工具链。改完 `web/src` 必须重新
build 并提交 `dist`，否则发布包里是旧界面（`tests/test_console_design.py` 会比对）。

## 测试

```bash
python3 -m pytest -q                                    # 全量
bash tests/native/run_tests.sh <libsophon>/include      # 原生引擎行为检查（104 项）
```

要求：

- 新增行为要带测试。修 bug 先写能复现的用例。
- **不删、不跳过、不放宽已有测试**来让 CI 变绿。测试失败先确认是实现错了还是用例写错了。
- 涉及 NPU 真实行为的改动（引擎、图、KV、调度时间片），除 pytest 外还要在板上跑
  `tools/` 里对应的验收脚本；只跑了 mock 的部分在 PR 里写明「未真机验证」。

## 真机验收

工具分类索引见 [`tools/README.md`](tools/README.md)。三条硬纪律：

- **不要 `kill -9` 正在跑 NPU 的进程**——会让 TPU 卡死，只能重启设备。停服务用 SIGTERM 等它退出。
- 每次跑完看 `dmesg | tail`，出现驱动超时或 oops 立即停止，不重试。
- 同一时刻只跑一个探针进程。

## 发布纪律

- **版本号只有一个来源**：`app/__init__.py` 的 `__version__`。控制台的 `web/package.json` 要同步
  （`tests/test_packaging.py` 会检查）。
- 改动影响发布产物（二进制、包、镜像）时 bump 版本并发新 release；**不要用同版本号覆盖已有资产**。
- 纯文档、测试、CI 改动不需要发版。
- 打包：`scripts/package_deb.sh --lib <libcv84x6_llm.so> --config <qwen3_5 配置目录>`。
  版本与发布边界的原因见 [`docs/DESIGN.md`](docs/DESIGN.md) §9。

## 提交与 PR

- 分支从最新 `main` 起，一个 PR 一件事。
- PR 描述写清：改了什么、为什么、怎么验的（命令 + 结果）。真机与主机侧分开写。
- 合并前 `python3 -m pytest -q` 与 `./scripts/build_web.sh` 都要过。

## 文档

- 当前契约写在 `docs/`，历史评测放 `docs/research/`。索引见 [`docs/README.md`](docs/README.md)。
- 改代码时同步改文档里过期的数字与路径；`path:line` 形式的引用要能对上。
- 不在入口 README 记逐版本流水账——版本变更看 release。
