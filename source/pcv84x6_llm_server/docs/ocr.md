# OCR：`POST /v1/ocr`（PP-OCRv6 det + rec，可选版面模式）

本服务把 **PP-OCRv6 medium** 作为第四类辅助模型提供：`kind = "ocr"`，
接口 `POST /v1/ocr`。一次请求 = 一张图进，整段文本 + 每行文本/置信度/四点框出。

`mode` 决定输出形状，**缺省 `"lines"`**：

| `mode` | 输出 | 用途 |
|---|---|---|
| `"lines"` | 每行文本/置信度/四点框，`text` 是这些行按阅读顺序换行拼接 | 截图、裁剪图、单列表单；本接口原本的行为，**逐字节不变** |
| `"layout"` | 先按版面模型分区（标题/段落/表格/图片…），再按阅读顺序给出整页 **Markdown** 与 `blocks` | 整页文档、双栏排版、需要标题与段落结构时；表格只输出文字，不还原结构 |

OpenAI 没有 OCR 接口，所以请求与响应形状是本服务自定义的；**鉴权、错误码、
`model` 字段与其他 `/v1` 接口完全一致**，已经对接本服务的客户端不需要新规则。

## 路由分流

| 现象 | 状态码 |
|---|---|
| 模型名不存在 | **404** |
| 模型未加载 / 加载中 / 卸载中 | **409** |
| 模型进程已退出（需要重新加载） | **503** |
| 模型存在且已加载，但 `kind` 不是 `ocr` | **400**，消息指出该调哪个接口 |
| 请求体不合法（字段缺失、类型不符、图片无法解码、超限） | **400** |
| worker 队列已满 | **429**（带 `Retry-After`） |

`/v1/models` 会列出已加载的 OCR 模型，`kind` 为 `"ocr"`。

## 请求

两种正文形式，选一种即可。

**JSON**

```json
{
  "model": "ppocrv6-medium",
  "image": "data:image/png;base64,iVBORw0KG...",
  "return_boxes": true
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `model` | 是 | 必须是 `ocr` 模型 |
| `image` | 是 | 三种写法：`data:image/<类型>;base64,<数据>`、纯 base64、`http(s)` URL（默认拒绝，见下） |
| `return_boxes` | 否 | 默认 `true`；`false` 时每行只回 `text` 与 `score`，`box` 为 `null` |
| `mode` | 否 | `"lines"`（默认）或 `"layout"`；其他值 400，消息列出这两个值 |

**multipart/form-data**（curl / Postman / 表单上传更方便的场景）

```
curl -H "Authorization: Bearer $KEY" \
     -F file=@page.png -F model=ppocrv6-medium -F return_boxes=false \
     localhost:8000/v1/ocr
```

文件字段必须叫 `file`，一次只能一个；`model` 必填；`return_boxes` 作为表单字段时是
字符串，`"true"/"false"/"1"/"0"` 都认，其他值 400（静默取默认值等于回答了另一个问题）。
`mode` 同样可作为表单字段。

### 图片上限与远程 URL

- 单张图 **≤ 20 MiB**，两种形式都在**读取过程中**就按这个数字截断，不是先缓冲再拒。
- `http(s)` URL 默认**拒绝**：服务端替客户端发起请求是 SSRF 面，而这台设备按设计是离线的。
  运维确认需要时设 `CV84X6_OCR_ALLOW_REMOTE=1`；此时抓取有 20 秒超时，并且同样按
  20 MiB 边读边截。拒绝消息里会写明这个变量名。
- 无法解码的图片返回 400 并说明支持 OpenCV 能读的格式（PNG/JPEG/BMP/WebP…）；
  这是**请求的问题**，不是模型的问题，所以不会变成 500 让人去翻 worker 日志。

## 响应

```json
{
  "id": "ocr-9f2c...",
  "model": "ppocrv6-medium",
  "text": "仓库盘点单 Warehouse Inventory Sheet\n编号\nNO.",
  "lines": [
    {
      "text": "仓库盘点单 Warehouse Inventory Sheet",
      "score": 0.9734,
      "box": [[45, 40], [259, 40], [259, 61], [45, 61]]
    }
  ],
  "usage": {"det_ms": 41.2, "rec_ms": 88.5, "lines": 17}
}
```

| 字段 | 说明 |
|---|---|
| `text` | 按**阅读顺序**拼接、换行分隔。忽略 `lines` 的客户端直接用这个 |
| `lines[].text` | 这一行的识别结果 |
| `lines[].score` | CTC 保留时间步的 softmax 均值（与 PaddleOCR / sophon-demo 同口径） |
| `lines[].box` | 四点在**原图像素**坐标，顺序为左上、右上、右下、左下（PaddleOCR 的顺序）。`return_boxes:false` 时为 `null` |
| `usage` | 没有 token，所以报实际工作量：det 毫秒、rec 毫秒、行数 |

`lines` 里**不含**解出空串的框：检测器在纹理上画出的噪声框会被丢掉（PaddleOCR 的
`drop_score` 也是这个意思）。所以 `len(lines)` 可能小于 det 找到的框数。

### 阅读顺序

按垂直中心把框**分组成本行**（同一行的高度差容忍半个行高），行与行自上而下，行内
自左向右。这跟 PaddleOCR 自己的 layout 排序一致，也是**表格**需要的顺序——
`table_stats.png` 就是 golden 里的一张，一行的单元格只有连起来读才有意义。

**`lines` 模式两栏正文会交错**（按 (y, x) 排的结果），要分栏请用 `mode: "layout"`
（见下节）。**竖排文字在两种模式下都识别不了**：det+rec 对是横排训练的，golden 里
竖排样本 0/7 行与参考一致。

## `mode: "layout"`：版面模式

整页进，Markdown 出。三步，每步的判据都不同：

1. **版面检测**（PP-DocLayout-M，640×640 输入）把页面分成 23 类区域中的若干块。
   预处理是 PaddleX 的 `Resize(keep_ratio=false)` + ImageNet 归一化——**整页拉伸到
   640×640，不是 letterbox**；用 PP-OCR det 那套补零会让每个框整体偏移。
   后处理（阈值 0.5、layout NMS、`layout_merge_bboxes_mode`）是 PaddleX
   `LayoutAnalysisProcess` 的 numpy 转写，见 `app/engine/ocr_layout.py`。
2. **整页只跑一次 det**，把 det 的文本框按「与哪个版面框重叠」分配进各区域。
   这是 PaddleX `get_overlap_boxes_idx` 的规则（两轴都要重叠 > 3 px）。一个框同时
   落进多个区域时取**面积最小**的（本服务的取舍，PaddleX 改为裁交集重跑识别）；
   一个框都不落时归入最近的 `text` 区域，页面上没有 `text` 区域时自成一个
   `other_text` 块——**任何情况下文字都不会丢**。
3. **阅读顺序**照 PaddleX 的 `xycut_enhanced`：按 y 投影切成横带，带内按 x 投影切成
   栏，递归；标题与图表块另用加权距离插入。**这是双栏页正确的唯一途径**——按 (y, x)
   排会把左右栏交错，把通栏段落塞进左栏。

### 响应（`mode: "layout"`）

```json
{
  "id": "ocr-9f2c...",
  "model": "ppocrv6-medium",
  "mode": "layout",
  "text": "# 关于开展设备巡检工作的通知\n\n各部门：\n\n为保障生产设备…",
  "blocks": [
    {
      "index": 0,
      "type": "title",
      "label": "doc_title",
      "score": 0.521,
      "box": [159, 94, 887, 150],
      "text": "关于开展设备巡检工作的通知",
      "lines": [{"text": "关于开展设备巡检工作的通知", "score": 0.97, "box": [[…]]}]
    }
  ],
  "lines": [ … 与 lines 模式同格式，但按版面阅读顺序 … ],
  "usage": {"layout_ms": 3.1, "det_ms": 41.2, "rec_ms": 88.5, "blocks": 10, "lines": 17}
}
```

| 字段 | 说明 |
|---|---|
| `text` | 整页的 **Markdown**（规则见下） |
| `blocks[]` | 按阅读顺序排列的区域。`label` 是 PP-DocLayout 的原始 23 类之一，`type` 是粗分类（`title`/`subtitle`/`text`/`table`/`image`/`chart`/`formula`/`header`/`footer`/`seal`/`number`/`aside_text`） |
| `blocks[].lines` | 落进这个区域的 OCR 行，区域内自上而下、自左向右；`return_boxes:false` 时 `box` 为 `null` |
| `lines` | 全部行按**版面阅读顺序**重排后的平铺列表（不再是 `lines` 模式的顺序） |
| `usage.layout_ms` | 版面模型本身的一次前向，与 det/rec 分开计 |

`lines` 模式响应**逐字节不变**：`mode` 缺省为 `"lines"`，`blocks` 为 `null`，
`usage` 只多出两个可空字段。这是卡面要求，也是 `tests/test_ocr_api.py` 钉住的。

### Markdown 规则

照 PaddleX 版面产线（`build_handle_funcs_dict` + `MarkdownConverter.convert`）：

| 类别 | 输出 |
|---|---|
| `doc_title` | `# <文本>` |
| `paragraph_title` | `## <文本>` |
| 正文 | 行按 PaddleX 规则合并：**中文行直接连接，英文行用空格连接**；段落之间空一行 |
| `table` | 先一行 `<!-- 表格：仅文字，未还原结构 -->`，再一行一个表格行、单元格用空格分隔。**不输出 Markdown 表格，也不输出 HTML** |
| `image` / `chart` / `seal` | `[图片]` / `[图表]` / `[印章]`，区域内若有文字附在后面 |
| `formula` | 原样输出识别到的文字（没有公式识别模型，不臆造 `$$`） |
| `header` / `footer` / `number` / `footnote` / `header_image` / `footer_image` / `aside_text` | 默认**不进入** `text`（PaddleX 的 `markdown_ignore_labels`），但仍保留在 `blocks` 里 |

**表格为什么只给文字。** 还原结构需要 SLANet 再加一个独立的单元格检测器，
MYS-2615 实测 `table_recognition_v2` 在合并单元格那张表上 22 格里只填出 4 格、
「状态」「负责人」两整列丢失（[`ocr-structure.md`](ocr-structure.md) §3.4）。
返回一张看起来有结构、实则缺列的 HTML 比不返回表格更糟，所以这里明确只给文字，
并在输出里写下这句话，不让读 Markdown 的人误以为列是原来的列。

### 耗时与内存（真机 `.157`，SN `HQDZCVEBFJIJA0021`）

一页 `mode: "layout"` 的实测（`cn_notice` / `en_report` / `mixed_spec` / `twocolumn`
四张，取中位数）：

| 阶段 | 耗时 | 说明 |
|---|---|---|
| `layout_ms`（**服务上报**） | **49–88 ms** | 版面预处理 + 版面 bmodel 前向 + numpy 尾部，即一次 layout 请求比 `lines` 多出来的部分 |
| └ 版面 bmodel 前向 | 5.4 ms | NPU 一次发射（`bmrt_test` 口径 2.9 ms，这里含 `NetEngine` 的拷贝与同步） |
| └ 预处理 | 26 ms | `cv2.dnn.blobFromImage` + 逐通道 std；见下 |
| └ numpy 尾部（NMS 等） | 25 ms | 一次性的 23 类两两 IoU 矩阵 |
| `det_ms` | 95–104 ms | 与 `lines` 模式完全相同（整页只跑一次 det） |
| `rec_ms` | 421–609 ms | 同上 |
| 端到端墙钟 | 679–830 ms | 服务同一进程、模型常驻；`lines` 模式约 620–780 ms |

**`layout_ms` 一开始是 105 ms，`bmrt_test` 的 2.9 ms 只是前向本身。** 剩下的是
本服务的 numpy 尾部与预处理，压下去靠三处（都已落在代码注释里，`tests/test_ocr_layout.py`
钉住结果不变）：

| 改动 | 前 | 后 |
|---|---|---|
| `_containment` 逐对 Python 双循环 | 96 ms | 0.3 ms（一次 `n x n` 数组） |
| 贪心 NMS 每步切片重算 IoU | 60 ms | 25 ms（每类一次两两 IoU 矩阵，贪心只读布尔行） |
| 预处理 numpy 链换 `blobFromImage` | 36 ms | 26 ms |
| **`layout_ms` 合计** | **105 ms** | **58 ms** |

**NPU 内存**：版面 bmodel 的 `device mem size` 是 **21,533,440 B（约 20.5 MiB）**
（`model_tool --info`：weight 12.2 MB + instruct 0.45 MB + runtime 8.9 MB），
与 MYS-2615 报的 21.5 MB 一致。它**按需加载**，所以：

- 只用 `lines` 的部署：0 额外内存；
- 第一次 `layout` 请求之后：+20.5 MiB，且不再释放（常驻到 worker 退出）。

板上 `bm-smi` 的进程行在这台机器上读不出我们的 worker（TUI 的 `Processes:` 段在本板
固件下不列出应用进程），所以这个数取自 bmodel 自己的声明，而不是运行时采样 —— 两者
在 MYS-2615 上对过，一致。

### 与 PaddleX 的偏差

| 项 | 本文实现 | PaddleX | 影响 |
|---|---|---|---|
| 一行落进多个区域 | 取面积最小的 | 裁交集、对每个区域重跑识别 | 跨框的行只保留一份文字；对同一批图无差异（见 `tests/test_ocr_layout.py`） |
| 区域检测（`PP-DocBlockLayout`） | 不跑，整页算一个 region | 跑，再在每个 region 内排一次 | 单 region 正是 PaddleX 在没有区域结果时的回退路径；多栏页仍按 x 投影分栏，双栏测试图逐行正确 |
| 标题与相邻碎文本框合并 | 不实现 | `update_doc_title_child_blocks` 等 | 多一个正文块，不会少文字 |
| Python 包 `paddlex` 依赖 | **无**，全是 numpy 转写 | 需要 | 板子跑得动 |

### 按需加载与「缺第 5 个文件」

- 版面 bmodel 在**第一次 `layout` 请求时**才加载（与 rec 档位同一机制）。只用
  `lines` 的部署永不占用这部分 NPU 内存（约 21.5 MB）。
- 老的**四文件**安装收到 `layout` 请求时返回 **400**，消息里写明缺的文件名，并指向
  控制台「模型」页的「更新」。`lines` 模式不受影响。
- 目录里的**「有新版本」检测能识别**这个缺失：`update_status` 按 tag 索引给出的
  **文件名单**与目录实际内容比对，四文件目录相对五文件清单恰好缺一个，
  `missing_files` 就是那个版面文件名。**前提是 dfss 上已经有
  `cv84x6_llm_ppdoclayout-m` 这个 tag**——这是负责人上传后才成立的事，
  `tests/test_dflag.py::test_a_directory_missing_only_the_layout_model_reports_an_update`
  钉住了这条逻辑。
- `kind` 判定仍是 `ocr`：`ppdoclayout-…` 这个文件名不属于 `ppocr` 前缀，而它又排在
  `ppocrv6-medium-det_…` **之前**，所以不加前缀规则的话模型类型会变成 `chat`。
  `KIND_PREFIXES` 里因此多了 `ppdoclayout` / `pp-doclayout` 两条。

## `mode: "vl"`：整页 VL 识别

整页进，**每个区域一次 PaddleOCR-VL** 出，Markdown 出。与 `layout` 用同一个版面模型、
同一套阅读顺序和同一套 Markdown 规则；差别只在「区域里的文字由谁读」：

| | `layout` | `vl` |
|---|---|---|
| 读取者 | PP-OCR（det + 三档 rec） | PaddleOCR-VL-1.5 |
| 提示 | 无（CTC 只认字） | 按区域类别给 `OCR:` / `Table Recognition:` / `Formula Recognition:` |
| 表格 | 一行文字，结构不还原 | **HTML，`rowspan`/`colspan` 都在** |
| 公式 | 原样文字 | LaTeX（`\(…\)` 归一成 `$…$`） |
| 模型数 | 1（ocr） | **2**（ocr 提供版面 + ocr_vl 提供识别） |
| 每页耗时 | 百毫秒级 | 每个区域一次 VL 推理，整页通常几十秒 |

### 为什么是两个模型、两个 worker

PP-DocLayout-M 和 3.3 GB 的 VL bmodel **不能在同一个进程里同时装载**：先跑版面
再在同一进程 `bmrt_load_bmodel` 会直接失败（`docs/ocr-vl.md` §6.1，MYS-2660 实测）。
所以 `vl` 是两次 RPC：

```
API 进程
  ├─ op: detect_page  → ocr worker  ──→ 区域列表（label / score / box）
  └─ op: ocr_page     → ocr_vl worker ─→ 每个区域裁剪 → VL → OTSL→HTML → 整页 Markdown
```

**不走 HTTP 回环**：API 进程同时是两个 worker 的客户端，一次整页就是两次 socket
往返。VL 的排队规则与聊天请求共用同一把引擎锁（`serial_only`），粒度是**一个区域**：
每个区域取锁 → 推理 → 释放。页面进行中到达的聊天请求等在当前区域之后，而不是等整页；
两边不会共用同一份 KV。

### 请求与响应

请求与 `layout` 完全一样，只是 `mode` 换成 `"vl"`：

```bash
curl -s http://<板子>:8000/v1/ocr \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"ppocrv6-medium","image":"<base64 或 data: URL>","mode":"vl"}'
```

响应结构与 `layout` 相同（`text` 为整页 Markdown，`blocks` 按阅读顺序），另外：

| 字段 | 说明 |
|---|---|
| `blocks[].task` | 这个区域用的提示（`OCR:` / `Table Recognition:` / `Formula Recognition:`）；**图片类区域为 `null`**，因为没让模型读 |
| `blocks[].text` | 表格是 HTML；图片类区域是占位符（`[图片]` 等）；其余是模型输出（已做 LaTeX 归一） |
| `blocks[].lines` | 恒为 `[]`：VL 的输出是「一个区域的文本」，没有行级几何 |
| `usage.vl_ms` | VL 的时间合计（vit + prefill + decode，整页累加） |
| `usage.vl_tokens` | VL 整页生成的 token 数 |

`lines` 与 `layout` 两个响应**逐字节不变**：`task`、`vl_ms`、`vl_tokens` 在另外两个
模式下**不出现**（不是 `null`），`tests/test_ocr_api.py` 钉住了键集合。

### 缺模型的 409

`vl` 要两个模型都在位。任一缺失时是 **409**，消息写明要加载哪一个：

- **PaddleOCR-VL-1.5 没加载** —— 409，消息给出模型名，并提示可以退回 `layout`。
  它**不会自动加载**：3.3 GB 常驻，和 `chat` 一样属于操作员的显式决定
  （`AUX_KINDS` 不含 `ocr_vl`）。
- **OCR 模型没加载**（也就没有版面 bmodel）—— 走 `/v1/ocr` 原有的准入检查，同样是 409。

**检查发生在任何 NPU 工作之前。** 版面一次前向是 400 ms 量级，为一个注定 409 的请求
先花掉它不划算；也让调用方先拿到「加载哪个模型」的答案。

### Markdown 与 `layout` 的差别

只有两条规则不同（其余全部复用 `ocr_layout` 的 label→格式表，两个模式不该把同一页
渲染成两种样子）：

- **表格**原样输出 HTML（`layout` 是「仅文字 + 一行注释」）。模型若没给 OTSL（答了
  正文），退回 `layout` 那种纯文本并标注，而不是输出一张空表。
- **图片**只输出占位符（`layout` 会附上区域内 OCR 到的文字——`vl` 根本没读它）。

### 区域合并（`merge_blocks`）

版面的原始框会先按 PaddleX 的 `merge_blocks` 合并，再交给 VL。规则窄得容易写错，
所以是从 `uilts.merge_blocks` 逐条转写的：

- 只有非豁免类别参与合并（豁免 = 图片类 + `table`，即 `non_merge_labels`）；
- `is_cross`：两个 `text` 框**左右并排**在同一行（水平投影不重叠、垂直重叠、
  间隙 < 较宽者 30%）——一句话被切开的两半；
- `is_updown_align`：两个 `text` 框**上下相接**，左右边只对齐一条（异或），
  间隙 < 较高者一半，**并且**两框的凸包盖住某个豁免块（夹在两段之间的图）；
- 合并后的堆叠图 **≥ 3:1** 时不合并，退回各自成块。

一个组只**识别一次**（堆叠图），答案记在组的第一块上，后续块的 `text` 为空——
这就是响应里 `blocks` 数可能多于 VL 实际调用次数的原因。

### 单项失败不会毁掉整页

某个区域的 VL 调用失败时，那个 `block` 带上 `error`、`text` 为空，其余区域照常返回，
Markdown 里跳过它。一页丢掉一张表，对调用方仍然有价值；回一个 503 则一无所有。

## 一个模型 = 一个目录 + 五个 bmodel

目录 `models/ppocrv6-medium/` 里放 det、三档 rec，以及版面模式的 PP-DocLayout-M：

```
ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel          74.9 MB
ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel       50.9 MB
ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel       46.1 MB
ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel      51.1 MB
ppdoclayout-m_f16_640_bm1684x2_static_20261104.bmodel               18.2 MB
```

- worker 加载 **det**（文件名的 `-det` 是判据），rec 三档与版面模型**按需加载**：一页
  只跑 320 的图片永远不会占用 1600 模型，只用 `lines` 的部署永远不占用版面模型。
  缺 det 或任何一档 rec，加载直接失败并列出缺的文件名。
- 版面模型是可选的**加载期**依赖：只有第一次 `layout` 请求才需要它（见上节）。
- `CATALOG` 里这一条用 `files: [...]` 声明五个文件：一次下载任务把它们逐个拉到暂存
  目录，**全部到齐并校验 md5 之后**才一次性移进 `models/ppocrv6-medium/`。中途失败或
  取消不会留下一个看起来能加载的目录。
- NPU 准入按**五个文件之和**（约 241 MB）+ 256 MiB 余量算，不是只算 det。
- **为什么是 M 不是 S**：PP-DocLayout-S 把表格判成 `image`（`cn_table_simple` S 给
  `image 0.708`、M 给 `table 0.786`），而表格正是版面模式要报出来的区域。S 更小更快
  （5.3 MB / 0.97 ms vs 21.5 MB / 2.88 ms），只做纯文本版面才够用
  （[`ocr-structure.md`](ocr-structure.md) §2）。
- 配置（`ppocr.json`、字典 `ppocr_keys_v1.txt`）随 deb 发布，所以 dfss 只下一个 bmodel
  集合就是完整的模型目录。

`rec` 按裁剪框的**宽高比**选档（`ppocr.json` → `rec.width_selection`）：

```
ratio = crop_w / crop_h
ratio * 1.15 <= 6.667   -> 320   (输出 [1, 40, 18710])
ratio * 1.15 <= 13.333  -> 640   (输出 [1, 80, 18710])
ratio * 1.15 <= 33.333  -> 1600  (输出 [1, 200, 18710])
否则                     -> 1600  (截断在 1600)
```

1.15 是实测的挤压容忍度：略长的行用窄档更便宜，且看不出来。**640 单独不够**：
`en_report.png` 有 34.8:1 的正文行，压进 640 等于横向挤 2.3 倍，同一裁剪在 1600 上
完全正确。

## 前后处理在哪，为什么

| 步骤 | 实现 | 理由 |
|---|---|---|
| det 预处理（resize/归一化/CHW/补零） | numpy + OpenCV，`app/engine/ocr_ppocr.py` | 数值要与 golden（onnxruntime）逐位对齐，放在 Python 里才能被 x86 测试直接验证 |
| det 前向 | NPU，通用单图 ABI `cv_net_*` | 一张静态图进、一张静态图出，与 chat/embed 的图结构假设无关 |
| DB 后处理（阈值/轮廓/minAreaRect/unclip/缩放回原图） | numpy + OpenCV + **pyclipper** | 同上；参数来自 `ppocr.json`，不是代码常量 |
| 四点透视校正裁剪 | OpenCV `getPerspectiveTransform` + `warpPerspective` | **不是外接矩形**：7° 倾斜行的外接矩形比字高好几倍，识别器看到的是糊掉的旋转 |
| rec 前向 | NPU，同一个 `cv_net_*` | 三档只是输入宽度不同 |
| CTC 贪心解码 | numpy | 图里已经带 Softmax，再算一次会看着合理但是错的 |

**参数一律读 `model-config/ppocr_v6/ppocr.json`**，包括 det 的
`thresh=0.2 / box_thresh=0.45 / unclip_ratio=1.4 / max_candidates=3000`。
sophon-demo 的 `ppocr_det_opencv.py` 里写死的是 **v4** 的 `0.3/0.6/1.5`，用 v4 的数
会丢掉 v6 故意输出的低置信框。

## 依赖：OpenCV 用设备的，pyclipper 随包

| 依赖 | 来源 | 说明 |
|---|---|---|
| `cv2` | **设备自带**的 sophon-opencv（`/opt/sophon/sophon-opencv-latest/opencv-python`，4.8.0） | 与 ffmpeg 同一原则：SDK 拥有这个构建，不 vendor。worker 启动时把该目录加入 `sys.path`；导入失败即**加载失败**，消息说明缺 sophon-opencv |
| `pyclipper` | `scripts/package.sh` `--no-deps` vendor（manylinux2014 aarch64 cp310） | DB 的文本框外扩需要，设备上没有 |
| `numpy` | 同上 | 所有前后处理算术 |

这些都在 **worker** 侧：API 进程从不解码图片，所以没有第二份实现需要同步。

## worker 协议

```
-> {"op":"ocr","req_id":"x","image_b64":"<base64>","mode":"lines"}
<- {"op":"ocr_result","req_id":"x","mode":"lines","text":"...","lines":[...],
    "det_ms":41.2,"rec_ms":88.5,"width":1240,"height":1754}

-> {"op":"ocr","req_id":"x","image_b64":"<base64>","mode":"layout"}
<- {"op":"ocr_result","req_id":"x","mode":"layout","text":"<Markdown>","lines":[...],
    "blocks":[...],"layout_ms":3.1,"det_ms":41.2,"rec_ms":88.5,"width":…,"height":…}
```

`mode` 在 **worker 里校验**（不只 API）：控制台的 `/api/test/ocr` 与 MCP 都直接落到
这个 op，第二份规则放在 API 会漏掉它们。`mode` 缺省时**整个字段不出现**，所以
`lines` 模式的请求帧与本功能之前逐字节相同。

图片走 socket 而不是共享路径，理由与音频相同：OpenCV 和变换参数都在 worker 侧。
一次 OCR 的超时是 300 秒——一页密排 A4 约 100 行、每行约 30 ms，这个上限约束的是
"NPU 卡住"，不是正常工作。

## 推理记录

一次请求一条记录：

| 字段 | 内容 |
|---|---|
| `source` | `/v1/ocr` |
| `output_text` | 响应里的 `text` |
| `messages` | `{"image": {"bytes": <字节数>}}`（multipart 时多一个 `filename`） |
| `params` | `return_boxes` + `mode` + worker 测出的 `width`/`height` + `lines`（行数）；`layout` 时多一个 `blocks`（区域数） |

**图片本身从不落盘**：记录里只有尺寸和字节数。像素留在 request 里，不留在日志里。

## 板上实测（`.151`，SN `HQDZCVEBFJIJA0027`）

四个 bmodel 经控制台下载 API → 校验 md5 → 装入 → 加载 → 对 golden 的 7 张图调用
`POST /v1/ocr`（multipart）。OpenCV 4.8.0（设备自带 sophon-opencv），numpy 1.21.5。

| 图 | 行数 | 文本与 golden 一致 | 最大框偏差 | HTTP 耗时 |
|---|---|---|---|---|
| `cn_notice.png` | 17 | 17/17 | 0 px | 1309 ms |
| `en_report.png` | 17 | 17/17 | 3 px | 795 ms |
| `mixed_spec.png` | 19 | 19/19 | 0 px | 749 ms |
| `skewed_lines.png` | 6 | 6/6 | 0 px | 415 ms |
| `table_stats.png` | 26 | 26/26 | 4 px | 647 ms |
| `ui_status.png` | 11 | 11/11 | 0 px | 305 ms |
| `vertical_text.png`（竖排，仅要求不报错） | 7 | 7/7 | 0 px | 233 ms |

- **逐行文本一致率 96/96 = 100 %**（横排 6 张；验收线 98 %）。竖排那张本卡不参与
  一致率，实际 7/7 也与 golden 一致——比配置文档预期的更好，见下。
- **框坐标：96 个框里 93 个与 golden 逐像素相同，95 个在 3 px 内，1 个 4 px。**
  逐行文本与框是同一份 golden 上的两件事，所以这个 4 px 单独说明：
  - **归因实验一（算术）**：把 **golden 自己的 f32 概率图**喂给本实现的
    `det_postprocess`，在板上得到 `table_stats.png` **26/26**、`en_report.png`
    **17/17** 个框与 golden **逐像素一致（0 px）**。即前后处理算术与生成 golden 的
    那一份逐位一致，偏差不来自本实现。
  - **归因实验二（bmodel）**：NPU 的 f16 图与 onnxruntime 的 f32 图相比，均值差
    4e-5、最大 3.6e-2，超过 `thresh=0.2` 的像素差 **22 / 24 个**（共约 21000）。
    DB 的轮廓与 minAreaRect 就建在这些边缘像素上：`table_stats.png` 第 24 个框
    一侧从 124 变成 128，**一条边平移 4 px**。
  - **归因实验三（敏感性）**：在 NPU 图上把 `thresh` 扰动 ±0.004，该框在 2~4 px 之间
    移动；`en_report.png` 的同一条在 `thresh+0.002` 时回到 **0 px**。即偏差量级与
    "轮廓落在概率分布边缘"一致，是 f16 累加与 f32 参考之间的正常数值差。
  - 三个实验都在 `tools/ocr/attribute_box_deviation.py` 里，一条命令可复现。
  - 因此验收表里 `RESULT: FAIL` 是**如实报告**：按"每个框 ≤ 3 px"的原文 1 个框超出。
    判据本身没有放宽，`--allow-box-outliers` 只是让一次未达标运行能把它为什么未达标
    记录下来。
- **耗时**：det 中位 114 ms，rec 中位 459 ms/图（17 行的一张 rec 合计 1.1 s，因为每行
  一次前向）。HTTP 端到端 233–1309 ms，与行数成正比。
- **NPU 占用**：加载 154 MiB，峰值 230 MiB（rec 三档按需加载，1600 档在被用到时才映射），
  卸载后 **0 MiB**。准入检查按四个文件之和 + 256 MiB 计。
- **下载链路**：`open.sophgo.com` 在本站 DNS 解析不到（板上 DNS 正常，PyPI 可解析），
  所以 dfss 拉取无法在 `.151` 上端到端验证；用本地 http 服务器提供四个真实 bmodel 走
  `POST /api/downloads` 的 `files` 路径验证了**逐文件 md5 校验 → 四个文件全部到位才
  一次性装入 → 扫描出 `kind=ocr`、4 个 bmodel**，全部通过。
  dfss 那一段只差厂商主机可用性，代码路径与 url 路径共用同一份校验/装入逻辑。

### 竖排为什么和配置文档说的不一样

`model-config/ppocr_v6/README.md` 记录竖排样本 0/7（那是与**官方 paddleocr** 对比），
而 golden（onnxruntime + 本实现的前后处理）对同一张图是 7/7。两者不矛盾：本实现与 golden
是同一套确定性算术，所以逐行全等；paddleocr 参考对竖排给出了不同的切分与识别结果。
**能力限制没有改变**——竖排确实读不出正确内容，只是 golden 把"错误的读法"也固定下来了。
这一点在接口文档里作为限制保留。

### x86 参考与真机对照（MYS-2640 验收 3、4）

两边跑**同一份切过的 ONNX + 同一份 numpy 尾部**，只差执行引擎；参考侧用 PaddleX 自己的
`create_predictor("PP-DocLayout-M")` + `xycut_enhanced` 排序，所以区域数、类别、阅读顺序
都能逐项比。

```
python3 tools/ocr/compare_layout.py \
    --layout-onnx /mnt/sda2/cv84x6_llm_server/build_ocr/struct/onnx/PP-DocLayout-M_cut.onnx \
    --ppocr-dir /mnt/sda2/cv84x6_llm_server/build_ocr/work \
    --images tests/data/ocr/img/{cn_notice,en_report,mixed_spec,twocolumn}.png
```

| 图 | 区域数（本实现 / x86 PaddleX） | 类别一致 | 阅读顺序一致 |
|---|---|---|---|
| `cn_notice.png` | 10 / 10 | 10/10 | 45/45 |
| `en_report.png` | 5 / 5 | 5/5 | 10/10 |
| `mixed_spec.png` | 3 / 3 | 3/3 | 3/3 |
| `twocolumn.png` | 6 / 6 | 6/6 | 15/15 |
| **合计** | **24 / 24** | **24/24** | **73/73** |

**差异：无。** 没有「本实现多一个框」「PaddleX 多一个框」「类别不同」的条目，也没有
顺序反转的配对。

真机 `.157` 用分支代码旁挂实例（`/data/layout-2640`，端口 8031）跑同样四张图，
与上面的 x86 结果逐区域比对：

| 图 | 区域数 | 类别 | 每个区域的 `box` | 每个区域的 `text` |
|---|---|---|---|---|
| `cn_notice.png` | 10 | 相同 | 逐坐标相同 | 逐字符相同 |
| `en_report.png` | 5 | 相同 | 逐坐标相同 | 逐字符相同 |
| `mixed_spec.png` | 3 | 相同 | 逐坐标相同 | 逐字符相同 |
| `twocolumn.png` | 6 | 相同 | 逐坐标相同 | 逐字符相同 |

双栏那张的阅读顺序在板上是：标题 → 左栏第一段 → **右栏第一段** → 通栏段落 →
左栏第二段 → 右栏第二段，与 `tests/data/ocr/twocolumn_truth.json` 一致，没有交错。

**MCP `ocr_read`（`mode: "layout"`）读一份扫描 PDF**：两页（`cn_notice` +
`twocolumn` 各渲染成一页，无文字层），两页都走版面识别，第一页输出 `#` 标题 + 三个
`##` 小标题的 Markdown，第二页输出两栏正确的顺序。同一份 PDF 在 `lines` 模式下
第一页 17 行、第二页 15 行，是交错顺序 —— 这正是两种模式的区别。

## 复现

```bash
# 板上编库
rsync -az native/ linaro@<board>:/data/ocr-test/native/
ssh linaro@<board> 'cd /data/ocr-test/native && cmake -B build && cmake --build build -j8'

# 后端直测（前后处理 + NPU），以及 HTTP 端到端
python3 tools/ocr/board_acceptance.py --model-dir <bmodel 目录> \
    --lib <libcv84x6_llm.so> --repo <checkout>
python3 tools/ocr/board_http_acceptance.py --repo <checkout> --lib <lib>  --port 8099
python3 tools/ocr/board_download_check.py --repo <checkout> --lib <lib> --target /data/ocr-test/dl
```

判定框偏差来源时用 `tools/ocr/` 里的两个一次性探针（不进发布包，命令写在文件头的注释里）：
`arith.py` 把 golden 自己的 f32 概率图喂给本实现，`perturb.py` 把阈值上下扰动看框怎么动。
前者为 0 px 即说明算术一致、偏差来自 bmodel 的 f16。

重跑真机验收：

```bash
# 1. 板上编库（通用 ABI 是新增符号）
rsync -az native/ linaro@<board>:/data/ocr-test/native/
ssh linaro@<board> 'cd /data/ocr-test/native && cmake -B build && cmake --build build -j4'
nm -D build/libcv84x6_llm.so | grep cv_net        # 6 个符号

# 2. 打包安装
bash scripts/package_deb.sh --lib <板上编出的 libcv84x6_llm.so> --config <qwen3_5 配置目录>
sudo dpkg -i dist/cv84x6-llm-server_*_arm64.deb

# 3. 控制台一键下载 ppocrv6-medium，然后加载

# 4. 识别
curl -s -H "Authorization: Bearer $KEY" \
     -F file=@page.png -F model=ppocrv6-medium localhost:8000/v1/ocr
```

操作前先 `pgrep -c bmrt_test` 确认没有别人在跑 NPU 测试。
