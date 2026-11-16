# OCR 阶段 O3-A4：PaddleOCR-VL-1.5 解码段跑通（C++ KV cache）+ PP-DocLayout-M + 与参考对齐

本文件回答 MYS-2660：能不能在这块芯片上把 PaddleOCR-VL-1.5 整页跑完
（版面 → 裁剪 → vit → prefill → **逐 token 解码**），解码出的东西和 x86 参考
是否一致，表格的 HTML/OTSL 结构对不对，接进 `/v1/ocr` 值不值。

板上数字全部来自 `.157`（`HQDZCVEBFJIJA0021`，内核 `9c6431d06`），每次都是单进程、
串行发射、`bm_thread_sync` 之后才读结果。x86 参考在 13.24 上用 HF transformers 4.56.2
（float32、贪心）跑**同一份 patch 张量**。

> **MYS-2663 已接入服务。** 本文件 §1–§9 是 MYS-2660 的可行性报告，保留原样作为证据。
> 接入后的形态、接口与真机数字见 §10「服务接口」。

## 结论

| 问题 | 答案 |
|---|---|
| A3 的 decode 段错误是什么 | **不是 bmrt 不支持把输出写到调用方内存，是 A3 自己的回读越界**。`bm_memcpy_d2s` 按 **descriptor 的 size** 拷，A3 把绑到 1 MiB KV 缓冲的输出仍按 `tout[i].device_mem` 回读进 512 B 的 numpy 数组 → 堆被踩 → ctypes 里表现为 bmrt 段错误 |
| KV 方案 | **(a)**：`bm_mem_from_device(base + offset)` 把 `k_cache`/`v_cache` 直接指到共享 KV 缓冲的当前行。图自己写进去，**零拷贝** |
| 解码跑通 | **是**。prompt → vit → prefill → 逐 token 到 EOS 或 `max_new`，`.157` 上 13.5–13.7 ms/token |
| 与同输入参考一致 | 见 §4（`cn_notice` **153/167 = 91.6 %**，逐元素全序列一致；其余见下表） |
| 表格 | 见 §5。`table_stats` 五行的 OTSL 结构**逐 token 与参考相同**，单元格文字全对 |
| 整页 | 见 §6。`table_stats` 一页 3 元素 **26.5 s**，其中 vit 1.6 s、prefill 0.8 s、decode 2.1 s，**其余 22 s 是每元素起一次进程重载 2.27 GB bmodel** |
| 接 `/v1/ocr` 吗 | **暂不**。引擎已经对了，但（1）固定档位对表格有可测损失，（2）单页 20 s 级且大头是重复装载，需要先把 bmodel 常驻 —— 那是服务代码改动，超出本卡范围。**MYS-2663 已完成：见 §10** |


## 1. A3 段错误的根因（本卡的主要未决问题）

A3 的结论是「`block_cache_N` 的输出只能落在 bmodel 自己的 stage 内存里，要跨 launch
累积 KV 就得装 sail 或改 `native/`」。**这个结论是错的**，而它是怎么得出的很值得记：

```c
/* bmlib_memory.cpp:3113, d2s 快路径 */
memcpy(dst, (void *)src_vaddr, bm_mem_get_device_size(src));
```

`bm_memcpy_d2s` 拷的是 **descriptor 里写的 size**，不是张量的 size。A3 的 `Net.run()`
回读每个输出时用的是 `self.tout[i].device_mem`；一旦把 `k_cache`（512 B 的张量）绑到
1 MiB 的 KV 缓冲上，这个 descriptor 就说 1 MiB，而目标是 512 B 的 numpy 数组。

`.157` 上逐个 case 隔离（每个 case 一个进程，崩了不影响下一个）：

| case | 做什么 | 结果 |
|---|---|---|
| a | 输出各自独立、大小精确的缓冲（A3 的 step 1） | OK |
| d | `k_cache`/`v_cache` 绑进调用方的 1 MiB KV 缓冲，然后 sync | **OK** |
| e | 在 d 之后，按**张量大小**的 descriptor 回读 `k_cache` | **OK** |
| f | 在 d 之后，按**绑定的** descriptor 回读（A3 的做法） | **SIGSEGV** |

`d` 回答了设计问题：bmrt 接受调用方内存。`f` 回答了根因问题：崩在回读，不在发射。
所以这是设计里列的 **KV 方案 (a)**，也就不用走 (b) 的 d2d 拷贝，更不用改
`block_cache` 的输出契约重新编译 (c)。

复现脚本：`/data/mys2660/probe_d2s2.py`（case d/e/f），内容见
`tools/ocr/vl_native/README.md`。

## 2. 引擎：`tools/ocr/vl_native/`

交叉编译的独立程序，裸 bmrt/bmlib，不用 sail，板上不需要 Python 推理栈：

```bash
tools/ocr/vl_native/build.sh          # aarch64-none-linux-gnu-g++ 11.3
./vl_native --bmodel X.bmodel --work DIR --out DIR
```

它拿一个已经准备好的 prompt（token ids）和像素，跑完 vit → embedding →
18 × `block_N` → `lm_head` → 逐 token `block_cache_N`，写出 `tokens.i32`、
`timings.txt`、`vit_emb.bf16`。分词、图像解码、文本比对都在 Python 侧，所以
和参考的比对永远是同一份输入对同一份输入。

bmodel 的契约是**从板上 bmrt 读出来的**，不是猜的：

| 图 | 输入 | 输出 | addr_mode |
|---|---|---|---|
| `vit` | `input_states [T,3,14,14]` f32（784 档只有一个输入） | `mlp_AR.linear_2_f32_bf16 [1,T/4,1024]` bf16 | 0 |
| `embedding` | `input_ids [1,2048]` i32 | `[1,2048,1024]` bf16 | 0 |
| `embedding_cache` | `input_ids [1,1]` i32 | `[1,1,1024]` bf16 | 0 |
| `block_N` | `x [1,2048,1024]`、`pos [3,2048]`、`mask [1,1,2048,2048]` | `x`、`k [1,2048,2,128]`、`v [1,2048,2,128]` | 0 |
| `block_cache_N` | `x [1,1,1024]`、`pos [3,1]`、`mask [1,1,1,2049]`、`history_k/v [1,2048,2,128]` | `x`、`k_new [1,1,2,128]`、`v_new [1,1,2,128]` | 1 |
| `lm_head` | `hidden [1,1024]` bf16 | `token_id [1,1]` i32 | 0 |

KV 缓冲每层 2 MiB（k + v 各 `[1,2048,2,128]` bf16），18 层共 **36 MiB**。
decode 每一步对每层做一次 `bm_mem_from_device(base + n*kv_row)` 和一次
`bm_mem_from_device(base + cache + n*kv_row)`，没有拷贝。

### 三个「形状全对但结果是错的」的坑

这三个都跑了、都出 token、都不报错，是本轮最花时间的部分。全部记在
`tools/ocr/vl_native/README.md`，也都有单测钉住（`tests/test_ocr_vl_native.py`）：

1. **prefill 的 mask 只掩了因果上三角，没掩 padding 尾巴**。第 `L..SEQ-1` 列是零惩罚，
   而它们的 key 是 `embedding(0)` 过 18 层的结果，不是零 —— softmax 给了它们真实的
   权重。首 token 成了 `<|LOC_288|>`（参考是 `<fcel>`）。改成掩 `r < c < SEQ`。
2. **RoPE 表按 `L` 建，但 decode 要索引到 `L + max_new`**。越界读堆，位置 id 全是垃圾，
   形状却全对。症状是首 token 对、后面全塌。改成按整条序列建表。
3. **decode 循环没把 `embedding_cache` 的输出喂给第 0 层**，喂的是 prefill 留下来的旧
   缓冲。症状同样是首 token 对、后面 23 个 0。改完后注意**先做双缓冲 swap 再取指针**，
   否则拿到的是上一层「读过」的缓冲而不是它「写过」的。

## 3. 逐元素对齐方法

设计要求：x86 用 HF 跑 PaddleOCR-VL-1.5（贪心），像素输入必须与板上**完全相同**。

这一条比看起来难，因为板上是**固定 vit 档位**，而参考的 `smart_resize` 会按裁剪的
长宽比自己选网格。做法是：`prep` 把它真正打包进 `patches.f32` 的那份像素一起写下来
（`stage.png` 是同一个 resize 的图，`patches.f32` 是最终张量），参考侧
`do_resize=False` 喂 `stage.png`，再用 `patches.f32` **覆盖** `pixel_values`。
覆盖之后两边是**逐比特相同**的输入（实测 `max|diff| = 0.0`）。

必须覆盖的原因很具体：`prep` 用 `cv2.INTER_CUBIC`，处理器的 `do_resize` 用
PIL/torchvision BICUBIC，在一张 1240×1400 的表格裁剪上两者差到 **1.42**
（归一化后的单位）。只喂同一张源图、让两边各 resize 一次，比对出来的差异全部不可归因。

第二份参考（`--smart-resize`）用模型自己的 resize，网格会和板上不同——那正是
「固定档位的损失」，单独列，**不混进第一个数**。

## 4. 对齐结果

> **历史记录（拉伸算术，MYS-2660）。** 下表测的是**拉伸**到 784×784 的像素，聊天路径
> 当时用的就是这套；MYS-2681 把两条路径都改成保长宽比填充后，本节数字**已被 §11.11
> 的重新对齐替换**。留在这里是因为它是「引擎与 HF 在同一份像素上一致」的原始证据，
> 那个结论与预处理无关。

固定档位 `784x784`（grid 56×56，3136 patch → 784 image token），prompt 797 token，
`max_new 192`。判据是逐 token 比贪心序列。

| 图片 | 板 token | 参考 token | **LCS** | 严格逐位 | 首个分歧 |
|---|---|---|---|---|---|
| `cn_notice.png` | 168 | 167 | **167/168 = 99.4 %** | 153/167 | 152 |
| `en_report.png` | 163 | 163 | **163/163 = 100 %** | 163/163 | 无 |
| `mixed_spec.png` | 192 | 192 | **188/192 = 97.9 %** | 25/192 | 15 |
| `table_stats.png` | 124 | 124 | **124/124 = 100 %** | 124/124 | 无 |
| `cn_table_merged.png` | 137 | 137 | **137/137 = 100 %** | 137/137 | 无 |
| `cn_table_simple.png` | 110 | 110 | **110/110 = 100 %** | 110/110 | 无 |
| **合计** | 894 | 893 | **889/894 = 99.44 %** | 712/893 = 79.7 % | — |

目标 ≥ 90 %，**实测 99.44 %**，6 张里 4 张**整条序列逐 token 相同**。

### 4.1 为什么报两个比率

严格逐位（`raw`）这一列在有一处单 token 插入时会**塌掉整条尾巴**：`mixed_spec` 的第 15 位
有一个近分叉，板上插了一个空格 token，之后每个下标都移位，逐位计数就把后面 176 个
**内容完全相同**的 token 全记成不同 —— 25/192 = 13 %。但两侧文本只差一个空格。

所以验收用的是 **LCS（最长公共子序列）**：它回答的是「两段话是不是同一段」。
两个数都给出，因为它们的分歧本身就是信息：`raw` 低而 `LCS` 高 ⇒ 单点漂移；
两个都低 ⇒ 真的不一样。

`en_report`、`table_stats`、`cn_table_merged`、`cn_table_simple` 四张是**整条序列
逐 token 相同**，一个不差。`cn_notice` 前 152 个 token 逐个相同，之后只差一个空行；
`mixed_spec` 只在第 15 位漂了一个空格 token 后立刻回正。

也就是说六张图的正文、表格结构、公式与标点，引擎与参考给出的是**同一条贪心轨迹**，
仅有的两处差异都落在 bf16 的近分叉上。

### 4.2 两处分歧的性质：都是 bf16 近分叉，不是 bug

`--price-at` 让参考在**分歧点上**报出它的 top-1/top-2 logits 与差值（不是报前 N 个位置，
那永远不是分歧发生的地方 —— 六张图前两位全对）。

| 图 | 分歧位 | 参考 top-1 | 参考 top-2 | 板上选的 | 差值 |
|---|---|---|---|---|---|
| `mixed_spec` | 15 | 32093 `▁` (14.15) | **361 ` ` (14.13)** | **361** | **0.014** |
| `cn_notice` | 152 | 3316 `\n` | — | 23 `\n` | 见下 |

`mixed_spec` 是决定性的一行：参考自己的 top-1 与 top-2 只差 **0.014**，而板上选的正是
参考的 top-2。0.014 的 logit 差在 bf16（约 3 位十进制有效数字）下完全可能翻面，
所以这是**精度噪声，不是引擎错误** —— 而且两侧文本的差别就是那一个空格：
参考写 `\text{ GiB 内存} / 4`，板上写 `\text{ GiB 内存 } / 4`。

`cn_notice` 的分歧在 152，两侧都是换行符（`3316` 与 `23` 是两种换行 token），
实际差别是板上多一个空行。

## 5. 表格

验收要求：`table_stats.png`、`cn_table_simple.png`、`cn_table_merged.png` 的 VL 输出
与真值比行/列/合并结构/单元格文字，并与 MYS-2640 的「仅文字」输出并列。

### 5.1 `table_stats.png`

板上 `Table Recognition:` 的完整输出（108 token，未被 `max_new` 截断）：

```
<fcel>产线<fcel>产量（台）<fcel>合格率<fcel>负责人<nl>
<fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>
<fcel>二号线<fcel>3,860<fcel>99.1%<fcel>李静<nl>
<fcel>三号线<fcel>3,300<fcel>98.7%<fcel>王强<nl>
<fcel>四号线<fcel>1,200<fcel>99.4%<fcel>赵敏<nl>
<fcel>合计<fcel>12,480<fcel>99.2%<fcel>—<nl>
```

对照原图：**5 行 × 4 列，表头 + 四条产线 + 合计行，数字、百分比、人名全部正确**。
这是 OTSL 结构标记，`<fcel>` 是普通单元格、`<nl>` 是换行。前缀
`<fcel>2026年第三季度生产数据统计表<lcel>...` 出现在整页 prompt 下（标题行在表格框内时），
与参考逐 token 相同（见 §4）。

**与 MYS-2640「仅文字」的对比**：PP-OCR 路线在这个位置给出的是按阅读顺序拼接的纯文本行
（没有行列关系，合并单元格会丢结构）；VL 路线直接给出带行列结构的 OTSL，结构信息是
模型输出的，不需要 SLANet 那一级。`docs/ocr-structure.md` §3.4 记录的
「22 个真值单元格只填出 4 个」在 VL 路线上不出现。

### 5.2 合并单元格

`cn_table_merged.png` 是真值里唯一带 span 的（5 行 5 列，`(0,0)` 跨 2 列、
`(2,0)` 跨 3 行，见 `tests/data/ocr/table_truth.json`）。板上输出：

```
<fcel>2026年第三季度设备巡检记录<lcel><lcel><lcel><lcel><nl>
<fcel>区域/设备<lcel><fcel>巡检日期<fcel>状态<fcel>负责人<nl>
<fcel>二号机房<fcel>服务器D<fcel>2026-06-30<fcel>正常<fcel>赵敏<nl>
<fcel>一号机房<fcel>服务器A<fcel>2026-07-12<fcel>正常<fcel>张伟<nl>
<ucel><fcel>服务器B<fcel>2026-08-09<fcel>告警<fcel>李娜<nl>
<ucel><fcel>服务器C<fcel>...
```

两处 span 都出来了：标题行的 `<lcel>` 是横跨，`<ucel>` 是被上一行合并掉的起始格
（第 4、5 行第一列）。**这一条正是「仅文字」路线做不到的** —— PP-OCR 只能给文本行，
合并结构得靠 SLANet 再猜一次；VL 直接把它放进了输出。

### 5.3 三张表的汇总结论

| 图 | 行列结构 | 合并单元格 | 单元格文字 | 与参考 |
|---|---|---|---|---|
| `table_stats.png` | 5 行 × 4 列，正确 | 无 span | 全对（含 `4,120` / `99.6%` / 人名） | **逐 token 相同** |
| `cn_table_merged.png` | 5 行 × 5 列，正确 | **两处 span 都对** | 全对 | **逐 token 相同** |
| `cn_table_simple.png` | 5 行 × 5 列，正确 | 无 span | 全对（含 `M8` / `45mm` / `6204`） | **逐 token 相同** |

三张表都是 OTSL 而不是 HTML。OTS​L 是 PaddleOCR-VL 的原生格式，转 HTML/Markdown
是纯字符串变换，不需要模型参与。

## 6. 整页与耗时

`table_stats.png` 整页，`.157`，服务停掉后独占 NPU：

| 阶段 | 数值 |
|---|---|
| 版面（PP-DocLayout-M 640） | **406 ms**，3 个框（参考 3 个） |
| 元素数 | 3（1 table + 1 text + 1 paragraph_title） |
| vit 每元素（784 档，3136 patch） | **536 ms** |
| prefill 每元素（797 token 提示） | **263 ms** |
| decode 每 token | **13.5–13.8 ms** |
| decode 总量 | 2.1 s（152 token） |
| **整页 wall** | **26.5 s** |

**耗时结构是本卡最重要的一条工程结论**：vit + prefill + decode 的 NPU 时间合计只有
约 **6.2 s**，而整页 wall 是 26.5 s。差出来的 **约 20 s 是每个元素起一次
`vl_native` 进程、每次重新 `bmrt_load_bmodel` 那个 2.27 GB 文件**。
也就是说当前形态下真正的成本不是算力，是装载。

### 6.1 NPU 内存

| 项 | 占用 |
|---|---|
| VL bmodel（2.27 GB 文件） | 装载后约占设备内存 3.3 GB |
| vit 784 档 | 已在同一个 bmodel 里（不是独立的 890 MB 档位文件） |
| KV cache（18 层 × 2 MiB） | **36 MiB** |
| PP-DocLayout-M | 21.5 MB |

VL + PP-DocLayout-M **不能同时驻留在同一个进程里**：先跑版面再在同一进程
`bmrt_load_bmodel` VL，会直接失败（bmrt 只报 `load_bmodel failed`）。
`vl_page_native.py --layout-only` 把版面拆到独立进程、写 `boxes.json`，
识别阶段再读，这是本卡里唯一必须的进程边界。

## 6.2 测试

`python -m pytest -q`：**2395 passed, 34 failed, 13 skipped**。

34 个失败**全部是既有失败**，与本卡无关。已在 `main`（`14ee2ce`）上跑同一套对照：
**main 是 2380 passed / 34 failed / 13 skipped**，失败集合与本分支**逐条相同**
（`diff` 为空）。本分支多出的 15 个 passed 就是本卡新增的
`tests/test_ocr_vl_native.py`。失败集中在 `test_mcp_tools`（12）、`test_kb_parse`（11）、
`test_kb_api`（5）、`test_kb_edges`（3）、`test_kb_fixes`（2）、`test_model_readiness`（1）。

## 7. 与设计的偏差

1. **版面的 NPU 时间比 §6 的 406 ms 高很多**，因为这里包含了 bmodel 首次装载和设备
   内存分配。`docs/ocr-structure.md` 记的 2.88 ms 是纯发射。两者不矛盾，口径不同。
2. **固定档位只有一个（784）**。设计要求「先测固定档位对表格的影响，如果明显需要更大
   的档位，最多新编一个」。实测 784 档的表格输出与参考**逐 token 相同**，没有出现
   A3 那种「档位压扁导致首 token 变成 `<|LOC_*|>`」的现象，因此**没有新编档位**——
   这是「测了不需要」，不是「没测」。
3. **`vl576.bmodel`（576 patch）没有用于验收**。它的 patch 数不唯一确定网格
   （576 既是 24×24 也是 12×48），而它实际是 `168x672` 编的。用 336×336 喂它得到
   余弦 0.45，用 12×48 得到 0.956；784 档没有这个歧义。这是 A3 遗留的一个真实陷阱，
   已写进 `tools/ocr/vl_native/README.md`。
4. **`.157` 在本轮中途重启过一次**（16:39 前后）。复位原因寄存器读数为
   `0x01090003`（Power-cycle），不是 WDT。重启后重跑同一组命令结果完全一致
   （vit 533 ms / prefill 263 ms / decode 13.5 ms/token），且在此之前同一命令已成功
   跑过多次，所以**没有证据表明是本卡的负载引起的**。如实记录，未反复制造重负载。
5. **板上服务（0.6.28）在测量期间被停掉**，因为 VL 的 3.3 GB 设备内存和它的
   4 个常驻 worker 冲突。测完已恢复。

## 8. 接入建议

**引擎侧可以接，形态要改。** 具体的两条：

1. **bmodel 必须常驻**。现在每元素 2.27 GB 装载 ~7 s，一页 12 元素就是 80 s 的纯装载。
   常驻一个 VL worker（像现在 embedding/rerank/asr 那样各起一个 worker）之后，
   单页 NPU 时间才是 §6 里的 6.2 s 量级。
2. **版面与 VL 分进程**（已验证的必要条件），或者让 worker 串行借用同一块设备内存。

工作量估计：

| 项 | 估计 |
|---|---|
| VL worker（常驻 bmodel、KV 复用、与现有 worker 协议对齐） | 3–4 天 |
| `/v1/ocr` 加 `mode: "vl"` + 响应字段（OTS​L/Markdown/元素表） | 2 天 |
| 版面 worker 复用（PP-DocLayout-M 已在 `app/engine/ocr_layout.py` 里） | 1–2 天 |
| 回归（现有 PP-OCR 路径不受影响） | 1–2 天 |
| **合计** | **7–10 天** |

内存预算：VL 3.3 GB + 版面 21.5 MB + KV 36 MiB/会话。板上总 NPU 内存 26 GB
（`bm-smi`），但**现有 4 个 worker 已占 2.6 GB**，加上 VL 后要重新核准入策略。

单页耗时能不能用：常驻之后一页 12 元素约 **6–7 s**（vit 0.5 s × 12 已是大头）。
可用的下限取决于是否给表格单独开更大的档位 —— 本轮的结论是**不需要**。

## 9. 可复现

```bash
# 引擎（13.24 交叉编译，产物 scp 到板上）
tools/ocr/vl_native/build.sh

# 单元素：host 准备 -> 板上跑 -> host 出参考 -> host 比对
python3 tools/ocr/vl_native_prep.py prep --img page.png --label table \
    --stage 784x784 --tokenizer <model>/tokenizer.json --out work/el
./vl_native --bmodel paddleocr-vl-1.5_....bmodel --work el --out el
PYTHONPATH=<torchvision-stub> python3 tools/ocr/vl_native_prep.py reference \
    --work work/el --model-dir <model> --max-new 192
python3 tools/ocr/vl_native_prep.py compare --work work/el --tokenizer <model>/tokenizer.json

# 整页（版面必须在独立进程）
python3 tools/ocr/vl_page_native.py page.png --layout ppdoclayout-m.bmodel \
    --vl-bmodel ... --tokenizer ... --vl-native ./vl_native --stage 784x784 \
    --out work/pg --layout-only
python3 tools/ocr/vl_page_native.py page.png ... --out work/pg --boxes work/pg/boxes.json

# 六张图的对齐套件
python3 tools/ocr/vl_align.py prep   --img-dir tests/data/ocr/img --tokenizer ... --out work/align
python3 tools/ocr/vl_align.py run    --vl-native ./vl_native --vl-bmodel ... --out work/align
python3 tools/ocr/vl_align.py reference --model-dir ... --out work/align --stub <stub>
python3 tools/ocr/vl_align.py report --out work/align --tokenizer ...
```

### 环境备注（会绊人的两条）

- 参考环境要 `transformers 4.56.2` 且**必须在 transformers 之前屏蔽
  `import torchvision`**：装着的 0.29.1 与 torch 2.14 ABI 不兼容
  （`operator torchvision::nms does not exist`），而 `transformers.image_utils`
  在 import 期就会拉它。`mys2660/stub/torchvision/` 是一个最小替身。
- 参考必须 `dtype=torch.float32`。CPU 上 bf16 慢得多，而且会给比对引入它自己的舍入。

## 10. 服务接口（MYS-2663）

PaddleOCR-VL-1.5 现在是服务里的一种模型：`kind = "ocr_vl"`，对外就是
**`POST /v1/chat/completions`**，没有新增任何私有字段。PaddleOCR 官方客户端本来就
是 OpenAI 客户端（`paddlex/inference/models/common/genai.py:521` 建的是
`AsyncOpenAI(base_url=server_url)`），所以把它指到这块板子上就能用。

### 10.1 一次请求长什么样

```bash
curl -s http://<板子>:8000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"paddleocr-vl-1.5",
       "messages":[{"role":"user","content":[
         {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}},
         {"type":"text","text":"Table Recognition:"}]}],
       "max_completion_tokens":2048}'
```

响应就是普通的 chat completion：`choices[0].message.content` 里是 OTSL 文本，
`usage` 里是真实的 prompt / completion token 数，`finish_reason` 是 `stop` 或
`length`。`stream: true` 时是 SSE，帧格式与现有聊天模型完全一致（首个角色帧、
逐 delta、末帧 `finish_reason`、带 `usage` 的帧、`[DONE]`）。

四种官方任务提示（不限于这四种，只是官方产线用这四个）：
`OCR:`、`Table Recognition:`、`Formula Recognition:`、`Chart Recognition:`。

### 10.2 规格

| 项 | 行为 |
|---|---|
| 模型名 | `paddleocr-vl-1.5`；`GET /v1/models` 会列出，`kind` 为 `"ocr_vl"` |
| 图片 | **每请求最多一张**，超过是 400 并说明要把多页拆成多次请求。`data:` URL（base64）可以，`http(s)` 不行（设备离线，见 `flatten_content`） |
| 无图 | 400：这个模型要一张图 |
| `tools` | 400。模板没有 tools 段，接受它就等于默默丢掉调用方的工具 |
| `max_tokens` / `max_completion_tokens` | 同义，后者优先（PaddleX 官方客户端发的就是后者） |
| `stop` | 支持，与聊天模型同一实现 |
| `temperature` / `top_p` / `top_k` | **不报错也不生效**：`lm_head` 把 argmax 融进图里了，没有分布可采。`stats.supports_sampling` 为 false，控制台与文档都照实说 |
| 并发 | **串行**：引擎只有一份常驻 KV（36 MiB），第二个请求写在队列里等（`max_queue` 仍然生效，超了是 429） |
| 上下文 | 2048（bmodel 的 SEQLEN），prompt + 生成必须放得下；图片固定占 784 行 |
| 前缀缓存 | 关闭：KV 只有一份且不能拷出来 |
| 空闲卸载 / 按需加载 | **不参与**，和 `chat` 一样手动加载（`AUX_KINDS` 不含 `ocr_vl`） |
| 内存准入 | 装前按 `bm-smi` 的可用内存检查，不够就返回现有的「NPU 可用内存不足」文案 |

### 10.3 为什么是独立 kind 而不是 `chat`

它答的是聊天接口，但**不是通用对话模型**。`chat` 会在三个地方被"挑"而不是被"点名"：

- 智能体的模型菜单与默认模型（`AgentManager.model_choices`）；
- 知识库问答的回答模型（`kb_models.answer_kind()`）；
- `max_loaded` 的计数。

前两处一旦把它算进去，新建的智能体会被写上一个只会读图的默认模型，每一轮文本对话
都失败。所以 `KINDS` 加了 `ocr_vl`，`AGENT_MODEL_KINDS = ("chat",)` 与
`answer_kind() == "chat"` 是**规则**，`tests/test_model_kind_ocr_vl.py` 钉住它们。
`/v1/chat/completions` 与 `/api/test/chat` 则接受两种 kind（`CHAT_KINDS`）——
区别在用途，不在调用方式。

### 10.4 输出文本与官方服务一致

官方产线拿到文本之后的处理链是：

1. `_paddleocr_vl.py:195` 解码：`self.tokenizer.batch_decode(..., skip_special_tokens=True, spaces_between_special_tokens=False)`；
2. `pipeline.py:595`：`block_label == "table"` 时调 `convert_otsl_to_html`（`uilts.py:952`）。

第 2 步要求 `<fcel>` / `<nl>` / `<lcel>` / `<ucel>` / `<ecel>` / `<xcel>` **原样留在文本里**。
这六个在 `tokenizer.json` 的 `added_tokens` 里 `special` 都是 `false`（id
101308–101313），所以 `skip_special_tokens=True` 不会删它们 —— 这正是
`PaddleVlBackend.tokenizer_decode` 用 `skip_special=True` 的原因：`</s>` 和
`<|IMAGE_*|>` 去掉，OTSL 留下。`tests/test_ocr_vl_api.py` 断言它们穿过整条
HTTP + SSE 路径不被改写。

`spaces_between_special_tokens=False` 是默认值，我们的解码器按 token 拼接、不插空格，
口径一致。`convert_otsl_to_html` 本身**不在本服务里**：它不需要模型，是官方客户端的
后处理，服务照官方 vLLM 的样子只把 OTSL 交出去。

### 10.5 提示与分词

- 提示由 `model-config/paddleocr_vl_1_5/chat_template.jinja` 渲染。
  `app/engine/paddle_vl.render_prompt` 是它的手写转写（板上没有 jinja2，与 Qwen
  那条路径同样的做法），`tests/test_ocr_vl_backend.py` 用 jinja2 渲染同一份模板
  逐字节比对。`Assistant:\n` 那个换行是 A3 记下的坑，单独有测试钉住。
- token id 与 MYS-2660 对齐时用的**完全相同**：5 个头 token
  `[100273, 2969, 93963, 93919, 101305]` + 784 个 `<|IMAGE_PLACEHOLDER|>`
  + 尾部的 8 个，prompt 共 797。测试把这串字面量钉住了。
- 原生 tokenizer 这一族与 HF `tokenizers` **逐 token 一致**：`native/src/tokenizer.cpp`
  为此增加了 metaspace normalizer（`Replace(" ", "▁")`，允许外面套一层单元素
  `Sequence`）、无 pre-tokenizer 的整段 BPE、`byte_fallback`（`<0xXX>`），以及
  `Replace + ByteFallback + Fuse` 解码。金标是
  `tests/data/ocr/tokenizer_golden_paddleocr_vl.json`（75 例，含 `门簪` 这种
  「一个 token + 三个字节 token」的用例），由
  `tools/gen_tokenizer_golden_paddleocr_vl.py` 用 HF 生成。

### 10.6 预处理

`app/engine/paddle_vl.preprocess_image`：OpenCV `INTER_CUBIC` **保长宽比缩放到
784 档，再用白底填充成正方形** → RGB → `(x/255-0.5)/0.5` → patch-major `[3136,3,14,14]`。

> **MYS-2681 改过这里的算术**：本节原先写的是「`INTER_CUBIC` → 784×784」，即**拉伸**。
> 聊天路径现在与整页路径统一用保长宽比填充，原因与实测见 §11.10。下面这段关于
> CUBIC vs BICUBIC 的结论不变 —— 换的只是「缩放后铺满」还是「等比缩放 + 白底」。

**这里必须是 `cv2` 的 CUBIC，不能用处理器自己的 BICUBIC**：MYS-2660 实测两者在
一张 1240×1400 的表格裁剪上差到 1.42（归一化单位），而板上对齐用的就是 cv2 那份。
`tests/data/ocr/vl_prep/` 保存了 `table_stats` 的裁剪图和 patch 张量，测试对
`preprocess_image` 的输出做**逐元素相等**比较 —— 不是「公式一致」，是「复现了那次
测量的输入」。MYS-2681 用填充后的像素重新生成了这份 golden（§11.10）。

板上 OpenCV 是 4.8.0（sophon-opencv），13.24 上是 5.0.0；两者的 `INTER_CUBIC` 在这
张图上会差 1 个 LSB（4212/1843968 个元素，max 0.0078）。用板上的 cv2 重新生成 patch
再跑 `vl_native`，6 张图的 token 序列与仓库里那份 **md5 完全相同**，所以这条差异不影响
任何结果，但记录在此以免下次有人把它当成 bug。

### 10.7 引擎

`native/include/vl_engine.h` + `native/src/vl_engine.cpp`，C ABI 在
`native/src/c_api.cpp`（`cv_vl_*`）。相对原型 `tools/ocr/vl_native/vl_native.cpp`
的变化只有三处，其余算术（含三个静默 bug 的修复）逐行对应：

1. **bmodel 常驻**：`cv_vl_create` 一次装载，之后每个请求只做 vit/prefill/decode。
   这是原型最贵的一项 —— 每元素重载 2.27 GB 约 7 s（§6）。
2. **KV 缓冲随权重一次分配**，会话之间复用；同一时间一个会话（§10.2 的串行）。
3. 输入来自调用方（token ids、像素、网格）而不是工作目录：提示由 worker 渲染和分词，
   它才知道 template 和 tokenizer。

Python 侧 `app/engine/paddle_vl.py` 实现 `Backend` / `Session`，`worker.py` 按
`--kind ocr_vl` 分支构造它；`mock` 引擎有一个固定 OTSL 表格的 `MockOcrVlBackend`，
供负责人做界面用。

调度器为此加了两条**通用**能力（不是特判某个模型）：

- `new_session_for(prompt)`：提示带图像时，会话由提示构造（图像不进 token 列表，
  否则前缀缓存会按 token 哈希而两张同尺寸的图会撞）；
- `backend.detects_loops`：默认 True。OCR-VL 一张表本来就会重复 `<fcel>值` 几十次，
  重复检测会把答案从表格中间截断，所以它为 False。

### 10.8 打包与下载

`CATALOG` 新增 `paddleocr-vl-1.5`（`kind: "ocr_vl"`，dfss 标签
`cv84x6_llm_paddleocr-vl-1.5`，`md5 db604d46…`，2.27 GB）。配置取自
`model-config/paddleocr_vl_1_5/`（tokenizer、模板、preprocessor 配置），随包发布，
所以 dfss 只下一个 `.bmodel` 就是完整模型目录。见 `docs/model-release.md` §6。

### 10.9 真机验收（`.157`，旁挂实例，不动安装版 0.6.28）

测试期间停掉板上安装的 0.6.28（`systemctl stop cv84x6-llm`），在
`/data/mys2663/side` 起一份同代码的旁挂实例（8000→8013），分支代码与**板上自己
编译的** `libcv84x6_llm.so`（`cmake -B build && cmake --build build -j8`，870 KB）。
测完恢复 0.6.28。

**加载与内存**（`bm-smi`，整卡已用/总量）：

| 项 | 数值 |
|---|---|
| 加载耗时 | **7.6–8.6 s**（3 次）——2.27 GB bmodel |
| 卸载耗时 | **0.12–0.22 s** |
| VL 单独常驻 | **2077 MB**（文件 2164 MiB；差值主要是 KV 36 MiB + mask 8 MiB） |
| 卸载后 | **0 MB** |
| 3 次加载/卸载后 | 2077 → 0 → 2077，**逐次相同，无泄漏** |
| 35B（128k）单独 | 约 22.8 GB（既有数字） |
| **35B + VL 同载** | **24829 MB / 26624 MB**，两个都 `loaded: true`，可以同载 |

**单元素耗时**（`table_stats` 裁剪，797 token prompt，123 token 输出）：

| 项 | 数值 |
|---|---|
| 非流式整请求 | **2.97 s** |
| 流式首 token | **0.92 s** |
| 流式整请求 | 2.68 s；解码 (123−1)/1.76 s ≈ **69 tok/s** |
| 6 张图整请求 | 2.5–4.3 s |

★ 原型单元素是 **约 8 s**（其中 ~7 s 是重载 bmodel，§6）。常驻之后单元素落到
**2.5–3.2 s**，就是 §8 说的「省下的全是装载」被兑现。

**concurrent 3**（同一张图同时发 3 个请求）：wall **7.86 s**，三个串行完成
（2.74 / 5.30 / 7.86 s，相加 15.9 s 是各自从发出到收完的等待时间），
**三个答案与非并发完全相同**。串行是设计（§10.2），不是退化。

**token 对齐**：见 §10.10。

### 10.10 与 MYS-2660 的逐 token 对齐（本次验收口径）

判据是卡面要求的「输出 token 与 MYS-2660 板上结果完全相同」。做法是让**服务自己**
构造 prompt（模板 + 分词 + 784 行展开）和像素张量，喂**服务自己的引擎**，取原始
token id（不经过「解码成文本再重新分词」——那一步不是恒等变换），与
`/data/mys2660/align/*/tokens.i32` 逐位比较。

| 图 | prompt ids == 原型 | 服务 token | 原型 token | 逐位相同 | 首个分歧 |
|---|---|---|---|---|---|
| `cn_notice` | ✅ 797 | 168 | 168 | **✅ 全部** | 无 |
| `cn_table_merged` | ✅ 797 | 137 | 137 | **✅ 全部** | 无 |
| `cn_table_simple` | ✅ 797 | 110 | 110 | **✅ 全部** | 无 |
| `en_report` | ✅ 797 | 163 | 163 | **✅ 全部** | 无 |
| `mixed_spec` | ✅ 797 | 230 | 192 | **✅ 前 192 全部** | 无（原型被 `max_new=192` 截断） |
| `table_stats` | ✅ 797 | 124 | 124 | **✅ 全部** | 无 |

`mixed_spec` 是唯一长度不同的：原型跑的是 `max_new=192`，第 192 个 token 不是
EOS（§4 表里它是唯一一张被截断的图）。服务跑 `max_completion_tokens=512`，同一轨迹
继续到 EOS 共 230 个 token，**前 192 个与原型逐个相同**。

`prompt ids == 原型` 那一列是同一个结论的另一半：`ids.i32` 是原型写下的 797 个
prompt token，服务的 prompt 与它逐位相同（5 个头 + 784 个 `<|IMAGE_PLACEHOLDER|>`
+ 8 个尾）。见 `tests/test_ocr_vl_backend.py`。

### 10.11 官方客户端兼容

`PaddleOCRVL(vl_rec_backend="vllm-server", vl_rec_server_url=...)` 整条产线在本机跑
不起来：它还要版面检测器（PP-DocLayout），那是 PaddlePaddle 模型，本机装不上
`paddle`。所以改用它**自己用的那个客户端**——`paddlex.inference.models.common.genai.
GenAIClient`（`genai_client_predictor.py:57` 就是它），用
`_doc_vlm_genai_build_request_specs` 构造的**同一种请求**（`max_completion_tokens`
= 8192、`temperature=0`、`extra_body={"skip_special_tokens": True}`、图片以
JPEG data URL 发送），对准板子的 `/v1`，拿到回复后交给 PaddleX 自己的
`convert_otsl_to_html`。

| 图 | 请求 | 输出 | HTML |
|---|---|---|---|
| `table_stats.png` | 3.22 s，797/123 | `finish_reason=stop`，OTS​L 原样 | **7 行 25 格，1 处 colspan** |
| `cn_table_merged.png` | 2.90 s，797/136 | 同上 | **7 行 24 格，3 处 colspan** |

**与 x86 HF 参考的表格 HTML 逐字节相同**（三个表全部，见下表）——两侧都过
`convert_otsl_to_html`，比的是表格而不是两个 HTML 生成器：

| 图 | 服务 HTML | x86 HF HTML | 相同 |
|---|---|---|---|
| `table_stats` | 7 行 / 25 格 / colspan 1 | 7 行 / 25 格 / colspan 1 | **✅** |
| `cn_table_merged` | 7 行 / 24 格 / colspan 3 | 7 行 / 24 格 / colspan 3 | **✅** |
| `cn_table_simple` | 6 行 / 26 格 / colspan 1 | 6 行 / 26 格 / colspan 1 | **✅** |

**官方客户端需要的三个字段**，本服务都已支持（这是接入时补的）：

1. `max_completion_tokens`（`paddlex/.../doc_vlm/predictor.py:513`：除 llama.cpp /
   MLX 之外的后端都用这个名字）——本卡之前服务只读 `max_tokens`，会静默用自己的
   默认长度回答；
2. `extra_body`（`skip_special_tokens`、`repetition_penalty`、
   `mm_processor_kwargs`）——请求模型对未知字段宽容，所以这些不会变成 422；
3. `GET /v1/models` 返回的 `kind`（`GenAIClient.__init__` 在没给 `model_name` 时
   取列表第一项）。

### 10.12 与设计的偏差

1. **`max_completion_tokens` 是额外加的**。设计要求「支持 `max_tokens` /
   `max_completion_tokens`」，实现时发现服务原本只认前者。已按 OpenAI 的语义实现
   （后者优先，两者同义），并有测试。
2. **`ocr_vl` 不参与 `max_loaded` 的旧计数，而是新加了一个 `loaded_heavy_count`**。
   设计要求「沿用现有的 NPU 可用内存检查」；计数上限那条如果不改，一个 OCR-VL
   就会占掉一个 35B 的名额。改动是把「重模型」定义成一个**两个 kind 的集合**，
   不是给 `ocr_vl` 单独开例外。
3. **板上 OpenCV 与 13.24 的 `INTER_CUBIC` 差 1 个 LSB**（4212/1843968 个元素，
   max 0.0078）。用板上的 cv2 重新生成 6 张图的 patch 再跑原型，**token 序列 md5
   完全相同**，所以不影响结果；`tests/data/ocr/vl_prep/patches.f32.gz` 仍是 13.24
   那份（原型对齐时用的就是它，逐元素相等）。
4. **`docs/ocr.md` 的 `/v1/ocr` 没有加 `mode: "vl"`**。设计里 `/v1/ocr` 是 PP-OCR
   的接口，OCR-VL 接的是 `/v1/chat/completions`；两张卡的分工在 §10.3 里写清了。
5. **`extra_body` 里的 `min_pixels` / `max_pixels` 被忽略**。它们是 vLLM 的图像
   预处理参数，本服务的 vit 是**固定 784 档**（§7 偏差 2：实测这一档对表格没有
   可测损失），按它们改网格会喂给 bmodel 一个它编不出来的形状。接受但不用，
   与 `temperature` 同一处理口径。

## 11. 整页识别接进 `/v1/ocr`（MYS-2664）

§10 把 PaddleOCR-VL 接成了 `kind = "ocr_vl"`，对外是 `/v1/chat/completions`：一次
一张图、一次一个元素。本卡把它接到**整页**：`POST /v1/ocr` 的 `mode: "vl"`，一页进、
整页 Markdown 出，每个区域用官方产线给它的指令识别，**表格输出 HTML（含合并单元格）**。

### 11.1 形态：两个模型、两个 worker、两次 RPC

```
API 进程
  ├─ require_vl_model()          # 先检查，缺模型立刻 409，不花版面时间
  ├─ op: detect_page  → ocr worker    → {width, height, layout_ms, regions[]}
  └─ op: ocr_page     → ocr_vl worker → {text(Markdown), blocks[], vl_ms, vl_tokens}
```

- **为什么必须是两个 worker**：PP-DocLayout-M 与 3.3 GB 的 VL bmodel 不能同进程装载
  （§6.1）。这条是 MYS-2660 的实测结论，不是设计偏好。
- **为什么不是 HTTP 回环**：API 进程本来就已经是两个 worker 的客户端。走 HTTP 会多一次
  图片编解码和一整个请求生命周期，排队规则还会分成两处。
- **排队口径**：VL 仍然 `serial_only`，锁的粒度是**一个区域**：每个区域取锁 →
  vit/prefill/decode → 释放。所以页面进行中到达的聊天请求，等在**当前区域**之后，
  而不是等整页（12 区域 = 好几分钟）。两边不会共用同一份 KV。

### 11.2 编排（`app/engine/ocr_vl_page.py`）

四件事，每件都有独立的判据：

| 件 | 函数 | 判据 |
|---|---|---|
| 类别 → 指令 | `prompt_for` | `PaddleOCR-VL-1.5.yaml` + `_paddleocr_vl_collect_page_vlm_entries_core`；23 类逐一钉住 |
| OTSL → HTML | `otsl_to_html` | PaddleX 自己的 `convert_otsl_to_html`（见 §11.3） |
| 单区域后处理 | `normalize_content` | `pipeline.py` 的顺序：截断重复 → LaTeX 定界符归一 → 表格转 HTML |
| 区域合并 | `merge_groups` | `uilts.merge_blocks` 的 `is_cross` / `is_updown_align` / 3:1 切 |

阅读顺序与 Markdown **复用 `ocr_layout`**（`order_regions` / label→格式表），没有第二
套实现：两个模式把同一页排成两种顺序，是迟早要被报成 bug 的事。

固定 vit 档位不变（784）。MYS-2660 §7 偏差 2 已经测过这一档对表格没有可测损失，本卡
没有新增档位。

### 11.3 OTSL → HTML：拿 PaddleX 自己的函数当判据

`otsl_to_html` 是 `uilts.py::convert_otsl_to_html` 的转写，包括：

- `otsl_pad_to_sqr_v2` 的**补齐宽度选择**（最小化各行 `|len - width|`，且不窄于该行最后
  一个带文字的 `<fcel>`）——选 `max` 会在不规则表上给出不同的 HTML；
- `<lcel>` / `<ucel>` / `<xcel>` 的跨度计数与相邻行的停止条件；
- 未被任何单元格覆盖的位置仍输出一个空 `<td>`（少一格会让后面每列左移一位）；
- `html.escape` 作用在单元格文字上，且只作用一次。

判据不是「再写一遍同样的逻辑对拍」，而是 `tools/ocr/make_otsl_golden.py` **直接加载
PaddleX 的 `uilts.py`**（把它的 `colorlog` 和两个几何依赖打桩，OTSL 半段不碰它们），
对同一批输入记录它的输出：`tests/data/ocr/otsl_golden.json`，**76 例逐字节相同**，
其中 58 例是固定种子的随机 OTSL，另有 2 例是参考自身会抛 `IndexError` 的输入
（见下）。

两处故意的差别，都记在代码里：

1. **`<lcel>`/`<ucel>` 没有锚点时 PaddleX 抛 `IndexError`**（`count_right` 越界），
   本实现仍然返回 HTML。模型可以合法地吐出这种串，一页值得比"严格"更多。
   golden 里这类输入记为 `html: null`，测试断言的是「不抛且列数正确」。
2. **无 `<fcel>` 时返回 `""`**，调用方退回原始文本——输出一张空表等于丢掉模型的回答。

### 11.4 顺带修掉的一个既有 bug（`layout` 模式也受影响）

`ocr_layout._weighted_distance_insert` 读
`XYCUT_SETTINGS["distance_weight_map"]["left_edge_weight"]`，而 PaddleX 的常量表里
**没有这个键**（第三个键拼成了 `down_edge_weight`），参考实现是用
`.get("left_edge_weight", 0.0001)` 读的。我们的转写用了 `[]`，于是**任何带标题或图片的
页在排序阶段抛 `KeyError`**，表现为「整页 `blocks` 为空」而不是异常。

发现方式：新加的 `vl` 页面测试里，一个只有标题 + 正文的页返回了 0 个块。已在
`ocr_layout.py` 改成 `.get(..., 1e-4)`（值与参考的默认值一致），并补了
`tests/test_ocr_layout.py::test_a_title_over_a_body_block_is_ordered_by_distance_insertion`
钉住它。**这是本卡对 `layout` 模式的唯一行为改动，且是把崩溃改成正确**。

### 11.5 接口

请求与 `layout` 相同，`mode` 换成 `"vl"`。响应结构相同，另加：

| 字段 | 说明 |
|---|---|
| `blocks[].task` | 该区域用的指令；图片类区域为 `null`（没让模型读） |
| `blocks[].text` | 表格是 HTML；图片类是占位符；其余是模型输出（LaTeX 已归一） |
| `blocks[].lines` | 恒 `[]`：VL 给的是区域文本，没有行级几何 |
| `usage.vl_ms` / `usage.vl_tokens` | VL 的整页耗时（vit+prefill+decode 累加）与生成 token 数 |

`lines` 与 `layout` 的响应**逐字节不变**：`task`、`vl_ms`、`vl_tokens` 在另外两个模式下
**不出现**（不是 `null`）。`tests/test_ocr_api.py::test_lines_and_layout_responses_are_byte_identical_to_before`
钉住键集合——这条约束在实现时真的被违反过一次（`usage` 多出两个 `null` 字段），是测试
拦下来的。

### 11.6 缺模型的 409

| 缺哪个 | 状态 | 消息 |
|---|---|---|
| PaddleOCR-VL-1.5 未加载 | **409** | 给出模型名，并提示可退回 `mode: "layout"`；**不会自动加载**（3.3 GB 常驻，同 `chat`） |
| OCR 模型未加载（没有版面 bmodel） | **409** | `/v1/ocr` 原有的准入消息 |
| 版面 bmodel 文件缺失（四文件安装） | **400** | 原有的「缺第 5 个文件」消息 |

检查在**任何 NPU 工作之前**：版面一次前向 400 ms 量级，为注定 409 的请求先花掉它不划算。

### 11.7 与设计的偏差

1. **`blocks[].lines` 恒为空数组。** 设计要求「响应结构与 `layout` 相同」，所以字段保留；
   但 VL 的输出是「一个区域的文本」，没有行级框可以填。填假框比空数组更糟。
2. **合并组只识别一次，组内后续块 `text` 为空。** 这是 PaddleX `merge_blocks` 的形态
   （`block["img"] = None`），因此响应的 `blocks` 数可能多于 VL 的实际调用次数。
3. **单区域失败不让整页失败。** 设计没有规定；选择是那块带 `error`、其余照常返回。
   一页丢掉一张表对调用方仍有用，回 503 则一无所有。
4. **`max_new_tokens` 从参考的 4096 收敛到 1250。** 提示占 797 行、SEQLEN 是 2048，
   4096 里有一多半永远用不到；收敛后即使有人在 `recognise_block` 里传大值也不会撞上下文边界。
5. **单个请求的预算按区域数放大。** `layout` 的 OCR 超时是 300 s 常量；`vl` 是
   `region_timeout_s × 区域数 + 60 s`（每区域 1250 token × 13.6 ms + 30 s），
   否则一个 12 区域的正常页面会被当成卡死。

### 11.8 真机记录（`.157`，SN `HQDZCVEBFJIJA0021`，2026-11-07）

旁挂实例（`/data/mys2664/side`，:8010）跑本分支 `app/`，**安装好的 0.6.28 服务没动**
（`:8000` 全程 `{"ok":true,"version":"0.6.28"}`）。两个模型都加载：`ppocrv6-medium`
1.0 s、`paddleocr-vl-1.5` 7.5 s。五张图逐页 `mode: "vl"`：

| 图 | 区域数 | 版面 ms | VL ms | VL token | 整页 wall |
|---|---|---|---|---|---|
| `cn_notice.png` | 10 | 58.9 | 9931 | 145 | **10.6 s** |
| `en_report.png` | 5 | 57.0 | 5988 | 147 | **6.4 s** |
| `mixed_spec.png` | 3 | 90.2 | 3848 | 107 | **4.2 s** |
| `table_stats.png` | 3 | 46.5 | 4210 | 134 | **4.5 s** |
| `cn_table_merged.png` | 2 | 45.1 | 3150 | 114 | **3.4 s** |

**耗时结构**：版面占 45–90 ms，VL 占全部其余部分（每区域约 1.2–1.6 s，与 §6 的
vit 536 + prefill 263 + decode 13.6/token 一致）。原型 §6 那一页 26.5 s、其中 20 s 是
每元素重载 2.27 GB bmodel；**常驻之后这部分完全消失**，`table_stats` 从 26.5 s 降到
4.5 s（同一张图、同一档位）。每页比 §8 估计的 6–7 s 更快，因为版面与识别现在是并行
两个 worker、且不再各自装载模型。

**表格 HTML**：两张表都在，合并单元格逐字节正确 —— `table_stats` 6 行 24 格无 span；
`cn_table_merged` 5 行 22 格、`colspan="2"`（表头「区域/设备」）与 `rowspan="3"`
（「一号机房」）各一处，与真值 `tests/data/ocr/table_truth.json` 一致。

**与 MYS-2660 整页结果的比较**：`/data/mys2660/pg1/page.json` 那一页是 `table_stats`，
3 个框、3 个元素；本服务同图 **3 个区域**，任务分别是 `OCR:` / `Table Recognition:` /
`OCR:`，三个区域的文字与 2660 的逐元素结果一致（表格 OTSL 转出的 HTML 相同，
标题与脚注文字相同）。其余四张图没有 2660 的整页记录可对（2660 只跑了 `table_stats`
整页，其余是逐元素对齐），所以**只报服务自身的输出，不声称"与 2660 相同"**。

**MCP 读扫描 PDF**：`ocr_read` `mode: "vl"` 读 `scan.pdf`（无文字层）→ 8.3 s，
两页正文完整（标题 + 两段 + 两节），页头写明「VL模式：… 只有扫描页走 VL 逐区域识别」。

### 11.9 一个必须记下来的真实缺陷：整页裁剪不能拉伸

第一版把每个区域**拉伸**到固定的 784×784（聊天路径的算术，§10.6），结果
`table_stats.png` 的三个区域里有两个输出幻觉：

| 区域 | 尺寸 | 拉伸后输出 | 正确文字 |
|---|---|---|---|
| 标题 | 706×47（15:1） | `1990年日本国立大学成立` | `2026年第三季度生产数据统计表` |
| 脚注 | 537×29（18.5:1） | `1. 1982年1月1日，由美国国家科学院…` | `注：合格率按抽检样本计算，抽检比例 5%。` |
| 表格 | 1037×540（1.9:1） | 正确 | 正确 |

拉伸把 15:1 的标题在竖直方向压了 **16.7 倍**，字形已经不可辨认；模型没有说"看不清"，
而是给了一句语法通顺、与页面无关的话 —— 这是本卡遇到的最危险的一类错误。

**参考实现为什么不会这样**：PaddleX 的 `smart_resize` 保长宽比，并且用
`min_pixels=112896`（336×336）**放大**小裁剪 —— 706×47 会被拉到 112×1316。本服务的
vit 只有一个固定 784×784 档位（§7 偏差 2），复现不了那个网格。

**修法（第一版，MYS-2664）**：整页路径改成**保长宽比缩放 + 白底填充**
（`_fit_into_square`），聊天路径当时**保持不变**（`fit=False`）——后者是 §4 全部对齐
数字测的那套算术，`tests/data/ocr/vl_prep` 逐元素钉着它。两条路径共用一个
`_patchify`，由一个 `fit` 参数选择。

同一份实测（同一进程、同一模型、只换预处理）：

```
title  squash -> '1990年日本国立大学成立'          fitpad -> '2026 年第三季度生产数据统计表'
note   squash -> '1. 1982年1月1日，由美国国家科学院…'  fitpad -> '注：合格率按抽检样本计算，抽检比例 5%。'
table  squash -> 正确                              fitpad -> 正确（单元格间空白更多）
```

表格那行说明填充不是"对表格的取舍"：它不改变表格的正确性。

**这个「聊天路径保持不变」的理由后来被推翻了**，见 §11.10：官方客户端正是把这种
宽条裁剪发到 `/v1/chat/completions` 的。

### 11.10 聊天路径也必须填充（MYS-2681）

§11.9 保留聊天路径拉伸，理由是「聊天调用方通常送接近正方形的裁剪」。**这个理由对
PaddleOCR 官方客户端不成立。**

PaddleX 的 `PaddleOCRVL` 产线（`vl_rec_backend="vllm-server"`）先做版面，再把
**每个区域裁剪**逐个发到 `/v1/chat/completions`；标题和脚注正是 10:1 以上的宽条。
也就是说拉伸不是"聊天路径的取舍"，而是让一个**完全按规范接入的官方客户端静默出错** ——
`/v1/chat/completions` 的 OpenAI 兼容是 MYS-2663 的验收目标，这种错法不能留。

**改动**：`_patchify` 的 `fit` 参数保留（它的两种算术是一个契约，测试还要拿拉伸当
对照），但**两个调用方都传 `True`**（默认值也改成 `True`）。聊天路径与整页路径对
同一张裁剪图现在产生**逐元素相同**的 patch 张量，`tests/test_ocr_vl_page_mode.py`
`test_the_chat_path_letterboxes_like_the_page_path` 钉住这一点。

**golden 重新固定**：`tests/data/ocr/vl_prep` 用填充后的像素重新生成（`stage.png`
与 `patches.f32.gz` 两个文件变了；`crop.png`/`ids.i32`/`meta.txt`/`prep.json` 不变 ——
裁剪和提示没变，变的只是裁剪到 784 的那一步）。§4 的旧数字是拉伸算术下的历史记录，
已被 §11.11 的重新对齐替换。

**真机前后对比**（10155 新环境，同一进程、同一模型、同一份裁剪，只换预处理；
`openai` 客户端走 `/v1/chat/completions`）：

| 区域 | 尺寸 | 拉伸（旧） | 填充（新） | 正确文字 |
|---|---|---|---|---|
| 标题 | 706×47 | `1990年日本国立大学成立` ❌ | `2026 年第三季度生产数据统计表` ✅ | `2026年第三季度生产数据统计表` |
| 脚注 | 537×29 | `1. 1982年1月1日，由美国国家科学院…` ❌ | `注：合格率按抽检样本计算，抽检比例 5%。` ✅ | 同左 |

表格区域不受影响：

| 区域 | 尺寸 | 拉伸 OTSL | 填充 OTSL | HTML |
|---|---|---|---|---|
| `table_stats` 表格 | 1037×540 | 255 字符 | 255 字符，**逐字节相同** | 6 行 24 格，无 span |
| `cn_table_merged` 整图 | 760×396 | 359 字符 | 363 字符 | span 结构相同，仅单元格文字里多几个空格 |
| `cn_table_simple` 整图 | 700×400 | 294 字符 | 294 字符，**逐字节相同** | 6 行 26 格，1 处 colspan |

`cn_table_merged` 那 4 个字符的差是 `服务器D` → `服务器 D` 这类空格，`convert_otsl_to_html`
之后两张表**去掉空白完全相同**。

**按官方客户端真正发的区域裁剪再测一遍**（`/v1/ocr mode:vl` 的版面框，即 PaddleX 会
逐个 POST 的那些），三张表的 HTML 在两种算术下**完全相同**（`table_stats` 6 行 24 格、
`cn_table_merged` 5 行 22 格含 colspan 1 + rowspan 1、`cn_table_simple` 5 行 25 格），
且与整页路径对同一区域的输出**逐字节相同** —— 也就是说换了预处理，表格既没变差，
也没和整页路径分家。

### 11.11 填充后的重新对齐（MYS-2681）

§4 的数字是拉伸像素上的。换了预处理之后按同样方法重做一遍：**板上的原型引擎**
（`tools/ocr/vl_native`，MYS-2660 那台）吃**服务自己的 `_patchify` 产出的填充像素**，
x86 上 HF（transformers 4.56.2、float32、贪心）吃**同一份 `patches.f32`**，
逐 token 比。

> 「同一份像素」在这里是字面意义：板上 sophon-opencv 4.8 与 13.24 的 5.0 在
> `INTER_CUBIC` 上差 1 个 LSB（§10.12 偏差 3 记过），所以参考侧用的是**板上写出的**
> `patches.f32`/`stage.png`，不是 13.24 重算的。这样比对里唯一的变量就是引擎。

按同样方法（板上服务自己的引擎 → 原始 token id ↔ x86 HF 同一份 `patches.f32`）：

| 图片 | 板上 token | 参考 token | **LCS** | 严格逐位 | 首个分歧 |
|---|---|---|---|---|---|
| `cn_notice.png` | 167 | 167 | **167/167 = 100 %** | 167/167 | 无 |
| `en_report.png` | 162 | 162 | **162/162 = 100 %** | 162/162 | 无 |
| `mixed_spec.png` | 186 | 192 | **111/192 = 57.8 %** | 38/186 | 14 |
| `table_stats.png` | 123 | 123 | **123/123 = 100 %** | 123/123 | 无 |
| `cn_table_merged.png` | 136 | 136 | **136/136 = 100 %** | 136/136 | 无 |
| `cn_table_simple.png` | 109 | 109 | **109/109 = 100 %** | 109/109 | 无 |
| **合计** | 883 | 889 | **808/889 = 90.9 %** | 735/883 = 83.2 % | — |

**6 张里 5 张整条序列逐 token 相同**，比 §4 的 4/6 多一张；合计从 99.44 % 降到
90.9 %，降到刚好过 90 % 线，全部来自 `mixed_spec` 一张。

> 计数口径：参考侧序列末尾的 `</s>` 不计入 —— 服务遇到 EOS 就停，EOS 不是它"发出"
> 的 token。§4 那张表把它算进去了，所以 `cn_notice` 在那边是 168 vs 167。

**`mixed_spec` 的分歧仍是同一个 bf16 近分叉**：第 14 位参考自己 top-1 是 `269`
（`▁▁`，14.598）、top-2 是 `5`（`2`，14.378），**差 0.22**，板上选的正是 top-2。
这一次它把整段输出带成另一种版式：参考把每个值缩进到下一行并用 `\(...\)` 包公式，
板上把值接在同一行 —— 两种都是这张规格书的合理写法，内容一个不少。§4.2 对
`mixed_spec` 记的是同一张图的同一个性质（当时在第 15 位漂一个空格 token）。

**金标与这里的关系**：`tests/data/ocr/vl_prep` 钉的是 `table_stats` 那张裁剪**在填充
算术下的张量**（不是 token），所以它与上面的 token 数字互相独立 —— 前者管"服务算出的
像素是不是这份"，后者管"这份像素喂进引擎出来的 token 是不是参考的"。两边都过。

**服务与原型的关系**：本轮对齐用的是**服务自己的引擎**（`cv_vl_*`），不是
`tools/ocr/vl_native`。原型在这张 `mixed_spec` 上同一位置也翻面（§4 那次是 187 token、
97.9 %），而 `tools/ocr/vl_native` 是 MYS-2660 的一次性验证程序，两处转录本来就可能
在近分叉上分家。判据必须是产品，所以用产品。

⚠ **`mixed_spec` 是这张卡里唯一一个"看结果不像故障、但确实不是逐 token 同一"的点。**
如果验收要求 6/6，它需要一次针对该图的 bf16 复核（参考侧 top-1/top-2 差 0.22，
板上 bf16 翻面完全可能）；本轮没有做，如实记在这里。
