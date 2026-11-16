# BMRT 未完成队列深度：能否配置、安全上界与实际收益

| 项目 | 内容 |
|---|---|
| **历史结论** | 队列深度是驱动的编译期常量，没有运行时配置入口；队列满时 CPU 等的是 TPU 在跑上一层，可回收余量约 1.0 ms/token（3%） |
| **当前约束** | **no-go**：不加开关、不做 hack，服务里也没有相关配置项。若仍要向厂商提问，问题清单见本篇 §6（重点已从「能不能加深」转成 `lm_head` 的阻塞行为） |
| **本篇保留** | 驱动符号证据、受控探针、与真实引擎的交叉验证——若将来厂商提供新运行时，这是复核起点 |

> 子任务 MYS-2469（父 MYS-2293）。本文只做只读分析与受控探针：
> **未改引擎、未改 bmodel、未改服务、未 bump、未发版**。
> 所有数字在 `10.42.0.242`（测试样机，账号见设备台账）、libsophon 0.4.15、Qwen3.6-35B-A3B
> 128k bmodel 上实测。板端原始日志 `board_2026-10-29.log` 未入库（体积与内含完整 dmesg），
> 从中摘出的表在 [`analysis/raw/queue_depth_table.txt`](../../analysis/raw/queue_depth_table.txt)，
> 驱动符号证据在 [`analysis/raw/driver-evidence/`](../../analysis/raw/driver-evidence/)，
> 真实引擎交叉验证另见 [`analysis/raw/decode_bench_crosscheck.txt`](../../analysis/raw/decode_bench_crosscheck.txt)。
> 下文引用 `board_2026-10-29.log` 的段落均可由这三份文件复核。

## 0. 结论先行

1. **没有合法的运行时配置入口。** 公开头文件里没有任何开关；驱动没有模块参数；
   设备树也不提供。深度是驱动里的一个**编译期常量**：`tsh_cfg_default` 的
   `mode = 1`，对应每 HWQ 16 槽；同一份驱动里还有一条 `mode = 2` 的
   **每 HWQ 64 槽**路径，但用户态无法切换（§1.3）。所谓「17」实际是
   **每 HWQ 16 个空槽 + 1 个正在执行的**，共 8 个 HWQ，每线程轮转绑一个。
2. **即使能配，收益也只有 1.0 ms/token（约 3%），不是 33%。** MYS-2457 §5.3 的 33%
   上界建立在一个错误前提上：把「第 18 个 launch 起每次阻塞 585 µs」当成 CPU 开销。
   实测那 585 µs **正好等于一层的 TPU 执行时间**（0.580 ms），TPU 在整条 chain 期间
   的忙碌占比是 **97–99%**。一次 token 的墙上时间里，TPU 空闲部分只有 **1.0 ms**，
   这才是任何队列深度改动能碰到的全部空间。
3. **队列确实被填满，且精确停在深度上限 16**（读驱动自己的 `free_slots`：占用峰值
   16/16）。但填满不是瓶颈 —— 填满之后多出来的 585 µs/层就是 TPU 在跑上一层的活，
   所以队列满已经成为当前最优状态，加深只会把阻塞从 submit 挪到 sync。
4. **替代路线（合并 40 个图为 1 个 net）的上限也只有 4%出头。** 能省掉的
   「图间 TPU 派发间隙」实测 0.35–0.49 ms / 40 图（8.8–12.3 µs/图），
   加上 CPU 入队开销合计上限约 1.0–1.2 ms / 24.5 ms chain（4.1–4.8%），
   而且要重编 bmodel、重做精度对齐，代价与收益不成比例。
5. **go/no-go：no-go。** 不建议为此向厂商申请开关，也不建议做 hack —— 即使走
   mode 2（64 槽）路径，收益上限仍是 1.0 ms/token（3%）。若仍要向厂商提问，
   见 §6 的问题清单（重点已从「能不能加深」转成
   「为什么 `lm_head` 的 launch 会阻塞 10 ms」）。

## 1. 队列到底长什么样子

### 1.1 公开头文件：没有这个开关

`/opt/sophon/libsophon-0.4.15/include/` 全部头文件里，与队列深度可能相关的只有：

| 位置 | 内容 | 与深度的关系 |
|---|---|---|
| `bmruntime_interface.h:475-496` | `bmrt_launch_tensor_ex`「CPU program will not be blocked」 | 只说非阻塞，未提队列深度或容量 |
| `bmdef.h:51-58` | `bm_runtime_flag_t`：`AUTO` / `SHARE_MEM` / `CHECK_MEM` / `SHARE_DYNMEM` / `SOC_CMDBUF_MEM` / `FREE_COEFF` / `NEURON_MEM_IN_PRE_ALLOC` / `YIELD_TO_KERNEL_TASK` | **8 个 flag 全部与内存分配或 kernel task 让位有关，没有一个是队列深度** |
| `bmlib_runtime.h:2399-2408` | `bm_set_sync_timeout` | 只设等待超时，不设容量 |
| `bmlib_runtime.h:3417-3455` | `bm_tpu_kernel_task_begin/end/wait_done` | 只影响 kernel task 与 subnet api 的排队优先级 |

`bmrt_set_flags` / `bmrt_get_flags` 的文档只写了「flag defined by `bm_runtime_flag_t`」，
而该枚举已完整列在上表。**没有任何公开 API、flag 或环境变量能改队列深度。**

### 1.2 运行时与驱动的符号、字符串

`libbmrt.so.1.0` / `libbmlib.so.0` / `bmtpu.ko` 的字符串与符号表里出现的环境变量只有
profile/mem-guard/log 一类（`BMLIB_ENABLE_PROFILE`、`BMRT_LOG_LEVEL_THRESHOLD`、
`BMRT_DYN_SUBMIT_LOCK`、`BMRT_DP_NUM`、`BMRT_SAVE_IO_TENSORS` 等），
**没有一个与队列深度相关**。其中 `BMRT_DP_NUM` 经反汇编确认是 `static_subnet()` 里的
数据并行度（按 `strtol` 解析后用于切分系数/切片，`libbmrt.so.1.0` `Launcher_CV84X6::static_subnet`
的 `getenv` 调用点），不是队列深度，**不作为证据使用**。

驱动的 `/sys/module/bmtpu/parameters/` 只有三个参数：
`tpu_core_num=4`、`tpu_dump_msg=0`、`tpu_log_lv=0`。**没有 depth/queue 参数。**

### 1.3 驱动里深度的真实来源：两个编译期常量，没有运行时入口

驱动 `bmtpu.ko` 自带一个只读的 proc 接口，直接暴露了队列几何：

```
$ cat /proc/bmtpu/kernel_info
=== BMDev Kernel Information ===
  dev_index: 0
Global max_depth: 16
Number of HWQs (NUM_HWQS): 8
...
--- HWQ Index: 0 ---
  free_slots: 16
  pushed_cnt: 0
  total done: 0
```

反汇编把这个 16 的来路完全查清了（逐条指令见
[`analysis/raw/driver-evidence/`](../../analysis/raw/driver-evidence/)）。
**深度来自驱动里的一个编译期常量，不是固件探测、也不是模块参数：**

* `bmdrv_probe` 调用 `tsh_init(handle, NULL)`（`x1 = #0x0`）。`tsh_init` 的序言是
  `cmp x1, #0` + `csel x20, default+0x68, x1, eq` —— 传 NULL 就用内建的
  `.data.tsh_cfg_default + 0x68`。该结构的第一个字段是 **mode**，dump 出来是 **`1`**。
* `tsh_init` 随后把 mode 写进硬件 `0x2d0_6004`（`str w2, [x20]` → `tpu_reg_write`），
  然后按 mode 分派：`cmp w21, #2` 决定走哪一族深度寄存器。
* **mode 1**：读 `0x6024`/`0x6028`，期望值 **`0x10101010`** —— 四个字节各 `0x10 = 16`，
  即**每 HWQ 16 槽**。这就是当前板子的状态（boot log 的
  `kfifo init: total size=16384` = `8 HWQ × 16 × 128B` 与之吻合）。
* **mode 2**：读 `0x6050`/`0x6054`，期望值 **`0x40404040`** —— 每字节 `0x40 = 64`，
  即**每 HWQ 64 槽**。同一份驱动里存在一条 depth=64 的路径，
  `bm84x6_task_init` 也是按 `mode == 2` 在 `16` 与 `64` 之间 `csel` 决定 kfifo 槽宽。
* 上述 6 处深度寄存器访问**全部是 `tpu_reg_read`**，没有一处 `tpu_reg_write`：
  驱动只是读回校验，深度是更下层（固件）设定的。
* 深度寄存器的字段宽是 8 位（每 32 位寄存器装 4 个 HWQ，`mask 0xff`，`shift (idx%4)*8`），
  所以**硬件上限是每 HWQ 255**，16 和 64 都是选择而不是极限。
* 设备树只提供 `sophgo_c906_fw_mode` 一个属性（`of_property_read_variable_u32_array`
  只读这一个名字），**不涉及队列深度**；`/sys/module/bmtpu/parameters/` 只有
  `tpu_core_num` / `tpu_dump_msg` / `tpu_log_lv` 三个参数，**也没有深度**。

**结论：16 与 64 都是驱动编译期选定的；用户态没有任何合法入口在两者间切换。**
切到 mode 2 需要改驱动重编重载（不在本任务允许范围内，且见 §2/§3：
即使切过去，收益上限只有 1.0 ms/token）。

### 1.4 为什么表现成「17」

`queue_scope` 单线程连续 48 次 launch（同步前）的逐次耗时：

```
  1    141.6        13     67.6
  2     64.3        14     57.1
 ...               15     76.4
 16     59.6       16     59.6
 17     59.8       17     59.8
 18    470.7  <- blocked
 19    591.3  <- blocked
 ... 之后每次稳定 577-611 us
first blocking launch index = 17 (1-based: 18)
```

前 17 次约 60 µs，第 18 次起约 585 µs。**16 个空槽 + 第 1 个已经在 TPU 上跑**
= 17 次能立刻返回。这与驱动的 `free_slots: 16` 完全吻合，也解释了 MYS-2457 测到的 17。

## 2. 关键：那 585 µs 不是 CPU 开销

MYS-2457 §5.3 推算 33% 收益的算式是「40 次入队的固有成本 40 × 62 µs = 2.5 ms，
而现在是 13.6 ms，所以理论上限每 token 省 11 ms」。这个推理只有在**TPU 在那 13.6 ms 里闲着**
时才成立。libsophon 自己提供了判定依据：`bm_profile_t.tpu_process_time`（`bmlib_runtime.h:2424-2444`，
经 `bm_get_profile()` 读取）。把它和墙上时间对比即可分辨。

### 2.1 单图重复（block_cache_0 × 40，stage 6）

`tpu_busy`，5 次重复取中位数：

| 形态 | 墙上时间 | TPU 忙碌 | 占比 |
|---|---:|---:|---:|
| 1 层 + 1 次 sync | 0.654 ms | 573 µs | **0.88** |
| 40 层 + 1 次 sync | 23.824 ms | 23178 µs | **0.97** |

`40 × 0.580 ms = 23.18 ms` 的 TPU 时间 vs 23.82 ms 墙上时间 —— **TPU 全程 97% 在忙**。
每层 TPU 时间 0.5795 ms，与观察到的 585 µs 阻塞**逐位吻合**（差 1%）。
也就是说：第 18 次 launch 的「阻塞」，就是 CPU 在等 TPU 把第 1 层跑完腾出槽位。

### 2.1b 同一个探针内部的对照实验（最强证据）

`queue_model` 的深度扫描本身就是一次**受控 A/B**：同一个图、同一个探针、同一轮运行，
只是 n（不同步的 launch 数）从 1 变到 64。n ≤ 17 时队列根本填不满，n ≥ 18 时
队列永久满载并持续阻塞。如果那 585 µs 是「加深队列能省掉的 CPU 开销」，
那么 `ms/layer` 应该在队列停止填满后**掉下来**：

| n | submit | sync | total | **ms/layer** | 队列状态 |
|---:|---:|---:|---:|---:|---|
| 1 | 0.055 | 0.598 | 0.653 | 0.6530 | 未填满 |
| 8 | 0.489 | 4.366 | 4.855 | 0.6069 | 未填满 |
| 16 | 0.967 | 8.692 | 9.659 | 0.6037 | 未填满 |
| 17 | 1.090 | 9.173 | 10.263 | 0.6037 | 未填满 |
| 18 | 1.435 | 9.429 | 10.864 | 0.6036 | 满载阻塞 |
| 24 | 4.970 | 9.408 | 14.378 | 0.5991 | 满载阻塞 |
| 40 | 14.403 | 9.404 | 23.807 | 0.5952 | 满载阻塞 |
| 64 | 28.570 | 9.406 | 37.976 | **0.5934** | 满载阻塞 |

**`ms/layer` 全程平稳在 0.59–0.61 ms，且 n=64（深度阻塞）比 n=1（不阻塞）还略低。**
把 sync 里省下的时间算进去，单层总成本与队列深度**完全无关**。
submit 那 14.4 ms 里被「卡住」的时间，一分不少地出现在原来 sync 的位置上 ——
**这不是开销被消除，而是等待被搬了个位置**。这正是「TPU 是瓶颈」的判据。
（原始的 submit 逐次成本见 `queue_scope`：前 17 次 ~60 µs，第 18 次起 ~585 µs，
585 µs ≈ 一层的 TPU 时间。）

### 2.2 真实 40 个不同图（token_shape，含 lm_head）

MYS-2457 的模型是 40 个**不同**的 `block_cache_<i>`（各自独立系数与顶点流），
所以用真实链条复测。三条 stage 阶梯都测：

| 上下文窗口 (stage) | chain submit | sync | 整 token 墙上 | TPU 忙碌 | TPU/墙上 | **可回收余量** |
|---|---:|---:|---:|---:|---:|---:|
| 2049 (stage 6) | 14.79 ms | 9.65 ms | **34.35 ms** | 33.34 ms | 0.97 | **1.01 ms** |
| 8193 (stage 4) | 16.28 ms | 10.64 ms | **36.92 ms** | 35.93 ms | 0.97 | **0.99 ms** |
| 131073 (stage 0) | 47.20 ms | 31.26 ms | **88.46 ms** | 87.41 ms | 0.99 | **1.05 ms** |

三条阶梯的余量都是 **0.99–1.05 ms/token**，与上下文长度无关。
按 stage 6 的 34.35 ms/token 算，1.01 ms 是 **2.9%**，不是 33%。

**为什么差这么多：** 585 µs 的阻塞发生在 submit 调用里，但它等的是 TPU。
即使队列无限深，这 40 层也只能被 TPU 一层一层做完 —— 时间下限是
`40 × TPU 单层时间`，而不是 `40 × CPU 入队时间`。队列深度只影响「CPU 提前多久把活交出去」，
而 CPU 早已跑在 TPU 前面（见 §3）。

### 2.3 交叉验证：真实服务基线

`decode_bench`（真实 `libcv84x6_llm.so`，64 token prompt / 64 decode）：

```
run 1: 64 tokens in 2.141s = 29.89 tok/s
run 2: 64 tokens in 2.140s = 29.91 tok/s
RESULT decode_tps_mean=29.90 spread=29.89-29.91 n_runs=2
```

29.90 tok/s = 33.4 ms/token，与 `token_shape` 在 stage 6 的 34.35 ms **同一量级且方向一致**
（差 1 ms，差额是真实引擎的 mask/pos 上传、token 回读与采样，MYS-2457 测得合计 0.05 ms
加上调度与 Python 侧开销）。探针的结论可以外推到真实服务。

## 3. 队列确实被填满了 —— 而且恰好停在深度上限

前两节关于「队列已满」都是从 submit 耗时推断的。这里直接读驱动自己的计数器：
`queue_occupancy` 在一个线程持续压满 40 图 chain 的同时，用另一个线程高频采样
`/proc/bmtpu/kernel_info` 的 `free_slots`：

```
# 40 graphs, 10 iterations of a saturated run
## at rest
  free_slots=[16,16,16,16,16,16,16,16]  pushed=[264,20404,1719,22019,...]
## while saturated
  watcher samples            = 2881
  min free slots on HWQ 0    = 16  (of 16 at rest)
  min free slots, all HWQs   = 112  (of 128 at rest)
  mean wall per saturated run= 24.377 ms
...
   HWQ   pushed_delta
     2          400          <- used
  total pushed delta = 400
```

**占用峰值是 128 − 112 = 16 个槽，这一个线程整个压测期间都绑在 HWQ 2 上
（`pushed_delta = 400` = 10 轮 × 40 图），而 HWQ 2 正好是 16 槽 —— 即它被填满了。**
也就是说队列**确实会饱和，且精确停在 16 这个深度上限**，与 §1.4 的逐次耗时、
§1.3 的 `free_slots: 16` 三处独立吻合。

这个观测**不能**用来支持「加深队列有价值」，恰恰相反：它是 §2 结论的第三个佐证 ——
队列填满之后，多出来的 585 µs/层无处可去，只能变成 CPU 阻塞，
而这 24.38 ms 的墙上时间里有 97% 是 TPU 在忙。**填满的状态已经是当前最优。**

（注：`min free slots on HWQ 0 = 16` 是因为该线程绑在 HWQ 2，不是 HWQ 0；
另外 8 个 HWQ 的少量占用来自其它子系统，不影响结论。）

## 4. 深度是每线程 / 每 HWQ，不是全设备共享

MYS-2469 的问题清单里问「每 device / core / thread」。这是可测的：
`queue_threads` 让 4 个线程同时各发 40 个 launch（barrier 对齐起跑），
看每个线程自己的首次阻塞点，以及驱动的 per-HWQ push 计数：

```
  thread    baseline_us    first_stall       stall_us
       0          160.3             18         1691.9
       1          232.5             18         3960.4
       2          268.5             18         3606.1
       3          193.7             18         1614.7

   HWQ   pushed_delta
     0             40  <- used
     1             40  <- used
     6             40  <- used
     7             40  <- used
distinct HWQs used by 4 threads: 4
first-stall index per thread ranges 17..17
```

**每个线程都独立拿到 17 次廉价 launch，且各自落在不同 HWQ。**
所以预算是**每线程/每 HWQ** 的（libbmlib 把提交线程轮转绑到 8 个 HWQ，
驱动日志里的 "Thread bound to HWQ %d (Round Robin)" 即此）。

这一点很重要，因为它说明：**多线程并发时队列容量不是瓶颈**
（`queue_scope` 实测 4 线程各 40 图，墙上时间线性增长到 95.6 ms，
是 TPU 串行执行的结果，不是队列容量限制）。真正的共享资源是 TPU 本身。

## 5. 替代路线：合并 40 个图为一个 net

MYS-2457 §5.3 认为「唯一剩下的形态是减少图的个数」，并给出 11 ms/token 上限。
`graph_tpu` 把同一批图**单独跑**与**串起来跑**的 TPU 忙碌时间相减，
得到图间派发间隙的真实值：

```
sum of per-graph TPU time      = 23542 us (23.542 ms)
chained TPU time               = 24036 us (24.036 ms)
inter-graph TPU dispatch gap   = 494 us (0.494 ms) over 40 graphs = 12.3 us/graph
chained wall                   = 24.717 ms
wall - TPU busy                = 0.681 ms (CPU enqueue + sync latency)
```

再测一轮（见 `analysis/raw/board_2026-10-29.log` 的 graph_tpu 段）得到
352 µs / 8.8 µs per graph，合并上限 1.005 ms / 24.462 ms chain（4.1%）。
即：

| 可省项 | 量级 |
|---|---:|
| 图间 TPU 派发间隙 | 0.33–0.49 ms / 40 图（8.3–12.3 µs/图） |
| CPU 入队 + sync 延迟（墙上 − TPU） | 0.63–0.68 ms |
| **合计上限** | **约 1.0–1.2 ms / 24.4 ms chain（4.0–4.8%）** |

**这与队列深度的上限是同一个数**，因为它们攻击的是同一个行项。而且合并图需要重编
bmodel、重做精度对齐，收益 4.8% 且只在 TPU 派发上 —— 投入产出比明显不成立。

## 6. 需要厂商确认的问题（可直接转交）

> 结论已从「能不能加深队列」转成「为什么有些 launch 会长期阻塞」。
> 第 1 条是唯一还值得问的，其余是把它问清楚所需的上下文。

1. **`lm_head` 的 `bmrt_launch_tensor_ex` 为什么在 launch 内部阻塞约 10 ms？**
   头文件（`bmruntime_interface.h:475`）明确写「CPU program will not be blocked」。
   本轮把 `lm_head` 放在**空队列**上单独测（前面先 `bm_thread_sync` 排空）：

   ```
   ## lm_head alone, queue empty (median of 5)
      rep    launch_ms    sync_ms       tpu_us
        1       10.094      0.001         9628
        ...
        5       10.001      0.001         9599
   per-token verdict: lm_head launch, empty queue = 10.055 ms
   ```

   **队列是空的，launch 仍耗时 10.06 ms，而它的 TPU 时间只有 9.60 ms。**
   即 launch 在等这一次推理自己完成 —— 这与「launch 不阻塞」的公开契约直接矛盾，
   也与其它 41 个图的正常行为（launch ~60 µs、由 `bm_thread_sync` 收尾）不同。
   这是本轮找到的唯一一处契约违背，也是 decode 里最大的单点成本（33 ms/token 的 30%）。
   **问题：这是有意的同步语义，还是可以实现为非阻塞？** 若能改成非阻塞，
   收益量级可能高于本文讨论的一切（但需另立任务验证，不在本轮范围）。
2. **`TSH_HWQ_DEPTH` 的 mode 1（16）与 mode 2（64）分别面向什么场景？**
   驱动里两条路径都在（`0x6024/0x6028` 期望 `0x10101010`，`0x6050/0x6054` 期望
   `0x40404040`），当前 mode 由 `tsh_cfg_default` 硬编码为 1，用户态无入口切换。
   请问厂商：mode 2 是否是给高吞吐/多模型场景准备的、有没有官方的启用方式
   （驱动参数、设备树、还是必须换驱动/dtb）？
   若厂商提供合法启用方式，本轮数据显示**收益上限仍只有 1.0 ms/token（3%）**，
   因此我们不申请在生产的 decode 路径使用；记录在此是为了让结论完整
   ——「不可配」的准确说法是「**当前不存在合法的运行时配置入口，且切换后的
   收益不值得为此重编重载驱动与配套 dtb**」。
3. **多个 `block_cache_<i>` 能否在 tpu-mlir 编译期合并为一个 net（多 subnet）？**
   若能，可省 0.35–0.49 ms/40 图（1.4–2.0%）的 TPU 派发间隙。同样不建议为此重编，
   仅作为编译侧的可行性备查。
4. **`bm_get_profile()` 的 `tpu_process_time` 在多核（core_num=4）下是累加还是墙钟？**
   本轮把它当作「设备忙碌时间」使用，交叉验证了它与墙上时间的比值在不同上下文下
   稳定在 0.97–0.99，结论不依赖这个细节；但厂商确认后可以让后续报告更严谨。

## 7. 边界与风险

* **本轮不改生产行为。** 没有写任何未知 flag、没有 LD_PRELOAD 假造能力、
  没有改 bmodel/引擎/服务。所有探针都是「用公开 API + 读驱动 proc + 反汇编只读证据」。
* **反汇编证据的分量。** §1.3 的 `0x10101010` 与「只读不写」是静态证据，
  解释力很强，但严格说不等于厂商文档。因此 §7 问题清单里保留了向厂商确认的那一条；
  **本文不把它当作「已获厂商确认」**。
* **`BMRT_DP_NUM` 不作证据。** 它确实是公开 strings 里的未公开环境变量，反汇编显示它在
  `static_subnet` 里做数据并行切分，与队列深度无关。列出来是为了防止后续有人拿它当线索。
* **测量条件。** 所有数字在 35B-A3B 128k bmodel、空闲设备（服务未加载模型）上取得。
  其他模型/其他 bmodel 的 stage 阶梯会改变绝对值，但 §2 的「TPU 忙碌占比 97%+」是
  结构性的（40 个串行图 + 1 个 lm_head），不预期会变。
* **未触碰预填充精度问题**（MYS-2394/2396/2403/2405）。本文全部在 decode。

## 8. 真机状态与恢复

| 项 | 状态 |
|---|---|
| 设备 | `10.42.0.242`，libsophon 0.4.15，Ubuntu 22.04.5，kernel 5.10.4 |
| 探针运行前 | 服务 `cv84x6-llm` active，**未加载模型**，`/dev/bm-tpu0` 无持有者 |
| 探针运行后 | 服务仍 active，模型仍未加载；`/tmp` 下有本轮探针二进制 |
| TPU 侧致命错误 | `bmdrv_thread_sync_api` 超时 / `bdc_reg_read` oops / `recursive fault` **全部为空** |
| 强杀 NPU 进程 | **未发生**。所有探针都 `timeout -s KILL`，实际全部正常退出（EXIT=0） |
| 临时进程 | 探针结束后无残留（`ps` 检查为空） |
| 读性能 | 探针结束后用 `queue_model` + `token_shape` 复测，数字与之前一致（TPU 正常工作） |

### 8.1 必须记录的一次驱动 oops（由本轮只读操作触发，非 TPU 故障）

本轮在排查 `/proc/bmtpu/` 时 `cat /proc/bmtpu/bmdi_api_info`，触发了 **bmtpu 驱动的一次
内核 oops**。这是本报告唯一一处对设备的意外影响，必须如实记录：

```
[10941.872688] Unable to handle kernel paging request at virtual address 0000000000002014
[10941.872688] Internal error: Oops: 96000005 [#2] SMP
[10941.902047] CPU: 5 PID: 356912 Comm: cat Tainted: GF     D    O
[10941.924796] pc : otp_reg_read+0x10/0x30 [bmtpu]
[10942.024937]  api_proc_show+0x34/0x1a0 [bmtpu]
```

**技术性质：**

* 崩溃发生在驱动的 `api_proc_show()` → `otp_reg_read()`：该 proc 读路径用了一个
  无效的 OTP 基址（`0x2014`，空指针 + 偏移），不是 NPU 执行错误，与 `bm_thread_sync`
  和任何探针的计算路径无关。
* 触发者是 `cat`（`Comm: cat`），不是探针进程；两次 oops（uptime 7504 s 与 10941 s）
  都是 `cat` 同一个 proc 文件。第一次发生在自动化收集脚本里，第二次是我手工核对时。
* **影响范围：** 崩溃进程（那个 `cat`）被内核杀掉，`Tainted: D` 标记为已 oops。
  驱动与设备本身继续可用 —— 之后立刻用 `queue_model` 和 `token_shape` 复测，
  TPU 数字与 oops 前一致（23.8 ms chain / 34.35 ms token）。
  **未重启、未重载驱动、未影响服务。**
* `dmesg` 里 `bmdrv_thread_sync_api` / `bdc_reg_read` 仍然为空，说明
  **本次没有发生 MYS-2457 README 里那种「TPU 卡死」事故**，两者性质不同。

**处置：** 后续所有采集都不再触碰 `bmdi_api_info`（`bmdi_base_info` / `bmdi_lib_info`
同族，一并避开）；只用 `kernel_info` 与 `wakeup_control`。已在该 proc 文件上
标注为「读即崩，勿碰」。建议 13.24 服务器管理 agent 记录：**libsophon 0.4.15 的
`/proc/bmtpu/bmdi_api_info` 在 CV84X6 上读会 oops** —— 这是驱动缺陷，与本次任务无关但值得上报厂商。

### 8.2 设备内存分配的一次瞬时失败

连续跑多个会 `bmrt_load_bmodel` 的探针后，`token_shape` 曾报
`bm_alloc_gmem failed, size = 0x1af73000`（约 431 MB）。当时该进程已退出，
重新单独运行即恢复正常。判断为前一进程的 device mem 尚未完全回收导致的瞬时碎片，
**不是泄漏**（后续单独运行全部成功，`dmesg` 无相关报错）。因此本轮的采集方式是
**一个探针跑完再跑下一个**，不并发、不连续紧接。

### 8.3 采集期间另一任务占用了同一台样机（记录在案）

本轮采集完成后（约 13:27），兄弟任务 **MYS-2468（8-token decode 调度时间片 A/B）**
在本机启动了 `tools/decode_quantum_ab.py` + `app.engine.worker`，加载同一 35B 模型并
占用 `/dev/bm-tpu0`：

```
PID 403310  tools/decode_quantum_ab.py ... --sessions 1 2 3 --decode 64 --wait-tpu-s 7200
PID 403313  -m app.engine.worker --decode-quantum 1 ...  (holds /dev/bm-tpu0)
```

之后任何探针再 `bmrt_load_bmodel` 都会得到 `bm_alloc_gmem failed`（设备内存已被
那个 worker 占满），这是**预期行为，不是本轮探针的故障**。

**处置：本轮不再占用 NPU，也不去动那个 worker**（它属于另一个任务的运行，
按约定一个时刻只允许一个 NPU 使用者）。本报告的所有数字都取自 MYS-2468 启动之前
（12:14–13:26）的独立采集，见 `analysis/raw/board_2026-10-29.log`。
`decode_bench` 的真实引擎交叉验证也是在那之前跑的，单独存档在
`analysis/raw/decode_bench_crosscheck.txt`（因为事后无法再复跑）。

## 9. 复现

```sh
# 板端构建（link 板上 libsophon）
cd analysis
INC=/opt/sophon/libsophon-current/include
LIB=/opt/sophon/libsophon-current/lib
for p in queue_model queue_scope tpu_busy token_shape graph_tpu queue_occupancy; do
  g++ -O2 -I$INC -o $p $p.cpp -L$LIB -lbmrt -lbmlib
done
g++ -O2 -pthread -I$INC -o queue_threads queue_threads.cpp -L$LIB -lbmrt -lbmlib

M=/data/cv84x6_llm_server/models/qwen3.6-35b-a3b-128k/qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel

./queue_model     "$M" --reps 5                       # 队列填满点与逐次成本
./queue_scope     "$M" --threads 4                    # 单线程逐次成本 + 多线程扩展
./queue_threads   "$M" --threads 4 --launch 40        # 预算是否每线程
./queue_occupancy "$M" --nets 40 --iters 10           # 满载时的真实占用
./tpu_busy        "$M" --iters 5                      # TPU 忙碌占比（单图 × 40）
./token_shape     "$M" --stage 6 --iters 5            # 真实 40 图 + lm_head 每 token
./graph_tpu       "$M" --stage 6 --iters 3            # 图间派发间隙（合并图上界）
```

**板端安全约定（与 MYS-2457 一致，必须遵守）：**

* 每个图的**所有输入先清零**再第一次 launch。decode 图会用收到的 position id
  去索引 KV/state，模板内存里的垃圾会让索引越界；CV84X6 上图内的越界设备读驱动报不出来，
  直接把 TPU 卡死（`bmdrv_thread_sync_api` 超时 → `bdc_reg_read` oops → "reboot is needed"），
  且进程变成不可杀的 D 状态。本轮全部探针都遵守此约定，`dmesg` 干净。
* **同一时刻只能有一个 NPU 探针。**
* 每个探针外层都套 `timeout -s KILL`，最长的 `graph_tpu` 给 1800 s。

## 附：探针一览

| 文件 | 回答什么 |
|---|---|
| `queue_model.cpp` | 单图重复 N 次不同步：填满点、逐次成本、40 图 chain 的 TPU 下界 |
| `queue_scope.cpp` | 单线程逐次 submit 成本 + N 线程各自 40 图的墙上时间扩展 |
| `queue_threads.cpp` | 队列预算是每线程/每 HWQ 还是全设备共享（配合 per-HWQ push 计数） |
| `queue_occupancy.cpp` | 满载运行时驱动自己的 `free_slots`（观测占用，不靠推断） |
| `tpu_busy.cpp` | 单图 × 40 的墙上时间 vs `bm_get_profile` 的 TPU 忙碌时间 |
| `token_shape.cpp` | 真实 40 个不同图 + `lm_head` 的每 token 墙上时间与 TPU 忙碌占比 |
| `graph_tpu.cpp` | 逐图独立 TPU 时间 vs 串接 TPU 时间 → 图间派发间隙（合并图上界） |
