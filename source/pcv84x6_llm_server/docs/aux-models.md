# 辅助模型：Embedding、Rerank 与 ASR

本服务除 chat 模型外还提供三类**辅助模型**，各自走标准接口：

| 类型 `kind` | 模型 | 接口 | 参考实现 |
|---|---|---|---|
| `embedding` | Qwen3-Embedding-0.6B（1024 维，last-token pooling + L2，支持 MRL 截断到 32） | `POST /v1/embeddings` | LLM-TPU `models/Qwen3_Embedding` |
| `embedding` | Qwen3-VL-Embedding-2B（图文，2048 维，MRL 64–2048） | `POST /v1/embeddings` | [部署与输入契约](qwen3-vl-embedding.md) |
| `embedding` | WeMM-Embedding-2B（Qwen3.5 底座，图文，2048 维） | `POST /v1/embeddings` | [部署与输入契约](wemm-embedding.md) |
| `rerank` | BGE-Reranker-v2-M3（XLM-R cross-encoder，一个 logit/对） | `POST /v1/rerank`、`POST /rerank` | LLM-TPU `models/Bge_Reranker_V2_M3` |
| `asr` | Qwen3-ASR-1.7B / 0.6B（bf16，seq1024，13 token/秒） | `POST /v1/audio/transcriptions` | LLM-TPU `models/Qwen3_ASR` |

第四类 **`ocr`（PP-OCRv6 det+rec，`POST /v1/ocr`）** 有自己的文档：
[`ocr.md`](ocr.md)。它与本文这三类的共同点（`kind` 判定、`--kind` worker、
`_check_npu_admission`、`aux_backend` 的串行锁、`AuxRequestError`/`AuxBusy`/
`AuxNativeError` 的映射、推理记录写法）是照搬的，不同点都在那份文档里。

三者都在板上实测复现参考 pipeline 的数值/文本（`.151`）：

- embedding 参考用例（query 带 instruction，文档不带）→ **0.6405 / 0.1494 / 0.5267**
- rerank 参考用例（`--normalize`）→ **0.8429 / 0.0003**
- ASR 两种规格的转写与 HF 参考一致（见 [§ ASR 真机结果](#asr-真机结果)）

## 类型从哪来

`kind` 是 **bmodel 文件名**的属性，不是配置项：`qwen3-embedding*`、`qwen3-vl-embedding*`、`wemm-embedding*` → `embedding`，
`bge-reranker*` → `rerank`，`qwen3-asr*` → `asr`，其余 → `chat`。同一个值出现在
`/api/models`、`/api/catalog`、`/v1/models`，并作为 `--kind` 写进 worker 命令行——
所以重启后的进程接管也按它匹配：`--kind` 对不上的 worker 不会被当成"我们的"。

`/v1/chat/completions`、`/api/chat`、`/api/chat/stream` 收到非 chat 模型返回 400 并
指出该调哪个接口；三个辅助接口收到类型不符的模型同样 400。
未加载/加载中是 409，模型不存在是 404——与 chat 接口一致。

## `POST /v1/embeddings`

OpenAI 形状，鉴权同 `/v1/chat/completions`。

| 字段 | 说明 |
|---|---|
| `model` | 必须是 `embedding` 模型 |
| `input` | 字符串或字符串数组，一次最多 **64** 条；空串 400；**token 数组 400**（服务端不暴露分词器，接受它就只能假装） |
| `encoding_format` | `float`（默认）或 `base64`（little-endian float32） |
| `dimensions` | 32 到隐藏维度之间；MRL 截断**在归一化之前**，所以截断后范数仍为 1 |
| `instruction` | 非标准，可选；拼在每条 input 前面 |

上述表格描述纯文本 Qwen3-Embedding。**Qwen3-VL-Embedding / WeMM-Embedding-2B** 还接受单个
`{"text": "描述", "image": "data:image/jpeg;base64,..."}` 对象及与字符串混合的数组，
两字段至少提供一个。其 `instruction` 是系统指令，`dimensions` 范围是 **64–2048**。
图片仅接受调用方上传的 JPEG/PNG data URL；每条一张，单张 4 MiB，每批最多 16 张、
总计 16 MiB。网络 URL、本地文件路径和视频均返回 400。两类模型的向量空间不同，
不能混用已有索引。完整示例见 [Qwen3-VL](qwen3-vl-embedding.md) 和
[WeMM](wemm-embedding.md)；两者默认指令和图片最小预算不同。

单条超过 bmodel 的 SEQLEN（Qwen3-Embedding 默认档为 **2048**，短文本档为 **512**）返回
400 并给出**该模型自己的**上限——截断后静默返回一个"只是前 N 个 token 的向量"比报错更糟。
调用方按 `model` 字段选档：`/v1/embeddings` **不做自动选档**，短文本档收到 513 token 就是
400，不会替你换成长档。

**SEQLEN 从 8192 降到 2048 是 MYS-2696 的改动**，原因是静态图：bmodel 是 `_static_`
的，一次前向固定跑满编译时的长度，与输入多长无关。`.157` 实测单条 8192 → 2811 ms、
2048 → 291 ms。padding 被 mask 掉，所以向量不变（24 条 1..1932 token 的混合文本，
最小余弦 0.99963），**已有知识库不需要重建**。新 bmodel 是我们自己编的
（`tools/embed/build_bmodel.sh`），发布在 `/tools/cv84x6_llm_server/` 下并带下载标签，
已装 seq8192 的板子会在控制台看到「有新版本」。

### 两档静态图：seq2048（默认）与 seq512（短文本档，MYS-2706）

同一份权重编了两个长度，目录里因此有**两个** embedding 条目：

| id | `context` | 单条（10 次中位） | 加载后 NPU | 定位 |
|---|---|---|---|---|
| `qwen3-embedding-0.6b` | 2048 | 292 ms | 1465 MiB | **默认**，长切片一次前向 |
| `qwen3-embedding-0.6b-seq512` | 512 | **82 ms** | 1217 MiB | 短文本/省内存，超 512 token 的切片走切分汇聚 |

单条那一列是 `.157` 实测（`tools/embed/seq512_bench.py`，`libcv84x6_llm.so`，四个 41–74
token 的中文输入各 10 次取中位；静态图跑满编译长度，所以文本多长都一样）。走 HTTP 时
seq512 中位 **105 ms**。服务里每个模型是独立的 worker 进程，两档**同时**加载时 NPU 占用
是两者之和，约 **2682 MiB**（1465 + 1217），见 `model-settings.md`。

短档**不默认下载、也不默认加载**：默认档不变，装不装、加载哪个由操作员决定，两档有各自的
下载标签。

**两档的向量互通**，这是能随便切的前提。seq512 与 seq2048 逐条余弦**相同到 7 位小数**
（在两者都接受的文本上），seq2048 与旧 seq8192 最小 0.99963（`docs/research/aux-dynamic-seq.md`
§5、§7）。所以：

- 用其中一档建的知识库，可以用**另一档**继续入库和检索，不需要重建；
- 只有**跨模型族**才需要重建（例如换成别的 embedding 模型）。

实现上这是目录条目里的新字段 **`vector_family`**：两档都填 `qwen3-embedding-0.6b`。
建库的「向量由谁建立」检查（`app/apps/kb/ingest.py`）、检索选模型
（`app/apps/kb/retrieval.py`）、重建（`app/api/apps_api.py`）都改成**按族判断**，
并且在记录的模型没加载时优先把**同族已加载的另一档**用起来。知识库的
`embedding_model` 仍记录**实际建库时用的那个 id**，所以看得到每库跑在哪档上。

不同族之间照旧拒绝，文案不变（`... 与该库建索引时使用的 X 不一致；向量空间不可比 ...`）。
`/api/models` 的每个模型新增 `vector_family`（非 embedding 模型为空串）；**目录里没登记
的 embedding 模型以它自己的 id 作为族**——手装的未知 build 一律当成独立族，宁可拒绝
也不写进无法比较的向量。

短档的代价在切片上：`MAX_CHUNK_CHARS = 1000` 的切片经常超过 512 token，入库时会走
既有的「被拒就对半切开、向量取均值再归一化」路径（`Ingestor._embed_fitted`，
PR #120），**不新增逻辑**。`.157` 实测一份 227 切片的中文语料：**7/227 = 3.1%** 的切片
超过 512 token（都是 1000 字符、605 token 的整块无标点 CJK），它们各多花一次前向；
其余 96.9% 一片一次。同一份语料建库 **68.6 s → 21.6 s**（seq2048 → seq512，
`tools/embed/board_kb_seq512.py`）。所以短档适合短文本/FAQ 与已经切得较细的库；整块
1000 字无标点的长文档比例越高，省下来的越少。

参考用例的 instruction（检索查询用，文档不加）：

```
Instruct: Given a web search query, retrieve relevant passages that answer the query
Query:
```

**这个词不能改**：把 `query` 写成 `question`，上面那三个相似度就会变成
0.6393 / 0.1521 / 0.5287——超出 0.002 的验收容差。`tests/test_aux_tokenize.py`
逐字固定了它。

## `POST /v1/rerank`（别名 `POST /rerank`）

Jina/Cohere 形状（OpenAI 没有 rerank 接口，这是 Dify / RAGFlow / LangChain 的事实标准）。

| 字段 | 说明 |
|---|---|
| `model` | 必须是 `rerank` 模型 |
| `query` | 非空字符串 |
| `documents` | 字符串数组，或 `{"text": ...}` 对象数组（两者可混用），一次最多 **256** 条 |
| `top_n` | 可选，排序后截断 |
| `return_documents` | 默认 `true`；`false` 时只回 `index` 与分数 |

结果按 `relevance_score` **降序**，`index` 指**原始输入位置**（排序不重新编号）。
分数是 `sigmoid(logit)`，落在 [0, 1] 且排序与 logit 一致。

## `POST /v1/audio/transcriptions`

OpenAI 标准形状，`multipart/form-data`，鉴权同其他 `/v1` 接口。

| 字段 | 说明 |
|---|---|
| `file` | 必填，≤ **50 MB**；WAV 直接解码，其他容器经 ffmpeg |
| `model` | 必填，必须是 `asr` 模型，否则 400 |
| `language` | 可选，交给 `build_prompt`。接受规范名（`Chinese`）或 ISO-639-1（`zh`），未知返回 400 并列出可用值 |
| `prompt` | 可选，作为上下文/system prompt 交给模型 |
| `response_format` | `json`（默认，`{"text": ...}`）、`text`（纯文本）、`verbose_json`、`srt`、`vtt` |
| `temperature` | 接受但**忽略**：本引擎贪心解码，假装采样会让两次相同请求结果不同。值域外的数字仍返回 400 |

`verbose_json` 返回 OpenAI 的字段集合：`task`、`language`、`duration`、`text`、
`segments`（每段 `id/seek/start/end/text/tokens/temperature/avg_logprob/
compression_ratio/no_speech_prob`）与 `usage`。

### 长音频：切段与时间戳

一个提示词能装多少音频由 bmodel 的 `MAX_INPUT_LENGTH` 决定：

```
每段秒数 = min( SEQUENCE_CAP, floor((MAX_INPUT_LENGTH - 提示词骨架 - 8) / 13) )
```

`MAX_INPUT_LENGTH=512`、骨架约 15 token、13 token/秒时算出 **37 秒**；代码再取上限
**30 秒**（`SEGMENT_CAP_SECONDS`）。`language` 和 `prompt` 都会占 token，所以这个
长度按**实际提示词**重算，不是常量。

更长的音频按整秒切段，逐段转写后按顺序拼接，每段一个 segment，`start`/`end` 首尾相接。
最后不足一秒的尾巴**补零到整秒**再提取特征，而不是丢掉——参考实现的
`y[:(len(y)//sr)*sr]` 会丢掉它，而那通常正是最后一个字。补零在**波形域**做：mel
特征域的 0 不等于静音（零功率的 log-mel 是 -1.5，不是 0），在特征上补零等于给音频塔
一个阶跃。

整段音频上限 **30 分钟**，超过返回 400（`MAX_AUDIO_SECONDS`）。

### 输出文本的解析

参考 pipeline 在生成循环里遇到 `<asr_text>` 就清空缓冲，所以最终打印的是标记**之后**
的内容。本服务对整段输出施加同一条规则：模型回显的 `language Chinese` 前缀被丢掉，
`language` 字段单独报告。生成里若没有 `<asr_text>` 但有 `language X` 前言（生成被截断），
前言也丢掉——回显不是转写结果。

解码到半个 UTF-8 字符时丢弃而不是输出 U+FFFD，与参考的 `if "�" not in word` 一致。

### 415 与 400 的分界

| 情况 | 状态码 |
|---|---|
| 非 WAV 且本机无 ffmpeg；或 ffmpeg/内置解码器无法解码 | **415**（音频的格式问题，不是请求格式问题） |
| 超过 50 MB、超过 30 分钟、未知语言、字段缺失/重复、`Content-Type` 不是 multipart | **400** |
| 模型未加载 / 加载中 | 409 |
| 模型不存在 | 404 |

### ffmpeg

目标设备自带 Sophon SDK 的 ffmpeg，在 `/opt/sophon/sophon-ffmpeg-latest/bin/ffmpeg`
（链接到 `sophon-ffmpeg_2.3.0`），**不在 PATH 中**。查找顺序：

1. 环境变量 `CV84X6_FFMPEG`（显式指定，指向不存在的文件时报"无 ffmpeg"而不回退——
   拼错了不该悄悄换一个二进制跑）
2. `shutil.which("ffmpeg")`（发行版安装，x86 开发机的情形）
3. `/opt/sophon/sophon-ffmpeg-latest/bin/ffmpeg`
4. `/opt/sophon/sophon-ffmpeg_*/bin/ffmpeg`（取版本号最大的，按数字比较）

**服务自身不安装 ffmpeg**，也不提供下载。没有 ffmpeg 的设备只支持 WAV，并在 415
里说明。

### 上传解析

`multipart/form-data` 由 `app/api/audio_upload.py` 自行解析，不走 starlette 的
`request.form()`：发布包不 vendor `python-multipart`，而且它的 `max_part_size` 只限制
非文件字段，一个 2 GB 的上传会先落到 `/tmp` 才被拒。自带的解析器在**读取过程中**
按 `Content-Length` 和实际字节双重计限，超限立即放弃请求。

## `POST /api/apps/asr/transcriptions/stream`（逐段流式，SSE）

长音频的演示前端用它：30 分钟音频按 30 秒切段，**每转完一段推一段**，界面边转边显示
进度，不需要等两分钟才看到第一个字。`/v1/audio/transcriptions` 的行为完全不变。

| | |
|---|---|
| 鉴权 | admin 会话 cookie（与 `/api/test/*` 相同），**不认** bearer key |
| 请求 | `multipart/form-data`，字段与 `/api/test/audio/transcriptions` 相同：`model`、`file`、可选 `language`、`prompt` |
| 响应 | `text/event-stream`，每帧 `data: <json>\n\n` |

```json
{"type":"meta","duration":95.5,"segments_total":4,"segment_seconds":30,"language":null}
{"type":"segment","id":0,"start":0.0,"end":30.0,"text":"…","infer_ms":2412.7}
{"type":"segment","id":1,"start":30.0,"end":60.0,"text":"…","infer_ms":1180.4}
…
{"type":"done","text":"<与非流式完全相同的拼接全文>","language":"Chinese",
 "duration":95.5,"usage":{"prompt_tokens":930,"completion_tokens":118,"total_tokens":1048},
 "infer_seconds":5.21}
{"type":"error","detail":"<中文原因>"}
```

- `meta` 在**解码之后、第一段 NPU 推理之前**发出，所以界面在引擎还空着的时候就拿到
  总时长和段数，可以画进度条。`duration` 是音频原长（秒）。
- 每段的 `start`/`end` 是它在文件里的时间，首尾相接；`infer_ms` 是该段 NPU 调用的耗时。
- `done.text` 与 `/v1/audio/transcriptions` 的 `text` **逐字相同**，各段文字与
  `verbose_json` 的 `segments` **逐字相同**——两条路径共用同一个切段函数
  （`aux_backend.segment_plan`）和同一个拼接函数（`aux_backend._summarise`），
  非流式的 `transcribe` 就是流式生成器收集起来的结果，不是第二份实现。
- `error` 只在**流已经开始之后**才出现（推理中引擎出错）。流开始之前的失败一律是
  HTTP 状态码，见下表。

### 状态码与 `error` 帧的分界

| 情况 | 响应 |
|---|---|
| 未登录 | 401 |
| 模型不存在 / 未加载或加载中 / kind 不符 | 404 / 409 / 400（与 `/v1` 一致） |
| `Content-Type` 不是 multipart、缺 `model`、缺 `file`、字段重复、超 50 MB、未知语言 | **400**（与非流式相同） |
| 本机无 ffmpeg 或解码失败 | **415**（与非流式相同） |
| worker 队列满 | **429** |
| 流开始后引擎出错 | 200 + `{"type":"error","detail":…}` 后关闭 |

这些「流开始之前」的判定发生在响应头之前：端点会先取出 worker 的第一帧，是 `meta`
才提交 200。所以切换到流式接口的客户端不需要为同一个问题处理另一种状态码。

### 断开即停

浏览器关掉页面后：当前这一段**跑完**（NPU 调用不可中断），下一段不再开始，worker 收到
`op:"cancel"`，连接关闭，推理记录写成 `cancelled` 并在 `params` 里记下已完成的段数
（`segments`）与总段数（`segments_total`）。

「不可中断」是 ABI 决定的：`asyncio.to_thread` 停不掉线程，中途取消只会让 worker 的
引擎锁在 NPU 还在跑的时候被释放，下一个请求就会踩进同一个引擎。所以
`_run_uninterruptible` 用 `shield` 让那一段跑完再取消。一段最多 30 秒（`SEGMENT_CAP_SECONDS`），
这就是取消延迟的上界。

### mock 后端演练

`--backend mock --kind asr` 的 worker 支持同样的帧序列（同样调用
`iter_transcribe`），并多一个环境变量让每段慢下来，界面开发时能看清进度、也能在中途挂断：

```bash
CV84X6_MOCK_ASR_SEGMENT_MS=1500 python -m app.engine.worker \
  --model-id qwen3-asr-0.6b --port 18001 --backend mock --kind asr
```

`segment_delay_ms` 只存在于 mock：真机上的段耗时是 NPU 决定的（0.6B 实测 4–18 倍实时）。


## 内存准入

同时在线的模型**不设数量上限**（v0.6.25 起；之前 chat 模型最多 2 个）。需要时在 `server.env` 里设
`CV84X6_MAX_LOADED=N`（或启动参数 `--max-loaded N`）限制 chat 模型数量，它**只统计 chat 模型**。chat 模型的 NPU 占用由上下文长度决定，
不做文件大小预检；放不下时 worker 加载失败，`load_error` 显示「NPU 内存不足」。辅助模型按 `bm-smi` 的**实测剩余 NPU 内存**准入，
要求 ≥ bmodel 文件大小 + 256 MiB，不足时返回 409 并给出两个数字；bm-smi 不可用时
（主机测试、mock 后端）跳过检查。

板上实测（`.151`，23.75 GiB NPU）：embedding 单独 2.54 GiB，rerank 单独 1.11 GiB，
两个同时 3.65 GiB；ASR 见下表。全部卸载后回到 0.00 GiB。

## 空闲自动卸载与按需自动加载（MYS-2657，MYS-2675 起可按模型配置）

上面的内存数字是**常驻**的：模型的设备内存都在加载时一次性分配、卸载时释放，推理过程
不再分配（`.157` 实测，连续三次 embedding 含 1800 字长文本，NPU 仍是 2605 MiB——那是
seq8192 的数；换成 seq2048 后同一实测是 1465 MiB，见 `model-settings.md`）。所以
「embedding 用完了内存还占着」不是泄漏，是模型本身还在。这两个开关让它按需在住。

**从 MYS-2675 起，这两个开关可以逐个模型单独配置**，每个模型还有一个自己的设备内存
上限。完整的语义、推算方法和接口在 [`model-settings.md`](model-settings.md)；本节的
两个全局设置现在只表示「**没有单独配置的模型用的默认值**」。

### 两个全局设置（`/api/settings`，即时生效，无需重启）

| 设置 | 默认 | 值域 | 含义 |
|---|---|---|---|
| `aux_idle_unload_min` | **0（关闭）** | 0–1440（分钟） | 空闲达到这个时长就卸载；**0 = 不自动卸载** |
| `aux_auto_load` | **false（关闭）** | bool | 请求指定的辅助模型未加载时自动加载 |

两项**默认都关闭**（v0.6.28 起），由操作员在「设置 → 辅助模型自动卸载」中开启；开启时建议
两项一起开（例如 10 分钟 + 按需自动加载），只开卸载不开自动加载时，卸载后的请求会收到 409
「未加载」。v0.6.27 默认开启（10 / true），而保存设置时会写入全部字段，所以从 v0.6.27 升级的
状态文件里如果正好是 10 / true，首次启动时改为关闭（只做一次，由 `aux_defaults_rev` 标记）；
其他值是操作员自己设的，原样保留。

越界的值**钳制**而不是拒绝（和这个接口的其他字段一致）。`GET /api/settings` 另给出
`aux_idle_unload_limit_min`（=1440），界面用它做输入框上限，不必自己写死。

### 单独配置优先于全局（MYS-2675）

`state.json` 的 `model_settings[<模型 id>]` 里可以给任何一个模型单独设
`idle_unload_min` / `auto_load` / `mem_limit_mb`，`null` 表示跟随默认。生效值的算法：

```
该模型有单独值  -> 用它（任何 kind 都算数，包括 chat）
否则 kind 在 AUX_KINDS -> 用上面的全局值
否则 -> 0 / false（chat 与 ocr_vl 的既有行为不变）
```

所以「单独开启」有两个方向都有用：给一个 35B 设 `idle_unload_min=1` 它就进空闲机制；
给某一个 embedding 设 `idle_unload_min=0` 它就在全局开着的时候也不被卸载。

用 `PUT /api/models/{id}/settings` 改，`GET` 同一条路由读，`/api/models` 的每个模型
也带 `settings`（原始值）和 `effective`（生效值）。接口见
[`model-settings.md`](model-settings.md) § 三。

### 默认只作用于四类：`embedding` / `rerank` / `asr` / `ocr`

`chat` 与视觉 OCR 模型（`ocr_vl`，**自己的 kind**，见 `docs/ocr-vl.md` §10.3）
**默认不自动卸载、也不自动加载**：35B 加载要几十秒，agent 依赖它常驻；OCR-VL 是
2.27 GB、装载 8 s、常驻 2 GB，一页识别是一串请求，卸载的收益会在下一次加载上赔回去。
这份白名单在 `app/core/models.py` 的 `AUX_KINDS` 里，是**全局默认**的作用范围；
单独配置不走这份白名单。

### 卸载：每模型各自的四个条件

后台任务每 **30 秒**扫一次（`IDLE_SWEEP_INTERVAL_S`），对每个模型同时满足才卸载：

1. 该模型的**生效**阈值 > 0（自己的值，或它在 `AUX_KINDS` 里时的全局值）；
2. 没有进行中的操作——`operation` 为 null（加载/卸载）且 `downloading` 为 false（下载/更新）；
3. **worker 报的 `inflight == 0`**；
4. 已经空闲够这个模型自己的阈值时长（不是全局的那个）。

阈值在循环**里面**逐个模型读：在循环外读一次会把先检查到的那个模型的阈值套到所有模型
上，于是 1 分钟的模型和 1 小时的模型会按彼此的节奏卸载。

第 3 条的取值方向是刻意的：**问不出来也算忙**。探针失败、RPC 超时、没有 client 可用，
一律当作「正在处理」，这一轮跳过、30 秒后再看——在 NPU 调用中途杀掉 worker 是唯一的
不可接受结果，多留 30 秒只是内存。

★ chat worker 的 `stats` 以前没有 `inflight` 字段，于是「问不出来算忙」把**每一个**
chat 模型都当成忙的——单独给 chat 开空闲卸载会永远不生效。现在 `Scheduler.stats()`
报 `inflight = len(active)`（排队中的不算：它们没有会话，等的是槽位不是 NPU）。

卸载走的是和手动卸载**完全同一条** `ModelManager.unload` 路径（先关 socket 再
SIGTERM，120 秒宽限），所以 `on_unloading`、推理记录和运维日志都和手动一致。日志写
`模型 <id> 空闲 N 分钟，自动卸载`。

**`inflight` 从哪来**：辅助 worker 的 `stats` 以前固定返回 `inflight: 0`，现在报
`_Serialised` 实际接纳的请求数（`gate.active`，每个请求整个生命周期占一个 slot，ASR
流式同样计入）。`queued` 是其中在等引擎锁的部分。这是 `/api/models` 上多出来的
`inflight` 字段，界面可以直接显示。

### 加载：请求指定的辅助模型没加载就装上

| 入口 | 行为 |
|---|---|
| `/v1/embeddings`、`/v1/rerank`、`/v1/audio/transcriptions`、`/v1/ocr` 及其 `/api/test/*` 代理 | 按**名字**指定的模型在磁盘上但未加载 → 加载并等就绪后继续处理 |
| 知识库检索 / 建库 / 重建索引 | 没有已加载的模型时，从**已下载**的模型里选一个加载 |
| MCP `kb_search`、`ocr_read`、`transcribe_audio` | 同上 |

- **只加载一次**：并发请求走 `ModelManager.load` 现有的去重（`_loads`），三个请求同时
  到达只会起一个 worker，三个都从它拿到结果。
- **失败仍是 409**：NPU 不够、worker 没就绪、正在下载、本模型内存上限不够——返回 409 和
  手动加载时**同一句**原因。生效的 `auto_load` 为 false 时也是 409，但原因写「自动加载
  已关闭」，因为这个操作员的下一步是去打开开关，不是去点「加载」。
- **大模型要几十秒**：给 chat / `ocr_vl` 单独打开按需加载是允许的，但第一次请求会等
  几十秒（35B 装载 14 s 以上，还要等能力探测）。接口的 `auto_load_note` 字段就是给界面
  提示这一点的。
- **kind 先判**：`/v1/embeddings` 收到一个没加载的 chat 模型仍然是 400，不会为了让
  35B 起来花掉一分钟再回 400。kind 由 bmodel 文件名决定，加载前后不会变。
- 加载前照旧做 `_check_npu_admission` 的实测剩余内存检查，以及本模型的上限检查
  （静态占用 > 上限 → 409）。

知识库/ MCP 的**选择顺序**（`ModelManager.candidates_for`）：

1. 已经加载的：最近加载的优先（操作员最后一次显式选择）；带 `vector_family` 的调用方
   （知识库）先看**同族**的已加载模型——例如库是 seq2048 建的、现在只加载了 seq512，
   就用 seq512，而不是跳过向量阶段；
2. 需要在**未加载**的里挑时：先滤掉生效 `auto_load` 为 false 的（这是唯一自己挑模型的
   路径，所以按每个候选自己的设置挑，而不是被一个关掉的候选挡住整个阶段）；embedding
   优先知识库记录的 `embedding_model`、其次它的**同族**模型（重建/追加必须留在同一个
   向量空间，而同族的不同档就是同一个空间），asr 优先 `qwen3-asr-0.6b`（更快、占用更小），
   其余按最近使用时间、再按名字。

只有「**没有下载**对应模型」或「自动加载失败」才把阶段标成 `skipped`，原因写清楚
（`没有已下载的向量（embedding）模型` / `向量（embedding）模型自动加载失败：…`）。

### 三个新增的模型字段（`/api/models`、`/api/stats`）

| 字段 | 类型 | 含义 |
|---|---|---|
| `last_used_at` | epoch 秒 / null | 上次使用的时间；加载完成时和每次推理解析到它时更新 |
| `unloaded_reason` | `"idle"` / null | 上次是**空闲自动卸载**才置 `"idle"`；手动卸载或任何一次加载都会清空 |
| `idle_unload_at` | epoch 秒 / null | 预计自动卸载的时间戳。生效阈值 0、未加载、有操作在飞时为 null |

MYS-2675 另新增 `settings` / `effective` / `mem_limit_default_bytes` /
`mem_static_bytes` / `mem_used_bytes` 五个字段，见
[`model-settings.md`](model-settings.md) § 三。`idle_unload_at` 现在按**该模型自己的**
生效阈值算，所以单独给一个 chat 模型设了阈值时它也有倒计时。

MYS-2706 另新增 `vector_family`（字符串，非 embedding 模型为 `""`）：这个模型属于哪个
**向量空间**。同族的不同 build（seq2048 / seq512）可以服务同一个知识库；不同族不行。
字段值来自下载目录的 `vector_family`，目录里没登记的 embedding 模型以自己的 id 为族。

`idle_unload_at` 由 `ModelManager.idle_unload_at()` 一处算出，`/api/models` 与
`/api/stats` 用的是同一个值——两处各算一次正是那种没人报也查不出来的 bug。

### 时钟

判断用**单调时钟**（`last_used_mono`），API 报 **epoch 秒**（`last_used_at`）。板上没有
RTC，开机后 NTP 会把时钟跳几分钟；用 wall clock 做减法会算出负的空闲时长，那会被读成
「永远空闲」。

### 服务关闭

`sweep` 任务在 lifespan 里启动（adopt 之后，让接管来的 worker 也有空闲时钟），在
`ModelManager.unload_all()` 的第一行停掉并 await——它和「回收所有 worker」是同一条
停机路径，不能出现一个还在扫描、另一个已经在 `_forget` 的竞态。

## 进程与协议

每个模型仍是一个 worker 进程，但辅助 worker **不建 Scheduler、不建前缀缓存**——一次
调用就是一次（embedding/rerank）或一轮（ASR）前向，没有跨请求的 KV 状态可调度或可缓存。
同一 worker 内的 NPU 调用用 `asyncio.Lock` 串行，排队数超过 `max_queue` 返回 `busy`
（上层转 429）。

**Embedding / Reranker 的并发**（v0.6.26 起）：每个 worker 同时只接纳 **2 个请求**（1 个在算、1 个排队，
`AUX_TEXT_MAX_QUEUE`，是全局 `max_queue` 的上限），第 3 个立即返回 429。一个请求的全部文本作为一次
引擎占用连续算完，先到先得，不再按条与其他请求交错。NPU 本来就是一次一个 forward，并发不会让请求更快，
只会多占内存（排队的请求要持有自己的输入）；交错还会让每个请求都变慢。知识库建库每次只发 4 个片段，
避免建库时检索要排在一个长批次后面。

```
-> {"op":"embed","req_id":"x","texts":["a","b"],"dimensions":null}
<- {"op":"embeddings","req_id":"x","vectors":[[...]],"tokens":[3,5]}

-> {"op":"rerank","req_id":"x","query":"q","documents":["d1","d2"]}
<- {"op":"scores","req_id":"x","logits":[1.2,-3.4],"tokens":[11,23]}

-> {"op": "transcribe", "req_id":"x", "audio_b64":"<base64>","filename":"a.wav",
    "language":"zh","prompt":""}
<- {"op":"transcript","req_id":"x","text":"...","language":"Chinese",
    "duration":4.2,"segments":[{"id":0,"start":0.0,"end":4.2,"text":"..."}],
    "prompt_tokens":80,"completion_tokens":10,"infer_seconds":0.9}

-> {"op":"transcribe_stream","req_id":"x","audio_b64":"<base64>","filename":"a.wav",
    "language":"zh","prompt":""}
<- {"op":"meta","req_id":"x","duration":95.5,"segments_total":4,
    "segment_seconds":30,"language":null}
<- {"op":"segment","req_id":"x","id":0,"start":0.0,"end":30.0,"text":"…","infer_ms":2412.7}
<- {"op":"done","req_id":"x","text":"...","language":"Chinese","duration":95.5,
    "prompt_tokens":930,"completion_tokens":118,"infer_seconds":5.21}
```

`transcribe_stream` 的 `meta` 一定先于第一个 `segment`，而**能提前判定的拒绝**（解码
失败、超时长、未知语言）在 `meta` **之前**以单条 `error` 帧发出——API 侧就是靠这一点
把 415/400 还原成状态码。非流式的 `transcribe` 是同一个生成器收集后的结果，两者的
`text` 因此不可能不同。

音频走 socket 而不是共享路径：ffmpeg 和 mel 前端都在 worker 侧，API 进程从不解码音频，
也就没有第二份需要同步的实现。一次 transcribe 的超时是 45 分钟（30 分钟音频 × 约 1x
实时 + 余量），因为这里的瓶颈是音频长度而不是"NPU 卡住"。

`health` 与 `stats` 额外回报 `kind`（`health` 还回报 `hidden_size`），所以控制台和
API 读到的是 worker 自己声明的类型，而不是文件名猜的。

### ASR 的引擎状态机

ASR 是三个辅助引擎里唯一**有状态**的一个：它持有 KV cache，所以一次请求是一串调用，
不是一次前向。原生引擎（`native/src/asr_engine.cpp`，C ABI `cv_asr_*`）提供：

```
cv_asr_clear()            丢弃上一次请求的历史
cv_asr_forward_audio()    音频塔逐块前向，暂存音频 embedding
cv_asr_forward_first()    文本 embedding → 拼接音频 → prefill → 首个 token
cv_asr_forward_next()     一次 decode，返回下一个 token
```

`aux_backend.AsrBackend` 在此之上实现参考 pipeline 的生成循环：**贪心**解码，遇到
`<|im_end|>` 停止，并受 KV cache 剩余空间约束（`SEQLEN - prompt - 1`）——模型若一直不
输出停止符，请求也必须返回。

每次转写前都 `clear()`，跨请求不保留上下文：一个客户端的转写结果不能依赖另一个的。

`forward_audio` 把音频塔输出暂存在自己的 buffer 里，而不是直接写进 embedding 的输出
buffer（参考实现可以这样做，因为它的调用顺序固定为 embed→audio）。这个 ABI 允许调用方
先跑音频塔，写进"下一次 embedding launch 会覆盖"的 buffer 会让两种顺序含义不同。拼接
在 `forward_first` 里按参考的顺序做，代价是每秒音频 26 KB 的拷贝。

## 推理记录

三个接口各写**一条**记录（按请求，不按文本/文件）：

| 接口 | `source` | `output_text` | `messages` |
|---|---|---|---|
| `/v1/embeddings` | `/v1/embeddings` | `"<N> vectors x <D> dims"` | 每条文本一个 user turn |
| `/v1/rerank` | `/v1/rerank`（走 `/rerank` 别名时是 `/rerank`） | 分数 JSON | query |
| `/v1/audio/transcriptions` | `/v1/audio/transcriptions` | 转写文本 | `{"filename","format","language","prompt","bytes"}` |
| `/api/apps/asr/transcriptions/stream` | `/api/apps/asr/transcriptions/stream` | 已推送各段的拼接文本 | 同上 |

ASR 的 `params` 额外记录 `duration`、`language_detected`、`segments` 与 `format`。
**音频本身从不落盘**，`messages` 里只有描述。

流式接口的记录在断开时写成 `cancelled`，`params.segments` 是**已推送完成的段数**、
`params.segments_total` 是总段数——"12 段里收到了 8 段"才是排查半截转写时要看的事实。

## 分词

用 HF `tokenizers`（Rust wheel，`scripts/package.sh` 以 `--no-deps` 单独装进
`vendor/`）读模型自己的 `tokenizer.json`——也就是参考 `AutoTokenizer` 读的那个文件。
引擎库自带的 `native/src/tokenizer.cpp` 实现的是 Qwen chat 词表，编码不了 XLM-R 的
sentencepiece 模型，所以辅助模型不走它。

分词结果由 `tests/test_aux_tokenize.py` 与 `tests/data/aux_token_golden.json`
逐 token 固定；golden 由 `tools/aux_golden.py` 用 transformers 生成，不要手改。
ASR 的提示词由 `tests/data/asr/prompts.json` 固定（1B 生成，24 组逐 token 全等）。

## ASR 真机结果

`.151`，0.6B 与 1.7B 依次经控制台 dfss 下载、加载、转写、卸载。

| | 0.6B | 1.7B |
|---|---|---|
| 加载耗时 | 3.5 / 7.5 s | 15.6 s |
| NPU 占用（bm-smi used） | **1639 MiB** | **4048 MiB** |
| 卸载后 | 0 MiB | 0 MiB |
| `asr_zh.wav`（4.20 s） | 甚至出现交易几乎停滞的情况。 | 同左 |
| `asr_en.wav`（15.05 s） | Uh huh. Oh yeah, yeah. He wasn't even that big… | Um. Oh yeah, yeah. He wasn't even that big… |

HF 参考（`tools/asr/hf_transcribe.py`，transformers 4.57.6 + qwen_asr，CPU fp32）
对同一文件给出：

```
asr_zh.wav  Chinese  甚至出现交易几乎停滞的情况。
asr_en.wav  English  Hmm. Oh yeah, yeah. He wasn't even that big when I started
                     listening to him, but and his solo music didn't do overly
                     well. But he did very well when he started writing for
                     other people.
```

正文逐字一致，差别只落在句首那个语气词上（HF `Hmm` / 1.7B `Um` / 0.6B `Uh huh`）——
4core bf16 bmodel 与 fp32 参考之间的正常波动，属于验收标准允许的"只有标点差异"之外
唯一的一处。

### 吞吐（`.151`，0.6B，HTTP 端到端含上传解码）

| 音频 | 时长 | 处理耗时 | 实时率 |
|---|---|---|---|
| `asr_zh.wav` | 4.20 s | 0.98 s | **4.3× 实时** |
| `asr_en.wav` | 15.05 s | 2.66 s | **5.7× 实时** |
| `long95.wav`（4 段） | 95.50 s | 5.21 s | **18.3× 实时** |

长音频的实时率更高是因为每段的固定开销被摊薄，而音频塔和 prompt 都按段走。卸载
（`POST /api/models/<id>/unload`）437 ms，之后 worker 进程消失、NPU 回到 0 MiB。

### 非 WAV 路径

`asr_zh.wav` 在 13.24 上用 ffmpeg 转成 mp3（16 kHz 单声道，25 KB）后上传，板上
`which ffmpeg` 为空（确认不在 PATH），服务仍转写为同一句、`duration` 仍是 4.204 s——
即第 7 条要求的 SDK ffmpeg 查找路径在真机上生效。

重跑真机验收用的脚本在交付评论里；`tools/asr/hf_transcribe.py` 是生成对照的那一个。

## 重跑真机验收

```bash
# 1. 板上编库
rsync -az native/ linaro@<board>:/data/asr-test/native/
ssh linaro@<board> 'cd /data/asr-test/native && cmake -B build && cmake --build build -j4'
nm -D build/libcv84x6_llm.so | grep -E 'cv_embed|cv_rerank|cv_asr'   # 17 个符号

# 2. 打包安装（vendor 依赖用上一版 VENDORED.txt 锁定）
PIP_CONSTRAINT=<旧版 vendor/VENDORED.txt> bash scripts/package_deb.sh \
  --lib <板上编出的 libcv84x6_llm.so> --config <qwen3_5 配置目录>
sudo dpkg -i dist/cv84x6-llm-server_*_arm64.deb && sudo dpkg -V cv84x6-llm-server

# 3. 通过控制台 API 从 dfss 下载模型，然后在「模型」页加载
# 4. 转写
curl -s -H "Authorization: Bearer $KEY" \
     -F file=@asr_zh.wav -F model=qwen3-asr-0.6b \
     localhost:8000/v1/audio/transcriptions
```

操作前先 `pgrep -c bmrt_test` 确认没有别人在跑 NPU 测试。
