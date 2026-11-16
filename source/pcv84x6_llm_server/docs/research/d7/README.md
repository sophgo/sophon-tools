# D7 卡死现场证据索引

每个目录对应报告 [`../d7-tpu-hang.md`](../d7-tpu-hang.md) 里的一次卡死，内容是该次卡死后
立刻在板上跑 `tools/e2e/d7_capture.py` 采到的原始输出。**全部只读采集**，没有一次采集动作
会写设备状态（`sysrq-w` 只打印、不改变任何东西）。

> **sophon-tools 版说明**：原始采集件（每个 run 目录的 dmesg 原文、内核栈、固件
> scaler 状态、kernel_fifo、推理记录与请求流水，共 9 个 run）属于板端原始日志，
> 不随本仓库分发，保留在原私有仓库 `zzttzzmyswy/cv84x6-llm-server` 的
> `docs/research/d7/R*/`。本仓库保留结论：本文件的内容表、各 run 的实验配置
> 表，以及 [`step1-stuck-command.md`](step1-stuck-command.md)、
> [`step2-3-conditions-and-fix.md`](step2-3-conditions-and-fix.md) 和
> [`../d7-tpu-hang.md`](../d7-tpu-hang.md) 的完整分析。

## 每个目录里有什么

| 文件 | 内容 |
|---|---|
| `dmesg-at-hang.txt` | 从开机算起的完整 dmesg，含 `wait api timeout` / `mbox submit timeout` |
| `kernel-stacks-sysrq-w.txt` | `echo w > /proc/sysrq-trigger` 的 `Show Blocked State`：**内核栈**。板上内核没开 `CONFIG_STACKTRACE`，`/proc/*/stack` 不存在，这是唯一的办法 |
| `threads.txt` | 每个 worker 每个线程的 `state` / `comm` / `wchan`（用户态侧） |
| `scaler_info.txt` | `/proc/bmtpu/scaler_info`：4 个 C906 核的固件状态。**`using_flag` / `cur_api_id` / `recvmsg_cnt` 是判卡死的关键** |
| `scaler_info-after-180s.txt` | 确认卡死后等 180 s 再读一次，用来证明「不会自愈」 |
| `kernel_fifo-tail.txt` | `/proc/bmtpu/kernel_fifo` 最后 64 条：卡在哪个 API、哪个 hwq、哪个 seq |
| `hwq-free-slots.txt` | `/proc/bmtpu/wakeup_control`：8 个 hwq 的空闲槽。**用来排除「队列满」** |
| `stats.json` | `/api/stats`：堆占用、TPU 使用率（如果服务还能答） |
| `recent-inference-records.txt` | 卡死前 N 分钟的推理记录（直接读 sqlite，不走 API —— API 此时已经不响应了） |
| `requests.jsonl` | 本次实验每个请求的开始/结束/耗时，用来定位「挂住的是哪一类」 |
| `result.json` | 本次实验的完整结论（配置、时长、在飞请求、卡死判定） |
| `capture-summary.json` | 采集器自己的清单：采到哪些段、哪些段失败、各计数器 |

## 各目录对应的实验

| 目录 | 实验 | 驻留 / 负载 | 卡死时刻 | NPU |
|---|---|---|---|---|
| `R0-smoke` | 首次复现 | 6 模型 / chat×2 + 五类各 1 | 136 s | 30440 MiB |
| `R1-ctrl-six` | 对照复跑 | 同上 | 136 s | 30440 MiB |
| `R7-ctrl-six-repeat` | 第三次 | 同上 | 136 s | 30440 MiB |
| `R9-six-resident-asr-idle` | ASR 驻留但不过流量 | 6 模型 / 除 asr 外全打 | 136 s | 30440 MiB |
| `R10-six-min-traffic` | 只打两类 | 6 模型 / chat×2 + vl | 125 s | 30440 MiB |
| `R11-six-chat-only` | **最小复现** | 6 模型 / **只 chat×2** | 125 s | 30440 MiB |
| `R14-six-two-threads-same` | R11 复跑 | 同上 | 125 s | 30440 MiB |
| `R8-three-hi-load` | 高并发替代堆压力 | chat,vl,asr / chat×4, vl×2, asr×2 | 559 s | 26469 MiB |
| `R17-long-run-wedge` | 单并发长跑后最终卡死 | 6 模型 / chat×1 | 130 min 后（第 3493 次请求） | 30440 MiB |

`R11` 和 `R14` 是最干净的两个现场：**一个请求都没完成**就卡住了，所以「卡在第一批 launch」
这件事没有别的解释空间。

`R17-long-run-wedge` 是另一类现场，同样重要：**前面 130 分钟、3492 次请求全部 200**，
dmesg 里一条 timeout 都没有，卡死发生在第 3493 次。`requests.jsonl` 里能看到前 3492 条
全部 `code=200`、最大并发 1；`result.json` 的 `inflight_at_end` 里那条 `chat` 就是再也没回来的
请求。这个现场是「单并发不是免疫、只是概率低」的唯一直接证据，别把它和「跑满 130 分钟很稳」
混为一谈。

> **读 `result.json` 时注意**：这个目录的 `result.json` 里 `hang.detected` 是 **`false`**，
> 因为 130 分钟的测量窗口**已经正常结束**了，卡死发生在窗口之后的收尾探针上 —— 监控线程此时
> 已经停了，所以它没把这次判成 hang。判定依据是另外三处，都在本目录里：
> `result.json` 的 `probe_after` 六个模型全是 `exc:ReadTimeout`、`dmesg_after` 里
> `wait_api_timeout: 4`、以及 `dmesg-at-hang.txt` / `scaler_info.txt` 里
> `using_flag: a5a5` + `cur_api_id: 0x90000003`。
> 不要按 `hang.detected=false` 把它当成「没卡死」。

不卡死的组没有单独建目录（它们没有现场可采），数据在报告的表里，`result.json` 在
13.24 的 `cv84x6-e2e/d7runs/`（未入库，只入库卡死现场）。
