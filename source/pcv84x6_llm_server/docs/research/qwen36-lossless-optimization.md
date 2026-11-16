# Qwen3.6-35B-A3B 精度无损的底层推理优化：decode 已到访存下界，prefill 才是缺口

> 子任务 MYS-2474（父 MYS-2293）。基线 `main` `c4fb0e1`（含 PR #40），
> 分支 `research/qwen36-lossless-optimization`。
> 本文只做分析、受控探针与实测：**未改引擎、未改 bmodel、未改权重、未改默认值、
> 未 bump 版本、未合并、未发布**。
> 所有数字在 `10.42.0.242`（CV84X6，libsophon 0.4.15）实测，模型为自编译
> `Qwen3.6-35B-A3B` 128k，md5 `3c8fb31702ad752ddcdb3f84e24d43b8`
> （`qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel`）。
> 复现脚本见 [`../../analysis/prefill_scaling.py`](../../analysis/prefill_scaling.py) 与
> [`../../analysis/README.md`](../../analysis/README.md)，原始输出见本文各表的「原始」引用。
>
> **后续修正（MYS-2477）**：§5.1/§6A 的 123 ms 是把其他小 memset 成本混入 FA 清零所得的错误估算。
> 实现后按 128 MiB memset 逐次计时及独立 A/B 复测，实际固定节省为 **43.8 ms/会话**；详见
> [`fresh-prefill-fa-state.md`](fresh-prefill-fa-state.md)。保留原始研究推导供追溯，性能引用以后者为准。

## 0. 结论先行

1. **decode 已经没有无损空间了：它跑到了访存下界的 91–92%。**
   一个 decode token 必须搬 **2.898 GiB** 权重（30 线性层 + 10 FA 层按 MoE
   8/256 稀疏 + `lm_head` 的 1017.1 MB）。用 `lm_head` 单图实测出的
   **101.4 GB/s** 作为这台板子可达的密集流带宽，地板是 **30.68 ms/token**；
   实测 **33.19 ms/token（30.13 tok/s）**。剩余 8% 不是「某个算子慢」，而是
   密集流带宽本身的上限。**任何主机侧（Python/调度/SSE/分词）改动上界 0.15%**，
   与 MYS-2457 的结论一致，本轮独立复测确认（§2）。
2. **真正的缺口在 prefill，而且它能被一个两参数的线性模型精确描述。**
   `t(N) = Σ_chunks [423 ms + 4.59 ms×L + 1000 ms×(k/2.048k 的前史)]`，
   在 N=2048/4096/6144/8192 四个点上误差 **≤1.1%**，外推到 N=131072 得 **44.1 min**，
   与台账记录的「127k 约 46 min」差 **4.2%**。这不是拟合巧合：三项分别对应
   每 layer 的固定 launch 成本、每行的专家计算、以及 O(N²) 的 history attention（§3）。
3. **长上下文的成本 76% 是 O(N²) 的 history attention，不是权重。**
   128k 冷预填充的 44.1 min 里，**2016 s（76%）** 来自 `block_kv_<i>` 随历史增长的部分，
   601 s（23%）来自每行的边际计算，只有 **27 s（1%）** 是每 chunk 的固定 launch 开销。
   顺带把一条常见设想证伪了：**把 `max_input` 从 2048 加到 16384 最多只省 24 s（1%）**，
   因为它只减少 chunk 数、不动前两项（§3.4）。
4. **prefill 不是访存受限，是计算受限 —— 与 decode 恰好相反。**
   单个线性层 prefill 419 MiB / 251.6 ms = **1.7 GB/s**，FA 层 2.1 GB/s，
   而同一个 `lm_head` 图能跑到 **98.7 GB/s**。所以 prefill 的优化方向必须是
   **算力/算子**（MoE 的 gather-dispatch、attention 的分块），不是搬数据；
   而 decode 的正相反。这两者过去被当成同一个「推理慢」问题，是本轮最重要的区分（§4）。
5. **一个 A 类无损项已定位并量化：短 prompt 首字可省约 120 ms（17%）。**
   每次 `prefill` 新建会话时，`activate(fresh)` 会对 10 个 FA 层各清零 k/v **完整 131072 槽缓冲**，
   即 **2.50 GiB/会话**（实测 memset 带宽 21.8 GB/s → **123 ms**）。用 `bmprof` 把 128 MiB 的
   memset 逐次对上（42 次 = 加载 22 + 1 会话 20；62 次 = 加载 22 + 2 会话 40，**无剩余**）。
   对 2048 行 prompt 只占 1.3%，但**对 64 行 prompt 占首字时间的 17.1%**，而短 prompt 正是
   交互式 agent 的主路径。清零范围本可只到 `history`，属低风险改动（§5.1）。
   > 注：我最初按「整轮 109 s 里 memset 共 258 ms」得出「0.24%、不做」的结论，那是把
   > 一次会话的固定成本摊到了一整轮测量上，**分母错了**。按时序重新归因后结论反转。
6. **本轮的 go/no-go（见 §6 实验卡）**：
   - **A（可做，A 类：权重与 bmodel 不变）**：§5.1 的 FA 缓冲清零范围 —— 短 prompt 首字 −123 ms，
     **本轮唯一建议落地的项**；
   - **B（需厂商/编译器，B 类）**：`block_kv` 的 O(N²) attention 分块 —— 唯一有量级收益的方向
     （76% 的成本所在），但必须先拿到算子级 trace，且求和顺序改变很可能过不了「逐 token 全等」；
   - **C（不算收益，不建议）**：合并 40 个 prefill 图为 1 个 net —— 上限仅 **1%**。

## 1. 模型与图的事实（已核实，非公式推断）

### 1.1 结构（`build35/hf/Qwen3.6-35B-A3B-int4-AutoRound/config.json`）

| 项 | 值 | 来源 |
|---|---|---|
| 架构 | `Qwen3_5MoeForConditionalGeneration`，`model_type=qwen3_5_moe` | `config.json` |
| 层数 | 40 | `num_hidden_layers`；bmodel 有 `block_cache_0..39` |
| 层类型 | **线性注意力 ×30 + 全注意力 ×10，每 4 层一个 FA**（第 3/7/…/39 层） | `layer_types`（逐层列出）；引擎 `kFaInterval=4` |
| hidden | 2048，bf16 | `hidden_size`；`lm_head` 输入 `[1,2048]` |
| 词表 | 248320 | `vocab_size`；`248320×2048×2 = 1017.1 MB` 与 `--weight` 逐字节相符 |
| MoE | **256 专家，每 token 取 8 个** | `num_experts=256`, `num_experts_per_tok=8` |
| 专家中间维 | 512 | `moe_intermediate_size` |
| 共享专家 | 中间维 512，gate 为 16-bit | `shared_expert_intermediate_size`；`extra_config` |
| FA 头 | 16 Q / **2 KV 头**，head_dim 256 | `num_attention_heads=16`, `num_key_value_heads=2` |
| 线性注意力 | 16 key 头 / 32 value 头，head_dim 128，conv kernel 4 | `linear_*` |
| **`lm_head` 是否 tied** | **否，独立** | `tie_word_embeddings: false` |
| MTP | 1 层（`mtp_num_hidden_layers=1`），**bmodel 里没有编进去** | `config.json` vs `--weight` 无 `mtp` net |

### 1.2 量化（`quantization_config.json`）

- INT4 AutoRound，`group_size=128`，`sym=True`，`packing_format=auto_round:auto_gptq`。
- **16-bit 例外层**：全部 40 层的 `mlp.gate`（路由门）与 `mlp.shared_expert_gate`
  （共享专家门）都是 `bits:16, data_type:float`；`mtp.*` 同为 16-bit。
  这与任务卡的描述一致，**本轮不改量化**。
- `w4bf16` 的含义从权重字节数与图 IO dtype 直接对上：权重存 int4（+每 128 组 2 B scale），
  计算与激活是 bf16（`input_states: bfloat16`）。

### 1.3 图的权重布局：**prefill 图与 decode 图共享权重，`embedding` 与 `embedding_cache` 也共享**

用 `model_tool --weight` 逐 net、逐 stage 累加偏移区间（原始输出已存
`analysis/raw/`，128k 与 32k 两份），得到 94 个 net 的权重字节。关键算术：

| 组合 | 字节数 | 与文件 20,638,679,040 B 之差 |
|---|---:|---:|
| 全部 94 net 的 stage-0 累加 | 43,865,333,760 | +113% |
| **40 个 decode block + `embedding` + `lm_head` + `vit`** | **20,626,341,888** | **−12,337,152（−0.060%）** |

第二条把差压到 0.06%（12 MB，量与对齐/头部/`lm_head` 的第二个 subnet 相符），
足以定性：**`block_<i>`、`block_cache_<i>`、`block_kv_<i>` 三套图的系数区是同一份**，
`embedding` 与 `embedding_cache` 也是同一份 1017.1 MB 矩阵（`tie_word_embeddings` 是
`embedding` 与 `lm_head` 的关系，不是与 `embedding_cache` 的关系）。
**这条推翻了 MYS-2457 §2.2 里「查不出共享关系」的边界**——当时是按 net 名猜的，
本轮用「总量必须等于文件大小」这个约束把它定死了。

> 仍取不到的：图内逐算子耗时、图内真实 DMA 量、`lm_head` 的两个 subnet 内部结构。
> 这些没有公开接口，见 §7。

## 2. decode：已到访存下界，只剩 8%

### 2.1 每 token 的权重搬运量

decode 只取 8/256 专家，所以每层实际读的是「密集部分 + 1/32 的专家部分」。
权重字节取自 `--weight`：

| 组成 | 每层字节 | 每 token 读取 |
|---|---:|---:|
| 线性层密集部分（attn/qkv/o/共享专家/门） | 34.78 MiB | ×30 = 1043 MiB |
| 线性层路由专家（8/256） | 12.00 MiB | ×30 = 360 MiB |
| FA 层密集部分 | 47.45 MiB | ×10 = 474 MiB |
| FA 层路由专家（8/256） | 12.00 MiB | ×10 = 120 MiB |
| `lm_head`（全密集） | 970.00 MiB | 970 MiB |
| **合计** | | **2,898 MiB = 2.898 GiB** |

**这个模型的强可证伪点**：如果 MoE 每 token 真要读全部 256 专家，每 token 是
**18.7 GB**，在 101 GB/s 下要 **185 ms**，而实测只有 33 ms。
所以「图内 MoE 确实只取 8 个专家」不是假设，是**被时间反证排除掉的**。

### 2.2 访存下界的标定：用 `lm_head` 自己

`lm_head` 是唯一一个「一次读一大块、算得极少」的图，所以它的耗时就等于
「读 1017.1 MB 要多久」，可以直接当带宽标尺：

```
graph_probe --net lm_head --stage 6 --iters 20
lm_head    submit 10.028 ms   sync 0.001 ms   total 10.029 ms
=> 1017118720 B / 10.028 ms = 101.4 GB/s
```

这个 101.4 GB/s 显著高于板级 `d2d` 实测（`bw_probe`：64 MiB 4.2 GB/s、256 MiB 11.9、
1024 MiB 22.0），因为图内访存走的是 TPU 的直接通路，不是驱动的 memcpy 通道。
**标定必须用图内路径，不能用 `bw_probe`**，否则下界会被高估 4–20 倍。

### 2.3 实测与下界对比

| 口径 | 每 token | 占 2.898 GiB 下界 |
|---|---:|---:|
| 下界（2.898 GiB ÷ 101.4 GB/s） | **30.68 ms** | 100% |
| `token_probe --stage 6 --iters 10 --lm` | **33.19 ms**（30.13 tok/s） | 108.2% |
| `decode_bench --decode 64 --runs 2` | **33.66 ms**（29.71 tok/s） | 109.7% |

`token_probe` 的原始输出（真实 40 层 launch 形态 + `lm_head`）：

```
chain        submit 14.429 ms  sync 9.390 ms  total 23.819 ms/token
chain+sync   23.104 ms
lm_head      launch 10.086 ms  sync 0.001 ms
token        chain 23.104 + lm_head 10.087 = 33.190 ms  (30.13 tok/s)
```

`decode_bench` 原始输出：

```
warmup 1: 29.86 tok/s
run 1: 64 tokens in 2.147s = 29.81 tok/s
run 2: 64 tokens in 2.162s = 29.60 tok/s
RESULT decode_tps_mean=29.71 spread=29.60-29.81 n_runs=2
TOKENS 16,13,16,13,...（两次运行逐 token 全等）
```

**结论**：decode 的 8% 余量分布在这三处，且都不可用主机侧手段回收：

| 余量来源 | 量级 | 能否无损回收 |
|---|---:|---|
| 40 次 launch 的提交与退役 | 33.19 − 30.68 = 2.51 ms | 需合并图为 1 net（B 类）；MYS-2469 已测上限 3–4%，且重编代价不成比例 |
| 主机侧全部工作 | 0.05 ms（0.15%） | MYS-2457 已测，本轮未重复；上界就这么多 |
| 降低 `lm_head` 精度 | 上限 5 ms（15%） | **C 类，改变数值，不属于「精度不变」结论**，单独立项并需逐 token 比对 |

**逐 token 全等**：`decode_bench` 两次运行的 64 个 token 完全相同；
`token_probe` 是纯图计时不产生 token。本轮 decode 侧**没有做任何改动**，所以全等是
必然的——列出来是为了确认基线本身是确定性的（argmax 融合，同输入必同输出）。

## 3. prefill：O(N²) 的 history attention 吃掉了 76%

这是本轮的主要新发现。此前 `docs/research/` 里的预填充工作都在讨论**宽度/对齐/精度**
（2394/2396/2403/2405），从没有测过**时间随长度的增长结构**。

### 3.1 单 chunk 宽度扫描（`analysis/prefill_scaling.py --rows ...`）

原始：[`analysis/raw/mys2474/prefill_scale.txt`](../../analysis/raw/mys2474/prefill_scale.txt)（repeat=2，取中位数）

| rows | chunks | ms | **ms/row** | rows/s |
|---:|---:|---:|---:|---:|
| 64 | 1 | 716.5 | 11.195 | 89.3 |
| 128 | 1 | 1017.6 | 7.950 | 125.8 |
| 256 | 1 | 1582.3 | 6.181 | 161.8 |
| 512 | 1 | 2786.3 | 5.442 | 183.8 |
| 1024 | 1 | 5139.5 | 5.019 | 199.2 |
| 2048 | 1 | 9821.1 | 4.795 | 208.5 |

**单点 2048 行 ≈ 9.82 s**，这是所有多 chunk 结果的基本单元。

### 3.2 多 chunk 与带历史的 extend

| 总行数 | chunks | 总 ms | ms/row | 原始 |
|---:|---:|---:|---:|---|
| 4096 | 2 | 20785.0 | 5.074 | [`prefill_multi.txt`](../../analysis/raw/mys2474/prefill_multi.txt) |
| 6144 | 3 | 32769.1 | 5.334 | [`prefill_6144.txt`](../../analysis/raw/mys2474/prefill_6144.txt) |
| 8192 | 4 | 45795.6 | 5.590 | [`prefill_multi.txt`](../../analysis/raw/mys2474/prefill_multi.txt) |

**ms/row 随长度上升**（4.80 → 5.59），说明有随历史增长的成本项。

用 `--tail 2048` 逐段 extend 到 16384，直接看每段耗时（原始 [`prefill_tail.txt`](../../analysis/raw/mys2474/prefill_tail.txt)）：

| call | rows | cum | ms | ms/row |
|---:|---:|---:|---:|---:|
| 1 | 2048 | 2048 | 9836.1 | 4.803 |
| 2 | 2048 | 4096 | 10835.8 | 5.291 |
| 3 | 2048 | 6144 | 11792.0 | 5.758 |
| 4 | 2048 | 8192 | 12836.0 | 6.268 |
| 5 | 2048 | 10240 | 13858.0 | 6.767 |
| 6 | 2048 | 12288 | 14955.1 | 7.302 |
| 7 | 2048 | 14336 | 16051.1 | 7.837 |
| 8 | 2048 | 16384 | 17145.2 | 8.372 |
| 9 | 2048 | 18432 | 18234.6 | 8.904 |
| 10 | 2048 | 20480 | 19327.6 | 9.437 |
| 11 | 2048 | 22528 | 20444.6 | 9.983 |
| 12 | 2048 | 24576 | 21560.2 | 10.527 |
| 13 | 2048 | 26624 | 22650.2 | 11.060 |
| 14 | 2048 | 28672 | 23711.1 | 11.578 |
| 15 | 2048 | 30720 | 24515.2 | 11.970 |
| 16 | 2048 | 32768 | 25896.6 | 12.645 |

**每增加 2048 行历史，同一宽度的 chunk 稳定多花约 1.0 s**（实测相邻差
1000/956/1044/1022/1097/1096/1094/1084/1093/1117/1116/1090/1061/804/1381），
即 **history attention 的 O(past×L)**。32768 行处已达 25.9 s/chunk，
而 2048 行处只要 9.84 s —— **2.6 倍**。这一段测到 32k（16 个 chunk），
把 §3.3 的模型验证范围从 8k 扩到了 32k。

### 3.3 两参数模型，四个点验证

单个 chunk 的耗时模型（第 k 个 chunk，长度 L）：

```
t_k = 423 ms + 4.59 ms × L + 1000 ms × k
```

- **423 ms/chunk** 固定项 = 40 层每层约 10.6 ms 的 launch 常数；
- **4.59 ms/row** 边际项 = 每行的专家计算；
- **1000 ms × k** = 第 k 个 chunk 要看的 k×2048 行历史。

累计 N 行的总耗时 = `Σ_k t_k`。**两个参数（423、4.59）由 N=64 与 N=2048 两点定出，
斜率 1000 由 §3.2 的相邻差直接读出，此后不再调参。** 四个多-chunk 总量验证：

| N | 模型 | 实测 | 误差 |
|---:|---:|---:|---:|
| 2048 | 9823 | 9821 | +0.0% |
| 4096 | 20647 | 20785 | −0.7% |
| 6144 | 32470 | 32769 | −0.9% |
| 8192 | 45293 | 45796 | −1.1% |
| **131072（外推 16×）** | **2645 s = 44.1 min** | **台账 ~46 min** | **−4.2%** |

逐 chunk 的验证更严（用 `--tail` 到 32768 的 16 个点，模型预测**当次** chunk 耗时）：

| cum | 实测 ms | 模型 ms | 误差 |
|---:|---:|---:|---:|
| 2048 | 9834.6 | 9823.3 | −0.1% |
| 8192 | 12838.1 | 12823.3 | −0.1% |
| 16384 | 17150.9 | 16823.3 | −1.9% |
| 24576 | 21560.2 | 20823.3 | −3.4% |
| 32768 | 25896.6 | 24823.3 | −4.1% |

**这是本轮最硬的证据**：两个参数、两个定标点、一个直接读出的斜率，
在 16 倍长度范围内逐点误差 ≤4.1%，且外推到 128k 后与三个月前独立记录的产品数字
（台账「127k 约 46 min」）差 4.2%。台账里「16k 约 100 s」也与 `--tail` 到 16384
的累计 107.1 s 吻合。

**误差的方向是一致的（模型总是偏快），这有物理含义**：实测斜率随历史缓慢上升
（16384 之前约 1.09 s/2048 行，之后到 1381 ms），说明 O(N²) 项在高位比线性外推更陡
——可能是 `block_kv` 在更长历史上换到了更贵的分块策略，或 KV 的 DMA 开始压到带宽。
**所以 44.1 min 应读作「乐观下界」**，真实 128k 更接近台账的 46 min 甚至更多。

### 3.4 128k 预填充的成本分解——以及一个被证伪的设想

按上面的模型拆 131072 行：

| 组成 | 秒 | 占比 |
|---|---:|---:|
| O(N²) history attention（`block_kv` 随历史） | **2016** | **76%** |
| 每行边际计算（4.59 ms × 131072） | 601 | 23% |
| 每 chunk 固定 launch（64 × 423 ms） | 27 | 1% |

**被证伪的设想：加大 `max_input`。** 直觉上「2048 太窄，加到 16k 就能快很多」。
实际算得：

| `max_input` | chunk 数 | 40 层 launch 次数 | 固定项 | 相对现状节省 |
|---:|---:|---:|---:|---:|
| 2048（现状） | 64 | 2560 | 27 s | — |
| 4096 | 32 | 1280 | 14 s | 14 s（0.5%） |
| 8192 | 16 | 640 | 7 s | 20 s（0.8%） |
| 16384 | 8 | 320 | 3 s | **24 s（1.0%）** |

**上限就是 1%**，因为它只减少 chunk 数，动不了占 76% 和 23% 的两项。
这条应该写进结论里，避免再有人把它当成大杠杆去重编 bmodel。

### 3.5 模型在高位偏快：O(N²) 比线性更陡（明确标注为观察，非结论）

3.3 逐 chunk 的误差随长度单调变大（−0.1% → −4.1%），方向一致，说明实测的
O(N²) 项在高位比「1000 ms/2048 行」的线性假设**更陡**：16384 之前平均约 1.09 s/2048 行，
28672 之后出现 1381 ms 的单步。可能的原因有三个，**本轮没有区分**：

1. `block_kv` 在更长历史上换到了更贵的分块/kernel；
2. KV 的 d2d 与 attention 的读开始压到带宽（板级 d2d 1024 MiB 实测只有 22 GB/s）；
3. 动态图的 shape 在某个长度上跨过阈值。

**这条只管方向**：44.1 min 应当读作**乐观下界**，真实 128k 更接近台账的 46 min。
要区分这三个原因必须做 32k 以上的实测（单次 44 min、独占整块板子），本轮未做。

## 4. 本轮最重要的区分：decode 是访存受限，prefill 是计算受限

同一块板子、同一份权重、同一批图，两条路径的瓶颈**相反**：

| | decode | prefill |
|---|---|---|
| 线性层单次耗时 | `block_cache_0` **0.657 ms**（submit 0.057 + sync 0.600） | `block_0` **251.6 ms** |
| 该层每 token / 每行的**必需**权重 | 46.78 MiB（密集 34.78 + 8/256 专家 12.00） | 418.8 MiB（整层，所有专家） |
| 折算有效带宽 | **74.7 GB/s** | **1.7 GB/s** |
| FA 层 | `block_cache_3` **0.710 ms**，59.45 MiB → 87.8 GB/s | `block_kv_3` **424.9 ms**，431.4 MiB → **1.1 GB/s** |
| `lm_head`（标尺） | 1017.1 MB / **10.028 ms** = **101.4 GB/s** | 同图 10.3 ms（每 chunk 一次） |
| 瓶颈 | **权重搬运**（整 token 达标尺的 92.5%） | **计算/算子**（带宽只用到 1.7 GB/s） |
| 正确的优化方向 | 降精度（C 类）、合并图（B 类，3–4% 上限） | **算子级**：MoE gather-dispatch、attention 分块（B 类） |

**读法**：decode 的单层 74.7 GB/s 与整 token 的 93.8 GB/s 都贴着 `lm_head` 的
101.4 GB/s，所以 decode 的每一层都在按「把它必须读的权重读一遍」的极限时间在跑；
prefill 的单层只有 1.7 GB/s，离同一把标尺还差 **60 倍**，说明 prefill 的时间
不花在搬权重上。**这是两条路径必须分开优化的全部理由。**

`block_0` 的 251.6 ms/call 与 `block_kv_3` 的 424.9 ms/call 来自本轮
`bmprof` 的 LD_PRELOAD 实测（原始 [`prefill_prof.json`](../../analysis/raw/mys2474/prefill_prof.json)，4 个 chunk × 40 层 = 168 次 launch）：

```
wall 109.5s, launch cpu total 45151 ms
block_<i> (prefill, L=2048): 130 calls, 248.9 ms/call
block_kv_<i> (history FA):    30 calls, 424.9 ms/call
embedding: 4 calls, 0.12 ms/call
lm_head:   4 calls, 10.3 ms/call
linear prefill 120 calls 251.6 ms/call ; FA prefill 10 calls 216.7 ms/call
```

用这些 per-call 值反推每 chunk：

```
chunk1 (无历史) = 30×251.6 + 10×216.7 = 9716 ms   vs 实测 9834 ms
chunk2+ (有历史) = 30×251.6 + 10×424.9 = 11798 ms vs 实测 10833/11792/12835 ms
```

**这解释了 3.2 的 1000 ms/2048 斜率**：有历史时 FA 层从 `block_3`（216.7 ms）
换成 `block_kv_3`（424.9 ms），差 208 ms × 10 层 = 2.08 s 的固定差，
再加上 attention 随 past 线性增长的部分。

### 4.1 prefill 的 sync 形态：不是优化点

prefill 的 `run(net,in,out)` 用默认 `wait=true`（`native/src/llm_engine.cpp:250`），
即**每层一次 sync**，而 decode 是 40 层一次。看起来像「prefill 少了 MYS-2377 的优化」。
**实测否掉了**：`bmprof` 记录 168 次 launch 对 169 次 sync，但 `sync_wait_ms` 合计只有
**3.08 ms**。也就是说 sync 返回时图已经跑完，TPU 没有在等 CPU。
把 prefill 改成批量提交不会改变 TPU 时间，**这条不做**。

## 5. 已定位的无损项与明确的否决

### 5.1 【已定位，A 类，短 prompt 首字可省约 120 ms，建议做】新会话对 FA 缓冲整段清零

每次 `prefill`（非 `extend`）都会 `activate(fresh)`，它对 40 层各 `zero(state_a/b)`
（`native/src/llm_engine.cpp:473-476`）。FA 层的 `state_a/b` 是**完整的 131072 槽 KV 缓冲**
（`history_k`/`history_v` 各 `[1,131072,2,256]` bf16），即每个 **128 MiB**，每层 k、v 各一个。

用 `bmprof` 在两次干净的跑里把 128 MiB 的 memset 全部对上（原始 [`prefill_prof.json`](../../analysis/raw/mys2474/prefill_prof.json)、[`two.txt`](../../analysis/raw/mys2474/two.txt)）：

| 来源 | 次数 | 字节 |
|---|---:|---:|
| 加载期：10 个 FA 层的 state_a/b（20）+ `block_kv` 模板 k/v（`llm_engine.cpp:618-619`，2） | 22 | 2.75 GiB |
| **每次 `prefill`（fresh）** | **20** | **2.50 GiB** |
| 每次 `extend`（`activate(fresh=false)`，不清零） | 0 | 0 |

验证：`--tail`（1 次 prefill + 3 次 extend）实测 **42 次** = 22 + 20；
两会话（2 次 prefill）实测 **62 次** = 22 + 40。**逐次对上，无剩余。**

按实测 memset 带宽 **21.8 GB/s**（5.25 GiB / 258.4 ms）折算，**每个新会话固定付 123 ms**：

| prompt 行数 | prefill 总耗时 | 清零占比 |
|---:|---:|---:|
| 64 | 721 ms | **17.1%** |
| 256 | 1582 ms | 7.8% |
| 2048 | 9821 ms | 1.3% |

- **这不是 0.24%（我最初按整轮 109 s 估算得出的错误结论）。** 对长 prompt 确实只有 1.3%，
  但**对聊天的短 prompt 是首字时间的 17%**，而短 prompt 正是交互式 agent 的主路径。
- **无损改法：按 `parked_kv` 的语义只清 `[0, history)`，不必清零整段。**
  证据是引擎自己的 `park()`：它对 FA 只搬 `[parked_kv, history)` 的新槽，
  `unpark()` 只恢复 `[0, history)`，两者都**完全不碰 `history` 之后的槽**
  （`llm_engine.cpp:432-463`）。也就是说引擎已经认定「超出 `history` 的槽无意义」，
  `activate(fresh)` 清满 131072 槽与这个判定自相矛盾。
- **引擎里那条「stale NaN in a masked lane still poisons FA」的注释是真的**，
  但它指的是**加载期**的模板内存（`:618-619` 与 `:651-654` 已经在做，**必须保留**），
  不是每个新会话都要重做。同一份 `state_a/b` 在会话之间被反复复用，
  只要每次 `fresh` 之后 `history=0` 且图按 `cur_pos` 定位写，就不会读到残留。
- **唯一要守的前提**：`fresh` 之后第一个 token 的 `cur_pos` 必须是 0。
  现有 `prefill_impl` 在 `activate` 之后立刻 `s->history = 0`，成立；
  需加断言把它变成不变量。
- **风险**：低，但有一处真实陷阱——若将来有人把 `fresh` 复用成
  「重用会话且不清 history」，残留槽会被读到。代码里必须留注释 + 断言。
- **验收**：同一 prompt 集合（含 ≥2048 长 prompt、连续多轮、快照 restore）逐 token 全等；
  64/256 行 prompt 的 TTFT 下降 ≥100 ms；`dmesg` 干净。
- **判断：建议做。** 这是本轮唯一「A 类（不动权重与 bmodel）+ 收益可测」的项。

### 5.2 【明确否决，避免重复包装】加大 `max_input`

§3.4 已算出上限 **1.0%**，且需要重编 bmodel、重做精度对齐。与 MYS-2469 否决
「加深队列」的理由同构：**方向对，上限太低**。

### 5.3 【明确否决】prefill 批量提交 / 减少 sync

§4.1 实测 `sync_wait_ms` 仅 3.08 ms / 169 次。无收益。

### 5.4 【不属于本轮结论，单独立项】`lm_head` 降精度、候选词表裁剪

前者把 argmax 结果可能改掉，是 **C 类**（改变数值），必须逐 token 比对 + HF 对齐，
不能算「精度不变」；后者直接改变语义（可能漏掉裁掉的 token）。两者都**不在本报告结论内**。

### 5.5 【不做重复】q=8 时间片、队列深度、对齐调整

分别是 MYS-2468（时间片 q=8，已发布 v0.6.11）、MYS-2469（队列深度，no-go）、
MYS-2394/2396/2403/2405（预填充对齐/精度，已否决）。
本轮一项都没有重新包装。

## 6. 优先级实验卡

### 实验 A（建议落地，A 类：不动权重、不动 bmodel）：新会话只清 `[0, history)` 的 FA 缓冲

- **假设**：`activate(fresh)` 现在对 10 个 FA 层的 k/v 各清 131072 槽（2.50 GiB/会话），
  但 `fresh` 分支紧接着把 `history` 置 0，因此**逻辑上需要清零的范围本来就是 0**；
  清满整段纯属省事。改成不清（或只清 `[0,history)`）后，短 prompt 首字省约 123 ms。
- **改动范围**：仅 `native/src/llm_engine.cpp` 的 fresh-prefill 状态重置。
  不能笼统删除 `activate(true)` 的清零：`Session::restore()` 也调用它，恢复前必须清除
  上一次更长会话留下的槽位。需要把 fresh prefill 与 restore 分开处理；
  不动 scheduler、不动图、不动数值路径。
- **为什么安全**：FA 图按 `cur_pos` 定位写新 K/V，mask 屏蔽 `history` 之后的槽，
  `prefill_impl` 在 `activate` 之后立刻 `s->history = 0`。**唯一要守的前提**是
  「`fresh` 之后第一个 token 的 `cur_pos` 一定是 0」——现有代码成立，须加断言守住。
  `block_kv` 模板的加载期清零（`:618-619`）**保持不变**：那是 demo 明确要求的防 NaN 措施。
- **baseline**：64 行 / 256 行 / 2048 行 prompt 的 TTFT（本轮实测 721 / 1582 / 9821 ms）。
- **预期**：64 行 −123 ms（−17.1%），256 行 −123 ms（−7.8%），2048 行 −123 ms（−1.3%）。
  **decode 侧无变化**（本改动不碰 decode 路径）。
- **无损验收**：
  1. 同一批 prompt（64 / 256 / 2048 / 16384 行）**逐 token 全等**——argmax 融合，全等是硬指标；
  2. **连续多轮**：同一会话 prefill → decode → extend → decode，输出不变
     （这条最关键，它验证「残留旧槽不会被读」）；
  3. **快照路径**：`snapshot → restore → extend → decode` 输出不变；
  4. **会话切换**：两会话严格交替（`tools/session_bench.py`），互不污染、token 各自全等；
  5. `dmesg` 干净、无 D 状态进程。
- **回退**：改动是 `activate()` 里的几行，回退即恢复原状；也可加环境变量
  （`LLM_FA_ZERO=fresh|history`）便于 A/B，默认取新行为。
- **风险**：**低但有一处真实陷阱**——若将来有人把 `fresh` 复用成「重用会话且不清 history」，
  残留槽会被读到。必须在代码里留注释 + 断言。

### 实验 B（需厂商/编译器，B 类；唯一有量级收益，但很可能过不了「全等」）：`block_kv` 的 O(N²) attention 分块

- **假设**：128k 冷预填充 44.1 min 里 2016 s（76%）是 `block_kv_<i>` 随历史增长的 attention。
  若改成 flash-attention 式分块累加，这项应从 O(N²) 降到 O(N)，理论上把 44 min 压到 10–12 min。
- **为什么不能自己动手**：引擎只能决定「用哪个图、传多长历史」，图内部怎么算没有接口。
  现有 bmodel 里没有分块版 `block_kv`。
- **必须先拿到**：`block_kv_3` 在 4k/16k/64k/128k 历史下的**算子级 trace + DMA 量**，
  确认那 1000 ms/2048 历史确实花在 score×value 上而不是 KV 重复搬运。**没有 trace 不能开卡。**
- **最大的风险，必须提前说清**：attention 分块会改变浮点求和顺序。在 bf16 下这几乎必然让
  末位不同，argmax 在近边界 token 上会翻转 → **「逐 token 全等」大概率不成立**，
  那时本方案就只能按 C 类处理（HF 对齐 + 任务正确率 + 长上下文验证），
  **不能算进「精度不变」的结论**。因此本卡的第一问不是「能快多少」，
  而是「厂商有没有**不改求和顺序**、只改片上复用的版本」。
- **验收**（若厂商提供新图）：4k/16k/64k 三档冷预填充各 3 次取中位数；
  逐 token 输出比对；`dmesg` 干净；前缀缓存 `restore → extend → decode` 不变。
- **回退**：新图单独成 net（如 `block_kvfast_<i>`），引擎按环境变量选，**默认关闭**，
  **不替换现有 net**。

### 实验 C（不建议做，除非与 B 同批）：prefill 图合并

- **上限**：固定项 27 s / 2645 s = **1.0%**（§3.4 已算死）。
- **判断**：**不建议**。与 MYS-2469 否决图合并同理——要重编、要重做精度对齐，收益 1% 不成比例。
  列在这里是为了让后来者不必再算一遍。

### 实验 D（调研，零代码）：向厂商要 `block_kv` 的算子级数据

- 问题清单（可直接转交）：
  1. `block_kv_<i>` 在 128k 历史下的 attention 是分块累加还是一次性大矩阵乘？
     若后者，**是否有不改浮点求和顺序**的分块版本（这一问决定 B 能不能保住「全等」）；
  2. 该图在 4k / 16k / 64k / 128k 历史下的逐算子耗时与 DMA 量；
  3. prefill 图与 decode 图共享系数区已由本轮证实（§1.3），确认 `block_kv` 也在同一系数区内
     （否则加图会多占 4.3 GB）；
  4. decode 侧：`lm_head` 的 101.4 GB/s 是否已接近该图的上限，或 4-core 切分还有余量
     （这直接决定 §2 的「只剩 8%」是否成立）。
- **第一步只是问清楚**，不写代码。

## 7. 工具/接口边界

| 想要的数据 | 现状 |
|---|---|
| net 级 IO 张量、dtype、stage 阶梯、`addr_mode`、`core num` | ✅ `model_tool --info` |
| net 级权重字节、跨图共享关系 | ✅ `model_tool --weight` + 总量约束（§1.3） |
| net 级 launch/sync/拷贝耗时（真实引擎） | ✅ `analysis/bmprof.c`（LD_PRELOAD，引擎不动） |
| 单图隔离耗时 | ✅ `analysis/graph_probe` |
| 真实一 token 的 launch 形态 | ✅ `analysis/token_probe` |
| **prefill 时间随长度的结构** | ✅ 本轮新增 `analysis/prefill_scaling.py` |
| **图内逐算子耗时 / DMA 量** | ❌ 无接口（这是实验 B/D 的硬前置） |
| **`lm_head` 的 2 个 subnet 内部** | ❌ 无接口 |
| **prefill 图在 32k 以上的行为** | ❌ 本轮未测（单次 44 min、独占板子） |

## 8. 风险与边界

- **decode 的 8% 余量结论依赖 `lm_head` 的 101.4 GB/s 就是这台板子的可达上限。**
  若厂商能证明图内可达更高带宽（比如 `lm_head` 自己的 4-core 切分不理想），
  下界要下修，余量会变大。这是本报告唯一可能「过于乐观」的地方，已列入 §6 实验 D 第 4 问。
- **prefill 模型（§3.3）在 ≤32k 实测（16 个逐 chunk 点），128k 是外推。**
  逐点误差 ≤4.1% 且方向一致（模型偏快），所以外推值应读作下界。
  与台账 46 min 的 4.2% 差异是支持它的证据，不是证明。
  要在 32k 以上验证必须先接受一次 40+ min 的独占测量。
- **§1.3 的权重共享结论**用「总量差 0.06%」定性。它排除了「三套图各存一份」，
  但**不能**给出精确的共享映射（哪些 net 共用哪一段系数）。
- **合成 prompt 的可代表性问题**：`prefill_scaling.py` 用确定性散列序列而非重复单 token，
  以避免所有行路由到同一批专家、把专家流量测低（这是刻意设计，见脚本注释）。
  但它仍不是真实文本；`decode_bench` 与台账数字吻合说明量级可信，
  **单个 prompt 的绝对值仍会随内容浮动**。
- **本轮让板子卡死一次**：见 §9。根因是我的探针，不是引擎。

## 9. 样机状态与一次卡死事故（如实记录）

### 9.1 事故

第一次运行 `prefill_scaling.py` 时**段错误**。查因是我把 C ABI 的前两个参数写反了：
真实签名是 `llm_session_prefill(eng, sess, tokens, n, pos3, ...)`
（`native/src/c_api.cpp:132`），我写成了 `(sess, ids, pos, n, ...)`。
参数里的 `n` 是一个 `ctypes` 指针，ctypes 因为 `argtypes` 已声明为 `c_int`
不会报错，引擎于是按一个天文数字的行数跑 prefill，FA 图按这个位置索引 KV，
越界读 → `bmdrv_thread_sync_api` 超时 → `bdc_reg_read` oops →
`Fixing recursive fault but reboot is needed!`，进程留在 D 状态无法回收。

**注意因果顺序**：那次段错误是报错退出，但**同一版脚本随后又跑了一次**，
第二次才真正把设备打死——不是「崩了就没跑」。这里我犯的第二个错是
看到段错误后只修了参数顺序就立刻重跑，**没有先在最小用例上验证新探针**。

这与 `analysis/README.md` 记录的「graph 输入必须先清零」是同一类失效
（越界设备读在 CV84X6 上不上报、只卡死），但触发点是**行数**而不是**输入内容**，
所以那条已有告诫没能防住它。已做三件事：
1. 探针在调用前校验 `0 < n < context`，不合法直接 `SystemExit`（已验证拒绝
   `n=999999999` 和 `n=c_void_p(0x1000)` 两种形态）；
2. 参数顺序对着 `native/src/c_api.cpp` 逐个核对，写进 `analysis/README.md`；
3. 把「先跑 64 行最小用例 + 查 dmesg」写成探针纪律。

dmesg 证据（`bdc_reg_read+0x10/0x30 [bmtpu]` ×9 处、`Fixing recursive fault but reboot
is needed!`）与当时进程状态已记录在案；重启后 dmesg 计数归零。

### 9.2 恢复

- 重启后 `systemctl is-active cv84x6-llm` → `active`，
  `/healthz` → `{"ok":true,"version":"0.6.11","loaded":0}`。
- 本次开机 `dmesg | grep -cE "bmdrv_thread_sync_api|bdc_reg_read"` → **0**。
- 无 D 状态进程；内存 310 MB used / 3512 MB available。
- **未改动** `/opt/sophgo/cv84x6_llm_server`、`/data/cv84x6_llm_server` 的模型与配置，
  未装包、未改服务、未改权重、未改 bmodel。
- 所有探针产物在 `/data/tmp/mys2474/`（临时目录，可删）。

## 10. 复现

```sh
# 板上构建探针（link 板上 libsophon）
cd /data/tmp/mys2474/analysis
INC=/opt/sophon/libsophon-current/include; LIB=/opt/sophon/libsophon-current/lib
g++ -O2 -I$INC -o graph_probe graph_probe.cpp -L$LIB -lbmrt -lbmlib
g++ -O2 -I$INC -o token_probe token_probe.cpp -L$LIB -lbmrt -lbmlib
g++ -O2 -I$INC -o bw_probe    bw_probe.cpp    -L$LIB -lbmrt -lbmlib
gcc -O2 -fPIC -shared -I$INC -o bmprof.so bmprof.c -ldl

M=/data/cv84x6_llm_server/models/qwen3.6-35b-a3b-128k/qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel
L=/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so
export LD_LIBRARY_PATH=/opt/sophon/libsophon-current/lib

# 单图隔离成本（§2.2 / §4）
./graph_probe $M --iters 20 --stage 6 --net lm_head --net block_cache_0 --net block_cache_3

# 真实一 token 的 launch 形态（§2.3）
./token_probe $M --stage 6 --iters 10 --lm

# prefill 宽度扫描（§3.1）
python3 analysis/prefill_scaling.py --lib $L --model $M --rows 64,128,256,512,1024,2048 --repeat 2

# 多 chunk 与带历史 extend（§3.2）
python3 analysis/prefill_scaling.py --lib $L --model $M --rows 4096,6144,8192 --repeat 1
python3 analysis/prefill_scaling.py --lib $L --model $M --tail 2048 --total 16384

# 真实引擎的 prefill 逐层拆分（§4）
BM_PROF=1 BM_PROF_OUT=/tmp/p.json BM_PROF_CALLS=/tmp/p.csv \
  LD_PRELOAD=./analysis/bmprof.so \
  python3 analysis/prefill_scaling.py --lib $L --model $M --tail 2048 --total 8192

# decode 基线（§2.3）
python3 tools/decode_bench.py --lib $L --model $M --tokens 9700,11,220,16,13,44,25 --decode 64 --runs 2
```

**每次只跑一个探针**，每个探针前后查 `dmesg | grep -E "bmdrv_thread_sync_api|bdc_reg_read"`。
