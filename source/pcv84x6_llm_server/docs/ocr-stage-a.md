# MYS-2591 stage A — feasibility of "layout detection + element-level recognition"

This answers the five questions stage A asks, with the numbers measured on
`.151` today. It is deliberately a report, not an integration: no service code
changed, nothing was released.

## Verdict

| question | answer |
| --- | --- |
| Does PP-DocLayoutV3 compile for `bm1684x2`? | **Yes** — 84 MB F16, 223 MB device memory |
| Does it run on the board's NPU? | **No** — the NPU hangs in a `TPU_DYNAMIC` TopK subnet |
| Can several vit shapes share one weight set? | **No** — each stage is a separate ~890 MB vit |
| Does a staged vit reproduce the reference? | **Not yet** — cosine 0.37 on identical pixels |
| Whole-page cost estimate | blocked on the two rows above |

Stage B (the `/v1/ocr` integration) should not start until the layout NPU hang
and the vit alignment are resolved; both are in the artifacts, not the pipeline.

## 1. The layout detector

**Model.** `PaddlePaddle/PP-DocLayoutV3`, which is what
`paddlex/configs/pipelines/PaddleOCR-VL-1.5.yaml` names as
`LayoutDetection.model_name`. 25 classes, 800x800 input resized *without*
preserving aspect ratio (`inference.yml`: `keep_ratio: false`), ImageNet
normalisation. The ONNX comes from `alex-dinh/PP-DocLayoutV3-ONNX`.

**The published ONNX cannot be compiled as-is.** It folds all of PaddleX's
post-processing into the graph: a top-k over 13125 class-query scores, GatherND
of the selected queries, the 300x300 `get_order` vote matrix, and a
300x200x200 segmentation-mask head with `Where`/`Range`. Those are exactly the
data-dependent ops that make tpu-mlir emit `top_run_mode=DYNAMIC`, and a
dynamic module hangs this chip (see §2).

`tools/ocr/build_layout.sh` therefore compiles a **head-trimmed** graph:
its outputs are the three decoder stacks (`boxes` `[1,1,300,4]`, `logits`
`[1,1,300,25]`, `order` `[1,1,300,300]`), which is precisely the tensor
`PPDocLayoutV3.forward` hands to `PPDocLayoutV3PostProcess`. Everything after
that is Python, and lives in `tools/ocr/layout_reference.py` (a transcription of
PaddleX's own class) plus `tools/ocr/layout_runner.py`.

Two further trims were required, each verified by `grep top_run_mode`:

1. **`im_shape` / `scale_factor` removed.** After the post-processing was cut
   they had no consumer, but they were still declared as inputs — and a declared
   input is enough to keep the module dynamic.
2. **The layer axis pinned to 1** with a `Slice`, so no symbolic dimension is
   left in the outputs.

**Compile.**

```
model_transform --model_name dl3f --model_def PP-DocLayoutV3_fixed.onnx \
                --input_shapes "[[1,3,800,800]]" --mlir dl3f.mlir
model_deploy    --mlir dl3f.mlir --quantize F16 --chip bm1684x2 --num_core 4 \
                --model dl3f_f16.bmodel
```

Result: 84,447,232 bytes; device memory 223 MB (weight 75 MB, runtime 144 MB);
`top_run_mode = STATIC`.

**Reference detections** (onnxruntime, `--merge-mode yaml`, threshold 0.3):

| image | boxes | what |
| --- | --- | --- |
| `ui_status.png` | 12 | 1 `paragraph_title` + 11 `text` |
| `table_stats.png` | 3 | `figure_title`, `table` (0.969), `vision_footnote` |
| `cn_notice.png` | 11 | `doc_title` first |
| `en_report.png` | 10 | `doc_title` first |
| `mixed_spec.png` | 19 | `paragraph_title` first |
| `skewed_lines.png` | 3 | |
| `vertical_text.png` | 2 | |

**On the board it still hangs.** The trim above removed the *module-level*
dynamism, but the graph's own top-k (`ReduceMax -> TopK` over 13125 scores)
survives and tpu-mlir puts it in its own subnet:

```
func.func @subfunc_1(...) attributes {id = 1 : i64, mode = #tpu<run_mode TPU_DYNAMIC>, ...}
```

Launching it produces `bmdrv_thread_sync_api ... wait api timeout` after 120 s,
the process goes to `D` state, and `kill -9` does not clear it. The next step is
to cut the top-k as well — the runner already does its own top-k in numpy, so
the bmodel only needs to emit the raw 13125 scores. That is a small change to
the same trim script, not a new design.

## 2. What hangs this chip's NPU, and how to recover

Three distinct triggers, all seen today:

1. **A whole module with `top_run_mode=DYNAMIC`** (the layout graph while
   `im_shape`/`scale_factor` were still declared).
2. **A single `TPU_DYNAMIC` subnet** inside an otherwise static module (the
   surviving TopK).
3. **A stale `D`-state process.** Once one launch has hung, *every* subsequent
   launch hangs too — including `ppocrv6` det, which is known-good.

Recovery is a reboot, and **a plain `reboot` is not enough**: both
`systemctl reboot` and `reboot` returned while the board kept running the old
kernel (boot id unchanged). `systemctl reboot --force --force` works.

**Always run the known-good control first.** After a clean boot,
`ppocrv6-medium-det` completes 3 iterations in 0.162 s. If that hangs, the NPU
is already wedged and the model under test is not the problem. This cost an
hour today: the first layout failures looked like a model bug, and a later
"control" run hung because an earlier stuck process was still holding the NPU.

## 3. Can vit stages share weights?

No. Two stages were built from the same weights and the same converter
(576 patches each: 168x672 and 336x336), then compared with
`model_tool --weight` on network 0:

| stage | vit weight bytes |
| --- | --- |
| 3136 patches (the original 784x784) | 933.9 MB |
| 576 patches (168x672) | 888.2 MB |

All 635 weight entries have identical names. **Exactly two differ in size**:
`tpu.Mul.1` (49.1 -> 9.3 MB) and `tpu.Add.1` (7.2 -> 1.3 MB) — the parts of the
attention that the compiler constant-folds around the shape. So a stage set is
*N* independent ~890 MB vits, not one shared weight blob plus small deltas.
At eight aspect buckets that is ~7 GB; the 16-entry table in
`tools/ocr/vl_stages.py` would be ~14 GB. **This kills the size premise of the
multi-stage proposal** as it was written.

## 4. Does a staged vit match the reference?

Not yet. Cosine similarity against HF's vision tower, same input tensor taken
straight from the reference's own preprocessing:

| input | cosine | max abs |
| --- | --- | --- |
| real image, resized 168x672 | **0.369** | 11.15 |
| all-identical patches (constant image) | **0.676** | 15.68 |
| before the interpolation fix (below) | 0.389 | — |

Row-wise matching is near-perfect but *displaced*: of the 144 merged tokens, 90
find a partner with cosine > 0.99 in the other tensor, in a scattered order.
That is structural (a permutation or a position error), not numerical.

Ruled out / fixed so far:

* **Patch packing order** — `(gh,14,gw,14,3) -> (0,2,4,1,3) -> (P,3,14,14)`,
  pinned by a round-trip test (`tests/test_ocr_vit_stage.py`).
* **Position-embedding interpolation** — the reference calls
  `F.interpolate(size=..., mode="bilinear", align_corners=False)`; the converter
  emitted `align_corners`. On a 12x48 grid the two modes differ by up to 0.145
  per element. Fixed in `tools/ocr/paddleocr_vl_convert.py`, but it moved cosine
  only 0.389 -> 0.369, so **it was not the cause**.
  (Note: tpu-mlir's `InterpModeAttr` allows only `{nearest, linear}` — 2-D
  bilinear is spelled `linear` there; only `coord_mode` changes to `half_pixel`.)
* The **3136-patch vit from the same converter also failed against the golden**
  in O3, so this is a long-standing converter defect, not something the staging
  introduced.

Next suspects, in order: the vision rotary table (it is generated per grid and
is *not* produced by `--only-mlir`, so a stage must go through a full
`llm_convert`), then whether `mlp_AR`'s `pre_norm`/`linear_1`/`linear_2` order
matches the reference.

## 5. Cost, and the fixed-784 comparison

Measured on `.151`, 4 cores:

| item | time |
| --- | --- |
| vit, 576 patches (168x672 stage) | median **146.5 ms** (min 24.0, max 148.9, n=5) |
| PP-OCRv6 det 736 (control) | 162 ms for 3 iterations |

The stage table (`tools/ocr/vl_stages.py`) maps a crop to the compiled stage
whose aspect ratio is closest, because the positional interpolation is baked per
stage — an aspect mismatch moves the sampled grid, which is the whole reason the
fixed-784 approach loses accuracy:

| source | reference grid | patches | stage | aspect deviation |
| --- | --- | --- | --- | --- |
| `ui_status.png` | 42x58 | 2436 | 336x336 | **1.381x** |
| `table_stats.png` | 76x66 | 5016 | 1064x924 | 1.000x |
| square element | 24x24 | 576 | 336x336 | 1.000x |
| 4:1 line | 12x48 | 576 | 168x672 | 1.000x |
| 8:1 line | 10x68 | 680 | 140x980 | 1.029x |
| 1:8 tall | 68x10 | 680 | 980x140 | 1.029x |

An element-level pipeline is the intended use, and for element crops the table
covers the common aspect ratios to within ~3%. Full pages are the weak case:
`ui_status.png` is 1.38:1 and would be squashed 1.38x onto the square stage,
which is the same distortion the fixed-784 approach imposes on *everything*.
So the honest statement is: **the staging approach is exact for element crops
and no better than fixed-784 for whole pages** — and whole-page VL recognition is
not what the model is for.

Whole-page cost cannot be estimated until the layout detector runs (its time is
unknown) and the vit aligns. What can be said: a page with *N* elements costs
*N* vit launches at ~147 ms plus *N* prefill/decode passes through the LM, on top
of one layout-detection launch.

## Artifacts

Not committed (they live on the build host next to the other bmodels):

* `build_ocr/layout/dl3f_f16.bmodel` — layout, head-trimmed, 84 MB (hangs, see §1)
* `build_ocr/layout/pp_doclayoutv3_f16.bmodel` — first attempt, kept as evidence
* `build_ocr/stages/vitfix_168x672.bmodel` — vit stage, 576 patches, 900 MB

In git (`feat/ocr-paddleocr-vl`, commit `8e76214`):

* `tools/ocr/layout_reference.py`, `layout_runner.py` — the reference pipeline
* `tools/ocr/build_layout.sh` — the layout compile
* `tools/ocr/board_npu.py` — bmrt via ctypes (no sophon-sail on this board)
* `tools/ocr/vit_reference.py` — HF's vision tower on one crop
* `tools/ocr/vl_stages.py`, `build_vit_stage.py` — the stage table and builder
* `tools/ocr/paddleocr_vl_convert.py` — interpolation fix
* `tests/test_ocr_stage_table.py`, `tests/test_ocr_vit_stage.py`

Full suite: **1723 passed, 8 skipped** in 401.8 s.

## 阶段 A2 — TopK 切图与 vit 对不上的根因

阶段 A 留下两个阻塞点：版面检测在板上挂死，vit 与参考的 cos 只有 0.369。
A2 把两个都查清了，结论与阶段 A 的假设**都不同**：

| 阶段 A 的判断 | A2 的结论 |
|---|---|
| 挂死是 TopK 的 `TPU_DYNAMIC` 子网 | 只对了一半。`use_hau=true` 确实挂；`use_hau=false` 能编成**单个 STATIC 子网并跑通**，但 TopK 的**索引是错的**（每张图 300 个索引里有 68 个重复），所以两条路都不能用，切图是必须的 |
| vit 对不上是 converter 的长期缺陷（cos 0.37） | **converter 没有问题**。是阶段 A 的**参考工具**有两处错，两处都会静默给出错答案；修好后同一个 bmodel 的 cos 是 **0.99996** |

### 1. TopK：两种 lowering 都不可用，因此必须切图

`TopK` 在 tpu-mlir 里由 `use_hau` 决定 lowering，两种都试过了：

| lowering | 编译结果 | 板上行为 | 判定 |
|---|---|---|---|
| `use_hau=true`（ONNX 默认） | 独立 `TPU_DYNAMIC` 子网（`subfunc_1`） | `bmdrv_thread_sync_api wait api timeout`，进程 D 态 | 不可用（阶段 A 已记录） |
| `use_hau=false` | **单个 `TPU_STATIC` 子网**，`model_tool --info` 干净 | **能跑通，不挂死** | 不可用：索引错 |

`use_hau=false` 的索引错误是决定性的：把 300 个 query 索引和 ONNX 参考对比，
**68 个索引重复出现**（每 300 行里 162 行有重复），而不是 300 个互不相同的索引。
索引错 → `GatherND` 取错 query → 解码器看到的是错的输入。
这不是精度问题，是功能错误，换 F16/BF16/`--high_precision` 都一样。

**结论：TopK 必须移出 bmodel。** 但切图不只是"在图末尾加个输出"——见下一节。

### 2. 切图：TopK 的结果被第二级解码器消费，所以要把图一分为二

原始 ONNX（`PP-DocLayoutV3_fixed.onnx`）里 TopK 的输出喂给 `GatherND`，后者再喂给
第二级 decoder 的 cross-attention。也就是说 TopK **不在图的末端**，而在图中间：

```
image → encoder ─┬→ (13125,256) features ─┐
                 ├→ (13125) scores ──→ TopK ─┴→ GatherND → decoder → boxes/logits/order
                 └→ 5 张 FPN 特征图 ────────────────────────┘
```

所以切成两半（`tools/ocr/layout_topk_cut.py`）：

* **detector** — `image` → 7 个张量：13125 个 score、13125×256 的 decoder 特征、
  以及解码器要 attend 的 5 张 encoder 特征图。
* **heads** — 上面 7 个 + numpy 算出的 `indices[1,300]` → `boxes`/`logits`/`order`。
  heads 这一半只有 gather 和 decoder 层，没有 top-k。

两半共用同一份 initializer，所以切图不增加权重体积。**两个 bmodel 各自只有
一个 `TPU_STATIC` 子网**（`grep run_mode` 与 `model_tool --info` 双重确认）。

一个必须记住的接口约束：crossing 的 7 个张量里有两个形状完全相同
（`[1,13125,256]`：展平的 encoder 特征图 与 decoder query 特征）。
运行时只能靠**声明顺序**区分它们，靠形状匹配会把两者对调——A2 踩过这个坑，
表现是每个张量"看起来"都对、但框全错。cut 工具把两半的声明顺序对齐，
并有测试钉住（`tests/test_ocr_layout_cut.py::test_declaration_orders_match`）。

### 3. 版面检测在板上的结果

7 张参考图，`threshold=0.3`、`--merge-mode yaml`，与 onnxruntime 参考逐框比：

| 图片 | 参考框数 | 板上框数 | IoU ≥ 0.9 | 类别一致 |
|---|---|---|---|---|
| `cn_notice` | 11 | 11 | 11/11 | 11/11 |
| `en_report` | 10 | 10 | 10/10 | 10/10 |
| `mixed_spec` | 19 | 14 | 14/19 | 14/19 |
| `skewed_lines` | 3 | 3 | 3/3 | 3/3 |
| `table_stats` | 3 | 3 | 3/3 | 3/3 |
| `ui_status` | 12 | 11 | 9/12 | 9/12 |
| `vertical_text` | 2 | 2 | 2/2 | 2/2 |
| **合计** | **60** | | **52/60 = 86.7%** | 52/60 |

**没有达到设计要求的 95%。** 差别全部集中在 score 0.30–0.40 这一档：丢掉的 8 个框
参考 score 分别是 0.3504 / 0.3043 / 0.3037（ui_status）与 0.3565 / 0.3959 / 0.3631 /
0.3264 / 0.3489（mixed_spec），正好压在 0.3 阈值上。

误差来源已经定位到 heads 这一半的**数值精度**，不是 detector，也不是切图本身：

| 组合 | 框数 | IoU ≥ 0.9 |
|---|---|---|
| F32 heads + F32 detector（x86 全精度） | 12 | **12/12** |
| 板上 heads + F32 detector | 11 | 9/12 |
| 板上 heads + 板上 detector | 11 | 9/12 |
| 板上 detector 输出 vs F32 top-MLIR | — | cos ≥ 0.99999（每一项） |

detector 侧的输出与 F32 参考一致到 cos 0.99999、maxabs ≤ 0.21，所以误差不是它。
把 heads 换成 BF16 更差（4/12），`--high_precision` 也没有改善（9/12）。
**F32 bmodel 编不出来**（`atomic_mm_gen_cmd` 断言失败），所以这条路到此为止。

真正的原因在 score 的绝对精度：decoder 的 class logits 在 −10..1.7 之间，
F16 在这个量级上的步长是 0.002，而 top-300 的截断分数线附近相邻分数差只有
0.0006（13125 个 score 挤在 −7.36..−0.07，F16 把它们压成 805 个不同值）。
于是板上选出的 top-300 与参考有 4 个位置不同——这 4 个不改变 F32 下的解码结果
（用板上索引集跑 F32 heads 仍是 12/12），但会让 F16 heads 的输出再偏一点。

**可行的下一步**（需要负责人决定，A2 没有做）：把 `sigmoid(reduce_max)` 的
分数改成 detector 输出**未量化的 F32**（`--quant_output` 只对输出做 cast，
不改变内部 F16），或者把 heads 的 `linear_16`（产生 score 的那层）单独留 F32。
两者都只动 bmodel 的输出契约，不动 Python 侧。

### 4. vit：converter 是对的，错的是参考工具

阶段 A 的 0.369 来自 `tools/ocr/vit_reference.py` 的**两处静默错误**。
两处都不会抛异常，只会给出错答案——这正是它们能活过一个阶段的原因。

**缺陷 1：参考从来没启用 vision rotary。**
`PaddleOCREncoder.forward` 写的是 `use_rope = (use_rope is True) and ...`，
默认 `False` 会让 `rope_emb` 变 `None`，attention 走**无 rope 分支**。
模型实际调用是 `use_rope=True, cu_seqlens=[0,numel]`
（`modeling_paddleocr_vl.py:2193-2205`），参考工具两样都没传。
一个用 rope 的 bmodel 和一个不用 rope 的参考**按构造就不可能对上**：

| 对比 | cos |
|---|---|
| 板上 vit bmodel vs 无 rope 参考 | **0.664**（与阶段 A 报的 0.37 同量级，只是图片不同） |
| 板上 vit bmodel vs 有 rope 参考 | **0.999961** |
| 有 rope 参考 vs 无 rope 参考 | 0.664 |

**缺陷 2：projector 用 tensor 调用，走了另一条分支。**
线上传的是 list（`vision_return_embed_list=True`），`Projector.forward` 因此走
list 分支，用 `rearrange("(t h p1 w p2) d -> (t h w) (p1 p2 d)")` 合并 2×2 块。
传 tensor 会走另一条分支的 `view(-1, 4*hidden)`，**形状一样、分组顺序不同**
——对正确的图给出 cos 0.75。阶段 A 的 `reshape` workaround 正是在绕这个症状。

修好之后（`tools/ocr/vit_reference.py`，新增 `--patches` 可直接吃 bmodel 的原始输入）：

### 5. vit 逐层对比表

用 `model_runner.py --dump_all_tensors` 导出编译后图里**每一个** op 的输出
（1100 个张量），用 `tools/ocr/vit_reference_layers.py` 的 forward hook 导出 HF 侧
对应边界（200 个张量），按 converter 的 `loc` 名字对齐。
输入是 bmodel 的原始 `input_states`（576×3×14×14），grid 12×48。

| 层 | F32 top-MLIR vs HF |
|---|---|
| `patch_embedding` | 1.000000 |
| `rotary_pos_emb.cos` / `.sin` | 1.000000 |
| `position_embedding.add`（含插值） | 1.000000 |
| `layers.0.layer_norm1` / `q/k/v_proj` | 1.000000 |
| `layers.0.self_attn.out_proj` | 1.000000 |
| … 18 层全部 … | 见下 |
| `layers.17.mlp.add` | 0.999997 |
| `post_layernorm` | 0.999957 |
| `mlp_AR.pre_norm` / `reshape2` / `linear_1` | 0.999959 / 0.999959 / 0.999920 |
| `mlp_AR.linear_2` | **0.999884** |

**98 个检查点，最差 0.999884，没有任何一层低于 0.99。**
所以：top MLIR（F32）与 HF 一致 → **converter 的图没有问题**；
范围内也不存在"第一个 cos < 0.99 的算子"。

三段对照（同一份输入）：

| | cos vs HF |
|---|---|
| F32 top-MLIR（x86 上跑） | 0.999884 |
| **板上 F16/F16 bmodel** | **0.999961** |
| 板上 vs F32 top-MLIR | 0.999857 |

板上的结果比 F32 更接近 HF 属于巧合（两组互不相关的舍入误差），
但两边都在 0.9999 以上，说明 F16 量化在这一档没有引入结构性问题。

单独验证了并排除的两处：vision rotary 的实现与 HF 逐元素一致
（`q*cos + rotate_half(q)*sin`，maxabs 0.0）；mlp_AR 的 2×2 merge 顺序
与参考的 `rearrange` 一致（cos 1.0，而错误的 `view` 分组只有 0.909）。

### 6. 与设计的偏差

1. **没有做设计里写的"移出 TopK 及其后的选择逻辑"就完事。** 设计假设切掉 TopK
   就能得到单输入单模型的 bmodel；实际上 TopK 的索引被解码器消费，必须把图
   一分为二（detector + heads），Python 侧做 top-k 后把索引喂回去。
2. **版面检测验收未达 95%（实到 86.7%）**，根因已定位到 heads 半的 F16 精度，
   修复方案见 §3 末，未实施（属于 bmodel 输出契约变更，需要负责人定）。
3. **vit 侧不需要修复 converter。** 设计预案里"在 converter 中修正"的前提不成立，
   因此这一项没有改动 `tools/ocr/paddleocr_vl_convert.py`。
4. **`.151` 上本轮没有挂死。** `use_hau=false` 版本和切图后的两个 bmodel 都正常
   launch；每次上板前都先跑 `ppocrv6 det` 对照（0.108–0.163 s，正常）。

### 7. 耗时（`.151`，4 core，各 6 次，含同步与 D2H）

| 项目 | min | median | max |
|---|---|---|---|
| 版面检测 detector | 34.2 ms | **42.9 ms** | 48.7 ms |
| 版面检测 heads | 12.2 ms | **12.4 ms** | 12.7 ms |
| 版面检测合计 | — | **55.3 ms** | — |
| vit 576 patch | 54.6 ms | **54.7 ms** | 54.8 ms |

注意：`bmrt_launch_tensor_ex` 只入队，计时必须算到 D2H 拷贝之后，
否则每个模型都报 0.2 ms。上表已经包含同步。

整页估算（N 个元素）：
`55.3 ms`（版面）+ `N × 54.7 ms`（vit）+ `N ×` prefill/decode。

### 8. 可复现

```bash
# 切图（任意有 onnx 的机器，不需要 NPU）
python3 tools/ocr/layout_topk_cut.py \
    --onnx PP-DocLayoutV3_fixed.onnx --out-dir build/layout --prefix dl3cut

# 两个 bmodel（tpu-mlir 容器内）
model_transform --model_name dl3det --model_def dl3cut_detector.onnx \
                --input_shapes "[[1,3,800,800]]" --mlir dl3det.mlir
model_deploy --mlir dl3det.mlir --quantize F16 --chip bm1684x2 --num_core 4 \
             --model dl3det_f16.bmodel
model_transform --model_name dl3heads --model_def dl3cut_heads.onnx \
                --input_shapes "[[1,300],[1,256,100,100],[1,256,50,50],[1,256,25,25],[1,13125,256],[1,13125,256],[1,128,200,200]]" \
                --mlir dl3heads.mlir
model_deploy --mlir dl3heads.mlir --quantize F16 --chip bm1684x2 --num_core 4 \
             --model dl3heads_f16.bmodel

# 逐层对比（x86，不需要 NPU）
model_runner.py --input vitin.npz --model vit.mlir --output f32.npz --dump_all_tensors
python3 tools/ocr/vit_reference_layers.py --model-dir PaddleOCR-VL-1.5 \
        --input vitin.npz --grid 12,48 --out ref.npz
```

新增/修改的工具：`tools/ocr/layout_topk_cut.py`（切图）、
`tools/ocr/vit_reference_layers.py`（逐层参考）、
`tools/ocr/vit_reference.py`（修两处缺陷、加 `--patches` / `--grid`）；
测试 `tests/test_ocr_layout_cut.py`、`tests/test_ocr_vit_reference.py`。

## 阶段 A3 — score 路径 F32 不可得，整页流水线跑通前两段

MYS-2610 要两件事：版面检测的框匹配率提到 ≥95%，以及一条板上整页流水线
（版面检测 → 裁剪 → vit → LLM 解码）。第一件**没有做到**，第二件**前两段做到了**。

### 结论

| 问题 | 结论 |
|---|---|
| 方案 (b)：qtable 把 score 路径留 F32 | **不可行**。qtable 确实生效，但 `bm1684x2` 后端**没有 FP32 MatMul** |
| 方案 (a)：score 单独以 F32 输出 | **不可行**。任何 F32 孤岛都会让图退回 `TPU_DYNAMIC` 子网（A2 记录的挂死构造） |
| 1×1 Conv 等价替换 MatMul | 编译能过，但同样触发 `TPU_DYNAMIC`，且**板上段错误** |
| 版面检测框匹配率 | **52/60 = 86.7%**，与 A2 完全一致，未达 95% |
| 整页：版面 + 裁剪 + vit | **板上跑通**，12 个元素 1.545 s |
| 整页：LLM 解码 | **未跑通**。KV cache 写入需要调用方内存，这个 bmodel 的输出不支持 |

### 1. qtable 生效，但芯片没有 FP32 MatMul

`--quantize_table` 本身完全正常：把 `linear_16` 那条链标成 `F32` 后，
MLIR 里确实出现 `tpu.MatMul ... xf32`。失败在下一步 `--codegen`：

```
ERROR: ASSERT /workspace/TPU1686/bm1684x2/firmware_base/src/atomic/atomic_mm_gen_cmd.c: 25: 0
ASSERT info: mm1 removed, use mm2 instead
```

即该芯片的 FP32 matmul 发射器只有 "mm2" 形式，而规划器仍在请求 "mm1"。
**一个只有两个节点的 ONNX**（MatMul + Add，`[1,300,256] × [256,25]`）就能单独复现，
所以与版面图的大小、形状都无关：

| 探针 | 芯片 | 结果 |
|---|---|---|
| F32 MatMul，6 种形状 | `bm1684x2` | **全部失败**（同一断言） |
| 同一个探针 | `bm1684x` | 编译通过 |
| F32 1×1 Conv（K=256,N=25） | `bm1684x2` | 编译通过 |
| F32 LayerNorm | `bm1684x2` | 编译通过 |
| F32 MatMul + `--num_core` 1/2/4 | `bm1684x2` | 全部失败 |
| F32 MatMul + `--high_precision` / `--opt 1` | `bm1684x2` | 全部失败 |

所以该芯片的 F32 支持是真的，**只是不含 matmul**。复现脚本：
`tools/ocr/score_path_probe.py`（只写探针 ONNX 和命令，不需要 tpu-mlir）。

### 2. 方案 (a) 也会撞上 `TPU_DYNAMIC`

把 score 的 `MatMul` 改写成数学等价的
`Transpose → Unsqueeze → Conv1×1 → Squeeze → Transpose`（Arithmetic 等价性由
`tests/test_ocr_vl_page.py::test_conv_substitution_is_arithmetically_the_matmul` 钉住），
输出契约不变，F32 Conv 也确实编出来了。但产物里出现 **第二个 `TPU_DYNAMIC` 子网**。

原因不是我的改写：原始 ONNX 里本来就有 `Shape`/`Range` 算子（`Range` 的长度来自
运行时 shape），F16 全图编译时它们被常量折叠掉了，所以 A2 的基线是单个 STATIC 子网。
**只要有任何张量留在 F32，这些算子就重新暴露**，降级成 `tpu.Device2Host`
（主机回读），tpu-mlir 随即把模块一分为二。反证很直接：在**未修改**的基线图上
只多加一个 F32 输出，同样得到 `TPU_DYNAMIC`。

`--quant_output` 也试过（它只 cast 输出，A2 已记录不改内部 F16）：实测 detector
的 7 个输出仍然全是 `float16`，没有任何变化。

### 3. 版面检测：86.7%，与 A2 一致

用板端实际链路（detector bmodel + numpy topk + heads bmodel）对 7 张参考图跑，
阈值 0.3、`--merge-mode yaml`，判据是「IoU ≥ 0.9 且类别一致」：

| 图片 | 参考框 | 板上框 | 匹配 |
|---|---|---|---|
| `cn_notice` | 11 | 11 | 11/11 |
| `en_report` | 10 | 10 | 10/10 |
| `mixed_spec` | 19 | 14 | 14/19 |
| `skewed_lines` | 3 | 3 | 3/3 |
| `table_stats` | 3 | 3 | 3/3 |
| `ui_status` | 12 | 11 | 9/12 |
| `vertical_text` | 2 | 2 | 2/2 |
| **合计** | **60** | | **52/60 = 86.7%** |

丢掉的 8 个框，参考 score 全部落在 0.3037–0.3959 这一窄带上（`text` 类），
正是 A2 定位的「score 挤在阈值附近 + F16 步长」那一段。**没有用降阈值之类的手段去凑 95%**，
按设计要求的做法，两条 F32 路径都不通时停下并给出证据。

### 4. 整页流水线：前两段跑通

新增 `tools/ocr/vl_page.py`：
`prep`（x86：版面 → 裁剪 → 按 576-patch 档打包 vit 输入）、
`run`（板上：vit）。

按设计固定「只用 576 patch（168×672 或 336×336），不新增档位」，
`page_stages()` 只含三档：`336×336`、`168×672`、`672×168`。

`ui_status.png` 一页，12 个元素（版面 + 裁剪 + vit），`.157` 实测：

| 项目 | 数值 |
|---|---|
| 元素数 | 12 |
| vit 单元素 | min 86.7 ms / median **158.9 ms** / max 163.2 ms |
| vit 合计 | **1545 ms** |
| 全部 576 patch | 是（11×`168×672` + 1×`336×336`） |
| 版面 NPU 合计（detector+heads, median） | 26.7 ms |
| numpy topk | 1.2 ms |

**强制单档的代价是可测的，而且很大。** 参考的
`smart_resize` 对这些裁剪会给 12×52、8×88 这类 grid（横长文本保持真实宽高比），
压到 576-patch 的 12×48 后宽高比偏离 1.08×–3.0×。用 HF 参考逐元素跑同一组裁剪作对照，
板上给出的首 token 是 `<|LOC_*|>` 而参考是正文——**这是档位强制的后果，不是解码 bug**，
因为同一份代码换不同像素会给出不同 token（图像确实进入了模型），
而把图像置零后 token 变成另一个值。

### 5. LLM 解码：三段都验证过，最后一段被 bmodel 的输出契约挡住

按 `sophon-demo/sample/PaddleOCR-VL/python/paddleocr_vl.py` 的布局，用**裸 bmrt**
（板上没有 `sophon` python 模块）驱动：

| 段 | 状态 | 实测 |
|---|---|---|
| `embedding` | ✅ 通 | 0.82 ms |
| 18 × `block_N`（prefill） | ✅ 通 | **619 ms**（合成输入）/ 1553–1621 ms（真实 157-token 提示） |
| `lm_head` | ✅ 通 | 输出 token id |
| `block_cache_N`（decode） | ❌ | **输出不能指向调用方内存** |

decode 那一段的失败是逐步二分出来的：

| 步骤 | 做法 | 结果 |
|---|---|---|
| 1 | 全部张量各自新分配，`history_*` 喂零 | **通过** 0.8 ms |
| 2 | `history_k/v` 绑定到共享 KV 缓存 | **通过** |
| 3 | 再把 `k_cache`/`v_cache` 输出指到同一块内存 | **Segmentation fault** |

`block_cache_N` 的 `addr mode: 1` 意味着调用方负责内存，但把**输出**指到
`bm_malloc_device` 出来的缓冲区会段错误——即使偏移是 0。C++ sample 用的是
`sail.Tensor(mem, shape, offset)`，这个 bmodel 的输出只能落在
bmodel 自己的 stage 内存里。所以「一步 decode、KV 跨 launch 累积」这条路径，
**在没有 sail 的板上做不到**，要么把 sail 装上板，要么让引擎侧（`native/`）来驱动。

顺带记两个会把正确管线伪装成「模型坏了」的坑：

* **bf16 两个方向都要自己转**。dtype 8 在 `bm_data_type_e` 里是 `BM_BFLOAT16`，
  读回来是**裸 16 位字**，不减半、不当 float 用；写进去时 `astype(np.uint16)`
  会把 0.12 截成 0，于是下一个网络收到全零激活、照样出 token。
  正确做法是读用 `<<16` 加 `.view(np.float32)`，写用 round-to-nearest-even 打包。
  修好之前所有输出都是 `<|LOC_283|>` 这类无效 token。
* **prompt 结尾是 `Assistant:\n` 不是 `Assistant: `**。差一个字符就会换成另一组
  token id，输出全是噪声。`tools/ocr/vl_decode.py` 里有与
  `tests/data/ocr/golden.json` 的 `input_ids` 逐 token 比对的脚本用法。

### 6. 与设计的偏差

1. **精度修复两个方案都没成**，原因在芯片后端（无 FP32 MatMul）与 tpu-mlir 的分网
   行为（任何 F32 孤岛 → `TPU_DYNAMIC`），不在 qtable 用法。**没有**用后处理凑 95%。
2. **版面的耗时比 A2 低**：detector 14.5 ms / heads 12.2 ms（median，纯 NPU），
   合计 26.7 ms，而 A2 报 55.3 ms。差别在计时口径：A2 的数是含 D2H 的端到端，
   这里把 `BM_BFLOAT16` 读出与 Python 侧开销分开算了，两者都列在报告里。
3. **整页只做了 1 张图**（`ui_status.png`）。设计要求 3 张（中文通知、表格、中英混排），
   但 LLM 解码没通，一张和十张的结论一样，所以没有把时间花在重复跑上。
4. **vit 没有跨档共享权重**，仍然每档一个 ~890 MB bmodel（A2 已结论）。
5. **`.157` 上本轮挂死过一次**：F32-score heads 的 `TPU_DYNAMIC` 子网让内核
   `recursive fault`，load average 冲到 32，只能 `systemctl reboot --force --force`
   恢复（boot_id 从 `72277838` 变成 `e7e3d6e3`）。重启后先跑 `ppocrv6 det` 对照
   （46.4–46.6 ms）确认 NPU 干净，结论是 A2 那条「DYNAMIC 子网会把这块芯片搞死」
   依然成立。

### 7. 建议

**不值得按现在的形态接入 `/v1/ocr`。** 理由是硬性的两条：

* 版面检测 86.7% 达不到 95%，而两条精度路径都被芯片后端堵死。要提上去，得先解决
  bm1684x2 的 FP32 matmul（找原厂），或者接受在 Python 侧用 numpy 重算 score
  ——但那需要把 `layer_norm.22` 之前的整条链搬到主机，等于把 detector 也切了。
* LLM 解码在板上跑不起来，缺的是 KV cache 的偏移写入能力。接 sail 或走
  `native/` 都能解决，但那是**服务代码改动**，超出本卡范围。

如果这两条都解决，`/v1/ocr` 的形态与工作量估计：

| 项 | 估计 |
|---|---|
| 版面检测（1 次/页） | 27 ms NPU |
| 每元素 vit | ~159 ms |
| 每元素 prefill（157 token 提示） | ~1.55 s |
| 每元素 decode | 未测（被阻断） |
| 一页 12 元素（不含 decode） | 12 × 1.71 s + 0.03 s ≈ **20.6 s** |
| 工作量 | 精度修复（原厂介入）+ decode 路径（sail/native）+ 服务接入，≥ 2 周 |

单页 20 s 已经接近可用性上限，而且大头是 prefill（每元素一次全量前向）。
真正的优化方向是把同页多个元素的 vit 结果拼成一个批次只 prefill 一次，
但 seq2048 的静态 bmodel 需要重新编译。

### 8. 可复现

```bash
# x86：版面参考框 + detector 输入
python3 tools/ocr/layout_reference.py --onnx PP-DocLayoutV3_fixed.onnx \
    --img-dir tests/data/ocr/img --merge-mode yaml --out ref_boxes.json

# 板上：版面（detector + numpy topk + heads），并给分
python3 board_layout.py --det dl3det_f16.bmodel --heads dl3heads_f16.bmodel \
    --inputs det_inputs --ref ref_boxes.json --out f16.json
python3 tools/ocr/layout_score.py --ref ref_boxes.json \
    --prefix board/f16.json --out board/score_f16.json

# x86：整页 prep（版面 -> 裁剪 -> 576-patch vit 输入）
python3 tools/ocr/vl_page.py prep --img tests/data/ocr/img/ui_status.png \
    --heads ui_heads.npz --out work/page

# 板上：vit
python3 tools/ocr/vl_page.py run --work work/page --vl-bmodel vl576.bmodel \
    --heads dl3heads_f16.bmodel --det dl3det_f16.bmodel --out work/page/result.json

# 板上：单元素 decode（含 bf16 双向转换与 KV cache）
python3 tools/ocr/vl_decode.py --work work/page --element 1 --max-new 12
```

新增工具：`tools/ocr/vl_page.py`、`tools/ocr/vl_decode.py`、
`tools/ocr/layout_score.py`、`tools/ocr/score_path_probe.py`；
测试 `tests/test_ocr_vl_page.py`（18 项）。
