# 端到端测试脚本（v0.6.29，MYS-2682）

在 13.24 上运行，经 SSH 隧道访问板子的 `:8000`。每个检查往证据库写一行
`{t, area, check, verdict, evidence}`。`report_tables.py` 把证据库生成报告里的表格。
报告：[`docs/e2e-0.6.29.md`](../../docs/e2e-0.6.29.md)。

## 运行环境

| 变量 / 文件 | 说明 |
|---|---|
| `E2E_BASE` | 服务地址，默认 `http://127.0.0.1:18155`（隧道到板子的 8000） |
| `E2E_WORKDIR` | 工作目录，默认本目录的上一级。里面放 `adminkey`、`inferkey`（管理 / 推理 key，各一行），证据库写到 `ledger.jsonl` |
| `E2E_BOARD_SH` | 在板上执行一条 shell 命令的 SSH 包装脚本（含登录信息，不入库） |
| `E2E_SUDO_PW` | 板上 sudo 密码。脚本里写成 `__SUDO_PW__`，由 `e2e_common.board()` 在执行前替换 |

Python 依赖：`httpx`、`openai`、`mcp`、`playwright`（A6 / A9）。测试素材取自 `cv84x6-demo-ui/tests/data`。

## 脚本

| 大项 | 脚本 |
|---|---|
| A1 安装与升级 | `a1_reinstall.py` |
| A2 模型、设备内存、单模型设置、接管 | `a2_models.py` `a2_vpp.py` `a2_vpp2.py` `a2_settings.py` `a2_cap.py` `a2_takeover.py` `a2_crash.py` |
| A3 `/v1` 对话、队列、辅助模型、PaddleOCR-VL | `a3_chat.py` `a3_queue.py` `a3_aux.py` `a3_vl.py` |
| A4 MCP | `a4_mcp.py`（`--vl` 只跑 VL 模式）`a4_kbread.py` `a4_kbread2.py` |
| A5 知识库应用 | `a5_kb.py` `a5_answer_probe.py` |
| A6 Agent | `a6_agents.py` `a6_opencode.py` `a6_oc2.py` `a6_ui_chat.py` `a6_pico_probe.py` `a6_pico_shot.py` |
| A7 / A8 管理 API、日志与审计 | `a7_a8.py` |
| A9 控制台（10 页 × 桌面亮 / 手机暗） | `a9_console.py` |
| A10 稳定性 | `a10_burst.py` `a10_burst_chat.py` `a10_soak.py <秒> <段名>` `a10_bisect_noasr.py` `a10_bisect_novl.py` |
| RC2 复测 | `rc2_fixes.py` `rc2_d5.py` `rc2_d6.py` `rc2_agent_crash.py` `rc2_kbfix.py` |
| D7 实验 | `d7_cancel.py`（H3：请求中途断开）`d7_h4.py`（H4：推理中 kill -9 主进程）；BSP 的复现脚本 `mys2691_d7_six.py` `mys2691_d7_replay.py`（在板上直接运行） |
| D7 二分与取证（MYS-2693） | `d7_experiment.py`（在板上跑一段受控混载，卡死自动采集并写 `result.json`）`d7_capture.py`（只读取证，**卡死后立刻单独运行**）`d7_drive.py`（在 13.24 上驱动「重启→跑→回收→再重启」的循环） |
| 最终包 | `final_smoke.py` |

`a2_crash.py`、`a2_takeover.py`、`d7_h4.py`、`rc2_d6.py`、`rc2_agent_crash.py` 会 `kill -9` 或重启服务；
`a10_*`、`d7_*` 会让板子满负载运行数分钟。只在专用测试板上运行。

## D7 脚本怎么分工（MYS-2693）

三个脚本各自解决一个不能混在一起的问题：

| 脚本 | 在哪跑 | 什么时候跑 | 做什么 |
|---|---|---|---|
| `d7_experiment.py` | **板上** | 每段实验一次 | 加载指定模型 → 断言每个模型都答 200 → 按 `--load kind:n` 起线程 → 监控 `dmesg`/堆/在飞请求 → 发现卡死立刻调 `d7_capture.py` 并把结论写进 `result.json` |
| `d7_capture.py` | **板上** | 卡死后立刻；也可以随时单独跑 | 纯只读取证：dmesg、sysfs、`/proc/bmtpu/*`、线程状态、`sysrq-w` 内核栈、bm-smi、`/api/stats`、最近 N 分钟的推理记录、worker 日志、版本 |
| `d7_drive.py` | 13.24 | 一组实验一个 `--plan` | 逐段「重启 → 等 `:8000` → 起 `d7_experiment.py` → 轮询 `DONE` → 回收 → 下一段」，状态写 `driver.json`，可断点续跑 |

三条踩过的坑已经写进脚本，改之前先看：

- **板上内核没开 `CONFIG_STACKTRACE`**，`/proc/<pid>/task/*/stack` 根本不存在（不是权限问题）。
  内核栈只能靠 `echo w > /proc/sysrq-trigger`（`d7_capture.py` 的 `blocked.txt`）。
- **`/proc/bmtpu/bmdi_base_info` 和 `bmdi_api_info` 一读就让读的进程 Oops**
  （`otp_reg_read+0x10`，`Internal error: Oops: 96000005`）。已在 `SKIP_PROC` 里排除，别加回去。
- **卡死后 `d7_experiment.py` 不做收尾探针**：卡住的 TPU 会让每个探针等满超时，六个模型
  能把一段实验拖成好几个小时，而结论早就定了。

## 证据库

`ledger/ledger_rc1.jsonl`（RC1）、`ledger/ledger_rc2.jsonl`（RC2 与最终包）是本次运行的原始记录。
重新生成表格：

```
python3 report_tables.py out.md ledger/ledger_rc2.jsonl
```

同一项记录多次时以最后一次为准；首判与终判不同的列入「复判记录」，原因写在终判的证据里。
