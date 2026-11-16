# D7 修复实验：第 1 步——认出卡住的那条命令

> 本文件是 MYS-2703 第 1 步的原始记录与结论，供回贴和写进
> `docs/research/d7-tpu-hang.md` 用。数据来自 10155，v0.6.29 正式包 +
> 只在板上编译的插桩原生库（未替换 13.24 的发布产物）。

## 结论

**卡住的是 35B 的 `lm_head`，一个 `core_num=4` 的图；不是单核命令。**

MYS-2693 的报告把 `kernel_fifo` 里最后那条 `block=0 send_core_num=0` 读成
「单核命令」，并据此推测是 `lm_head`/`greedy` 这类单核小网络。这次实测推翻了这个读法：

| 记录 | 卡死时最后一条 | 真实含义 |
|---|---|---|
| 引擎命令 trace（新） | `lm_head core=4`，之后无返回 | `lm_head` 是 **4 核**图 |
| `kernel_fifo` | `block=0 send_core_num=0` | **不是**单核命令；是同一个 4 核 `lm_head` 的另一种编码 |
| dmesg | `last=73811 cpl=73810` | `seq 73811` 就是这条 `lm_head` |

所以任务卡里「那条单核命令」这个前提本身不成立——**没有单核命令卡住**。
卡住的是 4 核的 `lm_head`。

## 三条独立证据

### 1. 命令 trace：最后一条是 `lm_head`，此前每条都回来了

在 `native/src/llm_engine.cpp` 的 `run()` / `sync_launches()` / `d2d()` /
`zero()` 里加了 `LLM_CMD_TRACE`：**在实际调用之前**写一行 `see`，返回后写
`done`。这样卡死时最后一行 `see` 就是没回来的那条命令。

`T2`（6 模型 + `chat:2`，140 s 卡死）里 35B worker（pid 2630）的尾部：

```
227.417131 ... L134528 see launch block_cache_39 core=4 in=5 out=3 wait=0
227.417640 ... L134529 done launch block_cache_39 rc=1
227.417654 ... 147420 see sync
227.422057 ... 147421 done sync rc=0          <- 40 层全部回来，同步也回来了
227.422075 ... 147422 L134530 see launch lm_head core=4 in=1 out=1 wait=1
                                              <- 之后再无任何一行
```

- 40 个 `block_cache_*` 每条都有配对的 `done ... rc=1`（`bmrt_launch_tensor_ex`
  返回 true，即 1）；
- `sync` 有 `done rc=0`；
- `lm_head` 只有 `see`，**没有 `done`**。

同一次运行里 35B 共 67266 次 launch、67265 次 done，缺的那一次就是 `lm_head`。

### 2. `lm_head` 是 4 核图（bmodel 自己说的）

板上 `tools/e2e/coreprobe.cpp` 读 `bmrt_get_network_info(...)->core_num`：

```
net                      core_num stages    in   out
embedding                       4      1     1     1
lm_head                         4      1     1     1
embedding_cache                 1      1     1     1
block_cache_0..39               4   (多数 1，少数 7 个 stage)
```

`core_num` 就是 `bmrt` 建 `core_list` 用的那个数（`bmruntime.cpp:1169`
`auto core_num = stage->core_num; std::vector<int32_t> core_list(core_num)`）。

对照引擎自己的启动横幅：

```
[engine] layers=40 ... lm_topk=1 greedy=0 ...
```

`lm_topk=1` 表示 argmax 已经融进 `lm_head`，**这个 bmodel 里没有 `greedy_head`
网络**——`sample_lm()` 走的是 `if (lm_topk || !net_greedy)` 那条分支，只发
`lm_head`，然后直接 `bm_memcpy_d2s_partial` 取 token。所以任务卡里
「也可能是 `greedy`」在 R11 这条路径上不成立：它根本不会被 launch。

### 3. `block=0` 不是单核，它每一轮 decode 都出现——是 `lm_head` 的位置

这一条最容易误读，所以单独摆事实。

`kernel_fifo` 打印的 `block` / `send_core_num` 是 **outbox packet 的位域**
（`84x6_tsh.h:172` 的 `tsh_outbox_packet_fields`），不是 `core_num`。解包：

| 包 | block | send_core | 出现在 |
|---|---|---|---|
| `0x0060198000000022` | 3 | 3 | 每个 `block_cache_*`（4 核批次） |
| `0x0000018000000002` | 0 | 0 | 每个 decode 轮的 `lm_head` |

**`block=0` 不是卡死特有的**：在**完全健康**的板上（T4 及一次单独 12 并发请求）
`/proc/bmtpu/kernel_fifo` 的分布是 `block=3` 61 条、`block=0` 3 条——`block=0`
每一轮 decode 都会出现，位置正是 `lm_head`。

**周期性对齐**（最硬的一条）：数 trace 里 35B 的 launch 序列，`lm_head` 每
**41** 次 launch 出现一次（40 层 + 1 次 `lm_head`）；`kernel_fifo` 里
`block=0` 按 **41 个 `block=3` + 1 个 `block=0`** 循环，同样每 41 次一次。
一个只发 3 个 token 的请求，trace 的 launch 序列是

```
embedding, lm_head, embedding_cache, lm_head, embedding_cache, lm_head
```

（`block_cache_*` 之外的都在这里），fifo 对应位置就是那 3 条 `block=0`。

**所以 `block=0` 是 `lm_head` 这个 4 核图在 outbox 里的编码**，不是「单核命令」。
MYS-2693 把它读成单核，是因为当时没有 trace 能给出网络名——这次补上了。

> 仍有一点没能从源码定死：`static_subnet` 把 `block_num = core_list.size()`
> 传下去（`BM1684X2.cpp:179`），若 `lm_head` 走这条路径，`block=0` 就该意味着
> 4 个核一个都没选中，与它能正常出 token 矛盾。合理解释是 `lm_head` 走的是
> dynamic 子网路径（`block_num` 来自 `net_info.core_ids`），或驱动/固件对
> 动态图另有编码。无论走哪条，**网络名和 4 核这个事实**由 bmodel
> （`core_num=4`）和 trace 双重给出，不受这个未定项影响。

## 三次复现

| 组 | 配置 | 结果 | 缺 `done` 的命令 |
|---|---|---|---|
| T1 | 6 模型 + `chat:2` | 125 s 卡死，0 个请求完成 | （首次插桩，见偏差） |
| T2 | 同上 | 140 s 卡死，0 个请求完成 | `lm_head core=4` |
| T3 | 同上 + LD_PRELOAD 垫片 | **加载即失败**，未进入负载 | —— |

T3 的失败是插桩本身的问题，不是设备问题：`LD_PRELOAD` 一个 hook
`bm_send_api_to_multi_core` 的 `.so` 之后，6 模型加载阶段的 `sync` 直接超时
（`Total 3 errors` + `NPU fault: sync timed out`），设备侧 `recvmsg_cnt` 始终为
0、`using_flag: 0`、`cur_api_id: 0x0`——设备根本没被用起来。该垫片已弃用，
`d7shim.c` 保留在仓库里但**没有参与**下面的结论；第 1 步靠的是引擎内插桩
（不经过 LD_PRELOAD，不改变调用序列）。

T4 是干净对照：`chat:1` 跑 156 s、67 次请求全 200，35B worker 的
`lm_head` 每次都有配对的 `done`，说明插桩不影响正常路径。

## 与任务卡的偏差

1. 任务卡的前提「卡住的是一条单核命令」**不成立**。实测卡住的是 4 核的
   `lm_head`。`kernel_fifo` 的 `block=0 send_core_num=0` 是位域编码，不是核数。
2. 任务卡建议的「LD_PRELOAD 垫片」这条路在本板上**会破坏加载**（见 T3），
   所以第 1 步改用引擎内插桩。垫片代码留在 `tools/e2e/d7shim.c` 但未用于结论。
3. 任务卡说「现有 `LLM_TRACE` 在 launch 之后才打印，不能用」——**这一点是对的**，
   新加的 `LLM_CMD_TRACE` 就是为了解决它（先写后调）。

## 复现命令

```bash
# 板上，插桩库已编译：
#   cmake -B build && cmake --build build -j8
#   md5 f8a8214c5a23d37addfd5c32f7eed7f3（第一版）→ 4ef3a65c4c4f4b2f8a65d924760217e0（修序数后）
# 让服务用它（drop-in，不替换安装包）：
cat > /etc/systemd/system/cv84x6-llm.service.d/zz-trace.conf <<'CONF'
[Service]
Environment=CV84X6_LLM_LIB=/data/mys2703/native/build/libcv84x6_llm.so
Environment=LLM_CMD_TRACE=/data/mys2703/trace/cmd.log
CONF
systemctl daemon-reload && systemctl restart cv84x6-llm

# 复现（约 125 s）：
setsid nohup /data/mys2693/d7rt/go.sh T2 20 chat,embed,rerank,asr,ocr,vl chat:2 \
  </dev/null >/data/mys2693/runs/T2.log 2>&1 &

# 卡死后看最后一条没有 done 的命令：
awk '$6=="see" && $7=="launch"' /data/mys2703/trace/cmd.log | tail -5
# 与 fifo / dmesg 对齐：
python3 tools/e2e/d7_cmdtrace.py --trace cmd.log --pid <35B pid> \
  --fifo kernel_fifo.txt --dmesg dmesg.txt
```
