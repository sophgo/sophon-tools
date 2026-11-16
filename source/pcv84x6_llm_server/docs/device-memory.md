# 设备内存 = NPU + VPP，以及 TPU 使用率

**结论先行**：CV84X6 的 `ion_npu_mem` 与 `ion_vpp_mem` 都是 TPU 可直接读写的设备内存，
bmrt 自己的分配器**早就在两块之间回退**；把权重和激活放进 VPP 与放进 NPU **逐位相同**。
所以本次改动不是「让 bmrt 会用 VPP」，而是：**承认它已经会，并让统计、准入、监控都按
「设备内存」算**，同时把性能指标从「TPU 频率」换成驱动给出的 **TPU 使用率**。

所有数字都来自 `.157`（CV84X6，libsophon 0.4.15，2026-11-07），复现命令见各节。

---

## 1. heap id、大小，以及 mask 3 到底覆盖什么

`/dev/ion` 的 `ION_IOC_HEAP_QUERY` 与 bmlib 的 `bm_get_gmem_heap_stat_byte_by_id` 实测：

| ion heap id | 名字 | 类型 | 大小 |
|---|---|---|---|
| 0 | `npu` | carveout | 27917287424 B = **26624 MiB**（26 GiB） |
| 1 | `vpp` | carveout | 2147483648 B = **2048 MiB**（2 GiB） |
| 2 / 3 / 4 | `ion_system_heap` / `ion_system_contig_heap` / `linux,cma` | system | 不是设备内存 |

device tree 的 `reserved-memory` 与之吻合：`ion_npu_mem` 0x10_9580_0000 起 0x6_8000_0000，
`ion_vpp_mem` 0x17_7fe0_0000 起 0x8000_0000。**板子不同大小不同**（64 GB 版本更大），
所以代码里一律运行时读，不写死。

对 bmruntime 来说这两个堆按 **bmlib 自己的编号**排（`bmlib/src/bmlib_memory.cpp:496`
的 `bm_get_carveout_heap_id`）：`carveout_heap_id[0]` 是 `npu`，`[1]` 是 `vpp`。
于是：

| mask | 含义 | 实测落地 |
|---|---|---|
| 1 | 只 NPU | `heap 0`，地址 0x1095800000 起 |
| 2 | 只 VPP | `heap 1`，地址 0x177fe00000 起 |
| **3** | **NPU 优先，满了再 VPP** | 先用 heap 0；NPU 满后同一个 mask 落到 heap 1 |
| 7 | bmrt `m_neuron_heap_mask` 的默认值 | `(7>>2)&1 == 1`，被 `bm_alloc_gmem` 归一成 `3` |

**mask 3 是最容易误读的一个**。它不是「NPU 堆」：

```c
/* bmlib_memory.cpp:591 bm_alloc_gmem */
if ((chipid == BM_CHIP_ID_1688 || chipid == BM_CHIP_ID_84X6) && ((heap_id_mask >> 2) & 0x1))
    heap_id_mask = (heap_id_mask | 0x2) & 0x3;      /* 7 -> 3 */
...
for (i = 0; i < ctx->heap_cnt; i++)                 /* 按 i 递增尝试 */
    if ((heap_id_mask >> i) & 0x1) { alloc heap i; if (ok) break; }
```

`heap_cnt` 是 2，`i` 从 0 递增，所以 **mask 3 = 先 heap 0（NPU），失败再 heap 1（VPP）**。
`native/src/*.cpp` 里所有 `kNpuHeapMask = 3` 的注释都写着「NPU heap」——名字对，理解不全：
那些缓冲其实一直可以是 VPP，只是 NPU 通常够用，从来没落过去。

实测（`probe_alloc2.c`，一次一块、立刻释放）：

```
基线                           heap[0] 26624MiB avail 26624 / heap[1] 2048 avail 2048
mask=3  1024 MiB  -> heap 0
mask=3  4096 MiB  -> heap 0
mask=3  20480 MiB -> heap 0
mask=3  28672 MiB -> 失败          （两个堆合计 28672 也放不下这一块）
先用 mask=1 占满 26 GiB NPU：
mask=3  1024 MiB  -> heap 1        ← 回退发生在这里
mask=3  3072 MiB  -> 失败          （VPP 只有 2 GiB，单块放不下）
mask=3  256 MiB   -> heap 1
```

**一条容易踩的坑**：`bm_malloc_device_byte_heap_mask` 的 `size` 形参是 `unsigned int`，
传 ≥4 GiB 会**截断成 0 然后成功返回**。第一次探针就是这样得出「4 GiB 分配成功、地址不变」
的假结论。要用 `bm_malloc_device_byte_heap_mask_u64`（bmrt 内部也走 u64 那条）。

## 2. bmrt 默认把 coeff / neuron 放进哪些堆

`Bmruntime` 的 `must_alloc_device_mem()`（`bmruntime.cpp:2677`）对**所有**设备内存
（instruction、variable instruction、neuron、coeff、io）都用 `m_neuron_heap_mask`：

```c
m_neuron_heap_mask = 7;                      /* 默认 */
if (getenv("BMRUNTIME_NEURON_HEAP_MASK")) …  /* 唯一的覆盖入口 */
bm_malloc_device_byte_heap_mask(handle, mem, m_neuron_heap_mask, size);
```

7 被归一成 3，于是**默认就是「NPU 优先、满了用 VPP」**。这一点不需要改代码验证，
实测一次就够（`probe_spill.c`，先占 25 GiB NPU，再普通 `bmrt_load_bmodel`）：

```
prefilled  heap[0] avail 1024MiB used 25600MiB / heap[1] avail 2048MiB used 0MiB
loaded     heap[0] avail    0MiB used 26623MiB / heap[1] avail  482MiB used 1565MiB
networks=59
nets with io in VPP range: 51, in NPU range: 8
```

**结论：VPP 已经在被用**。一个 3162 MiB 的 embedding bmodel 在只剩 1 GiB NPU 时也能加载，
其中 1565 MiB 落进了 VPP。`beam` 里常见的「只用上了第一块 NPU 内存」的印象，
在 `bmrt_load_bmodel` 这条路径上是不成立的。

## 3. VPP 能不能被 TPU 读写权重与激活：能，且逐位相同

这是唯一需要真机证明「不改变结果」的地方。做法（`probe_exact.c`）：同一个 bmodel 跑两遍，
一遍空 NPU 让它全落 NPU；一遍先占掉 25.6 GiB 只留 1 GiB，逼 coeff/neuron/io 落进 VPP。
每个网络喂**同一份确定性输入**（LCG 生成），输出按原始字节算 FNV-1a 哈希再比。

`.157` 结果：

| 模型 | 网络数 | NPU 模式占用 | VPP 模式占用 | 逐位一致 |
|---|---|---|---|---|
| `ppocrv6-medium-det` | 1 | NPU 146 MiB / VPP 0 | NPU(含占用块) / **VPP 0**（全在 1 GiB 内） | ✅ |
| `bge-reranker-v2-m3` | 26 | NPU 1132 MiB / VPP 0 | **VPP 120 MiB** | ✅ |
| `qwen3-asr-0.6b` | 60 | NPU 1637 MiB / VPP 0 | **VPP 627 MiB** | ✅ |
| `qwen3-embedding-0.6b` | 59 | NPU 2589 MiB / VPP 0 | **VPP 1565 MiB** | ✅ |

四个模型共 **146 个网络的输出哈希两两相同**，`diff` 为空。也就是说
**VPP 里的 coeff（权重）和 neuron（激活）算出来的字节和 NPU 里的完全一样**，
不存在「VPP 是给多媒体用的、精度/带宽不同」这类隐藏差异。

复现：`gcc -O2 -o probe_exact probe_exact.c -I$LIB/include -L$LIB/lib -lbmrt -lbmlib`，
`./probe_exact <bmodel> npu` 与 `./probe_exact <bmodel> spill`，比较 `^net\[` 行。

## 4. 单次分配的连续性限制，以及 VPP 保留量

**限制**：一次 `bm_malloc_device_byte_heap_mask` 只能落在一个堆里。所以
「两块堆合计还有 3 GiB」**不等于**「能分配 3 GiB」——见 §1 的 `3072 MiB -> 失败`。
准入判断因此必须同时看**合计**和**单个堆的最大空闲块**，两件事分开报。

各处 bmodel 的分解（`bmrt_get_bmodel_info`，单位 MiB）：

| bmodel | instr | var | neuron | coeff | io | 合计 | **最大单块** |
|---|---|---|---|---|---|---|---|
| embedding 0.6b | 604 | 74 | 337 | 1248 | 897 | 3162 | 1248 (coeff) |
| asr 0.6b | 6 | 2 | 15 | 1507 | 112 | 1643 | 1507 (coeff) |
| reranker v2-m3 | 33 | 8 | 40 | 1083 | 0 | 1165 | 1083 (coeff) |
| ppocrv6 det | 35 | 0 | 79 | 30 | 0 | 146 | 79 (neuron) |
| PaddleOCR-VL | — | — | — | — | — | 2269 (文件) | — |
| **35B-A3B 128k** | 28 | 8 | **414** | **19670** | **17971** | 38093 | 19670 (coeff) |

35B 的 `io_mem`（17971 MiB）是 128k 上下文的 KV，按 `bmrt_get_bmodel_info` 的算法
是「所有 net 的 io 之和」——那是**上界**，实际 bmrt 只按当前 net 需要分配，
实测常驻 22.8 GiB 而不是 38 GiB。这里记下来是为了说明：**不能拿这些数当准入依据**，
chat 模型仍然不做事前准入（理由见 `app/core/models.py` 的 `_check_npu_admission`）。

**VPP 保留量**：bmrt 会一路吃到 VPP 的最后一个字节，之后 VPSS/视频/显示去申请就失败，
而那个失败离「导致它的那次模型加载」很远。所以服务启动时**持有一块 VPP**
（`app/core/vpp_reserve.py`），默认 **256 MiB**，环境变量 `CV84X6_VPP_RESERVE_MB` 可改（0 关闭）。

为什么必须是「持有一块」而不是「读出来减掉 256 MiB」：bmrt 不认识任何「保留」概念，
能减少别人可分配量的只有**已被别人占用的内存**。实测（`probe_xproc.sh`，两个进程）：

```
holder:  mask=2 256 MiB -> 成功
observer 看到的堆:  heap[1] total 2048 avail 1792 used 256     ← 设备级可见
observer: mask=2 1900 MiB -> 失败（rc=5）                       ← 被挡住了
observer: mask=2 1700 MiB -> 成功                               ← 但没挡太多
holder 退出后:      heap[1] avail 2048，1900 MiB -> 成功
```

**这个做法的固有前提**：它靠「先占」生效，所以必须在**任何 worker 起来之前**拿到
（`app/main.py` 的 `lifespan` 第一步，早于 `adopt()` 与 autostart）；反过来，
如果服务先被别的东西抢走了 VPP，`acquire()` 会失败并降级——服务照常跑，
`/api/stats` 的 `vpp_reserve.acquired=false` 加 `reason` 说明原因，不假装保留了。

## 5. TPU 使用率：驱动计数器确实会动

原代码注释写着「`npu_usage` 在负载下也是 0」，实测**是错的**。`.157` 上开
`npu_usage_enable=1`（驱动初始化时默认就置 1）后：

```
空闲：                            usage:0   avusage:2
35B 解码 222 token（11:09:47 起）：
  11:09:47 usage:59   11:09:48 usage:92   11:09:49 usage:94
  11:09:50 usage:94   11:09:51 usage:96   11:09:52 usage:90
  11:09:53 usage:96   11:09:54 usage:95   11:09:55 usage:50
  11:09:56 usage:0    …  一直到 11:10:23 都是 0
```

**空闲 0 → 解码中 90–96 → 最后一个 token 后约 1 秒回到 0**。所以不需要引擎侧
「launch 到 sync ÷ 墙钟」那套替代口径，直接用驱动值即可，来源写作 `sysfs`。

机制（`libsophon/driver/bm_attr.c:790` `bm_npu_utilization_stat`）：每
`npu_usage_interval`（默认 500 ms）采一次每核的 TPU-busy 标志，存进 50 格滑窗，
`usage` = 窗内 busy 比例 × 2；`avusage` 是从使能到现在的累计平均。
滑窗 50 × 500 ms ≈ **25 s**，所以它响应慢一点但不会漏掉短请求。

**不要读 `avusage`**：那 3 就是「今晚一共忙了这么久」的平均，拿它当当前值会显示 3%。
同理**不要用 bm-smi 的 `tpuc` 列**当频率——那是使用率，历史上正是它让面板显示过
「当前 0 MHz」（`parse_bm_smi` 的注释记着这件事）。

## 6. `OCR_VL_NPU_BYTES` 校正

原值 3.3 GiB 是「2.27 GB 文件 + KV + workspace」的估算。MYS-2663 在 `.157` 用
`monitor.bm_smi_sample()` 实测常驻 **2077 MB**，MYS-2673 复核一致。差 1.2 GiB，
足以让一个本来放得下的加载被 409 拒掉。现改为 `OCR_VL_DEVICE_BYTES = 2077 MiB`
（旧名 `OCR_VL_NPU_BYTES` 保留一个版本，值相同）。

## 7. 接口字段（`/api/stats` → `device`）

```jsonc
{
  "device_mem": {                       // 新增
    "total_bytes": 29989978112,         // NPU + VPP 之和
    "used_bytes": 0,
    "free_bytes": 29989978112,
    "max_block_bytes": 27917287424,     // 单块上限＝较大的那个堆的空闲，
                                        // 不是 free_bytes：分配不能跨堆
    "heaps": [
      {"name": "npu", "total_bytes": 27917287424, "used_bytes": 0, "free_bytes": 27917287424},
      {"name": "vpp", "total_bytes": 2147483648,  "used_bytes": 0, "free_bytes": 2147483648}
    ],
    "source": "bmlib"                   // bmlib | ion | mock | none
  },
  "tpu_usage": {                        // 新增，替代 tpu_freq
    "percent": 94.0,                    // 驱动 usage 列；空闲 0
    "cores": [100, 94, 94, 94],         // 每核
    "source": "sysfs"
  },
  "tpu_freq": {                         // 已废弃，恒为空
    "mhz": null, "source": "none", "unit": "MHz",
    "deprecated": true, "use": "tpu_usage"
  },
  "npu": {                              // 已废弃一个版本，老控制台仍在读
    "total_percent": 94.0, "cores": [...], "heap": {...}, "smi": {...},
    "deprecated": true, "use": "device_mem"
  },
  "clocks": {"cpu_hz": 1800000000}      // tpu_hz 已删除
}
```

另在 `/api/stats` 顶层新增 `vpp_reserve`：

```jsonc
{"requested_bytes": 268435456, "held_bytes": 268435456,
 "acquired": true, "reason": null, "env": "CV84X6_VPP_RESERVE_MB"}
```

它不属于 `device`，因为那是服务自己的动作、不是设备读数；但 `free_bytes` 里已经不含
这 256 MiB，所以对账时必须能看到。

**取法**：优先 `libbmlib` 的 `bm_get_gmem_heap_stat_byte_by_id(handle, &stat, id)`
（id 0=npu、1=vpp），它和 bmrt 分配时用的是同一份数据；不可用时退到 ion debugfs 的
`/sys/kernel/debug/ion/cvi_{npu,vpp}_heap_dump/{total_mem,alloc_mem}`（那个目录默认
0700 root-only，服务账号通常读不到）。两者都拿不到时 `heaps: []`、`source: "none"`，
**准入判断跳过**而不是判成 0 内存——否则每次开发机测试都会被拒。

`bmlib` 路径要 `bm_dev_request` 一个句柄，用完 `bm_dev_free`；句柄本身不分配内存，
每 2 秒一次不会泄漏（实测反复取堆统计，`avail` 不变）。

## 8. mock 后端

控制台是按 `--backend mock` 开发的，所以 mock 必须给同样的字段：
`MOCK_HEAPS` 照抄板子形状（26624 MiB + 2048 MiB），装载量按 bmodel 文件大小累加、
先填 NPU 再溢到 VPP；`tpu_usage` 是有模型加载时 20–95% 的三角波、空闲为 0。
两者 `source` 都是 `mock`，明摆着是假数据。准入判断在 mock 上同样生效
（`test_device_memory_api.py` 用满了的假堆验 409），否则「设备内存不足」这条路
在板子之外根本测不到。

## 9. 没有改、也不打算改的

- **引擎侧分配策略**：`native/src/*.cpp` 的 `kNpuHeapMask = 3` 保持原样。它已经是
  「NPU 优先、VPP 兜底」，与 bmrt 内部一致；改成 `bmrt_load_bmodel_with_mem` 手工按块
  择优需要自己管 instruction/var/neuron/coeff/io 五块的生命周期，收益为零而风险是把
  逐位一致这件事重测一遍。**没有动机就不动。**
- **`bmrt_load_bmodel_with_mem` 在本板不可用**：`.157` 的 libbmrt 0.4.15 会要求一个
  `mem_info_t` 里没有具名字段的 `cdma_cmd_mem` 区域（`reserved[0..3]` 逐个试过都不是它），
  直接 `FATAL: device memory: cdma_cmd_mem don't alloc`。要用得先改 libsophon。
  这一点也让「手工分配」那条路在本板直接不通。
- **KV 池 / 前缀缓存**：`kv_pool.py` 的预算仍按 bm-smi 的 NPU 堆算。它回答的是
  「还能塞多少 KV」，与「模型放不放得下」是两个问题，本次不动（记为后续）。

## 10. 上板安全记录（本轮实际踩到）

- **不能在 NPU 执行中途强杀进程**。本轮一次 `pkill` 打断 35B 加载，`bmdrv_thread_sync_api`
  等 120 s 超时后 `bdc_reg_read` 触发 `synchronous external abort`，内核
  `Fixing recursive fault but reboot is needed` —— 板子必须重启。这是已知故障模式，
  恢复方式是 `systemctl reboot --force --force`（重启后 `npu_usage` 归 0、服务正常）。
  巡检脚本一律硬超时 + 串行，且**先看 `npu_usage` 再决定是否动手**。
- 长时间占大块 NPU 的探针（例如「占 25 GiB 再加载」）要留出足够的 VPP 余量：
  一次 `probe_exact` 的 spill 模式在留 64 MiB NPU 时直接加载失败（VPP 装不下 3162 MiB），
  留 1024 MiB 才跑通。
