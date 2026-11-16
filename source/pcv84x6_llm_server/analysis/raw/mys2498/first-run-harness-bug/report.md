# CV84X6 上下文/并发稳定性测试报告

生成时间（UTC）：2026-10-30T14:52:54Z　·　证据目录：`run-20261030T145254Z/`

## 结论先行

- 核心 20 次（无上下文 10 + 带上下文 10）：**20/20** 正常结束；HTTP 5xx 0 次、4xx 0 次、连接异常 0 次、空回复 0 条。
- 并发 9 次（3 档 × 3 路）：conc-long 3/3，conc-mid 3/3，conc-short 3/3；串话 0 次，标记回显正确 9/9。
- 推理记录一致性：核对 30 条请求，缺失 0、导出中缺失 0、重复 0、输出不一致 0、token 不一致 0、上下文条数不一致 0；直接读 SQLite 命中 30/30。
- 正常重启（`systemctl restart cv84x6-llm`，SIGTERM）：PID `187680` → `309295`，恢复 3.49s，历史记录保留 是，重启后新请求已落盘且一致。
- 验收判定：**通过**

## 环境与版本

| 项 | 值 |
|---|---|
| 设备 | CV84X6 10.43.0.151 (SN HQDZCVEBFJIJA0027, SSH 172.26.166.96:10151) |
| 安装版本 | deb `0.6.13`；`VERSION` 文件 `0.6.13`；服务自报 `/healthz` `0.6.13` |
| 服务状态 | `active`，MainPID `187680`，启动于 `Fri 2026-10-30 21:58:09 CST` |
| `/healthz` | `{"ok": true, "version": "0.6.13", "loaded": 1}` |
| 模型 | `qwen3.6-35b-a3b-32k`，loaded=True，context_length=32768，supports_sampling=False，加载耗时 64.8s |
| 权重文件 | `qwen3.6-35b-a3b-int4-autoround_w4bf16_seq32768_cv84x6_4core_history_dynamic_20261025_014034.bmodel`（20510543872 字节） |
| 内核 | `Linux sophon 5.10.4-9c6431d06-sophon-custom-00610-g9c6431d06798 #1 SMP Tue Oct 27 05:11:06 CST 2026 aarch64 aarch64 aarch64 GNU/Linux` |
| libsophon | `/opt/sophon/libsophon-current/lib/libbmrt.so
/opt/sophon/libsophon-current/lib/libbmrt.so.1.0` |
| 数据目录 | `/data/cv84x6_llm_server` |
| 记录库（测试开始前） | `/data/cv84x6_llm_server/state/inference_records.sqlite3`，1 条，90456 字节 |

服务启动命令（`systemctl show -p ExecStart`）：

```text
{ path=/usr/bin/python3.10 ; argv[]=/usr/bin/python3.10 -m app.main --host ${CV84X6_HOST} --port ${CV84X6_PORT} --backend native --data-root ${CV84X6_DATA_DIR} --env-file ${CV84X6_ENV_FILE} --install-dir /opt/sophgo/cv84x6_llm_server ; ignore_errors=no ; start_time=[Fri 2026-10-30 21:58:09 CST] ; stop_time=[n/a] ; pid=187680 ; code=(null) ; status=0/0 }
```

关键设置（`GET /api/settings`，已去除所有 hash 字段）：

| 设置 | 值 |
|---|---|
| `max_concurrent_per_model` | `2` |
| `max_queue` | `16` |
| `prefix_cache_entries` | `32` |
| `prefix_cache_max_mb` | `2048` |
| `prefix_cache_ttl_min` | `120` |
| `prefill_exact_tail` | `64` |
| `inference_logging_enabled` | `True` |
| `inference_log_retention_count` | `1000` |
| `inference_log_retention_days` | `30` |
| `require_api_key` | `True` |

> 本板 bmodel 的 `supports_sampling` 为 `false`：`lm_head` 只输出 int32，argmax 融在图里，`temperature`/`top_p`/`top_k` **不生效**，解码本身即确定。参数仍按固定值发送并记录，用于保证每次请求形状一致；不要把上表参数当作本机型实际可调的采样手段。

## 测试矩阵与参数

固定参数：`{"max_tokens": 128, "temperature": 0.0, "top_p": 1.0, "top_k": 1, "repetition_penalty": 1.0, "enable_thinking": false}`、`seed=24982496`；核心 20 次串行，每轮完整收到响应（含 `[DONE]`）才发下一轮；system prompt 固定为「你是严谨的中文助手，只按用户的要求简短作答，不要解释。」。长度档是整个 user message 的 Unicode 码点数：`[2, 10, 30, 60, 100, 200, 300, 400, 600, 800]`，每个长度一轮。

| 组 | 轮次 | 输入字数 | SHA-256（前 12） | 期望计数 | 期望回忆 | 上下文消息数 | HTTP | 首 token(s) | 总耗时(s) | prompt/completion/cached | decode_tps | finish_reason | 判分 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| nocxt | 1 | 2 | `35d2f79c4d17` | 0 | - | 2 | 200 | 0.917 | 0.955 | 35/1/0 | 29.051 | stop | 计数✓ |
| nocxt | 2 | 10 | `275473aeb653` | 42 | - | 2 | 200 | 0.501 | 0.572 | 39/2/21 | 29.267 | stop | 计数✓ |
| nocxt | 3 | 30 | `273f36a627c5` | 1 | - | 2 | 200 | 0.965 | 1.003 | 59/1/21 | 29.223 | stop | 计数✓ |
| nocxt | 4 | 60 | `efd7b4100388` | 2 | - | 2 | 200 | 1.433 | 1.473 | 79/1/21 | 28.219 | stop | 计数✓ |
| nocxt | 5 | 100 | `7919d1854bd9` | 3 | - | 2 | 200 | 2.178 | 2.215 | 110/1/21 | 29.025 | stop | 计数✓ |
| nocxt | 6 | 200 | `9a94686d56f7` | 1 | - | 2 | 200 | 3.433 | 3.471 | 198/1/21 | 29.066 | stop | 计数✓ |
| nocxt | 7 | 300 | `ec0adb95097d` | 2 | 竹篮 | 2 | 200 | 2.816 | 2.956 | 273/4/21 | 29.133 | stop | 计数✓ |
| nocxt | 8 | 400 | `411c80ecdfa8` | 3 | 竹篮 | 2 | 200 | 3.578 | 3.683 | 357/3/21 | 29.224 | stop | 计数✓ |
| nocxt | 9 | 600 | `38277218182f` | 1 | 陶罐 | 2 | 200 | 3.87 | 4.013 | 524/4/21 | 28.525 | stop | 计数✓ |
| nocxt | 10 | 800 | `461ee9556285` | 2 | 铜铃 | 2 | 200 | 5.273 | 5.415 | 687/4/21 | 28.998 | stop | 计数✗ |
| cxt | 1 | 2 | `35d2f79c4d17` | 0 | - | 2 | 200 | 0.208 | 0.245 | 35/1/28 | 29.132 | stop | 计数✓ |
| cxt | 2 | 10 | `275473aeb653` | 42 | - | 4 | 200 | 0.644 | 0.715 | 52/2/28 | 29.043 | stop | 计数✓ |
| cxt | 3 | 30 | `273f36a627c5` | 1 | - | 6 | 200 | 1.129 | 1.166 | 90/1/45 | 29.271 | stop | 计数✓ |
| cxt | 4 | 60 | `efd7b4100388` | 2 | - | 8 | 200 | 1.26 | 1.299 | 147/1/64 | 28.761 | stop | 计数✓ |
| cxt | 5 | 100 | `7919d1854bd9` | 3 | - | 10 | 200 | 1.866 | 1.903 | 235/1/128 | 29.163 | stop | 计数✓ |
| cxt | 6 | 200 | `9a94686d56f7` | 1 | - | 12 | 200 | 2.099 | 2.138 | 411/1/192 | 28.814 | stop | 计数✓ |
| cxt | 7 | 300 | `ec0adb95097d` | 2 | 竹篮 | 14 | 200 | 2.28 | 2.318 | 662/1/384 | 28.649 | stop | 计数✓ 回忆✗ |
| cxt | 8 | 400 | `411c80ecdfa8` | 3 | 竹篮 | 16 | 200 | 2.996 | 3.033 | 997/1/640 | 29.27 | stop | 计数✓ 回忆✗ |
| cxt | 9 | 600 | `38277218182f` | 1 | 陶罐 | 18 | 200 | 3.782 | 3.821 | 1499/1/960 | 28.574 | stop | 计数✓ 回忆✗ |
| cxt | 10 | 800 | `461ee9556285` | 2 | 铜铃 | 20 | 200 | 5.119 | 5.157 | 2164/1/1472 | 28.415 | stop | 计数✓ 回忆✗ |

## 成功率与分布（min / median / max）

| 组 | 请求 | 成功 | 成功率 | 空回复 | 首 token(s) | 总耗时(s) | decode_tps | prompt tokens | completion tokens | cached tokens | 计数正确 | 回忆正确 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conc-long | 3 | 3 | 1.0 | 0 | 6.578 / 8.287 / 12.483 | 6.793 / 8.463 / 12.661 | 23.948 / 28.694 / 29.137 | 511 / 512 / 513 | 5 / 5 / 5 | 0 / 0 / 0 | 1/3 | 0/- |
| conc-mid | 3 | 3 | 1.0 | 0 | 3.325 / 4.731 / 7.147 | 3.538 / 4.906 / 7.321 | 24.007 / 29.234 / 29.244 | 175 / 178 / 179 | 5 / 5 / 5 | 0 / 0 / 0 | 3/3 | 0/- |
| conc-short | 3 | 3 | 1.0 | 0 | 2.776 / 3.166 / 4.837 | 2.989 / 3.342 / 5.012 | 23.919 / 29.072 / 29.111 | 60 / 60 / 64 | 5 / 5 / 5 | 0 / 0 / 0 | 3/3 | 0/- |
| cxt | 10 | 10 | 1.0 | 0 | 0.208 / 1.982 / 5.119 | 0.245 / 2.021 / 5.157 | 28.415 / 28.929 / 29.271 | 35 / 323 / 2164 | 1 / 1 / 2 | 28 / 160 / 1472 | 10/10 | 0/4 |
| nocxt | 10 | 10 | 1.0 | 0 | 0.501 / 2.497 / 5.273 | 0.572 / 2.586 / 5.415 | 28.219 / 29.059 / 29.267 | 35 / 154 / 687 | 1 / 1.5 / 4 | 0 / 21 / 21 | 9/10 | 0/- |
| restart | 1 | 1 | 1.0 | 0 | 0.95 / 0.95 / 0.95 | 0.99 / 0.99 / 0.99 | 28.898 / 28.898 / 28.898 | 37 / 37 / 37 | 1 / 1 / 1 | 0 / 0 / 0 | 1/1 | 0/- |

错误分类（按组）：

| 组 | 错误类型 | 次数 |
|---|---|---|
| — | 无 | 0 |

> 两组不构成性能 A/B：带上下文组每轮重发全部历史，prompt token 必然更大。上表只用于判断服务是否稳定、时延是否出现异常长尾。

## 并发组（3 档 × 3 路独立请求）

| 组 | 档位字数 | 请求 | 成功 | 标记回显 | 串话 | 总耗时(s) | decode_tps | prompt tokens |
|---|---|---|---|---|---|---|---|---|
| conc-short | 60 | 3 | 3 | 3/3 | 0 | 2.989 / 3.342 / 5.012 | 23.919 / 29.072 / 29.111 | 60 / 60 / 64 |
| conc-mid | 200 | 3 | 3 | 3/3 | 0 | 3.538 / 4.906 / 7.321 | 24.007 / 29.234 / 29.244 | 175 / 178 / 179 |
| conc-long | 600 | 3 | 3 | 3/3 | 0 | 6.793 / 8.463 / 12.661 | 23.948 / 28.694 / 29.137 | 511 / 512 / 513 |

## 重启恢复

- 方式：`systemctl restart cv84x6-llm`（SIGTERM，未使用任何强杀手段）。
- MainPID：`187680` → `309295`，`/healthz` ok 耗时 3.49s；重启后重新登录 HTTP 200。
- 模型 `qwen3.6-35b-a3b-32k` 重新加载：HTTP 200，耗时 64.94s；从 restart 到可服务合计 68.44s。
  > 该服务没有开机自动加载模型：`systemctl restart` 后 worker 需要重新加载，因此「重启恢复」包含这一步，时间也照实计入。
- 记录数：重启前 30 → 重启后 30；历史记录保留 是。
- 重启后短请求（30 字）：HTTP 200，输出「1」，记录已落盘且与服务响应一致。
- 重启时间窗内的 `journalctl` 已存为 `journal-restart.log`。

## 推理记录一致性

- 管理 API 逐条按 `req_id` 核对：检查 30 条；详情缺失 0、导出中缺失 0、导出中重复 0、来源不符 0、状态非 `ok` 0。
- 字段比对：输入文本不一致 0、输出文本不一致 0、token 不一致 0、上下文消息数不一致 0。
- NDJSON 导出 31 行，逐行按 id 计数核对。
- 直接读 SQLite（`mode=ro`）：文件存在，94208 字节，可读=True，按 id 命中 30/30。
- 记录内是否出现原始 API key：未出现。

## 验收判定

| 判据 | 值 |
|---|---|
| `core_20_ok` | `True` |
| `concurrent_all_ok` | `True` |
| `some_answer_correct` | `True` |
| `sqlite_readable` | `True` |
| `restart_ok` | `True` |
| `records_missing` | `0` |
| `records_missing_from_export` | `0` |
| `records_duplicated` | `0` |
| `records_output_mismatch` | `0` |
| `records_metrics_mismatch` | `0` |
| `records_context_mismatch` | `0` |
| `records_input_mismatch` | `0` |
| `records_not_ok` | `0` |
| `records_source_mismatch` | `0` |
| `secret_leaks` | `0` |
| `http_5xx` | `0` |
| `empty_outputs` | `0` |
| `cross_talk` | `0` |
| `sqlite_missing` | `0` |
| `sqlite_output_mismatch` | `0` |
| `count_graded` | `20` |
| `count_correct` | `19` |
| `count_accuracy` | `0.95` |
| `passed` | `True` |

## 证据清单

| 文件 | 内容 |
|---|---|
| `rounds.jsonl` | 每轮一行机器可读数据（30 行，含失败行） |
| `manifest.json` | 每条 prompt 的全文、字符数、SHA-256、期望答案与 seed |
| `summary.json` | 上面表格的原始数字与验收判定 |
| `records-export.ndjson` | 服务导出的全部记录 |
| `records-check.json` | 逐条记录一致性核对结果 |
| `sqlite-check.json` | 直接读记录库的结果 |
| `env.json` | 版本、模型、设置、设备快照 |
| `raw/*.sse` | 每个请求的原始 SSE 响应体（失败也保留） |
| `journal-test.log` | 测试时间窗内的服务日志 |
| `journal-restart.log` | 重启时间窗内的服务日志 |
| `dmesg.txt` | 测试结束时的内核日志（检查 NPU 报错） |

重跑参数：`seed=24982496`、模型 `qwen3.6-35b-a3b-32k`；prompt 由 `tools/board_stability_suite.py` 的 `build_prompt` 按 seed 确定性生成，同一 seed 下可用 `manifest.json` 逐字复核。重跑会新建 `run-*` 目录，不覆盖本次证据。
