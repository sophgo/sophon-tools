# `.151` 上下文/并发稳定性实测（MYS-2498）

本目录是 `tools/board_stability_suite.py` 在 `10.43.0.151` 上的真实运行数据。
两次运行都保留，因为它们回答的是不同问题：

| 目录 | 结论 |
|---|---|
| `verified-run/` | **正式结果**。核心 20/20、并发 9/9、重启恢复、记录 30/30 一致，判定 PASS |
| `first-run-harness-bug/` | 第一次运行：机械指标同样全绿，但「回忆」4 轮全错 → 判定 **未通过**。**是测试工具自身的 prompt 矛盾，不是模型或服务的问题**，见下文 |

保留失败的那次是刻意的：它是这套工具唯一一次暴露自身 bug 的证据，删掉就等于把
「我们怎么知道它不是每次都这样」这个问题留空。

> 注：第一次运行发生时，工具的判定口径里还没有「回忆下限」，所以它当时判了 PASS。
> 事后补上 `some_recall_correct`（只对真正问了回忆的轮次生效）后重新计分，这次运行
> 判定为 **未通过** —— 这正是加这条下限的理由：0/4 的回忆不该被判绿。`summary.json`
> 里存的是**重新计分后**的判定，`report.md` 是当时生成的、仍写着 `通过`，两者不一致是
> 有意的，用来标明口径变更的时间点。

## 设备与版本

| 项 | 值 |
|---|---|
| 设备 | `10.43.0.151`（hostname `sophon`，`eth0 = 10.43.0.151/24`，SSH `linaro@172.26.166.96:10151`） |
| 安装包 | `cv84x6-llm-server 0.6.13`（deb），`/opt/sophon/cv84x6_llm_server/VERSION` = `0.6.13` |
| 模型 | `qwen3.6-35b-a3b-32k`，32k 配置，`supports_sampling=false`，加载 64.9 s |
| 权重 | `qwen3.6-35b-a3b-int4-autoround_w4bf16_seq32768_cv84x6_4core_history_dynamic_20261025_014034.bmodel`，MD5 `1178646a93a3ec0786e9de77ba57d6dd`（运行后校验仍 `OK`） |
| libsophon | `/opt/sophon/libsophon-current/lib/libbmrt.so.1.0`（`bm-smi` 自报 SDK / Driver 0.4.15） |
| 数据目录 | `/data/cv84x6_llm_server`（未迁移、未清空） |
| 内核 | `5.10.4-9c6431d06-sophon-custom-00610-g9c6431d06798`（aarch64，见 `env.json` 的 `kernel` 原值） |
| 服务 | `cv84x6-llm` active/enabled，`require_api_key=true`，`inference_logging_enabled=true`，保留 1000 条 / 30 天 |

设备身份由负责人安装前及验收时实测 `/factory/OEMconfig.ini` 确认：其中 `SN` 与 `DEVICE_SN`
均为 `HQDZCVEBFJIJA0027`。本次同时核对 `eth0 = 10.43.0.151/24` 和
`172.26.166.96:10151` 端口映射，全程仅访问该设备。`/proc/device-tree/serial-number`
与 eMMC CID 读到的 `9b01005931593036340064f4791ccc00` 是另一种硬件标识，不能据此否定出厂配置中的 SN。

关键前提：本板 bmodel 的 `lm_head` 只输出 int32、argmax 融在计算图里，因此
`supports_sampling=false`，**`temperature`/`top_p`/`top_k` 不生效**。工具仍按固定值发送并记录，
是为了让每次请求形状一致、记录可比；报告里不会把这些参数说成实际可调。

## 测试矩阵（固定参数）

```
max_tokens=128  temperature=0  top_p=1  top_k=1  repetition_penalty=1
enable_thinking=false  seed=24982496   system prompt 固定
```

长度档 = 整条 user message 的 Unicode 码点数：`2, 10, 30, 60, 100, 200, 300, 400, 600, 800`，每档一轮。
核心 20 次串行，每轮收完 `[DONE]` 才发下一轮。

任务设计：每条 prompt 要求数出材料里某个词出现几次。期望答案由生成器算出，
且材料保证被数的词**不出现在其他词内部**（否则「帆布」藏在「旧帆布包」里，
数对了和数糊了分不开）。2 字与 10 字档装不下词表，退化为固定指令（`答0`、`只回答这个数字：42`）。

60 字档起每轮写一句「本轮记录编号R<n>，关键词：X。」；300 字档起额外要求回答更早一轮的关键词，
所以带上下文组的「回忆」只能从历史里得到。

## 正式结果（`verified-run/`，运行于 2026-10-30T15:04:49Z）

### 核心 20 次

| 组 | 请求 | 正常结束 | 5xx / 4xx | 连接异常 | 空回复 | 计数正确 |
|---|---|---|---|---|---|---|
| `nocxt`（无上下文） | 10 | 10 | 0 / 0 | 0 | 0 | **10/10** |
| `cxt`（带上下文 10 轮） | 10 | 10 | 0 / 0 | 0 | 0 | 9/10 |

回忆正确 **4/4**（300 / 400 / 600 / 800 字档各一轮，分别答出 `竹篮`、`竹篮`、`陶罐`、`铜铃`）。
唯一一次计数错误在第 8 轮（400 字档，答 `4`，应为 `3`），同一轮回忆仍答对。
这是模型自身的计数错误，如实报告，未重跑覆盖。

### 延迟与 TPS（min / median / max，取自推理记录里的 `first_token_latency_s` 与 `decode_tps`）

| 组 | 首 token (s) | 总耗时 (s) | decode_tps | prompt tokens | completion tokens | cached tokens |
|---|---|---|---|---|---|---|
| `nocxt` | 0.492 / 2.507 / 5.313 | 0.575 / 2.61 / 5.475 | 28.14 / 29.08 / 29.34 | 35 / 154 / 692 | 1 / 1.5 / 4 | 0 / 21 / 21 |
| `cxt` | 0.198 / 1.959 / 4.357 | 0.25 / 2.027 / 4.66 | 26.80 / 29.00 / 29.27 | 35 / 323 / 2188 | 1 / 1.5 / 4 | 28 / 160 / 1472 |
| `conc-short` | 2.756 / 3.14 / 4.808 | 2.986 / 3.337 / 5.007 | 24.09 / 29.30 / 29.39 | 60 / 60 / 64 | 5 / 5 / 5 | 0 / 0 / 0 |
| `conc-mid` | 3.365 / 4.77 / 7.131 | 3.599 / 4.966 / 7.335 | 23.98 / 28.61 / 29.28 | 175 / 178 / 179 | 5 / 5 / 5 | 0 / 0 / 0 |
| `conc-long` | 6.575 / 8.281 / 12.48 | 6.813 / 8.483 / 12.68 | 23.92 / 29.21 / 29.30 | 511 / 512 / 513 | 5 / 5 / 5 | 0 / 0 / 0 |
| `restart` | 0.933 | 1.009 | 28.99 | 37 | 1 | 0 |

带上下文组的 prompt token 随轮次增长（35 → 2188），`cached_tokens` 最高 1472，
证明前缀缓存命中；4/4 回忆正确则提供历史信息被正确使用的证据。两类证据互不替代。
这**不是**性能 A/B：两组输入规模本来就不同，上表只用于判断稳定性与长尾。

### 并发 9 次（3 档 × 3 路同时）

| 组 | 档位 | 请求 | 成功 | 标记回显 | 串话 | 总耗时 (s) | 计数正确 |
|---|---|---|---|---|---|---|---|
| `conc-short` | 60 字 | 3 | 3 | 3/3 | 0 | 2.99 / 3.34 / 5.01 | 3/3 |
| `conc-mid` | 200 字 | 3 | 3 | 3/3 | 0 | 3.60 / 4.97 / 7.34 | 3/3 |
| `conc-long` | 600 字 | 3 | 3 | 3/3 | 0 | 6.81 / 8.48 / 12.68 | 1/3 |

每路请求带唯一字母标记（`KXAA` … `KXCC`），全部原样回显，且**没有任何一路拿到别的标记** ——
在 `max_concurrent_per_model=2` 的排队下也没有串话。`conc-long` 的 3 路里 2 路计数错（答 3 / 4），与核心组 400 字档同为词项计数错误；
本次未定位具体数值根因，不能据此归因于并发或服务。
并发下首 token 明显变长（2.8–12.5 s，单流是 0.2–5.3 s），符合 2 路并发的排队预期。

### 重启恢复

`sudo systemctl restart cv84x6-llm`（SIGTERM，未使用任何强杀）：

- MainPID `318133` → `338984`，`/healthz` ok 用时 **3.47 s**。
- 该服务没有开机自动加载模型，`restart` 后 `loaded=0`，需重新加载：**64.9 s**。
  从 restart 到真正可服务合计约 **68 s**。报告把这步照实计入，不把 healthz 恢复当可服务时间。
- 记录数重启前 100 → 重启后 100，**历史记录全部保留**；重启后短请求（30 字）HTTP 200、输出 `1`，
  记录已落盘且与客户端响应逐字一致。

### 推理记录一致性

- 30 条测试请求（20 核心 + 9 并发 + 1 重启后）逐条按 `req_id` 核对：
  **缺失 0、导出中缺失 0、重复 0、来源不符 0、状态非 ok 0**。
- 字段比对：输入文本不一致 0、输出文本不一致 0、token 不一致 0、上下文消息数不一致 0。
- 直接以只读 URI 打开 `/data/cv84x6_llm_server/state/inference_records.sqlite3`：命中 30/30。
- 记录内**未出现**原始 API key。
- NDJSON 导出当时共 101 行（含此前 `MYS-2496-acceptance` 那条、两次正式运行与排查用的 recall probe），
  逐行按 id 计数核对；`by source` 全部是 `/v1/chat/completions`。
- 最早一条记录仍是 `bfa4e6bcd59842dbbd541de5ccf4ddef`（`MYS-2496-acceptance`，14:13:08Z）——
  既有证据没有被破坏。

### 安装前状态与保留验证

安装前快照在设备 `/data/stability/pre-run/`（`state.json` 备份、设置摘要、模型 MD5、服务状态）。
运行后复核：

- 设置项与运行前**逐项一致**（含 `inference_logging_enabled=true`、保留 1000 条 / 30 天）。
- 权重 MD5 校验 `OK`，模型未被替换。
- `MYS-2496-acceptance` key 仍在（`requests=1`），未被删除、未被本任务使用。
- 本任务自建的 `MYS-2498-stability` key 在运行结束时删除（`DELETE /api/keys/... 200`）。

### 浏览器控制台核对

真实 Chromium（Playwright）经 SSH 隧道只读访问板上控制台，「推理记录」页：

- 页面渲染、登录、50 行列表、隐私说明、记录库状态（路径 / 条数 / 保留策略）均正常；
- 无 console error、无失败请求、1440px 下无横向溢出；
- 打开 `restart` 组那条记录（`584d183791af4e5c96c1487227c89be3`）详情，页面显示的请求 id、
  输入消息（`第201轮。数「风箱」出现几次，只答数字。材料：硬纸板、风箱`）、输出（`1`）、
  `prompt/completion = 37/1`、`TTFT 0.92s`、`TPS 29.0` 与实际请求一致；
- 截图 `console-record-detail.png`、`console-records-list.png`；
  脚本 `tools/probe_records_console.mjs`，通过项见 `browser-check-*.json`。

### dmesg

测试结束后 `dmesg` 中 `wait api timeout` / `bdc_reg_read` / oops 计数为 **0**，无 NPU 异常。
尾部的 `cv84x2-dvfs ... volt_write readback mismatch` 与 `systemd-journald Failed to set ACL`
是开机阶段既有告警（时间戳在 boot 后 10–31 s），与本次测试无关。

## 第一次运行：工具自身的 bug（`first-run-harness-bug/`）

第一次运行机械指标全绿（20/20、并发 9/9、记录 29/29 一致），但**回忆 0/4**，
四轮回忆输出都是纯数字。原因不在模型：

- 300 字档的 prompt 同时问了两件事（数词 + 第 4 轮关键词），
- 但回复格式仍写着「**只回答数字**」。

模型遵守了格式要求（这是正确读法），第二个问题于是永远拿不到答案。**是 prompt 自相矛盾，
不是模型不听话，也不是服务丢历史。** 判断依据是四次输出的形态完全一致（只有数字），
而不是「模型答不出来」的随机表现。

修正分两层：

1. **prompt**：一轮问两件事时，格式改成「请分两行回答：第一行只写出现次数，第二行只写第 N 轮的关键词」；
   只问一件事时保持「只回答数字」。修正后在真机上回忆 **4/4** 正确，同时 400 字档仍出现一次真实的计数错误——
   说明修好的是工具，模型的边界也照实暴露出来了。
2. **判定口径**：原判定只看「至少一条计数正确」，回忆 0/4 也能判 PASS，这正是这个 bug 能混过去的原因。
   现补上 `some_recall_correct`（仅在本次运行真的有回忆轮次时生效）：回忆全错时，要么模型没用历史、
   要么工具坏了，两种都不该是「通过」。用新口径重算第一次运行，判定从 PASS 变为 **未通过**。

回归测试 `tests/test_board_stability_suite.py::test_a_turn_that_asks_two_questions_never_says_only_answer_one`
把「问题数必须与格式要求一致」钉住，防止再犯。

## 复现

```sh
# 板上（纯标准库，无第三方依赖）
python3 tools/board_stability_suite.py \
    --evidence-dir /data/stability/evidence \
    --data-dir /data/cv84x6_llm_server \
    --device-label "CV84X6 10.43.0.151" \
    --restart --timeout 900

# 控制台核对（需 Playwright，仅主机侧）
node tools/probe_records_console.mjs --base http://127.0.0.1:18800 \
    --out ./records-out --record-id <req_id> \
    --playwright /path/to/node_modules/playwright
```

每次运行新建 `run-<UTC>/`，不覆盖既有证据。`raw/*.sse`（每个请求的原始响应体，约 120 KB）
留在设备 `/data/stability/evidence/` 上未入仓；需要时按 `rounds.jsonl` 的 `req_id`
对应 `records-export.ndjson` 即可完整复核。
