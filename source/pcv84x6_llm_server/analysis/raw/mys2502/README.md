# `.151` 旧版 v0.6.13 加载竞态多时机实测（MYS-2502）

本目录是 `tools/legacy_readiness_probe.py` 在 `10.43.0.151` 上的真实运行数据，
以及由它生成的单文件 HTML 报告。两次运行都在，因为它们各自只回答一半问题。

| 目录 | 模式 | 结论 |
|---|---|---|
| `run-20261031T182115Z-native/` | 原生（发布包原样） | 窗口内 18 次请求**全部 409**，放行 0；`edge` 时机**观测到**窗口（23.0 ms），但三个请求晚了 3.4 / 8.6 / 12.4 ms；ready 对照 6/6 正常摘要 |
| `run-20261031T183122Z-instrumented/` | 插桩（测试构建，窗口放大 8 s） | 窗口内 3 次请求**全部被放行**（`loaded=true, operation=loading`），输出正常摘要；窗口实测 5.01 s |

`run-20261031T182115Z-native/report.html` 是由 `--combine` 生成的**合并报告**，
交付给 issue 的就是这一份（81 KB，0 个外部引用，四章节齐全）。

## 结论

1. **缺陷真实存在，但只在这几毫秒里**。v0.6.13 的 `_load_locked()` 在 readiness
   握手之后立刻发布 `loaded=True`，随后才做能力探测（`stats` + `health` 两次本机 RPC），
   探测结束才清 `operation`。而 `_resolve_model()` 只检查 `loaded`，不看
   `operation`。所以「已发布 loaded、尚未就绪」这个状态**确实可以被放行**——
   插桩把这段窗口拉到 8 秒后，三个接口全部被放行进入 worker。
2. **原生条件下几乎打不中**。实测该窗口只有 **5.2–11.7 ms**（8 个时机，均值 7.04 ms），
   比一次 admin `GET /api/models` 的往返还窄。原生实验 18 次窗口内请求
   （0.1/5/15/30/45/60 s 各 3 个接口）**全部 409**，放行 0 次。
   注意这不是门控——v0.6.13 没有 v0.6.14 的 `require_ready`；它返回 409 是因为
   那时 `loaded` 还是 `False`。
   同一轮里 `edge` 时机**确实观测到了**那个状态（窗口 23.0 ms），但三个请求发出时
   窗口已关闭 3.4 / 8.6 / 12.4 ms —— 这是**边界未命中**，不是「窗口拦住了」。
3. **被放行后的输出没有异常**。插桩实验里被放行的 3 次请求，输出与 ready 对照组
   **逐字相同**（206 字，prompt 266 / completion 128 tokens 完全一致）。
   机制在 worker 侧：`app/engine/worker.py` 的 `amain()` **先**载入权重、
   **再** `await sched.start()`（`create_task`，不阻塞）、**最后**才
   `start_server()` 打开 socket。所以服务端 `loaded` 为真的那一刻，socket 与
   调度器都已就绪；能进 worker 的请求，引擎一定已经在跑。
   **局限**：时间分辨率 10 ms 量级，理论上仍可能存在「socket 已开、调度器任务尚未
   首次被调度」的极窄区间，本轮没有观测到。
4. **因此现场那一次异常不能用这条竞态解释**。本轮没有复现
   「两个女生约好一起出门……」同款异常输出，也没有任何证据把它归因到加载竞态。
   `garbage`/`empty`/`hang`/`U+FFFD` 计数全部为 0。

## 为什么必须两种模式

原生窗口是毫秒级，一次 admin 轮询就要 5–15 ms，**用轮询去命中它是碰运气**。
所以原生实验的价值是「测出窗口有多宽 + 证明原生条件下请求确实被拒」；
插桩实验的价值是「把窗口拉开，证明这个状态一旦可达就会被放行」。
两者缺一不可，报告里分成两块、从不混算。

插桩只改一处：`sitecustomize.py` 延迟 `WorkerClient.health`。该调用在 v0.6.13 中
**只有一个调用方**——`_load_locked` 的能力探测；`/api/models`、`/api/stats`、
readiness 握手都不经过它。探针启动时会读 journal 里的 `[test-build]` 行确认
放大真的生效，否则拒绝运行。

## 设备与版本

| 项 | 值 |
|---|---|
| 设备 | `10.43.0.151`（hostname `sophon`，SSH `linaro@172.26.166.96:10151`） |
| SN | `HQDZCVEBFJIJA0027`（实测 `/factory/OEMconfig.ini`） |
| 安装版本 | deb `0.6.13`；`VERSION` = `0.6.13`；`COMMIT` = `d63c17a4a4b09ce73641e9b01aeb27a3b5c70285` |
| **deb 与 tag 的关系** | release `v0.6.13` 的 tag 是 `5716b50`，而 deb 是从它的父提交 `d63c17a` 打的包。两者只差 `scripts/test_deb.sh`（4 行，一个**测试脚本**），`app/`、`web/`、`lib/` 载荷完全一致（`git diff d63c17a 5716b50` 只列出那一个文件）。写在这里，因为「装的是哪个 commit」必须能自证 |
| deb SHA-256 | v0.6.13 `d613c1b41c72390a3df395f094a72c1ce5038c569d4ed7b541d659763588d6fd`；v0.6.14 `2cbd366301ba6fc90d88649931901807cbc4ff646b53258f0ee48b4f7c1b1c00` |
| 模型 | `qwen3.6-35b-a3b-128k`，context 131072 |
| 权重 | `qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel`，20638679040 字节，MD5 `3c8fb31702ad752ddcdb3f84e24d43b8`（测前测后一致） |
| 内存布局 | 未改动：VPP 500 MiB（`vppreserved_size=0x1f400000`），TPU 26644 MiB |
| 数据目录 | 独立目录 `/data/cv84x6-readiness-v0613`，未污染 `/data/cv84x6_llm_server` |
| 内核 | `5.10.4-9c6431d06-sophon-custom-00610-g9c6431d06798` |
| 输入 | 444 字，SHA-256 `ac9764aab4bf94329051348ab1671c630d366dab5301eb6653d00018f9667631` |

## 测试输入与固定参数

输入逐字取自任务卡（`INPUT_TEXT` 常量），未改写、未删节、未重新断句：

```
两个女生约好一起出门吃火锅，……总结一下以上文章，主要内容
```

固定参数：`max_tokens=128`、`temperature=0`、`top_p=1`、`top_k=1`、
`repetition_penalty=1`、`enable_thinking=false`、`seed=2496`。
三个接口（`/v1/chat/completions` stream / non-stream、`/api/chat/stream`）
**同时发出**，请求体完全相同，只有路由和鉴权不同。

> 并发而不是串行是有原因的：一次 128 token 的生成在这块板上要 5–6 秒，
> 串行发三个接口会让第三个比第一个晚 11 秒。对毫秒级窗口来说那不是「同一时刻的三次采样」，
> 而是「三个不同时刻各一次」。

## 每个时机做了什么

一次时机 = 一次完整 **卸载 → 加载 → 在指定时刻发三个请求 → 等加载收尾**。
共用的加载会让前一个请求的时序污染后一个的状态，而状态正是唯一变量。
每个时机约 70 秒，这个代价就是实验本身。

原生矩阵：`0.1 / 5 / 15 / 30 / 45 / 60 s`（按秒数猜窗口）+ `edge`（盯状态发）+ `ready`（对照）。

## 数据

| 文件 | 内容 |
|---|---|
| `env.json` | 设备、内核、内存布局、版本、服务单元、输入哈希 |
| `bmodel.json` | 实际加载的 .bmodel 路径与 MD5（从 worker 命令行读，不靠目录猜） |
| `runs.jsonl` / `timing-*.json` | 每个时机的完整记录，含每次 attempt 的发送时状态与毫秒级窗口偏移 |
| `raw/` | 每次请求的原始响应体（SSE/JSON） |
| `worker-*.log` | 该时机加载时 worker 自己的初始化日志，**按端口切成单次加载**，不含上一次的残留 |
| `journal-*.txt` | 该时机的服务 journal 片段（`--since @<epoch>`，时区无歧义） |
| `records-export.ndjson` | 服务自身的记录导出 |
| `sqlite-check.json` | 绕过 API、只读打开 SQLite 的核对 |
| `summary.json` | 逐分类/逐接口聚合 + 判定 |
| `report.html` | 单文件自包含合并报告 |
| `report-audit.json` | 报告自检：0 个外部引用、四章节齐全 |
| `MANIFEST.json`（上一级） | 本目录每个文件的 SHA-256 与字节数 |

## 判定口径

- **窗口内 / 窗口后由「请求发出瞬间模型自己报的状态」决定**，不由延迟标签决定。
  一个「5 s」请求如果落在就绪之后，就如实算对照组。
- worker 的 `total_requests` 读**绝对值**：一次 load 换一个进程，新 worker 从 0 开始。
  记录表差值则有意义（表在数据目录，跨进程存活）。
- **U+FFFD 单列**：已知的流式逐 token 解码缺陷（MYS-2510/MYS-2520），
  每个输出都扫描，但**不参与竞态判定**。本轮窗口与对照组均为 0。

## 局限

- 每个时机每个接口只发一次。这不是统计采样，是「该时刻这一次发生了什么」的事实记录。
- 轮询分辨率 5–15 ms：原生 `edge` 只在 8 个时机里命中 1 次（23.0 ms 那次），
  且命中时请求仍晚了 3.4–12.4 ms。插桩实验不依赖这个运气。
- 插桩结论只描述「窗口被放大后的旧版行为」，不能当作原生时序证据。
- 现场异常发生在另一台设备的 v0.6.12，当时没有留下任何请求/回复内容；
  v0.6.12 与 v0.6.13 的加载路径（`models.py`/`worker.py`/`client.py`/`native.py`）
  **逐字节相同**，所以本结论对那条代码路径成立，但不等于复现了那一次。
- 未覆盖：图片请求、并发请求落进窗口、`max_tokens` 更大的情形。

## 收尾

- 服务已恢复 **v0.6.14**（`3c8cf59`），数据目录切回 `/data/cv84x6_llm_server`，
  MYS-2501 的 `state.json` 与 4612 条推理记录完好。
- 测试构建的 `sitecustomize.py` 与 systemd override 已删除。
- 自建 API key 每次运行结束即删除；`MYS-2496-acceptance` 未动（仅此一个 key）。
- 全程 `dmesg` 无 `wait api timeout` / `bdc_reg_read`，未重启设备，未改内存。
- v0.6.14 的准入闸门在恢复后**实测复验**：加载期间 `/v1/chat/completions`
  返回 `409 模型 … 正在加载中，请等待加载完成后再请求`。
