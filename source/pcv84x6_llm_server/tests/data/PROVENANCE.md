# 测试素材来源与摘要（tests/data/）

本目录是服务的**固定测试素材**，随仓库分发。它此前被仓库根 `.gitignore` 的
`data/` 规则吞掉，导致全新 checkout 直跑 `python3 -m pytest -q` 有 96 项
`FileNotFoundError`。根 `.gitignore` 现已对**这一个目录**开精确例外
（`!source/pcv84x6_llm_server/tests/data/` 与 `.../**`），其余 `data/`、
`models/`、`build/` 仍照旧忽略。

**这里的每一个文件都必须能回答三个问题**：从哪来、能不能分发、摘要是否固定。

## 规模与边界

- 34 个文件，共 14934782 字节（约 14.2 MiB）。
- 最大单文件 `ocr/postprocess.npz` 9.3 MiB，是 OCR 后处理张量 golden；
  其余均小于 2 MiB。
- **不含**模型权重、bmodel、客户文档、设备日志或任何个人数据。PDF 与图片
  都是为测试构造或取自公开样本，见下方逐项说明。

## 逐文件摘要

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `asr/features.npz` | 1927808 | `80968f7931630166af986d6552b21936ad3cc2bb0c792c7ba2a7bc0de7525292` |
| `asr/meta.json` | 1145 | `c45fcf707d5cda9f3aea15e580dab2fa500401f81d12b53196c14f24daf1b42c` |
| `asr/prompts.json` | 40491 | `116bc00790ab66f38d417cfc751a0387d36b6706806a4a1c479eef97129a9d7e` |
| `aux_token_golden.json` | 803228 | `00c79c2bb706e832d98782ee6fcab5d54a61cbc8542521bfc783c7bc9d11d3a4` |
| `bm_smi_noloop_cv84x6_idle.txt` | 3203 | `0e57c2705013a9a11d0db877759347cee92964fb7a97e83993339542f13146a1` |
| `kb/blank.pdf` | 549 | `7a3041ee1ce21d0d34fc8e2fc0eed1b8bf45908696b0edc72dcd5204460f3790` |
| `kb/mixed.pdf` | 220184 | `2b312f8ef51e7566e28e9b424fee6dab87ed39bb568c6f1299466005b1d9d8eb` |
| `kb/scan.pdf` | 146214 | `44fddf96a53cf89593e460bb7b142ce43758451608fbb557d7fd540e4a5c36fe` |
| `kb/text.pdf` | 84144 | `032459be1c56d32469d12b2a6c4e05bb47b54fb3d4929884cd35ad45b296613c` |
| `ocr/golden.json` | 170019 | `5f2bb23144b51dfab271dc54aca80cdd3c2a426f5214d0d45379a46d34c206af` |
| `ocr/img/cn_notice.png` | 177051 | `5f251c81f23f98bd00f30c628a65ffc6a744e9b36b199ce4e78552f5e998994e` |
| `ocr/img/cn_table_merged.png` | 71243 | `fa30979abc51d62cc314aa704167e23713b44d3c0be7263ce4e08fd05e3975d0` |
| `ocr/img/cn_table_simple.png` | 51630 | `30017d8b5d36d2e58b1760cfc44a047b381980febf430f4d54af5876d5ca7f9d` |
| `ocr/img/en_report.png` | 107896 | `1cf3069cc06f6a1e6733b94efa8a17a6fb87e02207231049db1e55f53f5e15a0` |
| `ocr/img/mixed_spec.png` | 132792 | `578b26c9a82eebeffe0d081b4b1d2ae3c7edbf87a543b7bca021bf7212cb3071` |
| `ocr/img/skewed_lines.png` | 130107 | `9b9feb845d2f495e10e7767e002021b3e11f55d135b95401f37f2a62e673723c` |
| `ocr/img/table_stats.png` | 91452 | `5524d0fa307e59d704830f74b942ff71a7338525cc46aeef4fd1acb8247d7c7e` |
| `ocr/img/twocolumn.png` | 171381 | `22b6e1ce721212a7d02fbe51cc5c3dc39f05f5845089d78605c2cefb2aa86d8f` |
| `ocr/img/ui_status.png` | 42498 | `0490f5a814e0a05bc7f5a405c7ec0ddd0e56fff95f3a54eb2b74cc8c9303c637` |
| `ocr/img/vertical_text.png` | 45254 | `6e5284ab20f5effca53f000214f0bd75fbb245dd85d7875bf6252ef20bf713b8` |
| `ocr/layout_tensors.npz` | 416821 | `efb4926ca3c8b9be5fb52415f9c636c0a879b98b3db59175eb7a30eb91c2d09b` |
| `ocr/otsl_golden.json` | 20893 | `527635e117ff7c937f9a629dcb9f92c412b3a32107baa9a4e2617be056e68f9c` |
| `ocr/postprocess.npz` | 9746867 | `cac266890cc7bec2cda4a43c5176e170747e8d2c864b8fe9a5f777271461e5ce` |
| `ocr/slanet_inference.yml` | 2035 | `8a6372d3269a6f112fe13a2da7952a84da6e112c10a3146cbb43de5bd01d19fa` |
| `ocr/table_truth.json` | 8262 | `dea3b044f85a1f9507e637ffc0e460feb7ace9101c406f470b67fb7097d8828c` |
| `ocr/tokenizer_golden_paddleocr_vl.json` | 38995 | `d8196ce4b2c80547ee8539b510cdda4773de3f0b66a90c5a098c00c1dcad9282` |
| `ocr/twocolumn_truth.json` | 4004 | `8efc2dc98b724ed4d1f92d0d4ff7e32199af3531ff88420b28f31e549b095ffd` |
| `ocr/vl_prep/crop.png` | 141239 | `08ee54e55e36c3c12b90f9b96d1b2c89501f7abfbc588b8a46a31ff628eb47ee` |
| `ocr/vl_prep/ids.i32` | 3188 | `8c0e421962378b364976dae1a5f26c4a08cbb2a799859ffbe8c55b9f106a987c` |
| `ocr/vl_prep/meta.txt` | 61 | `1cb235cbddd6ddca3708d28b2ab13f3712539db77cadd33b3917426c6b5caea9` |
| `ocr/vl_prep/patches.f32.gz` | 52759 | `ba6e42b2d5c3b9062494ff70e187bd73dc31fb240f5c6ee92c911ad83eedb25d` |
| `ocr/vl_prep/prep.json` | 298 | `3d224184c5f421d4b01f74eef23c65c2eb182aba9c8ee9b2904e42ccd258e70c` |
| `ocr/vl_prep/stage.png` | 73307 | `48db2c564777c0895b47aaa33cbeda8a9e3280e64cfe035b7ca22f9f8bf90026` |
| `qwen3_6_chat_template.jinja` | 7764 | `e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259` |

`tests/data/verify_fixtures.py` 校验上表：缺文件、多文件或摘要不符都会非零退出，
`tests/test_test_fixtures.py` 在 `pytest` 里跑同一份校验，因此素材被改动不会被
静默接受。

## 逐组来源

### `qwen3_6_chat_template.jinja`（7764 B）

Qwen3.6 对话模板原文，用于 `tests/test_tool_calls.py` 把服务手写的渲染器与
**模型自带模板**逐字节对拍。模板随模型权重分发，取自 Qwen3.6 官方仓库的
`chat_template.jinja`。它是测试的 oracle：手写渲染器只有和它对得上才算正确，
所以必须入库而不能在运行时生成。

### `bm_smi_noloop_cv84x6_idle.txt`（3203 B）

CV84X6 空闲状态下 `bm-smi` 的原始输出，供 `tests/test_monitor_smi.py` 验证
解析器。是设备输出的文本快照，不含凭据或客户数据。

### `aux_token_golden.json`（803228 B）

由 `tools/aux_golden.py` 用**参考 tokenizer** 生成的分词 golden，供
`tests/test_aux_tokenize.py` 对照服务侧分词结果。生成脚本已入库，重跑即可复现：

```bash
python3 tools/aux_golden.py --out tests/data/aux_token_golden.json
```

### `kb/`（4 个 PDF，451 KB）

知识库解析测试的输入：`text.pdf`（有文字层）、`scan.pdf`（扫描件，走 OCR）、
`mixed.pdf`（混合）、`blank.pdf`（空页边界）。均为测试构造的小型文档，
不含客户内容。

### `ocr/`（24 个文件，12 MiB）

OCR 链路的分层 golden，每一项都由仓库内脚本生成：

| 文件 | 生成方式 |
|---|---|
| `img/*.png`（10 张） | 测试用图，≤180 KB/张；中文文档、英文报告、中英混合规格书、表格、UI 截图、竖排中文、倾斜长行。后两者专门用于打破朴素预处理。 |
| `golden.json`、`table_truth.json`、`twocolumn_truth.json`、`otsl_golden.json` | `tools/ocr/make_golden.py`（见 `tools/ocr/README.md`） |
| `slanet_inference.yml` | PaddleX SLANet 推理配置原文（字符字典 + sentinels），`tools/ocr/table_postprocess.py` 按它构建字典 |
| `layout_tensors.npz` | `tools/ocr/make_golden.py` 记录的版面检测张量 |
| `postprocess.npz` | `tools/ocr/make_postprocess_golden.py --onnx-dir <ppocr onnx>`（见 `tools/ocr/README.md` §The tensor golden）。float32 det 概率图 + float16 rec softmax，共 110 个张量 |
| `tokenizer_golden_paddleocr_vl.json` | `tools/gen_tokenizer_golden_paddleocr_vl.py` |
| `vl_prep/*` | PaddleOCR-VL 预处理阶段的分阶段 golden（crop/stage 图、ids、patches、meta） |

`postprocess.npz` 与 `layout_tensors.npz` 体积最大，因为它们是**张量**而不是
结论：`golden.json` 只能说明"框错了"，说不出是检测错还是后处理错。这两份
必须随仓库分发，否则对应测试只能 skip —— 而 skip 会让门槛看起来通过。

### `asr/`（3 个文件，1.9 MiB）

`features.npz`（8 段音频的 log-mel 特征与波形）、`meta.json`、`prompts.json`，
由 `tools/asr/make_golden.py` 从参考实现生成：

```bash
python3 tools/asr/make_golden.py --llm-tpu <LLM-TPU 检出> --out tests/data/asr
```

## 大素材的处理原则

`postprocess.npz`、`layout_tensors.npz`、`features.npz` 三个张量 golden 合计约
11.8 MiB，仍随仓库入库，理由如上：它们是**可复现的固定 golden**，且没有它们
对应测试只能跳过。生成脚本与命令都在仓库内，摘要固定在上表，因此它们既
可分发也可重建。

真正不该入库的东西（bmodel、模型权重、客户 PDF/图片、设备日志）**没有**放进
这个目录；如果将来需要更大的 golden，应走"脚本 + 固定摘要"的获取流程，而不是
直接提交二进制。
