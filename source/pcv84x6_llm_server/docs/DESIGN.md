# CV84X6 离线 LLM 推理服务 — 设计

> 目标平台：CV84X6（8×Cortex-A55，NPU 23.75 GiB heap，SDK 2.3 / libsophon 0.4.15）。
> 目标：板上一条命令安装，Web 管理页点按钮上线模型，对外提供 OpenAI 兼容 API，全程离线。

本文是**当前**架构与关键不变量。历史方案与逐版本补丁史不在这里；实测专题见
[`research/`](research/README.md)，会话状态契约见 [`session-state-contract.md`](session-state-contract.md)。

## 1. 总体结构

```
浏览器 ─┐                    ┌─────────────────────────────────────┐
        ├──────────────────► │ FastAPI (uvicorn, 单进程 asyncio)   │
客户端 ─┤                    │  /api/*   管理面（cookie/token）     │
Agent  ─┘                    │  /v1/*    OpenAI 兼容面（sk- key）   │
                             │  /agents/* agent 同源反向代理        │
                             │  静态资源（前端 dist）               │
                             └───────────────┬─────────────────────┘
                                             │ JSON-lines, 127.0.0.1:port
                          ┌──────────────────┼──────────────────┐
                          ▼                  ▼                  ▼
                    worker: m1          worker: m2          worker: m3
                    NativeLLM           NativeLLM           NativeLLM    每模型一进程
                    scheduler           scheduler           scheduler    独占 NPU 内存
                    prefixcache         prefixcache         prefixcache
```

**为什么每模型一进程**：35B 权重直接映射进 NPU heap，「卸载模型」只有让进程退出才能被内核真正回收，
否则 Python 侧泄漏会变成假性占用；两个 35B 也无法在同一进程的 heap 里共存。主进程只做路由与统计，
崩了不影响正在推理的 worker。

## 2. 引擎：纯 bmrt C++，数据流对齐官方 demo

`native/src/llm_engine.cpp` 不依赖 sail，逐步对齐 sophon-demo `sample/Qwen3_5/python/qwen3_5.py`
（CV84X6 上官方验证过的实现）；C API 用法对照 LLM-TPU `models/Qwen3_5/cpp_demo/chat.cpp`。
两者不一致时以 Python demo 为准。

| 阶段 | 做法 |
|---|---|
| embedding | token 补零到 `max_input_length`，跑 `embedding`，输出即 prompt 矩阵 |
| vit | 每张图跑 `vit`，输出按行拷进 prompt 矩阵的 `vision_start+1` 处 |
| prefill | `block_<i>` 用自有缓冲；FA 层写 `[3,L]` M-RoPE 位置；线性层 `rec_state` 输入清零、原地更新；KV/状态拷入 decode 图的内部输入内存 |
| decode | `block_cache_<i>` 用图的内部内存；FA 新 KV 直接写到 `cur_pos` 槽位的视图；线性层 conv_state 从输出拷回、rec_state 原地更新 |
| 位置 | 文本 0..n-1；图片按 `get_rope_index` 的三维网格；decode 从 `max(pos)+1` 递增 |

分词与图像预处理也在引擎库里（`native/src/tokenizer.cpp`、`native/src/vision.cpp`），所以板上运行时
不需要任何第三方 Python 包。两者按「与 Python 参考实现逐字节/逐 bit 相同」验收：分词对
`tests/tokenizer_golden.json`（73 条）+ 644 条随机语料；图像对 `tests/vision_golden.json`，
`pixel_values` 逐元素 bit 相同。图像预处理是纯主机侧算术（解码、`smart_resize`、双三次缩放、归一化、
patchify），不碰 NPU，所以在工作站上就能比对。两处行为**按参考实现保留、不做"修正"**：RGBA/LA 的
alpha 是丢弃而非与黑底合成；极端长宽比下 `smart_resize` 返回 0（由 `preprocess_image` 提前报错）。

## 3. 关键不变量

### 3.1 形状与采样都由 bmodel 决定

`config.json` 会骗人：35B 那份写 `hidden_size: 1024` / 24 层，bmodel 实际是 2048 / 40 层。所有
buffer、mask、KV stride 一律从 `net.get_input_shape()` 取；`config.json` 只用于 tokenizer 和默认值。
不一致时打 warning 并继续用 bmodel 的值，缺 `config.json` 也能加载。

`lm_head` 输出 `[1,1]` int32，argmax 已融合进图，所以 `temperature` / `top_p` / `top_k` 不生效，
同一输入永远得到同一输出。请求里的采样参数被接受但不改变结果。

### 3.2 会话状态是四个数加设备缓冲

`history / pos_next / last_id / pending` 加设备缓冲才是完整状态。`last_id` 是下一次 `decode()` 要
embedding 的 token，**不在 KV 里**，所以快照必须带着它和 `pending` 一起走。`restore()` 是「变成这个
前缀」，不是「合并进当前状态」。`prefill` 在提交任何图之前拒绝越界 token id（调用方错误，不置
`fault`）；vocab 大小由 worker 通过 `llm_engine_set_vocab_size` 下发，因为图里没有这个形状。
`load()` 逐层校验 stage-0 IO 不超过共享 prefill 缓冲。逐条契约见
[`session-state-contract.md`](session-state-contract.md)。

### 3.3 动态预填充只跑 64 的倍数行

不足 64 行的整块、以及 64 的倍数之外的尾部行，全部走 decode 图回放。依据：2 行、5 行这类短动态宽度
会让 TPU 卡死（驱动 120 s 超时后 `bdc_reg_read` oops，只能重启），厂商官方 demo 上同样复现。图像行
不能走按 token id 重新 embed 的路径，尾部回放从 prompt 矩阵里取行，所以图片行不丢。

### 3.4 预填充 MoE 有数值误差，用精确尾部缓解

多 token 预填充图里的路由专家 MoE 在 CV84X6 上有数值误差（第 0 层与 HF 余弦 0.75，单 token 解码图
0.9999），厂商官方 bmodel 同样存在，**不是我们编译的问题**，误差逐层累积。因为线性注意力状态会衰减，
用 decode 图重算 prompt 末尾就能修正生成起点的大部分状态：

- ≥ 2048 token 的 prompt 精确计算最后 `prefill_exact_tail`（默认 64）个 token；更短的 prompt 精确
  计算最后 min(设置值, 16) 个。
- 低余数（`n % 64 < 16`）的短 prompt 原本几乎全走有误差的预填充图，实测 40 条中 5 条只写思考不作答；
  补 16 行精确后 39/40，且 `n % 64 ≥ 16` 的 prompt 输出逐 token 不变。代价只落在 `n % 64 < 16` 的
  prompt 上，多回放约 64 行。
- 放宽到 16 对齐的方案实测会让正确率下降、并在某些组合下卡死 TPU，已否决。

证据与复现：[`tools/precision/README.md`](../tools/precision/README.md)、
[`research/prefill-ab-eval.md`](research/prefill-ab-eval.md)、
[`research/prefill-exact-tail-eval.md`](research/prefill-exact-tail-eval.md)。

### 3.5 不要在 NPU 进程执行中途强杀它

`pkill` / `kill -9` 一个正在映射权重或跑图的 worker 会卡死 TPU，只能重启设备。停服务一律 SIGTERM
并等它自己退出；`prerm`、卸载、迁移数据目录都遵守这条。

### 3.6 会话初始化只清需要清的状态

十个 FA 层的 `state_a/b` 是**整段 131072 槽 KV 缓冲**（每层每侧 128 MiB），而线性层的 conv/rec 状态
只有几十 KB。两者在「谁需要清」上完全不同，`activate()` 因此按用途分三种模式（MYS-2477）：

| 时机 | 线性状态 | FA K/V | 依据 |
|---|---|---|---|
| fresh prefill（新会话或替换会话） | 清零 | **不清** | `history` 归 0，本会话不拥有任何 FA 槽 |
| `restore()` | 清零 | **清零** | 只铺 `[0, len)`，之后在 `len` 处 decode，`len` 之后的槽可达 |
| extend / decode / snapshot | 保持（必要时 unpark） | 保持 | 状态是活的 |

fresh prefill 不清 FA 之所以安全，是因为这三个读这些缓冲的地方都不会读到未写入的槽：预填充图通过
自己的输出写 `[0, L)`；decode 只写 `cur_pos` 这一槽；decode mask 对 `[cur_pos, win)` 全部填
`mask_value`（bf16 `0xC61C`），残留槽的贡献是 `q·k + mask_value`，被 softmax 丢掉，**不会是 NaN**。
「残留槽有限」由 `load()` 一次性清零保证，之后所有写入都是图输出。原来每个新会话要对 2.50 GiB 做
memset（实测 44 ms，64 行 prompt 首字的 6.2%；见
[`research/fresh-prefill-fa-state.md`](research/fresh-prefill-fa-state.md)）。

三个必须守住的前提，任何一条被破坏都会静默出错：

1. fresh prefill 之后 `history == 0`——`activate()` 自己建立，不留给调用方，失败路径也成立；
2. `restore()` 的清零不能去掉——它铺的是前缀，`len` 之后仍会被 decode 读；
3. `load()` 的清零不能去掉——那是「残留槽有限」的唯一来源，也是常规 demo 防 NaN 的那一步。

`tests/native/` 用 memset 观测把三条都钉住：fresh prefill 的 memset 只落在线性状态上、restore 仍清
FA、`load()` 每个 FA 缓冲各清一次；另有一条覆盖 park/unpark 的常驻切换，确认跳过清零没有动到
「两个会话各归各的 KV」。

## 4. 多会话与调度

**单流 decode 在 token 内完全串行，所以并发只能在 worker 内部多会话交替。** 一次 decode 是 42 个
graph launch（embedding + 40 层 + `lm_head`）串成的一条链，TPU 在一 token 内没有可以塞进第二路的空隙。

- 一个 worker 只加载一份权重，**每个会话独享自己的 KV/线性状态**。
- 引擎只有一个「常驻」会话：decode 图是 `addr_mode=1`，状态原地更新在图自己的输入内存上，绑定别的
  地址会漏掉更新。其余会话停放在各自的 NPU 缓冲里，切换时把旧会话状态拷出、新会话拷入。
- 调度器以**时间片**轮转：一次取一个就绪会话，跑一次 prefill 分块或至多 `decode_quantum`（默认 **8**）
  个 decode token，然后让出。`decode_quantum=1` 即旧的逐 token 轮转。每次切换要搬约 34.7 MB 线性
  状态，所以逐 token 轮转等于每 token 付一次这笔拷贝，2 路并发合计只有单流的 0.71×；8 token 一片把
  切换次数降到 1/8，合计回到约 0.94×，且输出逐 token 全等。见
  [`research/decode-optimization.md`](research/decode-optimization.md) §5。
- 每片内每个 token 仍走完整路径并 `await` 让出事件循环，所以取消仍按 token 生效，不会等一整片。
- **逐 token 文本是增量 UTF-8 解码出来的，不是逐 token detokenize。** 分词器是 byte-level BPE，
  一个汉字的三字节常被切到两个 token（`门簪` = `[96141, 97618, 103]`，首 token 结尾是 `簪` 的前两字节）。
  逐 token 调 `decode([id])` 会把不完整尾巴立刻变成 U+FFFD 且不可恢复，现场表现为 `门��`（MYS-2496）。
  所以 `Session.decode_bytes()` 把原始字节交给调度器的 `codecs` 增量解码器，由它在 token 之间拼接，
  不完整的尾巴留到下一个 token；`_finish()` 用 `final=True` 冲刷剩余字节，只有在生成真的截断在
  汉字中间（`max_tokens` 恰好落在三字节里的前两字节）时才出现一个 `�`，这是如实表示而不是缺陷。
  byte-level 后端（`NativeSession`）覆盖 `decode_bytes`，其余后端（mock、SAIL）走默认实现
  `decode().encode("utf-8")`，行为不变。见 `tests/test_utf8_stream_decode.py`。

> 诚实边界：这是**会话级并发（并发可用、延迟可控）**，不是真 batch 推理。bmodel 的 graph 没有
> batch 维，做不了 continuous batching。

### 4.1 并发上限与准入

每模型并发硬上限 3（`Settings.clamp` 与 worker 双重钳位）。调度器容量 = 3 个推理位 + `max_queue`
（默认 16），超出返回 429 + `Retry-After`。**新装默认 2**，已保存的设置不会被 `clamp` 改写；
实际合计吞吐随上下文与调度时间片而变，以「总览」的实时数据为准。

**会话内存按需增长**：停放会话的 FA KV 按 4096 槽位为单位增长，不按满上下文预留；线性状态固定
（约 31 MiB/会话）；prompt 矩阵每块现做 embedding 与 vit 拼接，只占一块宽。

**按 NPU 预算准入**：worker 加载后用 bm-smi 取剩余 NPU 减 512 MiB 作为「会话 + 前缀缓存」预算
（128k 约 1 GB，32k 约 3 GB）。每请求预留 `线性状态 + 20 KiB × min(ctx, prompt + max_tokens)`；
只有一个会话时总能进（它不停放），多个放不下时队首等前面的结束（FIFO，不插队），缓存挤占预算按 LRU
淘汰。拆除顺序：会话（各自等待在途 NPU 调用）→ 缓存快照 → 引擎（析构时持锁）。launch/sync 失败后
置 `fault`，此后调用立即失败并提示重启，health/stats 上报。

### 4.2 前缀缓存

两级，都计入「缓存命中率」：会话内多轮 KV 复用（后续轮次只 prefill 新增 token），以及**前缀缓存**
（以 prompt 前缀的 token 哈希为键缓存 KV 快照，LRU + 字节预算；新请求做最长前缀匹配，命中部分
`restore` 后 extend 剩余）。`cached_tokens / prompt_tokens` 即命中率，对外在
`usage.prompt_tokens_details.cached_tokens` 与 `/api/stats` 同时暴露。

快照点由 `NativeBackend.snapshot_points` 给出：第一条消息结束、最后一轮 assistant 开始，≥64 时向下
对齐 64；短对话前缀 <64 时，在不减少剩余部分 64 行预填充块的前提下精确切分；不切开图片，短于 16
token 不拍。缓存预算取设置项与 NPU 余量的较小者，空闲超过 TTL 的快照由调度循环每 10 s 清理。

**KV 快照优先放 NPU 内存，不是系统内存**（权重和 KV 使用独立的 NPU heap，不能按 Linux
`MemTotal` 推断容量）。三个必须遵守的点：

- **按前缀长度分配**，不按整段上下文。FA 的 KV 是 `[1, heads, head_dim, ctx]`，ctx 是最后一维；
  缓存 300 token 就只开 300。
- **预算按字节算**。`snapshot_plan()` 给元素数、预算给字节数，直接比较会按 dtype 宽度（bf16 = 2x）超支。
- **淘汰必须还内存**。`PrefixCache` 淘汰/覆盖/清空时调用 `store.release()`，否则每淘汰一个槽位就泄漏
  一块 NPU 内存。

`TieredSnapshotStore` 是默认策略：NPU 优先，预算耗尽才回退系统内存，所以缓存满了是**降级**而不是
请求失败。强制只用 NPU 时传 `--snapshot-location device`。

## 5. 进程与接口协议

worker 由主进程用 `python -m app.engine.worker --model <id> --port <p> --backend <b>` 拉起，在
`127.0.0.1:<p>` 上跑极简 asyncio JSON-lines 服务：`health`、`generate`（流式事件
`meta`/`delta`/`done`/`error`）、`stats`、`configure`（实时下发并发/缓存预算/decode 时间片）、
`shutdown`。取消：客户端断开 → 主进程关闭该连接 → worker 侧读到 EOF 即丢弃该 `req_id` 的会话。
`health` 的 `loaded` 来自 worker 自己的就绪标志（不是常量），`ok` 之外还要看它；父进程把「一次
`health` + 一次 `stats`」当作就绪握手，所以 `stats` 可答也是就绪的一部分（调度器已起）。

### 5.1 操作状态

控制台的「锁定」必须由后端提供：浏览器刷新一次就丢光本地状态，而模型加载要一分钟以上。契约只有
一条——**每个可操作对象返回一个 `operation`**，前端只根据它禁用控件并轮询。

模型：`operation` 为 `null`/`loading`/`unloading`，`operation_since` 是开始的 epoch 秒，
`loaded` **只有 worker 真正可用后**才为 true。`loading` 在 spawn worker **之前**写入，覆盖「进程
已起、health 未过」的整个窗口；此时 `loaded=false` 但 `pid` 已有值。加载失败在 `finally` 里清
`operation`/`pid`/`port`，写 `load_error`，回到可重试的 idle。同一模型的第二个 load **加入**在飞的
那次（共享 `asyncio.Future`），不 spawn 第二个 worker；已加载再 load 幂等 200。load 期间 unload 返回
409（半个 worker 正在往 NPU 映射权重，此时拆掉正是把 TPU 卡住的做法）。锁是**每模型一把**，
`GET /api/models` 不会被一次加载阻塞。

#### 5.1.1 「就绪」是原子发布的，不是逐步可见的

`loaded=true` 的含义是**权重、引擎、tokenizer/vision、缓存预算与调度器全部初始化完成**，因此它只在
一个时刻发布，且发布前必须依次证明：

1. 进程已起、readiness 握手已应答（`health` 的 `ok` 为真且未自称 `loaded:false`）；
2. 能力探测完成：`stats`（证明调度循环在跑）与 `health`（证明 worker 就是**这个**模型、且已就绪）。

任一步失败都是**加载失败**：清 `loaded`/`pid`/`port`、写 `load_error`（含失败阶段）、杀掉 worker、
回到 idle。不允许「loaded 但能力未知」这种状态——旧实现正是在探测**之前**置 `loaded`、并把探测异常
吞掉，于是请求可以进入半初始化的 worker，输出异常且无错误可查。

准入只有一条规则：`ModelManager.require_ready(model_id)`，OpenAI 与控制台两条路径都走它。
`loaded` 必须为真，`operation` 必须为 `None`（加载中/卸载中都是 409 `ModelBusy`），且 `/proc`
复核进程仍在（否则 503）。**409 不产生推理记录**：准入发生在记录上下文创建之前。

卸载的切换顺序同样是契约：先发布 `operation="unloading"`，再由 `on_unloading` 关闭并丢弃 RPC
client，最后 SIGTERM。两个顺序都不能颠倒——client 不先关，worker 的 shutdown 会等连接处理器直到
120 s 宽限并以 SIGKILL 收场；`unloading` 不先发布，这中间的请求会看到「loaded 但没有 client」。
因此 `WorkerClient.close()` 是**终态**：关闭后拒绝重连，否则一次控制台轮询就能把连接重新打开，
把本该 0.6 s 的卸载拖成 120 s。运行中的 `stats` 短暂失败只是上报问题，不会把已就绪的模型下线；
强校验只在初始化时发生。

`/healthz` 是**服务存活**探针（`loaded` 只是计数，可以是 0），不代表模型已加载；客户端判断能否推理
应查 `/v1/models`（只列当前可推理的模型）或控制台「模型」页的「已加载」。

agent：`operation` 为 `null`/`installing`/`starting`/`stopping`/`restarting`/`resetting`/
`uninstalling`/`configuring`，另有 `operation_since`、`busy`、`operation_label`。它是**推导**出来的，
不是第二份状态。`status` 仍是四值摘要，但 `starting` 期间 `status=stopped` 且 `running=false`，
由 `operation` 补齐语义。

**这些状态是进程内的**：服务重启后不恢复安装任务、也不恢复「正在加载」，重启后就是 idle。

### 5.2 重启后的进程接管

`operation` 不恢复，但**进程**会活过重启（`start_new_session=True`，单元文件 `KillMode=process`
只杀主进程），必须被认领，否则一次 `systemctl restart` 之后加载模型会再起一个 worker
（35B 占 20–23 GB heap）。启动时（lifespan，早于任何 load/autostart）按 `app/core/procs.py`
纯读 `/proc` 判定：

> **`KillMode` 必须是 `process`，不是 systemd 的默认值，也不能是 `mixed`。** 两种错误值都会在
> 主进程死亡时 SIGKILL 整个 cgroup：worker 一起死，接管永远没有可接管的对象；更糟的是正在跑
> NPU 的 worker 被强杀会留下卡死的 TPU（板上表现为 dmesg 里成串的 `wait api timeout`、core
> 打满 100%，只能 `systemctl reboot --force --force` 恢复）。正常停止 / 重启不依赖 systemd 收
> worker —— 服务自己的 shutdown 逐个 SIGTERM 并等待，这样卸载顺序（会话 → 缓存 → 引擎）才是
> 确定的；systemd 只负责主进程。`TimeoutStopSec` 要覆盖这条优雅退出路径（当前 180 s，worker
> 自身的宽限期是 120 s）。

| 事实 | 判定依据 | 过不了时 |
|---|---|---|
| 是不是我们会启动的模型 worker | `argv[1:3] == ["-m","app.engine.worker"]`、`--model-id`、`--model-path` 在本 `models_root` 内、`cwd` 在安装树内、`/proc/<pid>/exe` 是 Python | 不接管（不是我们的） |
| 是不是我们会启动的 agent | `exe` 与 `spec.command()[0]` 同一文件、`cwd` 在 agent 目录内、`--port` 与 `agents.json` 一致、非 flag 片段顺序匹配 | 不接管 |
| 还能不能服务 | worker 的 JSON `health`（校验 `model`）**且** `stats` 应答（证明调度器已起） | 记冲突：模型 `conflict` + load 409；agent `failed` + `orphan_pid`，start 拒绝 |
| 有没有活着的同 root 实例 | `-m app.main` 且 `--data-root`（或 env）解析后同路径 | 不接管，报冲突（两个 manager 驱动一个进程会互相卸模型） |

认领后 `AdoptedProcess` 实现窄接口 `PopenLike`，unload/stop 仍走原路径；信号走
`procs.signal_group`（拒绝 `pid<=0`，否则 `kill(0, sig)` 会打掉本进程组）。模型侧接管的进程
**拒绝 SIGKILL**：拿不到退出状态，且 prefill 中强杀会卡死 NPU，所以只 SIGTERM 并在 120 s 后报错
留给人工。`loaded` 不是记忆而是推导：`refresh()` 用 `/proc` 复核 pid（含启动时间，防 pid 复用）——
子进程在自己的 session 里、本进程没有 reaper，除了主动查没有别的机制会发现它死了。

接管同样是**就绪判定而非存活判定**：探测期间先发布 `operation="loading"`（否则这段时间模型看起来
是 idle，一次点击就会在旁边再起一个 worker），`health` 与 `stats` 都通过后还必须在 `loaded` 发布
**之前**读完 survivor 的能力（`supports_vision`/`context_length`/`supports_sampling`），否则重启后
会拿文件名猜的值去服务。任一步不过只记 `conflict`、不置 `loaded`、不发信号。

## 6. 持久化与数据目录

程序与数据分开：`/opt/sophgo/cv84x6_llm_server/` 只放程序，`etc/server.env`（`KEY=VALUE`）是数据
目录位置的**唯一来源**，systemd 用 `EnvironmentFile=` 读它。

| `$DATA/`（默认 `/data/cv84x6_llm_server`） | 内容 |
|---|---|
| `models/` | 每个模型一个子目录：`*.bmodel` + `config/`（可省略）+ `meta.json` |
| `state/` | `state.json`（API key 只存 sha256、设置、累计用量）、`session.key`、`inference_records.sqlite3`（推理记录，见 [`inference-records.md`](inference-records.md)）、`audit.db`（管理操作审计，见 [`logs.md`](logs.md)）、`logs/`（`platform.log` 与每个模型的 `worker-<id>.log`，均轮转） |
| `agents/` | 三个 agent 的安装、配置与数据 |
| `downloads/` | 下载临时文件。模型下载先写入 `downloads/models/<任务 id>/`，完成后才移入 `models/<模型名>/`；失败、取消或服务重启后残留的临时目录会被删除，半截文件永远不会出现在 `models/` 里 |
| `.cv84x6-data` | 标记文件，防止误删或误搬别的目录 |

原子写（写临时文件 + `os.replace`），避免掉电把状态写成半截。「设置 → 数据目录」可迁移：卸载所有
模型 → 复制 → 校验文件数与字节数 → 改写 `server.env`（临时文件 + rename）→ 切换运行中的路径 →
删除旧目录（只在旧目录有标记文件时）。任一步失败则清空新目录、配置与运行路径不变。同一时间只允许
一个迁移任务（再提交返回 409）。

推理记录是 `state/` 下的 SQLite（WAL）。它的连接在**卸载模型之前**关闭（`stop_everything` 的第
一步），复制期间没有写入者；切换后 `rebind` 把它重绑到新 `state/` 并按新读到的设置重新配置。关闭
到重绑之间的窗口里写入被丢弃（不重开旧路径），读取报「正在迁移」。这条顺序与模型日志同理：旧树即将
被删除，任何迟到的写入都会落在一个已经不复存在的目录里。

## 7. Agent 与同源代理

三个 agent 的 Web 界面都通过本服务同源代理访问：`/agents/<id>/`。不生成
`http://<板子IP>:<agent端口>` 这类链接——客户现场只转发服务端口，那种地址在浏览器里根本不通。
代理（`app/api/agent_proxy.py`）做的事：

- 认证：HTTP 与 WebSocket 都要求 console 管理员 cookie，不是匿名入口。去掉 `X-Frame-Options`，
  把 CSP 的 `frame-ancestors` 收窄到 `'self'`。
- **前缀改写**（`prefix_root` agent，即 opencode）：服务端改写 HTML/CSS/JS 里的绝对路径，并注入
  同源 shim 接管运行时才产生的 URL（`fetch`、XHR、`WebSocket`、`EventSource`、
  `history.pushState/replaceState`、元素 `src`/`href` 的 setter、`setAttribute`）。缺任何一半都不够：
  改写看不到脚本算出来的 URL，shim 来不及在模块图开始加载前生效。
- opencode 自己的 basic auth 由代理代替已认证的管理员出示，所以内嵌与外开都不再要求第二次登录；
  密码不写进日志，也不出现在 URL 里。上游 `Set-Cookie` 若 `Path=/` 会被收窄到 `/agents/<id>/`，
  否则多个 agent 在同一 origin 上互相覆盖 cookie。
- 非安全上下文（`http://<板子IP>:8000`）里 `crypto.subtle` 不可用，而 opencode 用它给附件算 SHA-256
  当 IndexedDB 的键。shim 在缺失时补一个只实现 SHA-256 的最小实现，其它算法明确 reject。

### 5.3 管理接口的对外契约（MYS-2676）

`/api/*` 有两个调用者：控制台（会话 cookie）和脚本（`Authorization: Bearer <admin key>`）。三条
不变量，都落在 `app/core/auth.py` 与 `app/core/errors.py` 里：

- **凭据分权限范围。** key 的 `scope` 是 `inference`（默认，只能 `/v1`）或 `admin`（还能 `/api`）。
  没有 `scope` 字段的老 key 读成 `inference`——升级不需要迁移，也不会把推理 key 变成管理 key。
  用 `inference` key 调 `/api` 是 **403 `forbidden_scope`**（不是 401：调用方身份是清楚的，
  缺的是权限）。
- **CSRF 只针对 cookie。** cookie 写请求校验 `Origin`（缺失放行，存在则须是本机、`CV84X6_MCP_ORIGINS`
  声明的地址，或与 `Host` 一致），另加 cookie 的 `SameSite=Lax`。Bearer 请求不做这项检查：
  浏览器不会自动带上它，没有可伪造的东西。
- **错误体统一。** `/api/*` 的每个 4xx/5xx 都是 `{"detail": <中文>, "code": <稳定英文码>}`。
  `detail` 的措辞可以改，`code` 不能——脚本按 `code` 分支。422 也转成这个形状。`/v1` 不动，
  那里仍是 OpenAI 的错误封装。

文档是**生成**的：`tools/gen_admin_api_doc.py` 从 `/api/openapi.json` 产出 `docs/admin-api.md`，
`tests/test_admin_api_docs.py` 重新生成一次并比对，因此它不会落后于代码。交互页 `/api/docs`、
`/api/redoc` 的静态资源提交在 `app/static/docs/`（板上没有外网，Swagger 默认从 CDN 取），
且与文档本身一样要求管理凭据。

## 8. 前端

React + TypeScript + Vite，构建产物 `web/dist` 提交在仓库里，由 FastAPI 直接托管（板上不需要 node）。
页面：总览（设备资源曲线、在线模型、吞吐、命中率）、模型（目录扫描、dfss 下载、加载/卸载、占用）、
对话（支持图片，流式，显示 TPS/FTT/命中）、API Key（创建/吊销/配额/用量）、Agent（安装、配置、
启停、内嵌）、文档。视觉取值只能来自 token，越界即测试失败——规范见
[`console-design.md`](console-design.md)，`tests/test_console_design.py` 是它的回归守卫。

## 9. 安装与发布边界

发布主入口是 arm64 `.deb`。`scripts/package.sh --stage` 产出的发布树是**唯一**的 payload 定义，
`package_deb.sh` 把它包成 deb，两个格式不会分叉。硬规则与原因：

| 规则 | 原因 |
|---|---|
| `prerm` 只 `systemctl stop`，从不 SIGKILL | worker 映射权重时强杀可能卡死 NPU，只能重启板子 |
| `postinst` 起不来也 `exit 0` | 非零 postinst 会让 dpkg 把包当「坏了」并阻塞之后所有 apt 操作；此时文件已就位 |
| `apt remove` 保留 `etc/server.env` | 它是数据目录位置的唯一记录，重装要靠它找回模型 |
| `apt purge` 也**不删**数据目录 | 里面有几十 GB 模型、客户端在用的 API key、管理密码哈希、装好的 agent；只打印 `rm -rf` |
| 缺 `linaro` 用户就失败退出 | 静默退回 root 等于让用户装的所有 agent 拿到 root |
| `libsophon` 缺失时只告警 | 厂商运行时不在任何 apt 源里；非零退出会把包卡在 half-configured |
| `etc/server.env` 不进包、不作 conffile | 它由软件自己改写（迁移时改 `CV84X6_DATA_DIR`）；conffile 会让 dpkg 就软件自己的文件反复询问 |
| postinst 复跑 `install.sh --in-place` | 写第二份配置逻辑，它迟早和 install.sh 说的不一样 |

验证：`tests/test_packaging.py` 静态检查上面每条规则；`scripts/test_deb.sh` 在 arm64 容器里真跑
装/重配置/升级/remove/重装/purge，断言数据目录逐字节不变。容器里没有 NPU 和 systemd，所以它证明
的是**维护脚本**，不是服务能起来——后者在真机验收里做。

## 10. 交付与验证纪律

pytest 覆盖调度器（并发公平性/取消）、前缀缓存（LRU/命中计算）、鉴权、OpenAI 协议一致性、管理面
CRUD；`MockBackend` 跑通全链路，所以全部能在 x86 上验，真机只验与 NPU 打交道的那部分。前端
`npm run build` 成功，浏览器验收见 [`web/acceptance/README.md`](../web/acceptance/README.md)；
真机按 `tools/` 的脚本跑接口、缓存、长上下文与并发。未经真机验证的部分，文档与汇报里明确标注，
不写「已通过」。
