# 验证工具索引

这里的脚本都**不在发布包里**（打包只带 `engine_check.py`、`e2e_check.py`、`cache_check.py`、
`cache_e2e.py`、`stress_check.py`、`vl_embed/service_check.py`），也不被 `app/` 引用。它们回答的是「这版本在真机上对不对」，
不是「单元逻辑对不对」——后者在 `tests/`。

多数脚本要在板上跑（链 `libsophon`、读真实 bmodel），少数是纯主机侧一致性检查，任何机器都能跑。
每篇的 `--help` 与文件头写了前提与参数。

## 服务冒烟与端到端

| 工具 | 需要 | 用途 |
|---|---|---|
| `e2e_check.py` | 板上跑着的服务 | 发布验收：加载模型、签发 key、把 OpenAI 接口与并发都过一遍 |
| `vl_embed/service_check.py` | 板上待测发行包、空闲 NPU | 隔离的多模态 embedding HTTP 验收；`--catalog-id wemm-embedding-2b` 增加真实 dfss 下载、摘要与内置配置验证，见 [WeMM 文档](../docs/wemm-embedding.md#目录下载端到端验收) |
| `takeover_e2e.py` | 两个服务进程 | 重启场景：真的重启服务，验证 worker 与 agent 被接管而不是重启一份 |
| `stress_check.py` | 板上跑着的服务 | 长上下文、并发、浸泡；逐项打印 PASS/FAIL |
| `cache_e2e.py` | 板上跑着的服务 + history bmodel | 前缀缓存验收：长 system prompt + 三轮重发全历史，打印命中 token 数 |
| `cache_check.py` | 引擎库 + history bmodel | 引擎级：分块 prefill、extend、快照/恢复、长文档召回 |
| `board_stability_suite.py` | 板上跑着的服务（**纯标准库**） | 上下文/并发稳定性：2–800 字定长自校验对话 20 次 + 并发 9 次 + 重启恢复，逐轮留证据，见下节 |
| `extended_stability_suite.py` | 板上跑着的服务（**纯标准库**） | 扩大稳定性（MYS-2501）：2–1200 字、无上下文/带上下文各 1000 次 + 并发 2×50 + readiness 专项，输出单文件 HTML 报告，见后文 |
| `comprehensive_stability_suite.py` | 板上跑着的服务（**纯标准库**） | 全方位稳定性（MYS-2510/MYS-2521）：16k–96k **token** 长上下文、连续对话 2k–16k 档位、UTF-8 回归、并发/队列、取消与协议、缓存/生命周期、VLM/工具、2 小时浸泡，逐维度判定 + 单文件 HTML 报告，见后文 |
| `legacy_readiness_probe.py` | 板上跑着的**旧版**服务（**纯标准库**） | 加载竞态：在多个加载时机实测「模型没加载完就推理」的真实结果，含 ready 对照，出单文件 HTML，见下文

## 性能与缓存

| 工具 | 需要 | 用途 |
|---|---|---|
| `engine_check.py` | 引擎库 + bmodel | 绕过 HTTP 与调度器直接驱动 `NativeBackend`，打印 FTL/TPS |
| `decode_bench.py` | 引擎库 + bmodel | 单流 decode 基准（C API，无 Python 后端） |
| `session_bench.py` | 引擎库 + bmodel | 多会话交替 decode、快照与 restore→extend 一致性 |
| `decode_quantum_ab.py` | 真 worker | decode 时间片 A/B：q=1 对 q=8，逐 token 比对输出 |
| `decode_quantum_smoke.py` | 真 worker | 高频并发冒烟：多轮 wave 下时间片的行为与稳定性 |

## 预填充研究

| 工具 | 需要 | 用途 |
|---|---|---|
| `prefill_width_probe.py` | 引擎库 + bmodel | 一次动态预填充发射：实际宽度、是否存活、TTFT |
| `prefill_ab_eval.py` | 引擎库 + bmodel | 对齐 64 vs 16 的回答正确率 A/B |
| `prefill_row_probe.py` | 引擎库 + bmodel | 一条 prompt 实际跑了多少行预填充、回放多少行 |
| `gen_prefill_probe_prompts.py` | 引擎库 + tokenizer | 生成 / 校验预填充探针用的真实 prompt id 文件 |

用例数据在 `prefill_probe_prompts/` 与 `prefill_ab_cases/`（含 `logs/` 与 `low/` 两套 40 条）。
结论见 [`../docs/research/`](../docs/research/README.md)。

## 精度与一致性（纯主机侧）

| 工具 | 需要 | 用途 |
|---|---|---|
| `tok_check.cpp` | 无板卡 | 分词器对 `tests/tokenizer_golden.json` 逐条比对 |
| `vision_check.cpp` | 无板卡 | 图像预处理对 `tests/vision_golden.json` 逐元素比对 |
| `resize_check.cpp` | 无板卡 | 双三次缩放单独对 Pillow 输出比对 |
| `gen_tokenizer_golden.py` / `gen_vision_golden.py` | Python `tokenizers`、torch/Pillow | 重新录制上面两个 golden 文件 |
| `gen_unicode_tables.py` | 无板卡 | 从 `unicodedata` 重新生成 `native/include/unicode_tables.h` |
| `precision/` | 板卡 + HF 参考实现 | 定位预填充 MoE 的数值误差，见 `precision/README.md` |
| `embed/` | 编译机 + 板卡 | Qwen3-Embedding 的 bmodel 编译、换 seq 的精度/耗时对比与建库回归，见 `embed/README.md` |
| `qwen35_hf_ref.py` | x86 + torch | 稠密 Qwen3.5 的 x86 greedy 参照（13 条中英文提示词 × 128 token），见 `../docs/qwen35-small.md` |
| `qwen35_board_run.py` | 板卡 + 引擎库 + bmodel | 同样输入的板上 greedy 输出，直接驱动 C API，不经 HTTP |
| `qwen35_compare.py` | 任意（纯标准库） | 逐 token 一致率与**首个分歧点**，区分「中途翻一个 token 又收敛」和「第一步就岔开」 |
| `qwen35_bench.py` | 板卡 + 引擎库 + bmodel | 加载耗时、静态占用、decode tok/s、短/8k TTFT、双会话 |
| `qwen35_prompts.json` | — | 上面三个工具的提示词集合（含一条带图） |

## UI / 运维（需浏览器）

| 工具 | 用途 |
|---|---|
| `ops_accept_server.py` | 用**故意慢**的加载跑真实服务，供浏览器在中途刷新 |
| `ops_refresh_browser_check.py` | 真实浏览器里点「加载」后刷新页面，验证锁来自后端 |
| `ops_agent_browser_check.py` | agent 安装/启停的操作锁，跨刷新验证 |
| `probe_console_agents_ui.py` | Agent 页：凭据是可选中的明文、iframe 可内嵌、「打开」可用 |
| `probe_console_readonly_proxy.py` | 只把读请求转发到真板卡，用来给新控制台截图 |
| `probe_opencode_prefix.py` | 用真 opencode 二进制走真代理，断言页面渲染且无 4xx |

`ops_refresh_browser_check.py`、`ops_agent_browser_check.py`、`probe_console_agents_ui.py`、
`probe_opencode_prefix.py` 需要 Playwright（不在 `package.json` 里，按需
`npm install --no-save playwright`）；`probe_opencode_prefix.py` 另需官方 opencode 包。
控制台的整体浏览器验收另见 [`../web/acceptance/README.md`](../web/acceptance/README.md)。

## 上下文/并发稳定性（`board_stability_suite.py`）

回答的是「这个版本在板上连续对话 10 轮、再并发几路，还稳不稳，证据能不能自证」。
只用标准库（板上没 httpx），拷到板上直接跑：

```sh
python3 tools/board_stability_suite.py --evidence-dir /data/stability --restart
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--base` | `http://127.0.0.1:8000` | 服务地址 |
| `--password` | `$CV84X6_ADMIN_PASSWORD` 或 `admin` | 控制台管理员密码，用于登录与建 key |
| `--evidence-dir` | `./stability-evidence` | 每次运行新建 `run-<UTC时间>/`，**不覆盖**已有目录 |
| `--data-dir` | `/data/cv84x6_llm_server` | 数据目录；用于直接读记录库与列模型文件 |
| `--model` | 已加载的模型 | 显式指定，防止测到另一个模型 |
| `--api-key` | 无（自建） | 复用已有 key；自建的 key 跑完会删除 |
| `--timeout` | 1800 s | 单请求超时（800 字 + 长上下文首 token 不快） |
| `--restart` | 关 | 跑完核心 20 次后 `sudo -n systemctl restart` 并重新加载模型 |

### 四组请求

| 组 | 次数 | 内容 |
|---|---|---|
| `nocxt` | 10 | 独立请求，只有 system + 当前 user message，长度 2/10/30/…/800 字各一次 |
| `cxt` | 10 | 同一逻辑会话连续 10 轮，每轮 messages = system + 此前全部 user/assistant + 当前输入 |
| `conc-short/mid/long` | 3×3 | 60/200/600 字档各 3 路**同时**发出，各自带唯一字母标记 |
| `restart` | 1 | 重启并重新加载模型后发一个 30 字请求 |

固定参数：`max_tokens=128`、`temperature=0`、`top_p=1`、`top_k=1`、
`repetition_penalty=1`、`enable_thinking=false`、固定 `seed`；核心 20 次**串行**，
每轮收完 `[DONE]` 才发下一轮。

需要注意：本板 bmodel 的 `supports_sampling` 是 **false**（`lm_head` 只出 int32，
argmax 融进图里），所以 `temperature`/`top_p`/`top_k` 实际**不生效**，解码本来就是确定的——
这正好让「数词」任务能判分。参数照发照记，是为了让每次请求形状一致、记录可比，
也让同一套工具指向真正支持采样的模型时仍然固定为贪心。`env.json` 会记录实测的
`supports_sampling`，报告不会把没生效的参数说成生效了。

### prompt 为什么能自己判分

每条 prompt 的正文长度精确等于它的档位（Unicode 码点数），由 seed 确定性生成，
`manifest.json` 里存全文 + SHA-256。任务是「下面材料里 W 出现了几次，只答数字」，
期望答案由生成算法自己算出来；材料里**其他词都不会包含 W**，所以「数对了」和
「糊弄过去了」能分开。2 字与 10 字档装不下词表，退化成固定指令（`答0`、
`只回答这个数字：42`），答案依然是可机械核对的定值。

从 60 字档起每轮还会写一句「本轮记录编号R<n>，关键词：X。」；从 300 字档起额外问
「第 m 轮的记录关键词是什么？」。带上下文组从历史里答对才算通过——这才是「历史
真的被用了」，而不只是消息条数在涨。

### 留什么证据

| 文件 | 内容 |
|---|---|
| `report.md` | 人读的报告：环境/版本/参数/完整矩阵/成功率/延迟与 TPS 分布/并发/重启/记录一致性/验收判定 |
| `rounds.jsonl` | 每轮一行，含 HTTP 状态、首 token、总耗时、token、finish_reason、输出、错误、判分 |
| `manifest.json` | 每条 prompt 的全文、字符数、SHA-256、期望答案、seed |
| `summary.json` | 上面各表的原始数字与验收判定 |
| `records-export.ndjson` | 服务导出的全部推理记录 |
| `records-check.json` / `sqlite-check.json` | 逐条记录一致性（管理 API 与直接读 SQLite 各一份） |
| `raw/*.sse` | 每个请求的原始 SSE 响应体，**失败也保留** |
| `env.json` | 版本、模型、设置（已剔除 hash）、设备快照 |
| `journal-test.txt` / `journal-restart.txt` / `dmesg.txt` | 只看本测试时间窗的服务日志与内核日志尾部 |

### 几条容易踩的

- **失败不重试**：任何失败都会原样落进 JSONL 与 `raw/`，重跑是新目录，不覆盖旧证据。
- **`--restart` 会重新加载模型**：本服务没有开机自动加载，`systemctl restart` 后
  `/healthz` 的 `loaded` 是 0，报告里的「恢复时长」把重新加载也算进去。
- **记录核对是双向的**：既走管理 API，也直接用只读 URI 打开
  `state/inference_records.sqlite3` 比对 `output_text`；API 说一致而磁盘上没有同样算失败。
- 组间不要当性能 A/B 看：带上下文组每轮重发全历史，prompt token 必然更大。

## 扩大稳定性（`extended_stability_suite.py`，MYS-2501）

回答的是「这个版本在 128k 模型上连续跑 2100 次，还稳不稳，而且模型加载没完成时
请求到底进不进得去」。它**复用** `board_stability_suite.py` 的 prompt 生成器、SSE
解析、记录核对与统计，不复制实现；MYS-2498 的 20+9 矩阵仍由原工具跑，行为不变。

```sh
python3 tools/extended_stability_suite.py --evidence-dir /data/stability/evidence \
    --model qwen3.6-35b-a3b-128k --readiness
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--base` / `--password` / `--data-dir` | 同上 | 与服务通信、直接读记录库 |
| `--evidence-dir` | `./stability-evidence` | 新建 `run-<UTC时间>/`，不覆盖 |
| `--model` | 已加载模型 | 显式指定 |
| `--api-key` / `--key-name` | 自建 `MYS-2501-stability` | 自建的 key 跑完删除 |
| `--seed` | `24982496` | 改动即换掉全部 prompt |
| `--sample-interval` | 5 s | 设备/worker 采样间隔 |
| `--skip-core` | 关 | 跳过 2000 次核心请求（readiness 专用的复跑） |
| `--readiness` | 关 | 核心组跑完后做停止/重载的 readiness 专项 |
| `--load-timeout` | 900 s | 重新加载模型的超时 |

### 矩阵

| 组 | 次数 | 构成 |
|---|---|---|
| `nocxt` | 1000 | 独立请求，system + 当前 user。长度档 2/10/30/…/1200 共 12 档，**连续循环**：83 整轮 × 12 档 = 996，再补最短 4 档各 1 次 → 前 4 档 84 次、其余 83 次，合计正好 1000 |
| `cxt` | 1000 | **100 个独立会话 × 每会话 10 轮**（不是 1000 轮同一会话）。每轮重发该会话全部历史；每会话长度档 = 2/10/30/…/800 |
| `conc` | 100 | **2 路 × 50 轮**，独立统计，不并入核心数字；每请求唯一字母标记，查标记回显与记录隔离 |
| `readiness` | 依加载时长 | 正常停止（SIGTERM）→ 重新加载 → 加载窗口内对三个接口反复探测 |

两个核心组的前 10 个请求**输入逐字相同**（`nocxt` 的第 i 个循环请求 == 任一 `cxt`
会话的第 i 轮的新 user message），所以两组之间唯一的差异就是历史——这一点在单测里
逐字断言，不是"差不多"。

### readiness 专项判什么

服务端能力探测完成前不得接受推理。所以窗口内：

- 三个接口（`/v1/chat/completions` 的 stream 与非 stream、`/api/chat/stream`）
  每一次尝试都必须是 **409**；被放行 1 次即判失败。
- 新 worker 就绪时它自己的 `total_requests`（generate 计数）必须还是 **0**——
  这是"请求有没有真的进到模型"的答案，HTTP 状态只回答"客户端有没有被告知不行"。
- 记录总数在窗口内不得增加（**0 条**）。
- 加载完成后发一个短请求：必须 **200**，且新增**恰好 1 条**记录。

探测是**观测**，不是伪造 loading 状态；并且只走正常停止 + 重新加载，不做任何强杀。

注意：worker 的 generate 计数用的是"新 worker 就绪时的绝对值"而不是前后相减——
重新加载会换进程，新进程从 0 开始，相减会得到没有意义的负数。

### 报告

输出单个 **自包含 HTML**（`report.html`），四个分页：

1. **整体结论** —— 成功率、判定、readiness 明细、环境/版本/矩阵/参数。
2. **测试时间线** —— 阶段与异常逐条带时间戳，附设备与 worker 采样。
3. **性能图表** —— 按组/长度档的 TTFT、decode TPS、总耗时、prompt token 曲线
   与每档判分柱状图，以及 min/median/p95/max 分布表。
4. **测试数据详情** —— 2100+ 条请求的可搜索/筛选/排序/分页表格。

报告**不依赖任何外部资源**（无 CDN、无外链字体），图表是内联 SVG，由本次运行的
数字直接画出。模型输出以 `textContent` 注入并做 `<` 转义，回复里带 `<script>`
也不会执行——这两点都由单测断言。

### 额外证据

| 文件 | 内容 |
|---|---|
| `report.html` | 上面那份单文件报告 |
| `timeline.jsonl` | 阶段与异常的机器可读时间线 |
| `samples.json` | 设备与 worker 采样（CPU/内存/TPU/NPU/队列/缓存） |
| `evidence.json` | 环境快照 + 记录核对 + SQLite 核对 + 判定，一份可直接喂给别的工具的汇总 |
| 其余 | 与 `board_stability_suite.py` 同名同义（`rounds.jsonl`、`manifest.json`、`summary.json`、`raw/`、`records-*.json`、`sqlite-check.json`、`env.json`、`journal-test.txt`、`dmesg.txt`） |

### 几条容易踩的

- **`variant` 参数不是可有可无**：1000 次请求如果只有 12 种正文，前缀缓存会把
  绝大多数请求变成命中，"1000 次独立请求"就名不副实；100 个会话若每轮共用一种正文，
  等于一个缓存前缀发 100 次而不是 100 段对话。所以每个循环、每个会话都换一份材料。
- **1000/1200 档不追加上下文回忆**：这两档在任何真实会话里都不存在对应轮次，
  问"第几轮的关键词"是无解的，只会诱导模型多吐一个数字干扰计数判分。
- **并发标记必须全局唯一**：串话是靠"回复里出现别人的标记"判定的，标记跨轮复用
  会把后面的轮次误判成串话。

## 全方位稳定性矩阵（`comprehensive_stability_suite.py`，MYS-2510）

回答的是「在**主要推理路径**上——真实长上下文、排队、客户端断开、加载/卸载生命周期、
视觉与工具调用、以及两小时混合浸泡——服务是否稳定」，并且**每个维度单独判定**，
不把"协议通过"混同为"答案正确"。

```sh
python3 tools/comprehensive_stability_suite.py \
    --evidence-dir /data/stability/evidence-mys2510 \
    --model qwen3.6-35b-a3b-128k --soak-seconds 7200
```

它是 `board_stability_suite.py` / `extended_stability_suite.py` 的**超集**，不是替代：
前两者的矩阵仍原样可跑，本工具 import 它们的 prompt 生成、SSE 解析、记录核对与统计。

### 与 MYS-2501 的关键区别

| 方面 | MYS-2501 | 本工具 (MYS-2510) |
|---|---|---|
| 长度档 | **字符**数 2–1200 | **token** 数 16k/32k/64k/96k，用模型自己的 tokenizer 构造并核验 |
| 长输入的题 | 数词出现次数 | 从材料中取回**指定仓库的六位编号**（只存在于材料中，猜不出来） |
| 事实位置 | 固定在尾部 | head/middle/tail 轮转（检索正确率与位置强相关） |
| 上下文上限 | 未覆盖 | 132k/200k prompt 必须被明确拒绝且**不处理任何 token**（实测每次写 1 条 `status=error`、`prompt_tokens=0` 的记录，这是 records 契约的行为） |
| 取消 | 未覆盖 | 首 token 前/流中/接近完成各 5 次，判**记录**而非 socket |
| 生命周期 | 未覆盖 | 20 次 load→推理→unload，查 worker/端口/NPU 内存残留 |
| 视觉/工具 | 未覆盖 | JPEG/PNG 各 20 次含多图；工具调用 30 次；thinking 各 10 次 |
| 浸泡 | 未覆盖 | **2 小时**墙钟，采样趋势 + 首尾漂移 |

### token 精确构造为什么必要

这个模型的中文大约 **0.6 token/字**，但数字是 1 token/位、英文远低于此——用字符数
冒充 token 会随材料不同漂移几十个百分点。本工具通过 `ctypes` 调
`libcv84x6_llm.so` 的 `llm_tokenizer_load`/`llm_tokenizer_encode`，走的就是 worker
编码 prompt 的同一条代码路径，所以档位名就是模型实际拿到的 token 数（实测各档偏差
< 0.1%，运行记录里逐档给出 `prompt_tokens`）。

构造是**线性**的：先量一个 64 条款块，再按比例重复并按测得的每条成本收敛。最初的
"追加一条 → 重新 tokenize 全文"写法在 64k 上要跑几分钟而且会卡住，这是实测踩到的。

### 判据（每维度单列，`None` 视为未通过）

| 维度 | 主要判据 |
|---|---|
| A 长上下文 | 长 prompt 全部正常结束；`prompt_tokens` 与档位差 ≤5%；超长输入被明确拒绝（4xx 或 SSE error 帧）且无记录声称处理过 token；50/100 轮会话无异常 |
| B 并发队列 | 全部符合预期、无串话；3 路在 `max_concurrent=2` 下**排队不拒绝**；临时 `max_queue=0/1` 出现 429 且恢复 |
| C 流式/取消 | 每次取消**恰好一条** `cancelled` 记录且保留部分输出；取消后短请求正常；协议错误码符合预期；SIGTERM 重启后**准入仍生效（409）**、显式重载后恢复、记录保留 |
| D 缓存/生命周期 | 观测到前缀复用且**答案不变**；TTL 淘汰后仍正确；20 次循环无残留 |
| E 视觉/工具 | VLM 全成功、记录只存尺寸；工具**协议与内容分开计**；非法定义 400 |
| F 浸泡 | 达到 2 小时；全程无 5xx/连接异常；采样覆盖；资源增长被标注 |

**成功 = HTTP 等于该阶段预期**：加载窗口的 409、队列满的 429 在各自阶段算通过。
**语义正确率**（检索/回忆/工具内容）单独统计，不参与稳定性判定；`cached_tokens` 只
说明复用，不作为答案正确的证据。

### 报告

单个自包含 `report.html`：总体结论 → 判据明细 → 矩阵与时间线 → 性能/资源图表
→ 记录一致性 → 环境参数 → 全部请求明细（搜索/筛选/分页）→ 未覆盖项。
无 CDN、无外链，图表是内联 SVG，模型输出经转义（单测断言）。

### 长上下文的真实时间成本（实测，`.151`，冷缓存）

| 档位 | 首 token 延迟 | 每 1k token | 相邻档增长 |
|---:|---:|---:|---:|
| 2k token | 10.3 s | 4.94 s | — |
| 8k token | 35.9 s | 4.37 s | ×3.49 |
| 16k token | 109 s | 6.63 s | ×3.04 |
| 32k token | 286 s | 8.72 s | ×2.63 |
| 64k token | **851 s (14.2 min)** | 12.96 s | ×2.97 |
| 96k token | **1696 s (28.3 min)** | 17.24 s | ×1.99 |

同一台 `.151`、同一模型、**冷缓存**实测。每 1k token 的成本从 4.9 s 单调涨到 17.2 s
（3.5 倍），相邻档增长因子 2.6–3.0（到 96k 是 2.0）——即介于线性与二次之间，
实测拟合幂次 a ≈ 1.5–1.7。**96k 单次 28 分钟**，这就是 64k/96k 各只跑 1 次、
16k 跑 3 次、32k 跑 2 次的原因；报告里逐档给真实 `prompt_tokens`。

prefill 随长度超线性（history attention 是 O(past×L)，见
[`../docs/research/qwen36-lossless-optimization.md`](../docs/research/qwen36-lossless-optimization.md)）。
**冷热缓存差别极大**：同一份 16k 材料第二次跑只要 13 s（命中前缀缓存），
因此长上下文组开始前会重载模型并核对缓存条目为 0，命中过半的行会被单独标注——
否则"16k 的延迟"记录的其实是缓存的延迟。

### 连续对话档位（A2，`--phases ctx`，MYS-2521）

回答的是「**16k 以下短/中上下文在真实连续对话里能不能撑住**」。它不是又一次单轮长
prompt，而是每个档位一条独立会话，每轮**追加完整 user/assistant 历史**重发。

```sh
python3 tools/comprehensive_stability_suite.py --phases ctx \
    --evidence-dir /data/stability/evidence-mys2521 \
    --model qwen3.6-35b-a3b-128k
```

- **档位以服务返回的会话累计 `prompt_tokens` 判定**，落在目标 ±10% 内才算到档。
  轮数是**结果不是输入**：会话一直长到 token 到档为止。默认 2k/4k/8k/12k/16k，
  低档各 2 条会话、12k/16k 各 1 条。
- 每轮植入带编号的关键词，**每个会话的前 4 轮固定是四个生僻词**
  （门簪/琴轸/秤砣/妆奁）——它们才是 UTF-8 字节切分的回归点，2k 档只有几轮，
  放在公共词池里永远轮不到。
- 到档后问 **3 个早期 + 2 个近期**事实。只问近期会在短滑动窗口下通过，只问早期会在
  只保留头部的情况下通过，两者都要才是「整段历史在」。
- **16k 会话到档后重启复验**：正常 `systemctl restart` → 首个请求 **409**（本版本不自动
  加载，属预期）→ 显式 `POST /api/models/<id>/load` → 用**完整历史**继续追问。
  连续性拆成三个独立事实：准入、重载、历史保留（重启后首问 token 不低于重启前）。

与 A 矩阵的单轮 16k/32k/64k/96k、以及 50/100 轮组**分开统计**，互不替代。

### UTF-8 回归（U1，`--phases utf8`，MYS-2521）

回答的是「**生僻字与 emoji 在所有输出路径上还是不是 `�`**」。让模型原样复述
`门簪、琴轸、秤砣、妆奁、😀、👍` 各 10 次，覆盖 `/v1/chat/completions` 的 stream 与
non-stream、以及 `/api/chat/stream`；再重放 MYS-2510 中实际失败的 12 个轮次
（chat50/chat100 的第 18/29/35/45… 轮）。

- **任一输出出现 U+FFFD 即判失败**，原文保留、**不重试覆盖**——重试通过会掩盖正是它要抓的
  间歇性字节切分。
- 同时比对 SSE 拼接文本、非流式 `content` 与记录里的 `response_content` 三者一致：
  v0.6.14 的缺陷活在**流式拼接**里，只测非流式会漏。

### 报告修正（R，MYS-2521）

MYS-2510 报告里的口径错误已按证据改正，且**改的是工具的计算逻辑**而不只是 HTML 文字，
每处都有单测：

| 项 | 原值 | 新值 | 依据 |
|---|---|---|---|
| 多轮回忆 | 136/263 = 51.7% | 136/148 = 91.9% | 263 条中 115 条是浸泡 `soak-ctx` 轮，不计入回忆分母。**剔除依据是分组不是 `expected_recall`**：该列在 MYS-2510 证据里 1240 行全为 null（chat 行也是），按它筛得到空集。`soak-ctx` 不计入的真实原因是其历史里每轮 assistant 回复被写死为「收到。」，等于教模型用「收到。」回答回忆提问 |
| 12 条回忆失败 | 模型能力问题 | 服务端逐 token 解码缺陷，v0.6.15 已修 | 输出为 `门��` 形态，首字正确尾部是 U+FFFD；记录里 `output_text` 与 `response_content` 同样是替换符 |
| 「4000 token 后答非所问」 | 有 | 删除 | 唯一数据来源就是上面 12 条截断行 |
| 取消记录状态异常 | 15 | 0 | 15 条 `cancel-recovery` 恢复探针被误计为取消记录 |
| 输出不一致 | 10 | 0 | 全部是 thinking-on 请求：比了 `output_text`（含 think 块）而非 `response_content` |
| 工具并行/多调用 | 未说明 | 未覆盖 | 53 次工具调用全是 `context_messages=2` 的单请求 |
| VLM 多图 | 80/80 | 16/80 真实多图 | 16 条多图请求的第二张全是 `[1,1]` 占位图 |

这些更正是**算术**，不需要重跑主矩阵；证据（`rounds.jsonl` 的 gzip 副本，含更正所依赖的列）
在 `analysis/raw/mys2510-supplement/`，单测直接拿它验证结论（1240 行里筛出 148 条、
136 条正确、未修正口径恰好是 263）。`expected_recall` 仍被记录并驱动判分，但**不决定分母**。

### 合并既有证据（`--carry`）

A2/U1 是新测的，主矩阵不重跑，所以交付的那份 HTML 需要把两次测量拼在一起。逐行重建
`Round` 对象后交给同一个 `summarize`，而不是手工改旧 HTML：

```sh
python3 tools/comprehensive_stability_suite.py --phases ctx,utf8 \
    --evidence-dir /data/mys2521-run \
    --carry analysis/raw/mys2510-supplement/mys2510-rounds.jsonl.gz \
            @summary-regenerated.json
```

- 报告顶部会写明「本报告合并了两次测量」及各自行数；`manifest.json` 里有
  `carried`（按来源分行数）与 `requests_this_run`，可以减出本次自己的口径。
- `input_text` 不落盘（长档单条上兆），所以还原后没有全文，只有 `input_chars` /
  `input_sha256`；统计与报告都不读全文。
- 未知字段直接忽略，旧证据文件因此仍可加载。

### 几条实测踩到的

- **两个探针进程会互相饿死**：调试时忘了杀掉先前的长 prefill 进程，两个 64k 预填充
  抢满 2 个并发槽，短请求排队 1000 s 以上，看起来像"服务卡死"。看
  `/proc/<worker>/task/*/wchan` 会看到 `bmdrv_thread_sync_api`，但那只是**在等 NPU**，
  不是 hang。判据是：worker CPU ≈ 0 且 `active` 长期不降；先确认没有别的探针进程。
- **200 不等于成功**：头已返回 200、body 随后超时的请求，只看状态码会记成通过。
  判据里要求 `finish_reason` 到位或客户端主动断开。
- **422 和 400 都可能是对的**：`tools` 传非 list 由 pydantic 先拒（422），
  `function.name` 缺失由端点校验拒（400）。断言单一码会把正常服务判成故障。
- **重启后模型不会自动加载**：启动只接管仍在运行的 worker，而 `systemctl restart`
  已经把它杀了。所以重启后 `loaded=false`、请求得到 **409**（准入正常工作），
  必须显式 `POST /api/models/<id>/load`（约 66 s）。
- **拒绝不一定是 4xx**：超长输入和队列饱和（`rate_limit_error`）都在 SSE 流内返回
  HTTP 200 + error 帧，因为响应头已经发出。只看状态码会得出"没有拒绝"或"成功"。
- **超长请求会写 error 记录**：`status=error`、`prompt_tokens=0`，是真实推理被正确
  拒绝的留痕，不是"写了不该写的记录"。
- **thinking 的 `max_tokens` 要先留给思考**：实测 192 token 全花在 think 块里
  （747 字 reasoning、0 字正文、`finish_reason=length`），正文为空是预算不足，不是故障。

## 旧版加载竞态探针（`legacy_readiness_probe.py`）

回答的是「**模型还没完全加载完就发推理请求，旧版服务到底会怎样**」。v0.6.14 起
`ModelManager.require_ready` 会把加载中的请求全部 409 拒绝，这个问题在新版上已经问不出来，
所以这个工具专门打旧版（v0.6.13），在多个加载时机上实测而不是从代码推断。

```sh
# 原生：直接打发布包
python3 tools/legacy_readiness_probe.py --mode native \
    --delays 0.1 5 15 30 45 60 edge ready \
    --evidence-dir /data/readiness-evidence \
    --data-dir /data/cv84x6-readiness-v0613
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--base-url` | `http://127.0.0.1:8000` | 被测服务 |
| `--model` | `qwen3.6-35b-a3b-128k` | 显式指定，防止测到另一个模型 |
| `--password` | `admin` | 控制台管理员密码；**不写进报告** |
| `--evidence-dir` | `./evidence` | 每次运行新建 `run-<UTC时间>-<模式>/`，**不覆盖**已有目录 |
| `--mode` | `native` | `native` = 发布包原样；`instrumented` = 测试构建（见下） |
| `--settle-delay` | 0 | `instrumented` 模式必填：延迟 `WorkerClient.health` 的秒数 |
| `--delays` | `0.1 5 15 30 45 60 edge ready` | 三种写法见下 |
| `--data-dir` | `/data/cv84x6-readiness-v0613` | 旧版实例的数据目录；用于直接只读核对记录库 |

### 每个「时机」是一次独立实验

一次实验永远是 **卸载 → 加载 → 在指定时刻发请求 → 等加载收尾**。共用一次加载会让
前一个请求的时序污染后一个的状态，而状态正是唯一变量。代价是每个时机约 70 秒，
这个代价就是实验本身。

`--delays` 的三种写法对应三种**不同的**实验，报告里分开列出：

| 写法 | 含义 |
|---|---|
| `0.1`、`5`… | load POST 发出后第 N 秒发请求。**是按秒数猜**窗口在哪 |
| `edge` | 一看到 `/api/models` 报 `loaded=true` 且 `operation` 仍非空就立刻发——这正是 v0.6.13 在就绪握手之后、能力探测结束之前发布的状态，是它**真实存在的窗口** |
| `ready` | 等完全就绪再发。对照组：证明服务正常时这个请求是好的 |

每个时机对三个接口各发一次：`/v1/chat/completions` stream、non-stream、
`/api/chat/stream`（console，cookie 鉴权）。请求体逐字相同，只有路由和鉴权不同。

### 判定只看记录下来的事实

- **窗口内 / 窗口后由「发送瞬间模型自己报的状态」决定**，不由延迟标签决定。
  一个「5 秒」请求如果落在就绪之后，就如实算对照组——否则窗口的数字会被虚增。
- 分类七档：`refused`(409)、`summary`、`summary_suspect`(含 U+FFFD)、`garbage`(退化/复读/碎片)、
  `empty`、`hang`(超时/断连无响应)、`http_error`(其他非 2xx)。
- **U+FFFD 单独统计**：那是已知的流式逐 token 解码缺陷（MYS-2510/MYS-2520），
  每个输出都会扫描并报告出现次数与上下文，但**不参与加载竞态的判定**。
  只有「对照组干净、窗口内异常」才能把异常归因于竞态。
- worker 的 `total_requests` 读**绝对值**而不是前后相减：一次 load 换一个进程，
  新 worker 的计数从 0 开始。记录表的差值则是有意义的（表在数据目录里，跨进程存活）。

### `instrumented` 模式：测试构建，不是发布包

原生窗口只有一两次 admin GET 那么窄，`edge` 能否命中取决于轮询运气。
`--mode instrumented` 用同一发布包，但以 `sitecustomize.py` 延迟
`WorkerClient.health`——该调用在 v0.6.13 里**只有一个调用方**：`_load_locked` 的能力探测，
位于 `loaded` 发布之后、`operation` 清空之前。所以放大的是状态机自己的窗口，
`/api/models`、`/api/stats`、readiness 握手都不经过它。

两种模式的证据放在不同目录、不同报告里。**插桩结论不能当作原生时序的证据。**
起法见脚本 `write_sitecustomize()` 生成的 `sitecustomize.py` 与
`CV84X6_TEST_PROBE_DELAY_S` 环境变量；探针启动时会读 journal 里的
`[test-build]` 行，确认放大真的生效，否则拒绝运行——避免报告声称插桩而实际在测原生。

## 板卡纪律

- **不要 `kill -9` 正在跑 NPU 的进程**：会让 TPU 卡死，只能重启设备。停服务用 SIGTERM 等它退出。
- 每次探针跑完看 `dmesg | tail`；出现 `bmdrv_thread_sync_api ... wait api timeout` 或
  `bdc_reg_read` oops 立即停止，不重试。
- 同一时刻只跑一个探针进程：两个 decode 进程争用整块 TPU，数字没有意义。
- 不要读 `/proc/bmtpu/bmdi_api_info`（在 CV84X6 上会 oops）。细节见
  [`../analysis/README.md`](../analysis/README.md)。

## 端到端测试（板卡 + 13.24）

| 工具 | 用途 |
|---|---|
| `e2e/` | v0.6.29 全功能端到端测试脚本、D7 复现实验和证据库，见 `e2e/README.md`；报告在 `../docs/e2e-0.6.29.md` |
