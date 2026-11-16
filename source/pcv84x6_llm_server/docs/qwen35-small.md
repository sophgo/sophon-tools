# Qwen3.5-9B / 4B：128k + 视觉编译、精度与板上实测（MYS-2754）

服务原本只提供 Qwen3.6-35B-A3B 一个对话模型。它是 MoE、128k、22.8 GB NPU——
**一块板子只要还要常驻辅助模型，就装不下它**。本文是补上两个稠密档（9B、4B）的记录：
怎么编、精度差多少、板上跑多快、能和哪些辅助模型共存。

| 模型 | 权重 | 上下文 | 视觉 | bmodel |
|---|---|---|---|---|
| `qwen3.5-9b-128k` | int4 AutoRound → w4bf16 | 131072 | 是 | 见 §5 |
| `qwen3.5-4b-128k` | int4 AutoRound → w4bf16 | 131072 | 是 | 见 §5 |
| ~~`qwen3.5-4b-bf16-128k`~~ | bf16（原始 checkpoint） | 131072 | 是 | **v0.6.32 起已从模型目录移除**（见下方说明） |


> **v0.6.32 更新**：按用户决定，4B bf16（`qwen3.5-4b-bf16-128k`）已从模型目录移除。理由是：它的 NPU 占用（13.3 GiB）与 9B w4（13.0 GiB）相当，速度只有后者的一半（7.2 对 15.7 tok/s），与参照的一致率也更低（83.8% 对 88.1%）。下文保留它的编译与实测记录作为证据；手动放进模型目录的 bf16 文件仍能被识别和加载。

## 1. 为什么是这两个尺寸，为什么是 Qwen3.5

- **Qwen3.6 没有 4B / 9B**（用户 2026-11-09 确认）。Qwen3.6 只有 35B-A3B 这一档，
  所以小尺寸只能回到 Qwen3.5——两者**同一家族、同一个 `qwen3_5` 架构**
  （`Qwen3_5ForConditionalGeneration`），35B 是 `qwen3_5_moe` 的 MoE，
  9B/4B 是稠密。引擎 `native/src/llm_engine.cpp` 从 bmodel 读结构、不依赖 MoE，
  所以不需要改引擎——但仍要实测证明，见 §3。
- **稠密反而更简单**：没有 routed expert，也就没有 MYS-2293 记录的
  "prefill 图里 MoE 算子精度塌到 0.75 余弦" 那个问题。这一点在 §3 的 prefill
  对齐数字上能直接看到。

结构与 35B 的差异（`config.json` 的 `text_config`）：

| 项 | 4B | 9B |
|---|---|---|
| hidden / layers | 2560 / 32 | 4096 / 32 |
| 全注意力层 | 8（`full_attention_interval: 4`） | 8 |
| Q / KV 头，head_dim | 16 / 4，256 | 16 / 4，256 |
| linear attn | 16 QK 头 / 32 V 头，head_dim 128，conv 4 | 同 |
| FFN intermediate | 9216 | 12288 |
| vocab | 248320 | 248320 |
| `tie_word_embeddings` | **true** | **false** |
| vision | depth 24, hidden 1024, out 2560 | depth 27, hidden 1152, out 4096 |

★ **`tie_word_embeddings` 两者不同**，这决定了 lm_head 是否与 embed 合并
（`LlmConverter.do_lmhead_merge`），也就是合并后 bmodel 里有没有独立的 `lm_head` 图。
两个模型必须分别验证，不能用一个的结论推另一个。

## 2. 编译

脚本 `tools/qwen35/convert.sh`，参数与线上 35B **完全一致**：

```shell
llm_convert -m <ckpt> -s 131072 -q w4bf16 -c bm1684x2 --num_core 4 \
  --use_history_kv --chunk_length 2048 --max_pixels 768,768 --dynamic --debug
```

沿用这条链路的理由只有一条：它是这块芯片上**唯一被验证过的 128k 配方**。

### w4 权重的来源

三个候选里选了 **Intel 官方的 AutoRound int4 包**：

| 候选 | 判断 |
|---|---|
| `Intel/Qwen3.5-4B-int4-AutoRound`、`Intel/Qwen3.5-9B-int4-AutoRound` | **采用**。`quant_method: auto-round`、`bits 4`、`group_size 128`、`packing_format: auto_round:auto_gptq`，与已验证的 3.6-35B 完全同构 |
| `kaitchup/...-autoround-W4A16` | 未采用：group_size 非 128，且投影命名未对齐 |
| bf16 源 + `-q w4bf16` 现场量化 | **不可行**，见下 |

★★ **bf16 源 + `-q w4bf16` 根本不会量化**。`ModelHandle.init_quantization()`
只在存在 `quantization_config` 时才走 INT4 分支；没有它就走
`get_qtype(dtype, 16)` → `bf16`，即原样 bf16（`ModelHandle.py:88-96`）。
所以 w4 必须来自**已经量化好的 checkpoint**，不能拿 bf16 现量化。这条在 MYS-2434
已经踩过，这里复核了容器里的代码路径：

```shell
$ python3 -c "from tpu_mlir.python.llm.LlmConverter import LlmConverter; ..."
bits16 bf16 -> bf16
bits4  bf16 -> w4bf16     # 只有在 quantization_config 存在时才会走到
```

bf16 版（`qwen3.5-4b-bf16-128k`）反过来用官方 `Qwen/Qwen3.5-4B` 原始 checkpoint。

★★ **但它必须传 `-q bf16`，不能沿用 `-q w4bf16`。** 这一点我先写错了，编出来才发现：

`ModelHandle.init_quantization` 在没有 `quantization_config` 时，只是根据 dtype 算出
`half_precision_quantize`（`bf16`），并**不修改 `conv.quantize`**；而
`compile_block_args` 在 `quant_bits == 16` 的分支里直接用 `conv.quantize` 传给
`model_deploy.py`。于是 `-q w4bf16` + bf16 源 = **真的把 block 量化成 w4**，
只是文件名还叫 bf16。

现场证据：错误的那个 bf16 构建产物 `block_0` 是 69 MB，而 w4 构建的 `block_0`
是 66 MB——只差 5%，bf16 该是 2.2 倍；`task.txt` 里 48 个 piece 全是
`--quantize w4bf16`。改成 `-q bf16` 重编后，76 个 piece 全是 `--quantize bf16`。

对 int4 checkpoint 依然用 `-q w4bf16`：那条路有 `quantization_config`，
`quant_bits=4`，`compile_block_args` 拼出 `w4` + `bf16` = `w4bf16`，是对的。

### ★★ 容器里的两个补丁，以及为什么两个都要查

镜像 `tpu-mlir:1.30.2-38` 是共享的、被反复手工改过。MYS-2588 踩过一次：
镜像我里 `Qwen3_5Converter.py` 被改成 `num_split_fused_moe=2`，导致 3.6-35B 整轮编译失败。

本次建容器时**同样发现 `num_split_fused_moe=2`**（663/1173 两行），已 `cp *.orig` 还原。
`convert.sh` 开头因此加了一道硬检查：`LlmConverter.py` 与 `.orig` 的差异必须**正好两行**
（MASK_SIZE 那一对），`Qwen3_5Converter.py` 必须与 `.orig` 完全一致，否则拒绝编译。

必须保留的那一处是 MASK_SIZE：

```python
# LlmConverter.py:61
self.MASK_SIZE = self.tpu_info.npu_num * 8   # wheel 原值 * 4
```

`bm1684x2` 的 `npu_num = 16`，所以 64 → 128。MYS-2588 实测：同板同服务下冷 prefill
在 16k/32k/64k/96k 分别快 24/36/49/55%，短 prompt 与 decode 速度不变，输出逐 token 相同。

### 磁盘

128k 的中间产物很大。MYS-2588 实测每个 piece 留一整套 npz（约 1.7-1.9 GB），
154 个 piece 光中间 npz 就 267 GB。`tools/qwen35/prune_npz.sh` 在某个 piece 的
`.bmodel` 已经产出后删掉它的 npz（合并只用 `.bmodel`），**不要删 out 根目录下的
`block_N_top_weights.npz`**——未完成 piece 的 mlir 还指着它们。

写满时 bmodel 会被**静默截断**（MYS-2588：`block_cache_27_5` 只写了 10 MB，正常 460 MB，
而 `model_deploy.py` 的 rc 不一定非 0）。所以 `tools/qwen35/verify_pieces.sh`
逐个 `model_tool --info` 校验并比对大小，再合并。

## 3. 精度

参照物在 x86 上用 HF 原版生成：`tools/qwen35_hf_ref.py`，greedy、各 128 token，
13 条中英文提示词（含一条带图），提示词在 `tools/qwen35_prompts.json`。
板上用 `tools/qwen35_board_run.py` 跑同样输入，`tools/qwen35_compare.py` 逐 token 比对。

### 3.1 `qwen3.5-4b-128k`（w4）精度

参照物：**同一个 int4 checkpoint** 在 x86 上反量化回 bf16 后用 HF `transformers` 跑
（`tools/qwen35_hf_ref.py`），greedy、各 128 token、12 条中英文提示词。
对拍用 `tools/qwen35_compare.py`，板上侧是 `tools/qwen35_board_run.py` 直接驱动 C API。

| 用例 | 一致/总数 | 一致率 | 首个分歧 |
|---|---|---|---|
| zh-explain | 62/124 | 50.0% | 61 |
| zh-poem | 29/29 | 100% | — |
| zh-code | 128/128 | 100% | — |
| zh-math | 46/128 | 35.9% | 44 |
| zh-table | 78/78 | 100% | — |
| en-explain | 99/100 | 99.0% | 28 |
| en-code | 111/111 | 100% | — |
| en-list | 13/128 | 10.2% | 11 |
| en-json | 55/55 | 100% | — |
| zh-json | 48/48 | 100% | — |
| zh-cot | 128/128 | 100% | — |
| mix-long | 69/128 | 53.9% | 69 |
| **合计** | **866/1185** | **73.1%** | — |

**128 token 完全一致的用例：7/12**；最早分歧点 11，中位 44。

### 3.2 `qwen3.5-9b-128k`（w4）精度

同样的方法（同一 int4 checkpoint 反量化的 HF 参照、12 条 × 128 token）：

| 用例 | 一致/总数 | 一致率 | 首个分歧 |
|---|---|---|---|
| zh-explain | 98/98 | 100% | — |
| zh-poem | 30/30 | 100% | — |
| zh-code | 77/128 | 60.2% | 75 |
| zh-math | 44/128 | 34.4% | 43 |
| zh-table | 76/76 | 100% | — |
| en-explain | 119/119 | 100% | — |
| en-code | 109/109 | 100% | — |
| en-list | 84/84 | 100% | — |
| en-json | 56/56 | 100% | — |
| zh-json | 48/48 | 100% | — |
| zh-cot | 128/128 | 100% | — |
| mix-long | 128/128 | 100% | — |
| **合计** | **997/1132** | **88.1%** | — |

**128 token 完全一致：10/12**；最早分歧 43，中位 75。

9B 明显好于 4B（88.1% vs 73.1%，10/12 vs 7/12）。这与"更大的模型对量化更鲁棒"一致，
也说明两个模型必须各测——不能用一个的精度结论推另一个。

两个分歧同样**都是同义改写**：`zh-code` 在第 75 个 token 处把注释措辞换掉，
前面的 `def merge_intervals` 骨架、`intervals.sort` 排序逻辑逐 token 相同；
`zh-math` 在第 43 个 token 处把"假设水池的总容量为 **1** 个单位"写成
"假设水池的总容量为 **1**（即注满 1 个单位的水量）"，多一个括号解释，
后面的效率算式一致。

### 3.3 `qwen3.5-4b-bf16-128k` 精度

参照物是**官方 `Qwen/Qwen3.5-4B` bf16 原版**，板上是同一份权重的 bf16 编译产物——
两者浮点数完全相同，所以**任何分歧都是引擎/编译器的问题，不是量化的代价**。

| 用例 | 一致/总数 | 一致率 | 首个分歧 |
|---|---|---|---|
| zh-explain | 124/126 | 98.4% | 103 |
| zh-poem | 29/29 | 100% | — |
| zh-code | 128/128 | 100% | — |
| zh-math | 128/128 | 100% | — |
| zh-table | 78/78 | 100% | — |
| en-explain | 30/107 | 28.0% | 14 |
| en-code | 121/121 | 100% | — |
| en-list | 51/99 | 51.5% | 38 |
| en-json | 55/55 | 100% | — |
| zh-json | 48/48 | 100% | — |
| zh-cot | 128/128 | 100% | — |
| mix-long | 65/128 | 50.8% | 62 |
| **合计** | **985/1175** | **83.8%** | — |

**128 token 完全一致：8/12**；最早分歧 14，中位 62。

#### 这个结果不符合 issue 给 bf16 定的标准，要说清楚

issue 的要求是「bf16 版应当基本逐 token 一致」。83.8% / 8-of-12 **没有达到**
「基本一致」该有的水平——对照 w4 版的 73.1% / 7-of-12，bf16 只好了 10 个百分点，
而它本该接近 100%。

**已经排除的原因**（都验过）：

- **不是构建问题**：`block_0.bmodel` 是 231 MB，w4 版是 66 MB；`module.platform`
  是 `"LLM"` 而不是 `"LLM_QUANTIZED"`；76 个 piece 全是 `--quantize bf16`。
  即权重确实是 bf16，没有被量化。
- **不是模型错**：4 个分歧用例的内容都正确。`en-explain` 参考写
  "store the key and value vectors for every token"，板上写
  "store a separate key-value pair for every token in the input and output history"——
  同一件事的两种说法。`en-list` 的五条对比内容与顺序都对。
- **不是 tokenizer**（同一份 `tokenizer.json`，prompt 长度逐条相同）。

**最可能的原因**：bf16 的数值精度比 int4 更"脆"——int4 的量化噪声足够大，
反而把近似平局的 logits 稳定地推向同一侧；bf16 下两个候选的 logits 差异在
1e-3 量级，TPU 的累加顺序（`--num_core 4` 下的分块归约）与 x86 torch 的
归约顺序不同，就足以翻转 argmax。一次翻转会改变后续上下文，之后整段走向
另一条同样合理的措辞路径。

**这条没有在本次交付里解决**：要真正定位需要逐层对拍（`tools/precision/` 那套
`run_dbg.py` + `cmp_dbg.py`），那是独立的工程量。本次交付如实给出数字，
不把它写成"基本一致"。

#### 怎么读这张表

一致率低的四个用例（en-list 10%、zh-math 36%、zh-explain 50%、mix-long 54%）
**不是答错**，是同义改写。逐个看分歧点前后：

- `en-list`：分歧在第 11 个 token，参考 "…establishes a **link** before data transfer"，
  板上 "…establishes a **reliable link** before data transfer" —— 后面整段错位，
  但五条对比的**内容与顺序都对**。
- `zh-math`：第 44 个 token，参考写 "设水池的总容量为 $1$。

* 甲管效率…"，
  板上多插了一句 "我们将"注满"视为正效率，"排空"视为负效率。" —— 多一句解释，
  后面的算式仍然正确。
- `zh-explain`：第 61 个 token，参考 "MoE 在推理时仅激活与当前输入最相关的少量专家"，
  板上 "MoE 在推理时通常只激活少量专家（如 Top-k 策略）" —— 同一件事的另一种说法。
- `mix-long`：第 69 个 token，同理。

**这正是 int4 该有的表现**：单个 token 的 argmax 被量化噪声推翻一次，后面就走上
另一条同样合理的措辞路径。逐 token 一致率对这种情形天生悲观——它不是"错多少"，
是"从哪一步开始用不同的词说同一件事"。

**判断依据不是一致率，是分歧点之后还有没有错**：7 个用例逐 token 完全相同（含
`zh-cot` 128/128 全程算式、`zh-code` 128/128 完整 Python 函数、`zh-json`/`en-json`
完整 JSON），其余 5 个的分歧都是措辞。没有出现"数字算错""代码语法坏""JSON 结构坏"。

#### 与 bf16 版的区别（为什么 bf16 版必须 100%）

bf16 版的权重就是参照物本身，任何分歧都是引擎/编译器的问题，**可以要求 100%**。
w4 版经过 int4 量化，逐 token 完全一致在 128 token 的生成上不现实——上表就是证据。
两个标准不同是有意的，不能拿 w4 的 73.1% 去放行 bf16 版，也不能拿 bf16 的 100%
去要求 w4 版。

### 为什么 bf16 版要"基本逐 token 一致"，w4 版不要求

bf16 版的权重就是参照物本身的浮点数，所以任何差异都是**引擎或编译器**的问题，
不是量化的代价——它可以要求 100%。w4 版经过 int4 量化，逐 token 一致在长生成上
本来就不现实（一个 token 翻转会改变后续上下文），合理范围看的是**首个分歧点的位置**
和**一致率**，而不是"全对"。

### 3.4 中文问答与工具调用（`qwen3.5-4b-128k`，经服务 HTTP 接口）

逐 token 对拍走的是引擎 C API；这一组走**真实服务**（`/v1/chat/completions`），
证明新模型在服务链路上（worker、tokenizer、chat template、scheduler）也是通的。

**中文问答**（`temperature 0`，`max_tokens 200`）：

> **问**：用两句话解释什么是 KV cache。
>
> **答**：KV cache（键值缓存）是大型语言模型在生成文本时，为了加速推理过程而预先存储的
> 中间计算结果。它通过复用前序 token 的键值对，避免了在每一步生成中重复计算历史上下文，
> 从而显著降低计算开销并提升生成速度。

usage：`prompt_tokens 20 / completion_tokens 61 / total_tokens 81`。

**工具调用**（`tools` + `tool_choice: "auto"`）：

> **问**：北京现在天气怎么样？请调用工具查询。
>
> `finish_reason`: `tool_calls`
> `tool_calls`: `[{"id": "call_b8ac3eaf178686915f739b6a", "type": "function",
> "function": {"name": "get_weather", "arguments": "{\"city\": \"北京\"}"}}]`
> `content`: `null`

模型没有把答案编成散文，而是正确地产生了 `tool_calls`、选中 `get_weather`、
按 schema 填了 `{"city": "北京"}`，并以 `finish_reason: tool_calls` 结束——
这是 agent 能不能用它的判据。

## 4. 板上实测（.157）

`tools/qwen35_bench.py` 一次跑完验收要的全部时延/吞吐/占用。

### 4.0 `qwen3.5-9b-128k`（w4）实测

同一台 `.157`，同一条 `tools/qwen35_bench.py`：

| 项 | 4B w4 | **9B w4** |
|---|---|---|
| bmodel 大小 | 4,019,560,448 B | **8,843,063,296 B** |
| 加载耗时 | 13.4 s | **31.2 s** |
| 静态占用 | 8651.5 MiB | **13,331.2 MiB** |
| 加载后 NPU 余量 | 17,972.5 MiB | **9,244.2 MiB** |
| 单会话 decode | 25.6 tok/s | **15.7 tok/s** |
| 短 prompt TTFT | 226 ms | **371 ms** |
| 8k prompt TTFT | 17.0 s | **20.1 s** |
| 双会话 decode | 9.9 + 9.6 tok/s | **6.4 + 6.3 tok/s** |
| `hidden_size` | 2560 | 4096 |
| `kv_bytes_per_token` | 32768 | 32768（同为 8 层 full attn） |

两个模型的 `kv_bytes_per_token` 相同，因为它们的 full-attention 层数、KV 头数、
head_dim 完全一样（8 层 / 4 头 / 256），只有 hidden 与 FFN 不同——这解释了
为什么 9B 的静态占用多 4.7 GiB 而 KV 成本一样。

### 4.0b `qwen3.5-4b-bf16-128k` 实测

| 项 | 4B w4 | **4B bf16** |
|---|---|---|
| bmodel 大小 | 4,019,560,448 B | **9,257,050,112 B**（2.3×） |
| 加载耗时 | 13.4 s | **31.1 s** |
| 静态占用 | 8651.5 MiB | **13,648.5 MiB** |
| NPU 余量 | 17,972.5 MiB | **8,926.9 MiB** |
| 单会话 decode | 25.6 tok/s | **7.2 tok/s**（0.28×） |
| 短 prompt TTFT | 226 ms | **1025 ms** |
| 8k prompt TTFT | 17.0 s | **45.6 s** |
| 双会话 | 9.9 + 9.6 tok/s | **3.5 + 3.3 tok/s** |

bf16 的代价很直接：**显存 1.6×、decode 速度 0.28×、8k prefill 2.7×**。
它存在的意义只有两个——w4 版的精度参照物，以及"差一个 token 也要对"的场合。
日常推理该用 w4。

### 4.1 `qwen3.5-4b-128k`（w4）实测

真机 `.157`（10.43.0.157，libsophon 0.4.15，固件 `fd3aca2`，`libcv84x6_llm.so` v0.6.30），
`tools/qwen35_bench.py` 直接驱动 C API，一次运行：

| 项 | 实测 |
|---|---|
| bmodel 大小 | 4,019,560,448 B |
| **加载耗时** | **13.4 s** |
| **加载后静态占用** | **8651.5 MiB NPU**（VPP 未用，仍只有启动时保留的 256 MiB） |
| 加载后 NPU 余量 | 17,972.5 MiB / 26,624 MiB |
| **单会话 decode** | **25.6 tok/s**（32 步，贪心） |
| **首 token 时延（短 prompt，8 token）** | **226 ms** |
| **首 token 时延（8k prompt，8192 token）** | **17.0 s** |
| **双会话 decode** | A 9.9 tok/s + B 9.6 tok/s，合计 19.4 tok/s |
| 引擎自报 | `layers=32 seq=131072 max_input=2048 hidden=2560 vit=1(2304 patches) history=1` |
| 会话状态 | `session_state_bytes` 4121.5 MiB，`kv_bytes_per_token` 32768 B（0.03125 MiB），`linear_state` 25.5 MiB |

读法：

- **静态占用 8.45 GiB**，是 bmodel 4.0 GB 的两倍——int4 权重解包后按 w4bf16 放在 NPU 里，
  加上 neuron workspace 和每个 full-attention 层的 KV 模板。这个数才是内存规划用的。
- **8k prompt 的 17.0 s** 是冷 prefill，`--chunk_length 2048` 意味着 4 个 chunk 依次跑
  prefill 图。它与 35B 的同口径数字不能直接比：35B 只有 10 层 full attention，
  这个模型 32 层里有 8 层，且 hidden 更小。
- **双会话合计 19.4 < 25.6**：两个会话在同一个 engine 里时间片轮转，总吞吐低于单会话，
  这与 35B 的行为一致（`docs/research/decode-optimization.md`）。
- `kv_bytes_per_token = 32768` = 8 层 full attention × 2（K 和 V）× 4 KV 头 × 256 dim × 2 B，
  与 config 对得上；按 128k 满上下文算 KV 是 4.0 GiB，正好等于 `session_state_bytes`
  减去线性状态。

★★ **测这个的时候板子卡死过一次**，用的是 `systemctl reboot --force --force` 恢复
（本任务共 1 次）。判据就是 `docs/research/d7-tpu-hang.md` 记的那套：
`/proc/bmtpu/scaler_info` 的 `recvmsg_cnt` 20 秒不增长、`using_flag == 0xa5a5`、
`cur_api_id == 0x90000003`。**这三条同时成立就是不卡自愈的，只能重启**。
`std::bad_alloc` 不是卡死的原因——那次是我自己的探针 ABI 写错了（见 §6）。

### 与辅助模型共存

板子的 NPU 堆是 25.70 GiB（`.157`，`npu heap base 0x1095800000 size 0x66d000000`），
D7 的规则是**至少留 1 GiB**。四个辅助模型实测静态占用：

| 模型 | 静态占用 |
|---|---|
| Qwen3-Embedding-0.6B (seq2048) | 1465 MiB |
| BGE-Reranker-v2-M3 | 1136 MiB |
| Qwen3-ASR-0.6B | 1639 MiB |
| PP-OCRv6 det+layout | 约 154 MiB（另有 rec 档位按需加载） |

合计约 **4.4 GiB**（不含 rec 档位）。对照 §4.1 实测的 **8.45 GiB**：

| 组合 | NPU 占用 | 余量（下限 1 GiB） |
|---|---|---|
| 4B w4 + 四个辅助模型 | 8.45 + 4.4 = **12.9 GiB** | **13.7 GiB** ✓ |
| 9B w4 + 四个辅助模型 | 13.0 + 4.4 = **17.4 GiB** | **8.6 GiB** ✓ |
| 4B bf16 + 四个辅助模型 | 13.3 + 4.4 = **17.7 GiB** | **8.3 GiB** ✓ |
| 35B-A3B 128k + 四个辅助模型 | 22.2 + 4.4 = **26.6 GiB** | **超出 0.9 GiB** ✗ |

最后一行就是这个交付的理由：**35B 装不下任何辅助模型**，而 4B w4 装得下全部四个
还余 13.7 GiB。9B 与 4B bf16 的数字在各自编完后补进上表。

## 5. 产物与发布信息

三个文件都在 13.24 的 `/mnt/sda2/cv84x6_llm_server/build_qwen35/out_*/` 下，
**上传与加标签按 issue 约定由负责人做**，这里只给清单。

### qwen3.5-4b-128k（4B w4）

| 项 | 值 |
|---|---|
| 文件名 | `qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_033630.bmodel` |
| md5 | `af0bf863862a9f68ea2bdc10695f67c1` |
| 字节数 | 4,019,560,448 |
| 13.24 路径 | `out_4b_s131072/` |

### qwen3.5-9b-128k（9B w4）

| 项 | 值 |
|---|---|
| 文件名 | `qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_051942.bmodel` |
| md5 | `7224f129dd233bf77665183e65a6b124` |
| 字节数 | 8,843,063,296 |
| 13.24 路径 | `out_9b_s131072/` |

### qwen3.5-4b-bf16-128k（4B bf16）

| 项 | 值 |
|---|---|
| 文件名 | `qwen3.5-4b_bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_064932.bmodel` |
| md5 | `e5cb4febb96e4c126f0ca5ee9730f558` |
| 字节数 | 9,257,050,112 |
| 13.24 路径 | `out_4bbf16_s131072/` |

### 要加的两行标签

`.dfss_down_flag` 里，每个模型两行（主标签 + `.md5` sidecar），格式见
[`model-release.md`](model-release.md)：

```
cv84x6_llm_qwen3.5-9b-128k         qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_051942.bmodel
cv84x6_llm_qwen3.5-9b-128k.md5     qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_051942.bmodel.md5
cv84x6_llm_qwen3.5-4b-128k         qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_033630.bmodel
cv84x6_llm_qwen3.5-4b-128k.md5     qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_033630.bmodel.md5
cv84x6_llm_qwen3.5-4b-bf16-128k    qwen3.5-4b_bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_064932.bmodel
cv84x6_llm_qwen3.5-4b-bf16-128k.md5 qwen3.5-4b_bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_064932.bmodel.md5
```

sidecar 文件内容（`md5sum` 格式，两个空格）：

```
af0bf863862a9f68ea2bdc10695f67c1  qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_033630.bmodel
7224f129dd233bf77665183e65a6b124  qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_051942.bmodel
e5cb4febb96e4c126f0ca5ee9730f558  qwen3.5-4b_bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_064932.bmodel
```

★ 已确认 dfss 现网（`/.dfss_flags`，82 个标签）**没有**任何 `qwen3.5` 标签，
所以这六个新标签不会撞名。

## 6. 工具

仓库里新增的四个脚本，都在 `tools/`：

| 脚本 | 在哪跑 | 作用 |
|---|---|---|
| `qwen35_hf_ref.py` | x86（有 torch） | 从原始 checkpoint 生成 greedy 参照（13 条提示词 × 128 token） |
| `qwen35_board_run.py` | 板 | 同样输入的板上 greedy 输出，直接驱动 C API |
| `qwen35_compare.py` | 任意 | 逐 token 一致率与首个分歧点 |
| `qwen35_bench.py` | 板 | 加载耗时、静态占用、decode tok/s、短/8k TTFT、双会话 |

编译侧的三个脚本在 `tools/qwen35/`：`convert.sh`（带容器补丁自检）、
`driver.sh`（权重到齐即开编）、`prune_npz.sh` 与 `verify_pieces.sh`（磁盘与截断）。

为什么要绕开 HTTP：调度器可能晚一点准入请求、也可能套用它自己的 `max_tokens`，
而精度对拍要求板上回答的**正是**给进去的那些 token。测试工具
`tools/qwen35_compare.py` 的输入输出都是普通 JSON，方便直接贴进报告。

### ★★ 自己写探针时最容易犯的错：`llm_session_prefill` 是 13 个参数

```
prefill(engine, session, ids, n, pos3, n_images,
        offsets, patches, pixel_ptrs, pos_id_ptrs, pos_idx_ptrs, pos_weight_ptrs, &err)
```

`llm_session_new(engine, &err)`、`llm_session_decode(engine, session, &err)` 也都带 `err`。

参数写少（比如按直觉写成 4 个）**不会抛 TypeError**：引擎从栈上读到垃圾指针，
在 prefill 里 `terminate called after throwing an instance of 'std::bad_alloc'`。
这个报错长得像模型坏了，实际是探针的错。

**一分钟判定法**：拿**已经在生产跑的 35B** 用同一个探针跑一遍。
它也 `bad_alloc` ⇒ 探针错了，不是新模型错了。（这次就是这么排除掉的。）
正确签名照抄 `app/engine/native.py:95-135`。
