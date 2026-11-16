# D7：TPU 偶发卡死的触发条件（10155，v0.6.29）

| 项 | 内容 |
|---|---|
| **结论** | 卡死由两个条件共同决定：① NPU 堆被占到几乎不剩（6 模型 = 30440/30720 MiB）；② **同一个 worker 上有并发请求在飞**。并发 ≥2 时 **7/8 组在 125–136 s 内卡死**；并发 = 1 时同样的堆可以撑 **130 分钟 / 3492 次请求**，然后仍然卡在第 3493 次。所以并发是把复现时间从「小时级」压到「秒级」的开关，**不是免疫开关** |
| **复现率** | 6 模型 + 同一 worker 并发 ≥2：**7/8 复现**，全部 125–136 s。6 模型 + 每 worker 1 并发：**2 次共 9000 s 里 1 次**（R17 第 3493 次，约 2 小时），R12 的 20 min 干净。少驻留一个模型（5 模型）：3/3 干净（各 15–20 min） |
| **责任层** | 驱动 / 固件。`bm_api.c` 的 `core_id = 0; //always 0` 与 `84x6_mbox.c` 的 `mbox_claim` 是本任务能指到的最具体位置 |
| **应用层缓解** | **只能降低频率，不能消除**。「每 worker 1 并发」把 MTBF 从 ~2 分钟提到 ~2 小时；「少驻留一个模型」把 5 模型压到 20 分钟窗口内不复现（没有跑到 2 小时，所以不知道它的 MTBF）。**本任务未改服务代码** |
| **任务卡** | MYS-2693（父 MYS-2293 阶段 22） |

> 本文件只做定位与取证。所有实验都在 10155 上、装的都是 v0.6.29 正式包；没有改
> `app/`、`native/`、`web/`、`scripts/`、版本号、tag、release。

## 结论先行

1. **并发是把卡死从「小时级」压到「秒级」的开关，但它不是免疫开关。**
   下面的分组是这次最关键的一张表 —— 同样是 6 个模型驻留、同样是 NPU 30440/30720 MiB，
   只把负载线程数从 1 改成 2，卡死时间就从「两小时后」变成「两分钟」：

   | 组 | 驻留 | 线程 | NPU | 结果 |
   |---|---|---|---|---|
   | R12 | 6 模型 | **chat×1** | 30440 | 20 min，538/538 全 200 |
   | R17 | 6 模型 | **chat×1** | 30440 | **130 min / 3492 次全 200**，第 3493 次卡死 |
   | R11 / R14 | 6 模型 | **chat×2** | 30440 | **125 s 卡死，0 个请求完成** |
   | R10 | 6 模型 | chat×2 + vl | 30440 | **125 s 卡死** |
   | R9 | 6 模型 | chat×2 + embed/rerank/ocr/vl | 30440 | **136 s 卡死** |
   | R0/R1/R7 | 6 模型 | chat×2 + 全部五类 | 30440 | **136 s 卡死（3/3）** |
   | R16 | 6 模型 | chat×1 + embed×1 + vl×1（3 个**不同** worker） | 30440 | 20 min，503/503 全 200 |
   | R15 | 5 模型（无 VL） | chat×2 | 28363 | 20 min，670/670 全 200 |
   | R13 | 5 模型（无 VL） | chat×1 | 28363 | 15 min，404/404 全 200 |
   | R3 | 5 模型（无 VL） | chat×2 + 四类 | 28363 | 20 min，958/958 全 200 |
   | R5 | 5 模型（无 ASR） | chat×2 + 四类 | 28801 | 20 min，794/794 全 200 |
   | R6 | 3 模型 | chat×2 + vl + asr（4 线程） | 26469 | 20 min 全 200 |
   | R8 | 3 模型 | **chat×4 + vl×2 + asr×2（8 线程）** | 26469 | **559 s 卡死** |
   | R2 | 2 模型 | chat×2 + vl | 24829 | 20 min，598/598 全 200 |
   | R4 | 5 模型（无 chat） | 各 1（5 线程，不同 worker） | 7688 | 20 min，827/827 全 200 |

   **读法**：并发 ≥2 时，只要堆接近满（6 模型）就 7/8 在 2 分钟内卡；并发 = 1 时同样的堆
   能撑 130 分钟（3492 次），但**第 3493 次还是卡了** —— 所以并发不是「会不会卡」，而是
   「多久卡一次」。R16/R4 说明**跨 worker** 的并发不算：3 个不同模型各 1 个并发跑 20 min 干净，
   起作用的是**同一个 worker 内的并发**。
2. **卡死现场是「一个 launch 没有被固件应答」，不是队列满。**
   - `mbox submit timeout hwq 5 need 1` 出现在 `mbox_claim()` 连续返回 `-EAGAIN` 直到
     `delay_ms`（20 s）超时之后（`84x6_mbox.c:393`）。`mbox_claim` 只在这两种情况下失败：
     目标 core 的固件环满（`mbox_seq - mbox_ack >= MBOX_DEPTH`，深度 8），或该 core 上有一个
     未完成的 job 与要申请的 core 区间重叠。
   - 捕获时 `wakeup_control` 显示 8 个 hwq 的空闲槽是 14–16/16 —— **邮箱槽位没满**，所以不是
     「hwq 堵了」，而是 `mbox_claim` 找不到可用的 core。
   - `kernel_fifo` 里最后几条都是 `LAUNCH_FUNC`、`mode=SYNC`、`send_core_num=3`，之后 `seq`
     不再增长，`age` 一直涨到 130 s 以上。
   - 最强的一条：R11/R14 **一个请求都没完成**就到 125 s 超时，说明第一批 launch 就没回来。
3. **驱动把 4 个 core 的问题放大成整块设备的问题。** `bm_api.c:1487`：
   ```c
   if (bmdi->cinfo.chip_id == BM_CHIP_ID_84X6) {
           core_id = 0;   //always 0
   }
   ```
   而 84X6 分支的等待条件是 `atomic_read(&thd_info->api_inflight) > 0`，等的是
   `thd_info->msg_done` —— 一个**不区分 core** 的完成量。任何一次 launch 没被应答，所有
   在 `bmdrv_thread_sync_api` 里的线程都会一起等满 120 s，然后一起报超时。
   `dmesg` 里 6 条 `wait api timeout` 的 `core_id=0` 全部相同，正是这个原因。
   R11/R14 更直接：**一个请求都没完成**就到 125 s 超时了，说明第一批 launch 就没回来。
4. **卡死不可自愈。** 确认卡死后等 180 s 再打一次最便宜的模型，仍然 `ReadTimeout`；
   `using_flag` 停在 `0xa5a5`（`TPU_USING_FLAG`，驱动自己认为 core 仍然 busy），
   `recvmsg_cnt` 不再增长。只有 `systemctl reboot --force --force` 能恢复。
   `ps` 里只剩内核的 `[bm_mbox]`（D 态），用户态线程随进程退出消失了，但**固件仍然卡着** ——
   所以这不是「用户态进程没清干净」，重启是唯一手段。
5. **同一个 `running_flag`，两种卡死形态。**
   - R0/R1/R7（6 模型）：`running_flag: aa0b0036`，其中 `0b` 那一位与正常值 `aa55040a` /
     `aa550036` 不同，说明固件状态机停在了某个不该停的位置。
   - R8（3 模型 2 倍并发）：`running_flag: aa550036`（与正常一致），但 `using_flag` 仍是
     `0xa5a5`、`cur_api_id` 停在 `0x90000003`（LAUNCH_FUNC）。
   两种形态的共同点：`cur_api_id = LAUNCH_FUNC` + `using_flag = 0xa5a5` + `recvmsg_cnt` 冻结。
   **给驱动团队的判据建议**：以这三项组合为准，不要只看 `running_flag`。

## 环境

| 项 | 值 |
|---|---|
| 设备 | 10155，`ssh -p 10155 linaro@172.26.166.96`，板内 IP `10.43.0.155` |
| 内核 | `5.10.4-75e6993a7-sophon-custom-00613-g75e6993a7975`（2026-11-03 构建） |
| libsophon / 驱动 | `0.4.15`（`/opt/sophon/libsophon-0.4.15`），`bm-smi` 自报 SDK/Driver 均 0.4.15 |
| 固件 | `FIRMWARE_VERSION=f6175ad`，`BUILD_TIME=2026-10-30`（core0–3 各一份） |
| 安装包 | `cv84x6-llm-server 0.6.29`（GitHub release `v0.6.29`），`/healthz` 自报 `0.6.29` |
| 设备内存 | NPU 30720 MiB + VPP 4094 MiB（`/api/stats` 的 `device_mem`） |
| 系统内存 | 28375 MiB |
| DTB 共享内存基址 | `0x1080000000`，与固件硬编码一致 —— **不是** MYS-2479 那个 DTB 错位问题 |

> 环境核对结论：MYS-2479 查过的「DTB `scaler_shm_mem` 基址 ≠ 固件硬编码 `0x1080000000`」
> 在这块板子上**不成立**（`dmesg` 里 `Original physical address from DTS: 0x1080000000`，
> `shared memory init: physical base 0x1080000000`），所以本次卡死与那条已知缺陷无关。

## 实验设置

每组实验都是「重启 → 等 `:8000` 起来 → 加载指定模型 → 每类请求按固定间隔循环」，
统一由 `tools/e2e/d7_experiment.py` 在板上跑，由 `tools/e2e/d7_drive.py` 在 13.24 上
驱动（重启、起停、回收结果）。每组开始前先对**每个**模型各打一次请求并断言 200，
否则整组作废 —— 否则「6 个模型」只是假设而不是事实（MYS-2691 就踩过 OCR 实际没加载、
整段 `/v1/ocr` 全是 409 的坑）。

负载线程与间隔沿用 MYS-2691 的复现脚本：chat 0.5 s、embed/rerank 2 s、ocr/vl/asr 5 s；
`chat:2` 表示两个 chat 线程并行（模拟两个 agent 同时对话）。

## 实验汇总

| 组 | 配置（驻留模型 / 负载线程） | 时长 | 请求 / 成功 | 结果 | NPU 起始占用 |
|---|---|---|---|---|---|
| R0-smoke | 6 模型 / chat×2, embed, rerank, ocr, vl, asr | 136 s 时卡死 | 11 / 7 | **卡死** | 30440 MiB |
| R1-ctrl-six | 同上（对照复跑） | 136 s 时卡死 | 51 / 7 | **卡死** | 30440 MiB |
| R7-ctrl-six-repeat | 同上（第三次） | 136 s 时卡死 | — | **卡死** | 30440 MiB |
| R9-six-resident-asr-idle | 6 模型 / 除 asr 外全打 | 136 s 时卡死 | 9 / 5 | **卡死** | 30440 MiB |
| R10-six-min-traffic | 6 模型 / 只 chat×2 + vl | 125 s 时卡死 | 2 / 0 | **卡死** | 30440 MiB |
| R11-six-chat-only | 6 模型 / **只 chat×2** | 125 s 时卡死 | 0 / 0 | **卡死** | 30440 MiB |
| R2-min-chat-vl | chat, vl / chat×2, vl | 20 min | 598 / 598 | 全部 200 | 24829 MiB |
| R3-six-noVL | chat, embed, rerank, asr, ocr / 1+1+1+1+2 | 20 min | 958 / 958 | 全部 200 | 28363 MiB |
| R4-six-noChat | embed, rerank, asr, ocr, vl / 各 1 | 20 min | 827 / 827 | 全部 200 | 7688 MiB |
| R5-six-noASR | chat, embed, rerank, ocr, vl / chat×2 + 各 1 | 20 min | 794 / 794 | 全部 200 | 28801 MiB |
| R6-three-chat-vl-asr | chat, vl, asr / chat×2, vl, asr | 20 min | 全 200 | 全部 200 | 26469 MiB |
| R16-six-cross-model-3t | 6 模型 / **chat×1 + embed×1 + vl×1（3 个不同 worker）** | 20 min | 503 / 503 | 全部 200 | 30440 MiB |
| R17-six-single-long | 6 模型 / **chat×1（长跑）** | **130 min** | 3492 / 3492，第 3493 次卡死 | **窗口内干净，窗口后卡死** | 30440 MiB |
| R8-three-hi-load | chat, vl, asr / **chat×4, vl×2, asr×2** | 559 s 时卡死 | 316 / 315 | **卡死** | 26469 MiB |

「卡死」的判定有两个独立触发条件，取先到的：
- `dmesg` 里出现**新的** `wait api timeout`（决定性，但要等驱动 120 s 超时才打印）；
- 有请求在飞、且连续 `--stall-s`（默认 150 s）没有任何一个请求成功（更早，用于抓现场）。

按 NPU 起始占用排序（注意 R17 的「卡死」是在 130 min 之后）：

| NPU 起始占用 | 组 | 结果 |
|---|---|---|
| 30440 MiB（剩 280） | R0 R1 R7 R9 R10 R11 R14 | **7/7 在 125–136 s 卡死** |
| 30440 MiB（剩 280） | R12（1 并发） / R17（1 并发） | 20 min 干净 / 130 min 后卡死 |
| 30440 MiB（剩 280） | R16（3 个不同 worker 各 1 并发） | 20 min 干净 |
| 28801 MiB（剩 1919） | R5 | 干净 |
| 28363 MiB（剩 2357） | R3 / R15 / R13 | 干净 |
| 26692 MiB（剩 4028） | R8（8 并发） | 559 s 后卡死 |
| 26469 MiB（剩 4251） | R6 | 干净 |
| 24829 MiB（剩 5891） | R2 | 干净 |
| 7688 MiB（剩 23032） | R4 | 干净 |

## 每条假设的结论

### H1 按模型二分：卡死是否需要某个模型参与 —— **不成立：没有单个模型是必要条件**

| 去掉谁 | 组 | 结果 | 说明 |
|---|---|---|---|
| 去掉 VL | R3 / R15 / R13 | 0/3 复现（20/20/15 min，958/670/404 全 200） | VL 不是必要条件 |
| 去掉 35B chat | R4 | 0/1 复现（20 min，827 全 200） | 35B 不是必要条件 |
| 去掉 ASR | R5 | 0/1 复现（20 min，794 全 200） | ASR 不是必要条件 |
| 只留 chat+VL | R2 | 0/1 复现（20 min，598 全 200） | 两个最重的模型也不够 |
| 只留 chat+vl+asr | R6 | 0/1 复现（20 min，4 线程全 200） | 少模型低并发不卡 |

**但是**「去掉任何一个模型」都同时减掉了那 1.6–4 GB 的堆占用，所以这批数据**不能**证明
「模型种类无关」；能证明的是「**没有任何单个模型是必要条件**」。
真正起作用的变量由 R11↔R12、R14↔R12、R11↔R15 三对对照给出（见 H2）。

> 特别提醒：`vl` 那 40 次 409 是 MYS-2691 踩过的坑的重演（该组 OCR 被前置步骤卸载后没重新
> 加载）。本任务的脚本在每组开跑前对**每个**模型各打一次并断言 200，所以本文件里所有
> 「N 个模型」都经过了这一步验证。

### H2 堆余量 / VPP —— **堆余量成立（作为必要条件之一），VPP 不成立**

拿掉 ASR 的那组（R5，NPU 28801 MiB）确实干净；但拿掉 VL（R15，28363 MiB）也干净，
而 6 模型 30440 MiB 只在**并发 ≥2** 时卡。所以堆余量是**两个必要条件之一**：

- **堆余量这一半**：所有卡死组的 NPU 起始占用是 30440 MiB（剩 280 MiB），或 R8 的
  26469 MiB（剩 4251 MiB，但并发 8 线程）。而同样是 30440 MiB 的 R12 靠「1 个并发」逃过。
- **VPP 这一半：完全不成立。** 全部 14 组实验里 **VPP 的 used 一直是 256 MiB**，那 256 MiB
  是启动时就持有的 `vpp_reserve`，**没有任何一组把模型权重放进 VPP**。卡死的 R8 在 NPU
  还剩 4 GB、VPP 完全没动的情况下照样卡死。
- 顺带修正一条此前的缓解建议：**「卸掉 ASR 让 VPP 不被占用」这条在本次数据里没有依据** ——
  VPP 从来没被模型占用过。真正起作用的是「少驻留一个模型 → 堆余量变大」这件事本身，
  与 VPP 无关。

### H3 持续时长 / 累计次数 —— **成立（是概率积累，不是阈值）**

- 并发 ≥2 时**不需要**长时间：R11/R14 是 **0 个请求完成**就到 125 s 超时，R10 是 1 个请求，
  R0/R1/R7/R9 是 5–7 个请求后 136 s。这一档是「几乎必然、立刻」。
- 并发 = 1 时**需要很长的累计**：R17 连续 **130 分钟、3492 次请求全部 200**，第 **3493** 次
  卡死；R12 跑 20 min（538 次）没赶上。两组合计约 **9000 s / 4030 次**里 1 次。
- 所以「累计次数 / 时长」**是**变量，但它影响的是概率而不是有无：
  单并发下每次请求都有一个小概率把设备打进坏状态，约 **1/4000 次**；
  并发 ≥2 时这个概率大到第一批请求就中。
- 这也解释了为什么 RC1「重启后 30 分钟 1157 次全 200」、RC2 两组 9 分钟都复现不出：
  那几组的时长和次数都还在「单并发安全区」的量级里（虽然它们用的是混合负载）。
- **结论：与「累计多少次」有关，但关系是「每次请求都有小概率」，不是「跑够多久必然坏」。**

### H4 卡死前的操作（kill -9 / OCR 卸载加载）—— **证据不足（未完成）**

- 本任务的 6 次复现（R0/R1/R7/R9/R10/R11/R14）**全部没有**做 `kill -9`、也**没有**做 OCR
  卸载/加载：每组都是「重启 → 加载 6 个模型 → 直接加负载」。所以那两个前置操作**不是必要
  条件**，但**是否提高复现率没有验证**。
- 脚本已经支持这组前置操作（`--pre crash-idle,crash-busy,ocr-cycles:5`，实现见
  `d7_experiment.py` 的 `crash()` / `ocr_cycles()`），板子到期前没来得及跑，
  记为**证据不足**，不是「不成立」。
- 仍然成立的一条纪律：`kill -9` 主进程本身不会触发卡死（MYS-2691 与 RC2 的 H4 都验证过
  接管正常），但「不要 SIGKILL 正在执行 NPU 的进程」这条仍然要保持。

## 卡死现场证据

原始输出在 [`d7/`](d7/README.md)（每次卡死一个目录，含 `summary.json`；目录说明见那个
README）。每个目录里都同时有 **dmesg 原文**、**`sysrq-w` 的内核栈**、**固件 scaler 状态**、
**hwq 空闲槽**、**卡死前 10 分钟的推理记录** 和 **本次实验的请求流水**。
（sophon-tools 源码快照不携带这些板端原始日志，只保留本报告与 `d7/` 下的结论文档；
原始件见原私有仓库。）

### 共同签名

```
# 1) 邮箱 + 等待
mbox submit timeout hwq 5 need 1
bmtpu: bmdrv_thread_sync_api:1526: bm-sophon0 bmdrv_thread_sync_api,
       wait api timeout, wait 120000ms, core_id=0, inflight=1, last=..., cpl=...

# 2) 固件共享状态（/proc/bmtpu/scaler_info，core0）
using_flag: a5a5          <- TPU_USING_FLAG，驱动认为 core 仍 busy
cur_api_id: 0x90000003    <- LAUNCH_FUNC，停在这个 API 上
recvmsg_cnt: <不再增长>
running_flag: aa0b0036（6 模型组） / aa550036（R8）
                          ^^ 正常值是 aa55040a（空闲）/ aa55003 系

# 3) 队列没满 —— 排除「邮箱槽位不足」
HWQ Index | Free Slots:  0..7 = 16,15,16,16,16,15,15,16   （共 124/128 空闲）

# 4) 用户态：所有在飞请求的线程 D 态，卡在同一个内核函数
task:python3.10 state:D  bmdrv_thread_sync_api+0x240/0x560 [bmtpu]
                         bm_ioctl -> bmdev_ioctl -> __arm64_sys_ioctl
```

### 关键一条：`mbox submit timeout` 的来源

`driver/84x6/84x6_mbox.c`：

```c
int bmdev_mbox_submit(...) {
    int need = (int)block_num + 1;
    ms = bmdi->cinfo.delay_ms ? bmdi->cinfo.delay_ms : 20000;
    for (;;) {
        ret = mbox_claim(nmax, need, &start);   // 只返回 0 或 -EAGAIN
        if (!ret) { /* post job */ return 0; }
        if (time_after(jiffies, timeout)) {
            pr_err("mbox submit timeout hwq %d need %d\n", hwq_idx, need);
            return -ETIMEDOUT;
        }
        usleep_range(200, 400);
    }
}

static int mbox_claim(int nmax, int need, int *start) {
    for (s = 0; s <= nmax - need; s++) {
        if (mbox_queue_blocked(s, need)) continue;     // 有别的 job 压着这个 core 区间
        for (i = 0; i < need; i++)
            if (mbox_ring_full(s + i)) ...             // 固件环 seq-ack >= 8
        if (!blocked) { *start = s; return 0; }
    }
    return -EAGAIN;
}
```

`mbox_ring_full()` 读的是**固件写的** `mbox_seq` / `mbox_ack`。所以
`mbox submit timeout` 的含义是：**连续 20 s 找不到一组可用的 core**，而不是「队列深度不够」。
`wakeup_control` 显示槽位几乎全空，与这条一致。

### 为什么一个 core 不应答会让整块板子哑掉

`driver/bm_api.c`（`bmdrv_thread_sync_api`，84X6 分支）：

```c
if (bmdi->cinfo.chip_id == BM_CHIP_ID_84X6) {
        core_id = 0;   //always 0
}
...
if (bmdi->cinfo.chip_id == BM_CHIP_ID_84X6) {
        while (atomic_read(&thd_info->api_inflight) > 0 && ret != 0)
                ret = wait_for_completion_timeout(&thd_info->msg_done,
                                                  msecs_to_jiffies(timeout_ms));
}
```

`core_id` 被强制成 0，等待的是**不区分 core** 的 `msg_done`。因此：

- 只要一次 launch 没被应答，**所有**调用 `bmdrv_thread_sync_api` 的线程一起等满 120 s；
- `dmesg` 里多条超时的 `core_id` 全是 0、`inflight=1`，就是这个结构的直接后果；
- 6 个 worker 各自有独立 fd，但共享同一个 `bmdi`，所以一个 core 卡住 = 整块设备不可用。

这是**驱动层的扇出放大**，不是应用层能修的。

## 给驱动团队的复现步骤

最短路径（3 模型 2 倍并发，R8 复现、559 s）：

```bash
# 板上，v0.6.29 已安装、服务已起来、模型全部未加载
pip 不需要；脚本只用标准库 + 安装包自带的 httpx
PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor \
  python3.10 d7_experiment.py --run R8 --out /tmp/d7 \
    --minutes 20 --models chat,vl,asr --load chat:4,vl:2,asr:2 --stall-s 150
# 卡死后（或任何时刻怀疑卡死）立刻采集：
python3.10 d7_capture.py --out /tmp/d7/captures --tag confirmed
```

更稳的复现（6 模型，3/3 命中，136 s）：

```bash
PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor \
  python3.10 d7_experiment.py --run R7 --out /tmp/d7 \
    --minutes 20 --models chat,embed,rerank,asr,ocr,vl \
    --load chat:2,embed:1,rerank:1,ocr:1,vl:1,asr:1
```

两个脚本都不需要改服务代码，`d7_capture.py` 是纯只读的。

**驱动侧建议优先看三处**：

1. `bmdrv_thread_sync_api` 在 84X6 上把 `core_id` 强制成 0 并用全局 `msg_done` 等待 ——
   是否应该按 core 分别等待，至少让一个 core 卡住不放大成 4 个 core 全哑。
2. `mbox_claim` 在 core 不可用时只能空转 20 s 后失败 —— 是否应该在 `mbox_ack` 长时间不前进时
   报出**是哪个 core、卡在哪个 seq/packet**（现在只有 `hwq` 和 `need`，信息不足以定位）。
3. 固件在 `cur_api_id=LAUNCH_FUNC`、`using_flag=0xa5a5` 且不再前进时的自恢复/看门狗。
   现在这条路径下固件永远不会自己醒，只能整机重启。

## 给负责人的规避建议（应用层，本任务**未实现**）

> 先给结论：**应用层没有「消除」的办法，只有「把频率降下来」的办法。**
> 下面第 1 条能把 6 模型下的 MTBF 从约 2 分钟提到约 2 小时（实测），
> 第 2 条在 20 分钟窗口内把 5 模型压到不复现，但没有跑到小时级，所以不知道它的 MTBF。

1. **限制「同一个 worker 上并发的 NPU 调用数 ≤ 1」，这是本次验证过最有效的应用层手段。**
   两组对照把变量锁得很死（都是 6 模型、NPU 30440 MiB）：

   | 做法 | 实测 |
   |---|---|
   | 同一个 worker 上来 2 个并发 | R11/R14/R10/R9/R1/R7/R0：**125–136 s 卡死（7/8）** |
   | 每个 worker 一次只处理 1 个请求 | R17：**130 min、3492 次全 200**，第 3493 次卡死；R12：20 min 干净 |

   注意 R16（6 模型、3 个线程但**分别打 3 个不同 worker**）跑了 20 min、503 次全 200 ——
   所以**不是「线程多」而是「同一个 worker 的并发高」**。落到实现上，最贴合的是
   「每个 worker 的在飞请求 ≤ 1」这条准入（辅助模型现在已经是这个语义，35B / VL 不是）。
   代价是混载时延上升，而且**它把 MTBF 从分钟级提到小时级，不是消除**。
2. **「少驻留一个模型」也有效，但同样只是把频率降下来。** 去掉 VL（2.2 GB）后，同一 worker
   并发 2 也干净（R15：20 min、670 次；R13：15 min、404 次；R3：20 min、958 次）。
   三组都只跑了 15–20 分钟 —— 按 R17 的经验，20 分钟干净**不能**推出小时级安全。
3. **不要靠「减少驻留模型数量」或「留 VPP」规避。** 卡死与驻留模型个数没有单调关系
   （R4 驻留 5 个、R8 只驻留 3 个，R8 反而卡死）；**VPP 从头到尾没被模型用过**（一直是
   256 MiB 的 reserve），「卸掉 ASR 让 VPP 空出来」这条旧建议在本次数据里没有依据。
4. **卡死后不要试图热恢复。** 本次 7 次卡死没有一次自愈（等 180 s 后最便宜的模型仍
   `ReadTimeout`，`recvmsg_cnt` 一个字节都没动），用户态进程退出后固件仍停在
   `using_flag=0xa5a5`。检测到 `wait api timeout` 就应直接进「需要重启」状态并对外返回
   明确的 503（D9 已经做了这件事）。
5. **监控判据**：`/proc/bmtpu/scaler_info` 里 core0 的
   `cur_api_id == 0x90000003 && using_flag == 0xa5a5 && recvmsg_cnt` 在 2 个采样周期内不变
   → 已经卡死。这比等 `dmesg` 的 120 s 超时早得多。
   实测的 `recvmsg_cnt` 在卡死后完全冻结（R11：卡死时 6292，180 s 后仍是 6292）。

### 一条容易误读的日志：`Coeff ... Check:**FAILED**`

卡死组的 35B worker 日志里会出现若干 `Check:**FAILED**`，紧跟 `Total N errors`。**这是结果，
不是原因**，别拿它当"权重被踩了"的证据：

`Bmruntime::trace()`（`tpu-runtime/src/bmruntime_bmodel.cpp:307`）只在 `sync_cores()` 拿到
非 `BM_SUCCESS` 之后才被调用（`bmruntime.cpp:718`），它做的事是把每一块 coeff 从设备读回
来重算 SHA256 比对。**设备已经卡死时这些回读本身就会失败**，于是报 FAILED。
同一批日志里 `[engine] NPU fault: sync timed out; reboot the board` 在前、trace 在后，
顺序就是证据。干净组（R12/R17）的日志里没有 trace 块。

（这一条值得记下来，因为它长得非常像根因，而且是我自己先误判了一次才查清楚的。）

## 与任务卡的偏差

- 任务卡要求「每组至少 20 分钟」：并发 ≥2 的组在 125–136 s 就卡死，无法跑满 20 min；
  卡死本身就是结论，没有为了凑时长去重试同一组。
- 任务卡要求「一组配置长跑 ≥ 2 小时」：**已做**（R17，130 分钟），结论与预期相反 ——
  单并发也卡，只是发生在 2 小时后（第 3493 次请求）。这一条是本次最容易被误读的数据，
  所以单独列在结论第 1 条。
- 任务卡列的 H4「比较『先做 kill -9 / OCR 卸载加载再加负载』与『重启后直接加负载』的复现率」：
  只完成了后者（7 次卡死全部是「直接加负载」），**前者没有单独跑**。
  这一条按「证据不足」记录，`crash-idle,crash-busy,ocr-cycles:5` 这组前置操作已经写进脚本
  （`--pre`），可直接补跑。
- 每组的「时长」对卡死组记的是「到卡死为止」的时长，不是计划时长。
- 板子在 2026-11-08 12:40 之后处于卡死状态（R17 的收尾），用
  `systemctl reboot --force --force` 恢复。本次任务共重启 **20 次**：驱动脚本发起 19 次
  （每组实验开始前的干净重启 + 卡死后的恢复），加 1 次手工恢复（R0-smoke 卡死后）。
  所有重启都用 `--force --force`，每一次 `boot_id` 都变了、`:8000` 都恢复了。

## 收尾时板子的状态

任务卡要求结束时板子可用。2026-11-08 13:00 CST 最后一次 `systemctl reboot --force --force`
之后实测：

| 项 | 实测 |
|---|---|
| 安装包 | `cv84x6-llm-server 0.6.29`（dpkg），`/healthz` 自报 `{"ok":true,"version":"0.6.29","loaded":0}` |
| 已加载模型 | 无（`/api/models` 里 `loaded` 全为 false） |
| NPU 堆 | `npu 0/30720 MiB`，`vpp 256/4094 MiB`（256 是启动 reserve） |
| TPU 使用率 | `0.0%`，四核 `[0,0,0,0]` |
| dmesg | 本次开机后 `wait api timeout` **0** 条，`Internal error: Oops` **0** 条 |

注意：本次开机后的 `wait api timeout` 是 0，但**更早的开机**里我因为读
`/proc/bmtpu/bmdi_base_info` 触发过 2 次 Oops（`otp_reg_read`），当时的 boot_id 是
`1c7f8d66`。那两次是采集脚本早期版本的问题，已经修掉（`SKIP_PROC`），
与 D7 卡死无关，也不在当前这次开机里。

---

# 修复实验（MYS-2703，2026-11-08）

同一个 10155、同一份 v0.6.29 正式包。三件事：认出卡住的那条命令、把「堆满」与
「同 worker 双会话」拆开、试出能连续 60 分钟不卡的应用层修复。

原始记录分两份：
[`d7/step1-stuck-command.md`](d7/step1-stuck-command.md)（命令身份）与
[`d7/step2-3-conditions-and-fix.md`](d7/step2-3-conditions-and-fix.md)（条件与修复）。

## 更正上文的四处读法

1. **「卡住的是一条单核命令」不成立。** 新增引擎内命令 trace（在实际调用**之前**落盘）
   显示：卡死时 35B 的最后一条是 `lm_head core=4`，此前 40 层 `block_cache_*` 与
   `sync` 全部正常返回。`kernel_fifo` 里的 `block=0 send_core_num=0` 是 outbox packet
   的位域，不是核数——它在**完全健康**的板上每个 decode 轮都会出现一次，位置正是
   `lm_head`。所以「单核命令」这个前提本身就是误读。
2. **`greedy` 这条路径根本不存在。** 引擎启动横幅 `lm_topk=1 greedy=0`：argmax 已融进
   `lm_head`，`sample_lm()` 走 `if (lm_topk || !net_greedy)` 分支，只发一次 `lm_head`
   再直接 D2S 取 token。上文「也可能是 `lm_head` / `greedy`」应读作「就是 `lm_head`」。
3. **`threads.txt` 里那个 D 态线程的归属**、以及 R11 现场「0 个请求完成」这两条维持原判，
   与本次 T1/T2 一致（125 s / 140 s 卡死，0 个请求完成）。
4. **前缀缓存不是条件。** 把 35B 的 `prefix_cache_max_mb` 设为 0 后，R11 配置仍然
   125 s 卡死。park/unpark 与快照腾挪**不需要**参与触发。

## 第 2 步：条件是「NPU 堆余量」，不是「哪个模型在场」

压舱物实验把两个变量拆开：5 模型（无 VL，R15 原本干净）+ 一个只 `bm_malloc` 不用
的独立进程占 2153 MiB，把 NPU 余量压到 **279 MiB**（与 R11 的 280 相同）。

| 组 | 驻留 | NPU 余量 | 结果 |
|---|---|---|---|
| B1 | **5 模型（无 VL）** | 279 MiB（压舱物） | **136 s 卡死**，0 个请求完成，卡在 `lm_head` |
| C1 | 6 模型，**前缀缓存关闭** | 280 MiB | **125 s 卡死**，0 个请求完成 |

**「堆几乎占满」就是条件本身**，第 6 个模型（VL）与 VL 的活动都不是必要条件；
前缀缓存也不是。上文 H2 的「堆余量是必要条件之一」在本次被收紧成「它是唯一的那个」。

## 第 3 步：修复=准入里守住余量下限

扫描（5 模型 + `chat×2`，压舱物调余量，每组 12 分钟，只变余量一个数）：

| NPU 余量 | 结果 |
|---|---|
| ~280 MiB | 136 s 卡死 |
| 512 MiB | 135.8 s 卡死 |
| **640 MiB** | **12 min / 398 请求全 200** |
| **1024 MiB** | **12 min / 404 请求全 200** |

边界在 512–640 MiB 之间。默认取 **1024 MiB**，因为「20 分钟干净不等于几小时干净」
（R17 就是 130 分钟后才卡）。

实现（`app/core/models.py` 的 `ModelManager._check_npu_reserve`，新设置项
`CV84X6_NPU_RESERVE_MB`，默认 1024，0 关闭）：

```
NPU 当前空闲 − 本次加载自身的占用 < R  →  409 device_memory_insufficient
```

三个要点，都来自实测踩的坑：

- **必须减去本次加载的占用**。只比「当前空闲 ≥ R」就是原有 `_check_npu_admission`
  在问的问题，而它对 6 个模型全回答「装得下」；要问的是**装下之后还剩多少**。
- **对 chat 也生效**。原有准入对 chat 直接跳过；而故障就发生在 chat 上。
  这里用 `static_bytes()`（35B = 22752 MiB，上一次加载实测），不是文件大小估算。
- **只比 NPU 堆**。VPP 在全部现场都停在 256 MiB 启动保留上；把它算进来会把
  「NPU 剩 280 / VPP 剩 3838」判成「还有 4 GiB」，正好放行卡死配置。

板上验证：按 R11 的顺序加载 6 个模型，第 6 个（VL）现在是
`409 {"code":"device_memory_insufficient"}`，消息里给出模型、余量、下限和该卸载谁。
**触发这次卡死的那个配置，从 API 层面就装不出来了。**

原生侧同时给 `d2d()` / `zero()` 补了返回值检查（原来完全丢弃），
但要注意：本次全部卡死现场里 d2d 与 memset 都是 `rc=0`，所以它们**不是**病因，
这项改动是防御性的。

### 60 分钟验证（修复装到板上之后）

`/data/mys2693/runs/S60`，修复允许的最大配置 + `chat:2`（与 R11 同样的负载形状）：

| 项 | 实测 |
|---|---|
| 时长 | **3600.5 s** |
| 请求 / 成功 | **2027 / 2027 全 200** |
| 卡死 | 无 |
| `wait api timeout` | 0（前后都是） |
| Oops | 0 |
| NPU | 起始 28516 MiB 已用 / 结束 26724 MiB |

对照 R11：同一块板、同样 `chat×2`、6 模型，**125 s 卡死、0 个请求完成**。

**修复没有消除驱动缺陷。** `bmdrv_thread_sync_api` 那条依然在（见上文「给驱动团队的
复现步骤」）。修复做的是不让应用层把设备推到那个状态；把
`CV84X6_NPU_RESERVE_MB=0` 关掉、重新占满堆，卡死会照旧发生。

---

# 运行期预算漏掉了同一个下限（MYS-2784，2026-11-11）

MYS-2703 的修复只在**加载**路径上守住了 1 GiB 余量。worker 自己的运行期预算
（parked 会话 + 前缀缓存能拿多少）仍然是

```
加载后空闲 − NPU_SAFETY_BYTES(512 MiB)
```

**512 MiB 正是上面扫描表里实测会卡死的两个点之一（280、512 卡；640 起干净）。**
所以一次加载可以通过准入检查，然后把准入检查要保的那 1 GiB 花掉。

## .151 实测（24 GiB 堆，35B-A3B 128k，客户 stress_check 的 long 形态）

| 项 | 实测 |
|---|---|
| 加载后 NPU 空闲 | 1567 MiB |
| worker 运行期预算（旧逻辑） | 1056 MiB = 1567 − 512 |
| 两路 17.7k 并发会话 | 是（`max_concurrent=3`，第三路排队） |
| NPU 空闲最低 | **2 MiB**（1567 → 1024 → 327 → **2**） |
| 同一时刻 resv + cache vs 预算 | **1510 MiB vs 1056 MiB** |
| 客户现场 | 121 s 后 `NPU fault: memset failed`，即驱动 120 s 超时 |

客户的现场与这条曲线形状一致，只是晚了一秒：2 MiB 空闲之后紧接着就是卡死。

**第二个缺陷，同一套算术。** `_fits` 只在**准入**时校验
`cache + reservations ≤ budget`，而 `PrefixCache.put` 只校验自己的 `max_bytes`，
而那个值就是整个预算。于是「会话跑完 put 一个快照」可以在已经被预约占满的预算上
再加一份：757 MiB 预约 + 753 MiB 缓存 = 1510 MiB，最后一个 2 MiB 台阶就是它。
两处 `put`（prefill 中途的 `snapshot_points` 和生成结束后）现在都在**快照分配之前**
校验余量，而不是插入之后再驱逐 —— 原生后端的 `snapshot()` 本身就在分配设备内存，
事后驱逐等于已经记到堆账上了。

## 修复与验证

* `npu_kv_budget` / `npu_cache_cap` 改用与加载检查**同一个** `npu_reserve_bytes()`
  （`CV84X6_NPU_RESERVE_MB`，默认 1024，0 关闭），不再有第二个常数；
* 两处缓存插入前校验 `cache + reservations + 本次快照 ≤ budget`，不够就跳过这次缓存
  （缓存是优化，会话是活干活）；
* 同一次 4 路 × 17.7k 负载，装修复后：NPU 空闲**全程 1567 MiB 不动**，
  0 个采样点超预算，`wait api timeout` 0，`NPU fault` 0。

**结论不变：驱动缺陷还在。** 这次修的是「不让应用层把堆推到 2 MiB 那个状态」。
把 `CV84X6_NPU_RESERVE_MB=0` 关掉，同一条曲线会照旧出现。

## 关于 130 s 卸载

客户 reload 第 3 轮的「卸载耗时 130 s」就是 `UNLOAD_GRACE_S + KILL_GRACE_S`
（120 s + 10 s）：worker 卡在 `bmdrv_thread_sync_api` 里，SIGTERM 唤不醒它，
只能等满宽限期。这是上面那个卡死的后果，不是独立问题。

但它暴露了一个独立缺陷：`_terminate` 为「收到 SIGTERM 仍未退出」的 worker 记了
`conflict`，紧接着 `unload` 调 `_forget` 把它清掉了。于是模型显示「已卸载」，
而进程还占着 22 GiB；下一次加载在这个洞上又起了一个 worker，
报 `bmrt_load_bmodel failed (wrong chip or corrupt file?)`，然后 409。
现在存活者会保留 `conflict`：加载被拒并指名 pid，「卸载」按钮仍然够得着它。
