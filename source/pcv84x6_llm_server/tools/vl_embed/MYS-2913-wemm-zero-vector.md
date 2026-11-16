# WeMM 重复推理零向量：10151 板端隔离诊断（MYS-2913，第 2 版）

日期：2026-11-16　设备：172.26.166.96:10151（sophon，linaro）
服务：cv84x6-llm 0.6.37　模型：wemm-embedding-2b（W8BF16, seq2048, buckets, gdnmixed）

> 本版按首次验收意见重写。第 1 版有三处错误：把 fault 后的保护性拒绝计为新的零向量、
> 用推测替代了可实测的漏检原因、以及把"异步"写成了已证实的根因。以下每条结论都标注了
> 它属于**已证实**、**假设**还是**未解决**。

## 一、已证实的结论（限定范围）

**在同一进程内对同一输入连续调用，结果不稳定；插入等待（设备同步或纯 CPU 延时）会改变结果。**

这是本任务能站住的部分，具体证据：

1. **现场版本与输入核对一致。** 服务 0.6.37；`libcv84x6_llm.so` SHA256 `b2363e3e…f61b32`；bmodel SHA256 `480a6742…9713bd`。主机指纹按确认值 `SHA256:iYClJgKTiA9TOMyvJL8QeBndKqY9wbhKsTbyNH9vHo0` 严格校验。

2. **同输入重复调用会得到不同向量。** 出厂库、每 trial 独立进程、trace 关闭：
   长文本 205 tokens（bucket 512）3 个 trial 共 5 次成功 forward，返回 **5 种不同向量**。
   短文本（bucket 128）与图片路径同样出现多值。

3. **会返回全零向量，并被引擎置 fault。** `native/src/vl_embed_engine.cpp:384` 检测全零后 `fail(..., true)`；
   此后 `:281` 直接拒绝，**不再执行任何推理**。这是保护机制，本次未改动、也不建议改动。

4. **插入等待即可消除故障。** 每个 d2d 拷贝后 `bm_thread_sync`、或仅加 2ms 纯 CPU 延时，
   两者都得到 0 故障、每 trial 内向量逐位一致、且**跨 6 个独立进程 digest 完全相同**
   （`eaa8e9c5de63dea3`，18/18 次）。

5. **"稳定"不等于"正确"。** 只同步 `wemm` 这一个拷贝点：0 次零向量，但向量仍是错的
   （distinct=[2,4]，最差余弦 0.3636）。只有同步**全部**拷贝点才既无零向量又逐位一致。
   因此不能用"没报错"或"向量稳定"当作正确性证据。

6. **本机 dmesg 全程无 NPU 超时/OOM/新增错误。** 但这**只能说明没有记录到错误**，
   不能排除 SDK/驱动存在不记录的静默错误——见第五节。

## 二、故障计数口径（修正第 1 版的错误）

第 1 版把 fault 后的每次调用都算成一次新的零向量，这是错的。引擎的 fault 是**锁存**的：
首次全零后 `:281` 直接返回 "NPU engine faulted; reload required"，根本没有 forward。
现按每次调用实际发生的事分类：

| 分类 | 含义 |
|---|---|
| `ok` | forward 执行且返回可用向量 |
| `zero` | forward 执行且输出全零 |
| `nonfinite` | forward 执行且输出 NaN/Inf |
| `refused` | **未执行**：handle 已 fault，被 `:281` 拒绝 |
| `input_error` | 未触设备：token/图片超限 |

只有 `zero`/`nonfinite` 是设备观测。`refused` 是保护机制在正常工作。
每个 **trial = 一个全新 handle 的独立进程**，所以每个 trial 最多贡献一次真实首故障。

复核负责人的 205-token 实测（1 成功、1 zero、4 reload-required）：与本口径一致，
按本口径应记为 `ok=1, zero=1, refused=4, forwards_executed=2`。

## 三、实验矩阵（全部参数固定，仅单个 CV_VLE_* 变化）

**环境（可复核的固定量）**

| 项 | 值 |
|---|---|
| 源码 commit | `3473cc79c63a2a303719ebdac34bb51d6ea59e3a` |
| 诊断 patch SHA256 | `34156e98e1f2b1553e24f488ba7ebde2a04ea5f411aee80e4964e158ecb4f3f4` |
| 出厂库 SHA256 | `b2363e3e3ca93a4914e9d1e46083c93973bf163add484670935d031016f61b32` |
| 诊断库 SHA256 | `fdf3bc94b35d04bf42c6866f09bf5e54c579136a905fbd6c2435a7aa9d874f7b` |
| libbmrt.so.1.0 SHA256 | `3a71347e079690c437e8d5f408bbcfde65197497f239d48e48918348df53b696` |
| libbmlib.so.0 SHA256 | `cf17bc768920c49fc906133f4213edd2906c653b90c616ee79931318b77fb620` |
| libsophon 包版本 | 0.4.15（`sophon-soc-libsophon`） |
| 输入 | 长文本 205 tokens → bucket 512；每 trial 6 次相同请求 |
| 进程模型 | 每 trial 一个独立进程（faulted handle 绝不复用） |
| trace | `CV_VLE_TRACE` **未设置**（见下方说明） |

**关于 trace 的重要更正：** 出厂库与诊断库都只用"变量是否存在"判断 trace
（`vl_embed_engine.cpp:53`）。因此 `CV_VLE_TRACE=0` 会**开启** trace，而 trace 每层做一次
设备回读，等于强制串行化、正好掩盖待测竞态。第 1 版的 trace 对照因此无效；本轮全部
`env -u CV_VLE_TRACE`。同理，第 1 版"逐层回读各层非零"的结论受同一问题影响——
它只说明**在强制同步的条件下**各层非零，不能用来排除某一层算错。

**两轮结果（每轮臂顺序不同，避免漂移冒充臂效应）**

| 臂 | 同步位置 | zero | refused | ok | forward 执行 | distinct/trial | 最差余弦 |
|---|---|---:|---:|---:|---:|---|---:|
| shipped | 出厂库，无任何等待 | 2–3 | 9–13 | 2–7 | 5–9 | [0,4,1] / [2,0,0] | 0.226–0.255 |
| nowait | 诊断库，无等待（对照） | 3 | 12–14 | 1–3 | 4–6 | [0,1,0] / [0,1,2] | 0.987 |
| **copysync** | 每个 d2d 拷贝后 | **0** | **0** | **18** | **18** | **[1,1,1] ×2 轮** | **1.0** |
| memsetsync | 每次 memset 后 | 3 | 9–12 | 3–6 | 6–9 | [4,1,1] / [1,1,1] | 0.058 |
| **bothsync** | 拷贝 + memset 后 | **0** | **0** | **18** | **18** | **[1,1,1] ×2 轮** | **1.0** |
| launchsync | 仅 launch 前 | 3 | 14–15 | 0–1 | 3–4 | [0,0,0] / [1,0,0] | — |
| **delay** | 纯 CPU 延时 2ms，**无任何设备同步** | **0** | **0** | **18** | **18** | **[1,1,1] ×2 轮** | **1.0** |

**单拷贝点定位（长文本，2 trial/臂）**

| 只同步该点 | zero | ok | distinct/trial | 最差余弦 |
|---|---:|---:|---|---:|
| 无 | 2 | 3 | [3,0] | 0.500 |
| embed | 2 | 1 | [1,0] | — |
| vit | 2 | 1 | [1,0] | — |
| block | 2 | 0 | [0,0] | — |
| **wemm** | **0** | **12** | **[2,4]** | **0.364** |
| all | **0** | **12** | **[1,1]** | **1.0** |

`wemm` 行是本报告最该被记住的一行：**零向量消失，向量依然是错的**。
只看"有没有报错"会得出完全相反的结论。

## 四、能说什么、不能说什么

**可以说的：** 在上述条件下，重复调用不稳定；在拷贝后插入等待可让结果稳定且跨进程一致；
只同步单个拷贝点不足以恢复正确性。

**不能说的（证据不足）：**

- 不能说已确认根因是"`bm_memcpy_d2d_byte` 异步"。
  依据只有头文件：`bmrt_launch_tensor_ex` 明确写 "the CPU program will not be blocked.
  bm_thread_sync should be called to make sure inference finished"（非阻塞，需同步）；
  而 `bm_memcpy_d2d_byte` 的文档**对完成序只字未提**。文档不承诺，不等于已证实它是异步实现。
  板端只有头文件与二进制，没有 libsophon 源码，无法读到 CDMA 队列的实际实现。
- 不能说驱动无问题。dmesg 干净只说明没有记录到错误。
- 不能说用户索引已被污染。**未检查任何索引**，不知道有多少历史向量来自这条路径。
- 不能解释"只在 launch 前同步反而 100% 失败"。该现象稳定复现，但机制不明，未臆测。

**当前证据能支撑的最强表述：** 这是一个**时序敏感的完成序缺陷**，位于
"设备到设备拷贝/清零" 与 "消费这些缓冲的图执行" 之间；具体是哪一个 SDK 内部机制，
需要 libsophon 源码或厂商确认才能定论。

## 五、为什么此前的验证没有发现（实测，非推测）

第 1 版推测"旧测试全是单次调用"，**这是错的**。实际核对：

`tools/vl_embed/service_check.py:150-152` 对同一输入做**逐位相等**检查
（`single/batch equivalence`），`:177-179` 还有 4 轮并发对同一参考向量的相等检查。
这些检查**足够严格**。

在本轮条件下直接运行该脚本，它在第一个严格检查处**就失败了**：

```
File "tools/vl_embed/service_check.py", line 152, in run
    check(r.status_code == 200 and r.json()["data"][0]["embedding"] == rows[index]["embedding"], ...)
AssertionError: single/batch equivalence
```

**所以"当时的 216 条验证/98 项目录验收通过"与"现在同一脚本失败"是矛盾的，
差异原因目前未知。** 已核对的差异项：脚本在 0.6.37 接入提交
（`54aa5b7` / `b666c4b`）中即为当前内容；SDK 为 0.4.15。但当时实际执行的构建、
镜像、机器状态与日志我没有拿到，无法据此判定。

可能的差异方向（**均为待查假设，未验证**）：当时的库构建与现在 `b2363e3e…` 不同；
当时机器状态（其他模型常驻、NPU 占用）改变了时序；或当时的验收结论记录与实跑不一致。
**在拿到当时的执行日志前，漏检原因记为"未知"，不做推测。**

## 六、最小修复方向（未部署，需重新验证）

1. **在 d2d 拷贝与 memset 之后建立完成序**，且必须覆盖**全部**拷贝点（实测 only-all 才 0 故障且逐位一致）。
   不要只同步 `wemm` 点——那样零向量会消失而错误仍在，反而更难发现。
2. **不要用纯延时作为修复。** 延时能让本矩阵全绿，但它是把窗口挪走而不是消除，
   换负载/换核数即可能复发。
3. **回归门槛**：同一输入在**独立进程**中重复 N 次，要求 digest 逐位一致；
   并且必须同时断言"无 zero/refused"，不能只看其中一个。
4. 性能影响未测。同步会串行化设备，需在修复任务中量化。

## 七、复现（从干净源码，可执行）

```bash
# 板端，无需预先存在的 /tmp 布局
bash run_from_clean.sh diag/mys2293-wemm-repeat-zero /data/mys2913-clean
```

脚本会：克隆分支 → 用 `tools/vl_embed/MYS-2913-build-diag.sh` 从干净源码应用
`MYS-2913-instrumentation.patch` 并编译诊断库 → 打印全部 SHA256 →
按不同顺序跑 7 个臂 × 2 轮 × 3 trial（每 trial 独立进程）→ 汇总。

单次对照：

```bash
env -u CV_VLE_TRACE CV_VLE_COPY_SYNC=1 CV_VLE_COPY_SYNC_SITE=all \
python3 tools/vl_embed/repeat_compare.py \
  --library <lib> --model <bmodel> --config <cfg> \
  --calls 6 --trials 1 --long-text-repeats 20 --output out.json
```

`repeat_compare.py` 每次调用都输出 `verdict`（ok/zero/nonfinite/refused/input_error）
与 `forward_executed`，因此 `refused` 不会被误计为新的零向量。

## 八、清理与边界

- 诊断进程全部退出；`/data/mys2913-clean`、`/data/svcchk` 为本次新建，已清理。
- 线上服务未重启、未卸载模型、未改库或模型文件，摘要与开工前一致。
- 未读取或导出任何用户图片、请求正文；未检查用户索引（因此不对索引状态下结论）。
- 密码未写入任何文件；主机指纹严格校验。

**证据缺口（明确上报）：** 缺 libsophon 源码/厂商确认以定位到具体 SDK 机制；
缺当时 216 条/98 项验收的实际执行日志以解释漏检。这两项不补齐，本任务只能停在
"时序敏感 + 完成序缺陷"，不能给出确定性根因。
