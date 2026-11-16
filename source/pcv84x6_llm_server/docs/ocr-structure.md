# OCR 表格与复杂版面识别：PP-DocLayout + SLANet + PP-OCR 在 CV84X6 上的可行性

本文件回答 MYS-2615 的问题：**用 PaddleOCR 的轻量版面/表格模型，能不能在 CV84X6 上
做出「表格与复杂版面识别」**，代价多少，值不值得接入 `/v1/ocr`。

结论先行，证据在后。所有板上数字都来自 `.157`（`HQDZCVEBFJIJA0021`），
`bmrt_test` 取中位数；x86 参考在同一台机器上用 onnxruntime 跑**同一份切过的 ONNX**
加**同一份 numpy 后处理**——两边只差图与硬件，这样比较才有意义。

## 结论

| 问题 | 答案 |
|---|---|
| 三个模型能编成纯 `TPU_STATIC` 的 bmodel 吗 | **能**。版面 S/M 与 SLANet_plus 各自只有一个 `TPU_STATIC` 子网，`model_tool --info` 可证 |
| 版面与 x86 参考对齐吗 | **S 35/35 = 100 %；M 26/27 = 96.3 %**（逐图见 §2） |
| SLANet 与 x86 参考对齐吗 | **4/4 图 HTML 逐字符相同**——但这只说明板上复现了参考 |
| 表格**识别正确**吗 | **不。** 合并单元格那张：5 行结构对、两处 span 对，但 **22 个真值单元格只填出 4 个**（18 个丢），日期还被截成 `2026-06-3` |
| 整页原型能跑通吗 | **能跑，但表格文字基本没填上**；纯文本页（中文通知、中英混排）文字正确、阅读顺序正确 |
| 整页耗时 | 14–32 s 一页，**其中 OCR 占 95 %**，而那 95 % 是每张图起一个进程，不是 NPU 时间 |
| 建议接入吗 | **暂不接入 `/v1/ocr`**。模型可编可跑，但表格识别质量不达标（见 §3.4） |

三个模型里只有 **SLANet_plus 需要改造**才能编译（自回归解码器，见 §3）；版面的
ONNX 也只需切掉尾部，不需要发明新算子。

## 1. 编译结果

| 模型 | 输入 | 输出 | bmodel | 设备内存 | 子网 |
|---|---|---|---|---|---|
| PP-DocLayout-S | `image [1,3,480,480]` f32 | boxes `[1,4789,4]`、scores `[1,23,4789]` | 8.7 MB | 5.3 MB | 1 × `TPU_STATIC` |
| PP-DocLayout-M | `image [1,3,640,640]` f32 | boxes `[1,8500,4]`、scores `[1,23,8500]` | 18.2 MB | 21.5 MB | 1 × `TPU_STATIC` |
| SLANet_plus @64 步 | `x [1,3,488,488]` f32 | bbox `[1,65,8]`、struct `[1,65,50]` | 85.5 MB | 90.8 MB | 1 × `TPU_STATIC` |

编译命令：`tools/ocr/build_layout_sm.sh`、`tools/ocr/slanet_unroll.py`（参数见各自的
`--help`）。全部 `--chip bm1684x2 --quantize F16 --num_core 4`。

**没有 `TPU_DYNAMIC` 子网**是这张卡的硬要求（`docs/ocr-stage-a.md` §2：动态子网会挂死
NPU），三个模型都满足。

### 板上 NPU 时间（`bmrt_test`，单次发射）

| 模型 | NPU 时间 |
|---|---|
| PP-DocLayout-S 480 | **0.97 ms** |
| PP-DocLayout-M 640 | **2.88 ms** |
| SLANet_plus @64 步 | **5.63 ms** |
| PP-OCRv6 det 736（对照） | 45.6 ms |
| PP-OCRv6 rec 640（对照） | 9.3 ms |

版面检测比现有 OCR 的 det 还便宜两个数量级，SLANet 也只有 det 的 1/8。
**NPU 不是瓶颈。**

## 2. 版面检测：切图与对齐

PP-DocLayout-S/-M 的官方 ONNX 把 PaddleX 整套后处理也编进了图：`MulticlassNMS` +
gather/top-k 金字塔。这部分有两个理由必须切掉：它会被 tpu-mlir 划进 `TPU_DYNAMIC`
子网（会挂死），而且它产出的行数依赖数据，静态 bmodel 声明不出来。

`tools/ocr/layout_cut.py` 把图截在两个稠密张量上，并把 `scale_factor` 一并剪掉——
**切点选在按 `scale_factor` 除法之前**，否则 `scale_factor` 会作为第二个输入留下，
每个调用方都要记住它的语义。切完图是单输入静态 CNN。

截断后的 numpy 尾部在 `tools/ocr/layout_postprocess.py`，是 PaddleX 的转写而不是
重写。两处约定必须照抄，改了就对不上：

* **切出来的那个 NMS 用普通 IoU，PaddleX 的 layout NMS 用 `+1`**。`iou()` 里给交集和
  两个框的边长都加 1（VOC 老约定）。在切出来的 NMS 里误用 `+1`，`skewed_lines.png`
  的 100 行里会换掉 13 行。
* **框先取整再比阈值**，顺序也照抄。

`--verify` 用两条独立断言固定这件事：numpy 的 NMS 必须复现**未切图 ONNX 自己**
的 100 行，numpy 的整条尾部必须复现 **PaddleX 自己的 `LayoutAnalysisProcess`**。
两张模型 × 9 张图都是 9/9。

### 板上对 x86 参考

阈值 0.5、`merge_mode` 取 PP-StructureV3 的配置。判据是 IoU ≥ 0.9 且类别一致。
逐图列出（`structure_board.py` 原样输出）：

**PP-DocLayout-S — 35/35 = 100 %**

| 图 | 板上框数 | 参考框数 | IoU≥0.9 | 类别一致 |
|---|---|---|---|---|
| `cn_notice` | 11 | 11 | 11/11 | 11/11 |
| `cn_table_merged` | 2 | 2 | 2/2 | 2/2 |
| `cn_table_simple` | 2 | 2 | 2/2 | 2/2 |
| `en_report` | 8 | 8 | 8/8 | 8/8 |
| `mixed_spec` | 8 | 8 | 8/8 | 8/8 |
| `skewed_lines` | 1 | 1 | 1/1 | 1/1 |
| `table_stats` | 3 | 3 | 3/3 | 3/3 |
| `ui_status` | 0 | 0 | — | — |
| `vertical_text` | 0 | 0 | — | — |

**PP-DocLayout-M — 26/27 = 96.3 %**

| 图 | 板上框数 | 参考框数 | IoU≥0.9 | 类别一致 |
|---|---|---|---|---|
| `cn_notice` | 10 | 10 | 10/10 | 10/10 |
| `cn_table_merged` | 2 | 2 | 2/2 | 2/2 |
| `cn_table_simple` | **1** | 2 | **1/2** | **1/2** |
| `en_report` | 5 | 5 | 5/5 | 5/5 |
| `mixed_spec` | 3 | 3 | 3/3 | 3/3 |
| `skewed_lines` | 1 | 1 | 1/1 | 1/1 |
| `table_stats` | 3 | 3 | 3/3 | 3/3 |
| `ui_status` | 0 | 0 | — | — |
| `vertical_text` | 1 | 1 | 1/1 | 1/1 |

`ui_status` 两张都是 0 框：该图 12 个框的参考分数全在 0.30–0.40，被 0.5 阈值滤掉
（A2 曾用阈值 0.3 量到 12 个，见 `ocr-stage-a.md` §3）。**这里的 0/0 是「与参考一致」，
不是「图上没有版面」。** 这是选取 0.5 这个单一阈值的副作用，也是 §7 第 3 条要按 f16
重定阈值的理由之一。

M 漏的那一个框是 `cn_table_simple.png` 的 `table_title`：f32 参考分数
**0.50055**，只比 0.5 阈值高 0.0006；f16 把它压到阈值下。这是 f16 的临界效应，
不是算错——`docs/ocr.md` 记录的 PP-OCR det 框偏差是同一类。它的实际后果很小
（丢的是一个标题框，表格本体没丢），但**说明「阈值附近 ±0.001 的框」在 f16 上不可靠**，
接的时候要么把阈值调到 0.4 左右，要么接受这一档损失。

### S 与 M 的差别：S 认不出表格

这是选型上最需要注意的一条。同一批图上：

| 图 | PP-DocLayout-S | PP-DocLayout-M |
|---|---|---|
| `cn_table_merged.png` | `image` 0.703 | **`table` 0.687** |
| `cn_table_simple.png` | `image` 0.708 | **`table` 0.786** |
| `table_stats.png` | `image` 0.768 | **`table` 0.892** |

**S 把表格判成 `image`，M 判成 `table`。** 整页原型是靠 `label == "table"`
选表格区域去走 SLANet 的，所以用 S 的话这条流水线根本不触发。S 的 100 % 是在
「和它自己的参考一致」意义上成立的，不代表它能支撑表格识别。

→ **整页原型统一用 M。** S 的价值是更小更快（5.3 MB vs 21.5 MB，0.97 ms vs 2.88 ms），
如果只做纯文本版面、不做表格，S 够用。

## 3. SLANet_plus：改造自回归解码器

官方 SLANet_plus 的 ONNX **不只是编不过，是根本跑不起来**：onnxruntime 在 shape
inference 就拒绝它，tpu-mlir 转 `.mlir` 时报
`operand conv2d_24.b_0 not found`。三处导出缺陷，都在导出脚本里：

1. **Loop body 直接引用外层的权重。** `gru_cell_0.w_0` 和六个 `linear_*.w_0/b_0`
   没有在 body 里声明，而是抓外层作用域。ONNX 允许，tpu-mlir 的转换器不允许。而且
   它们是 `Constant` **节点**不是 initializer，得先物化才能内联。
2. **Loop 声明了 9 个 carried 输入、只声明 8 个 carried 输出**，丢了 `done` 标志。
   这违反 ONNX 的 `len(outputs) == carried + 1`，`onnx.checker` 不查所以能发出来。
   反汇编时按类型对齐才能确认哪 8 个对上哪 8 个——不是猜的：消费 `while.0.2` 的两个
   `Cast` 只和 `scale.3.0`（int64 写游标）对得上，`while.0.3` 和 `while.0.6` 依次对上
   bbox 与 structure 累加器。
3. **tpu-mlir 完全转不了 Loop**，所以解码器必须展开成直筒图。

`tools/ocr/slanet_unroll.py` 做上面三件事，另外两处配套：

* **写游标钉成字面量**。它是 int64 标量，初值 0，每步加 1——展开后就是步号。钉死它
  才能把 `Range/Where/Min` 那条 clamp 链从 scatter 索引里拿掉。
* **`OneHot` 改 `Gather`**。这才是拿掉 `TPU_DYNAMIC` 子网的关键。解码器用
  `OneHot(argmax(logits))` 选词嵌入再拼特征，tpu-mlir 把 `OneHot` 单独划成动态子网
  ——用一个只有 `ArgMax`+`OneHot` 的两节点图复现过，结果就是一个 STATIC + 一个
  DYNAMIC。`OneHot` 在 depth 恒定、values `[0,1]` 时**就是**从单位阵里取一行，所以
  换成 `Gather(eye(50), idx)` 是等价变换，不是近似：对 Paddle 自己的预测器逐 token
  比对，44 和 21 个 token 全同。

`ScatterElements` 反而**没有**动：静态索引的 scatter 单独测过，编出来是
`TPU_STATIC`，所以没有理由去改它的语义。

**步数是参数不是常数**（`--steps`），因为展开后的图是 O(步数) 的：8 步 18.0 MB /
23.5 MB，64 步 85.5 MB / 90.8 MB。两张测试表实际用 44 和 21 步，取 64 步留了余量；
500 步（模型的 `max_text_length` 上限）没有编，按这个线性关系约 670 MB 设备内存，
不现实。**这是方案的主要成本项**。

### 板上对齐

两张既有表格 + 两张新中文表格，与 x86 参考比 HTML：

| 图 | 行数 | 单元格 | 结构 | HTML |
|---|---|---|---|---|
| `table_stats.png` | 7/7 | 25/25 | 相同 | **逐字符相同** |
| `ui_status.png` | 6/6 | 6/6 | 相同 | **逐字符相同** |
| `cn_table_merged.png` | 7/7 | 24/24 | 相同 | **逐字符相同** |
| `cn_table_simple.png` | 7/7 | 28/28 | 相同 | **逐字符相同** |

4/4。新图由 `tools/ocr/make_table_images.py` 生成（70 KB / 50 KB，都在 300 KB 预算内），
其中 `cn_table_merged.png` 带 2 处合并单元格（表头 1×2、左列 3×1）。

**但要说清楚 SLANet 的输出不是原表格的忠实重建**：`cn_table_merged` 真值是 5 行 ×
5 列 / 22 格，SLANet 给 7 行 / 24 格（多两行是标题与备注被当成表格、列数只有 3）。
这不是板上误差（x86 一样），是 SLANet_plus 在这类细线表格上的固有限制。
**所以「4/4 相同」的含义是「板上复现了参考」，不是「识别正确」**——识别是否正确，
见 §3.4 的逐格比对。

### 3.4 单元格文字逐格比对（验收 3）

这一节是**返工后补的**，上一版报告只比了 HTML 结构就写了「中文文字都对」，那是错的。

工具：`tools/ocr/compare_cells.py`，拿 `make_table_images.py` 产出的
`tests/data/ocr/table_truth.json` 当基准，逐格报告「找到了哪些、丢了哪些」。
只看匹配数会掩盖本项目真实的失效模式——**整列丢失**。

**合并单元格那张（`cn_table_merged`，真值 5 行 × 5 列 / 22 格，2 处合并）**

| 对象 | 行 | 单元格 | 文字命中 | span |
|---|---|---|---|---|
| 板上原型 | 5/5 | **12/22** | **4/22** | 2 处都对 |
| x86 参考（同一份 numpy 尾部） | 5/5 | 12/22 | 4/22 | 2 处都对 |
| PaddleX `table_recognition_v2` | 5/5 | **22/22** | **22/22** | 2 处都对 |

- **板上 = x86 参考，逐格完全一致**：说明板上没有额外损失，差距不在硬件、不在 f16。
- 丢的 18 格是「状态」「负责人」两整列 + 所有日期/人名，日期还被截成 `2026-06-3`。
- 实际输出（板上原样）：

```html
<html><body><table><tr><td colspan="2">区域/设备</td><td>巡检日期</td></tr>
<tr><td>二号机房</td><td></td><td>服务器D 2026-06-3</td></tr>
<tr><td rowspan="3">一号机房</td><td></td><td>服务器A 2026-07-1</td></tr>
<tr><td></td><td>服务器B 2026-08-0</td></tr>
<tr><td></td><td>服务器C 2026-09-1</td></tr></table></body></html>
```

**根因（§5 有完整证据）：`table_recognition_v2` 不是 SLANet_plus 产线。**
它用 `SLANeXt_wired` + 独立的 **RT-DETR 单元格检测器**
（`RT-DETR-L_wired_table_cell_det`）拿单元格几何，所以能检出 22 格；
而卡片指定的 SLANet_plus 只有结构头，自带的 bbox 分支在这一页只给 12 个框
（3 列）。**我们没有那个检测器，也就没有第 4、5 列的位置**，文字自然填不进去。

这是**方案层面的缺口**，不是调参能补的：要拿到 PaddleX 那个结果，必须再编一个
RT-DETR 单元格检测模型（未在本卡范围内，见 §9）。

### 预处理里一个反直觉的点（三种写法差 5 倍行数）

SLANet 的填充值有三种写法，都能跑，结果完全不同：

| 填充写法 | 填充区取值 | `cn_table_merged` crop 解出 |
|---|---|---|
| 归一化后填 127.5（配置字面） | 127.5 | **1 行 / 2 格** |
| 填 0 **像素**再整体归一化 | -2.12 | **6 行 / 13 格** |
| **归一化空间填 0**（实际喂进模型的） | **0.0** | **5 行 / 12 格** ✅ |

判据不是读配置、也不是驱动 preprocessor 对象——那两条分别给出 127.5 和 127.5。
决定性的做法是在 `PaddleStaticRunner.__call__` 上把张量截下来：填充区精确是 `0.0`，
内容区 min/max 为 -2.05/2.64。本实现按这个张量对齐，误差 5e-7，解出与 PaddleX
一致的 5 行 / 12 格。

`tests/test_ocr_structure.py` 钉住了这一条，防止「照配置改成 127.5」这种看似正确的
整理把结果改坏。

## 4. 整页原型

`tools/ocr/structure_page.py`：版面（M）→ 表格区域走 SLANet 得 HTML 与单元格框 →
单元格内用 PP-OCR 识别文字填回 → 非表格区域按版面顺序用 PP-OCR 识别 → 拼 Markdown。
有 `rowspan/colspan` 时输出 HTML（GFM 能渲染），否则输出管道表。

三张图按卡面要求取「中文通知 / 表格 / 中英混排」：

| 图 | 类别 | 元素数 | 版面 | 表格结构 | OCR | 合计 |
|---|---|---|---|---|---|---|
| `cn_notice.png` | 中文通知 | 10（全文本） | 804 ms | — | 31 213 ms | **32.0 s** |
| `cn_table_merged.png` | 表格 | 2（1 表 + 1 文本） | 811 ms | 824 ms | 14 165 ms | **15.8 s** |
| `mixed_spec.png` | 中英混排 | 3（全文本） | 814 ms | — | 12 926 ms | **13.7 s** |

**中文通知（`cn_notice`）实际输出**——文字与阅读顺序都正确：

```
关于开展设备巡检工作的通知

设备管理科

巡检范围

二、责任分工

三、注意事项

巡检期间如发现异常，应立即停机并上报设备科，严禁
设备带病运行。

一号厂房由张伟负责，二号厂房由李静负责，三号厂房
由王强负责。各责任人须在巡检结束后三个工作日内提交
书面报告。

覆盖一号厂房至三号厂房全部生产设备，包括配电柜、
空压机、冷水机组及传送带系统。

各部门：

为保障生产设备安全稳定运行，经研究决定，于本月
15 ...
```

> 返工前的版本把这段**整段倒序**输出（页脚在最前、标题在最后）：版面模型自带的
> 顺序在 `cn_notice` 上是乱的，而 PaddleX 并不信任它——它在
> `sort_normal_blocks` 里按「行桶 → 列桶」重排。本实现补了这一步
> （`structure_page.reading_order`），上面是修复后的顺序。**限制**：`xycut_enhanced`
> 的多栏切分没有移植，双栏页会串行，报告不假装它解决了。

**中英混排（`mixed_spec`）**：三段文字都识别出来了（含 `8 × ARM Cortex-A55`、
`≤ 25 W (typical)`、`-20°℃ ~60°C` 这类混排），顺序正确。

**表格（`cn_table_merged`）**：结构与 span 正确，但文字只填出 4/22——见 §3.4，
这是 SLANet_plus 缺单元格检测导致的，本卡无法解决。

### 耗时构成——瓶颈不在 NPU

**OCR 占了 90 %+，而它的十几秒里 NPU 只占很小一部分。** 实测 det 45.6 ms、
rec 9.3 ms——`cn_notice` 有 10 个文本区域、几十行，纯 NPU 也就 1–2 s。
剩下的三十秒是**每次调用都起一个 python 进程**（原型用子进程调 `board_npu.py`，
每次都要 `bmrt_load_bmodel`）。`cn_notice` 的 31 s 是因为它有 10 个区域、每个区域
一次 det，进程启动被付了 10 次。

这不是原型的缺陷被掩盖，而是**接入时的关键结论**：模型常驻的话，一页的 NPU 时间
大概是 `版面 3 ms + 表格 6 ms + OCR 约 1.5 s`。当前的 14–32 s **不能**当成接入后的
实际耗时。

## 5. 与 paddlex 端到端产线的差异

**返工前这条写错了**：原报告称「paddlex 需要 GPU 侧依赖，本站没跑通」。
实际原因是缺包，装上 `paddlex[ocr]` 后 `table_recognition_v2` 在本机
（`venv-structure`，paddlex 3.7.2 / paddle 3.0.0）可以正常跑。

装上之后立刻暴露了本方案最重要的一件事：**这个产线用的不是 SLANet_plus。**

```
TableStructureRecognition:
  WiredTableStructureRecognition:    SLANeXt_wired
  WirelessTableStructureRecognition: SLANeXt_wireless
WiredTableCellsDetection:            RT-DETR-L_wired_table_cell_det
WirelessTableCellsDetection:         RT-DETR-L_wireless_table_cell_det
```

结构由 SLANeXt 出，**单元格几何由一个独立的 RT-DETR 检测器出**。所以：

| 图 | PaddleX 检出单元格 | 真值 | 本原型（SLANet_plus 自带 bbox） |
|---|---|---|---|
| `cn_table_merged` | **22** | 22 | 12 |
| `cn_table_simple` | **25** | 25 | 28 |
| `table_stats` | 24 | — | 25 |

PaddleX 的单元格数**与真值精确相等**，本原型的数则随模型走。这就是 §3.4 那 18 个空格
的全部来源：我们缺的不是后处理，是**那个检测器**。

这与验收意见里提的「整图 7 行 / 26 格 vs crop 5 行 / 14 格」也对得上——返工后
这两个数已经修正为**整图 7 行 / 24 格、crop 5 行 / 12 格**，且与 PaddleX 在同样输入上
的输出一致（PaddleX 整图也是 7 行）。差异不再是我们的 bug，而是模型 + 缺检测器。

## 6. 一个必须记下来的坑：`bmrt_launch_tensor_ex` 是异步的

`board_npu.py` 原本调完 `bmrt_launch_tensor_ex` 就去 `bm_memcpy_d2s` 取输出，
**中间没有 `bm_thread_sync`**。头文件写得很清楚：

> After calling this API, inference on TPU is launched. And the CPU program will
> not be blocked. `bm_thread_sync` should be called to make sure inference finished.

后果是读到了 NPU 还在写的缓冲区：**同一个全零输入，连续三次发射分别得到
0.8911 / 0.5435 / 0.129**，而且看起来像「加载某个 bmodel 会破坏另一个的结果」。
排查时先后怀疑过缓冲区尺寸、输入名、NPU 内存、甚至重启了三次板子，最后是头文件
一句话定性的。补上 `bm_thread_sync` 后连续发射逐位相同。

这个 bug 值得单独写一段，因为**它长得像模型坏了**，而实际上一个 byte 都没错。

## 7. 建议：暂不接入 `/v1/ocr`

### 为什么

**表格识别质量不达标，而且缺口不在我们能调的地方。** §3.4 的逐格比对：合并单元格那张
22 格里只填出 4 格，「状态」「负责人」两整列丢失。根因是卡片指定的 SLANet_plus 只带
结构头，缺 PaddleX 产线里那个独立的 RT-DETR 单元格检测器（§5）。在这之前接进去，
用户拿到的是**看起来是表格、实则缺列的 HTML**——比不返回表格更糟。

纯文本版面这条路是通的：`cn_notice` / `mixed_spec` 的文字与阅读顺序都对（§4），
如果要先上**版面 + 文字**（不做表格），条件基本具备。

### 要做完需要什么

| # | 事项 | 说明 | 估计 |
|---|---|---|---|
| 1 | **补 RT-DETR 单元格检测 bmodel** | `RT-DETR-L_wired_table_cell_det`，512×512 输入。这是补齐那 18 格的唯一途径 | **3–4 人日**：转换器 + 后处理移植（DETR 系，参考 `layout_cut.py` 的经验）+ 板上对齐 |
| 2 | 单元格文字取法 | **返工前这条写错了**：现原型已经是「整表 crop 跑一次 OCR + 匹配」，不是「每格一次 det」。真正要改的是反向的——补上检测器后，把 22 个单元框拿去匹配那次 det 的结果；`fill_cells` 已经是 PaddleX 的 IoU+距离匹配，直接复用 | 0.5 人日 |
| 3 | SLANet 步数定档 | 64 步 85.5 MB / 90.8 MB 可接受；500 步上限按线性外推约 670 MB，不现实。要统计真实文档的 token 分布再定档（像 rec 的 320/640/1600） | 1 人日（含统计脚本） |
| 4 | 阈值按 f16 重定 | §2 的 0.50055 → 0.4999 说明 0.5 太贴边；`ui_status` 在 0.5 下 0 框、0.3 下 12 框。照抄 PaddleX 的分类别阈值（0.3–0.5） | 0.5 人日 |
| 5 | `/v1/ocr` 加 `mode: "layout"` | 返回 Markdown；复用现有「四 bmodel 一个模型 + 按需加载 rec 档位」的机制 | 2 人日 |
| 6 | 双栏切分（可选） | 现在的 `reading_order` 只做单栏；`xycut_enhanced` 的多栏切分未移植 | 1.5 人日 |
| | **合计** | 不含第 6 项 | **约 7–8 人日** |

### 资源

**额外 NPU 内存**（当前方案）：版面 M 21.5 MB + SLANet 90.8 MB = **约 112 MB**
（PP-OCR 的 det+rec 已在用，不重复算；版面 S 只要 5.3 MB）。
若补 RT-DETR 单元格检测，还要再加一个模型的常驻内存（未编，未测）。

**一页的 NPU 时间**：版面 2.9 ms + 表格 5.6 ms + OCR 约 1.5 s（估算，未按常驻实测）。
当前的 14–32 s 是**进程启动开销**，不是接入后的耗时（§4）。

### 形态

在 `/v1/ocr` 上加 `mode: "layout"` 返回 Markdown，而不是新开端点——现有的
「四 bmodel 一个模型、按需加载 rec 档位」机制可以复用。

## 8. 复现

```bash
# x86：切图 + 参考
python3 tools/ocr/layout_cut.py --onnx PP-DocLayout-M.onnx \
        --out PP-DocLayout-M_cut.onnx --verify tests/data/ocr/img
python3 tools/ocr/structure_reference.py --onnx-dir <dir> \
        --img-dir tests/data/ocr/img --out ref

# 编译（容器内）
tools/ocr/build_layout_sm.sh <onnx-dir> <out-dir>
python3 tools/ocr/slanet_unroll.py --onnx SLANet_plus.onnx \
        --out SLANet_plus_u64.onnx --steps 64

# 板上（.157）
python3 structure_board.py --bmodel dlM.bmodel --model PP-DocLayout-M --ref-dir ref
python3 table_board.py --bmodel slanet.bmodel --ref-dir ref --chars-yml slanet_inference.yml
python3 structure_page.py page.png --layout dlM.bmodel --table slanet.bmodel \
        --table-yml slanet_inference.yml --layout-side 640 \
        --ppocr-model-dir ppocr/models --ppocr-config repo/model-config/ppocr_v6 \
        --json page.json

# 逐格比对（验收 3）：板上 vs 真值
python3 tools/ocr/compare_cells.py --truth tests/data/ocr/table_truth.json \
        --got-json page.json --table cn_table_merged.png

# 与 PaddleX 端到端比对（§5）
python3 -c "
from paddlex import create_pipeline
p = create_pipeline('table_recognition_v2')
r = list(p.predict('tests/data/ocr/img/cn_table_merged.png'))[0]
open('/tmp/pdx.html','w').write(r['table_res_list'][0]['pred_html'])
"
python3 tools/ocr/compare_cells.py --truth tests/data/ocr/table_truth.json \
        --got-html /tmp/pdx.html --table cn_table_merged.png
```

`make_table_images.py` 同时写出 `tests/data/ocr/table_truth.json`（两张新表的真值：
合并那张 22 格、普通那张 25 格），比对以它为准。

## 9. 没有做的事

* **RT-DETR 单元格检测器**：这是补齐丢失列的唯一途径（§5、§7），但不在卡片范围内，
  未编、未测。
* `SLANeXt_wired`：同样的改造流程能编成单个 `TPU_STATIC`（289 MB / 339 MB 设备内存），
  但体积是 SLANet_plus 的 3.7 倍、没做精度对齐，**不推荐**。PaddleX 的
  `table_recognition_v2` 产线用的正是它，所以「结构」这一半其实可以换；
  缺的仍然是单元格检测。
* 双栏页面的阅读顺序：`reading_order` 只做单栏（§4）。
* 500 步展开：按线性外推约 670 MB，没编。
* 旧 bmodel（PaddleOCR-VL 路线）的结论不变，见 `docs/ocr-stage-a.md`。
