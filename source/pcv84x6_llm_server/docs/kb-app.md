# 知识库问答（演示应用 K1）

把 txt / md / PDF / 图片变成可检索的知识库，提问时做 **BM25 + 向量 → RRF → rerank** 的混合检索，
并在加载了对话模型时基于检索结果流式生成带引用的回答。每个阶段的分数和耗时都返回给前端。

界面由负责人实现，本应用只提供接口。设计上的第一原则是 **按当前已加载的模型自动降级**：
一次只能把 35B 或 embedding/reranker 放进 NPU（35B 128k 加载后占 22.8 / 23.75 GiB），
所以任何一个阶段"没有模型"都是正常的运行状态，不是错误，必须带原因返回 `skipped`。

## 1. 模型与阶段的关系

| 阶段 | 需要的模型 | 没有模型时 |
|---|---|---|
| 建库（切片 → 向量） | `embedding` | 文档 `failed`，原因写明；加载后「重试」即可继续 |
| 解析扫描页 / 图片 | `ocr` | 该页跳过并写进 `warnings`；整篇无文字则 `failed` |
| BM25 | 无 | 始终可用 |
| 向量检索 | `embedding`，且**与建库时同一个向量空间** | `vector` 阶段 `skipped` |
| 精排 | `rerank` | `rerank` 阶段 `skipped`，按 RRF 顺序 |
| 生成回答 | `chat` | `/answer` 返回 409 |

「同一个向量空间」是**向量族**（`vector_family`），不是同一个模型 id。Qwen3-Embedding
有两档静态图（seq2048 默认、seq512 短文本档），它们同族，所以**用其中一档建的库可以直接
用另一档入库和检索**，不需要重建（MYS-2706，实测余弦 ≥ 0.9995）。换成别的 embedding
模型仍然要重建，`vector` 阶段会 `skipped` 并说明。

两个典型演示：

1. 加载 `qwen3-embedding-0.6b` + `bge-reranker-v2-m3` + `ppocrv6-medium`，建库并展示完整混合检索
   （四个阶段都是 `ok`）。
2. 卸载 embedding 与 reranker，加载 35B，演示「关键词检索 + 生成回答」：`vector` 与 `rerank`
   阶段 `skipped`，回答照常流式输出并带引用。

建库之所以严格要求 embedding 模型，是因为 `vectors.npy` 的不变式是
**每行对应 `chunks.jsonl` 的一行，顺序一致，否则文件不存在**。允许"这篇文档没有向量"会让矩阵
出现空洞，而矩阵之外没有任何地方记录哪几行是空的。

## 2. 存储

```
<数据目录>/apps/kb/<kb_id>/
    kb.json         名称、创建时间、建库用的 embedding 模型 id 与维度
    docs/<doc_id>/
        source.<ext>    原文件
        meta.json       状态、进度、页数、警告、切片数
        pages/<n>.png   预览图（OCR 框的坐标系就是它）
    chunks.jsonl    一行一个切片，索引顺序
    vectors.npy     float32，单位向量，行号与 chunks 对齐
```

* 所有写入走 **临时文件 + `os.replace`**。断电只会在"旧文件"与"新文件"之间二选一。
  写序固定为 vectors → chunks，所以看到新 `chunks.jsonl` 的读者一定能找到与之匹配的向量。
* `apps` 是数据目录的**一个 part**（`app/core/storage.py` 的 `PARTS`），不是别处的子目录：
  设置页的「搬迁数据目录」必须带上它，否则一次成功的迁移会让知识库的向量凭空消失。
* 删除文档会过滤聚合并重建矩阵（`keep_idx`），不重新 embedding —— 代价是 O(库) 的内存操作，
  收益是删一个文档不需要几分钟的 NPU 时间。

## 3. 解析

| 类型 | 做法 |
|---|---|
| txt / md | UTF-8（含 BOM），失败再试 GB18030，都不行 → 400 |
| PDF | **pypdfium2** 逐页取文字层；去空白后 < 20 字符视为扫描页 |
| 图片 | png/jpg/jpeg/webp/bmp，直接 OCR |

* 扫描页以 **2 倍比例渲染**（长边 ≤ 2048 px）交给 PP-OCR；**每页**都生成预览 PNG（长边 1024 px）。
* OCR 返回的框在"OCR 渲染图"的坐标系里，按两张图的尺寸比缩放到预览图坐标 —— 前端把框画在
  预览图上，所以这一步不能省。
* 需要 OCR 而模型未加载：该页跳过、`meta.json` 的 `warnings` 写明页号；整篇无文字则 `failed`。
* 上限：单文件 50 MiB、PDF 300 页、单库 20000 切片。上传复用 `app/api/audio_upload.py` 的
  有界 multipart 解析（release 不 vendor `python-multipart`），支持一次多个文件。
* 未知扩展名 **直接拒绝**，不猜。`.docx` 是 zip，前四字节是 ASCII，按内容嗅探会把 Word 文档
  当成文本存下来，然后在解析阶段变成乱码 —— 说"读不了 Word"比这好。

## 4. 切片

按句切（`。！？；!?;`、`. ` 后跟空白、以及换行 —— OCR 与 PDF 都是逐行来的，表格行没有句号），
再合并到 **400 字符**，相邻切片重叠约 **60 字符**（在句子边界取整）。

* 单句超过 400 字符时**整句保留**：过长的切片只是粗，切断的句子是错的。
  **但整句保留有硬上限 1000 字符**（`chunker.MAX_CHUNK_CHARS`）：超过就按字符硬切，
  因为 embedding 模型对超长输入是**拒绝**而不是截断，一条病态长句会让**整篇文档**建库失败。
  没有标点的 CJK 长句是最常见的触发源。
* 字符上限不等于 token 上限：稀有字（CJK 扩展 B、私用区）一个字 3 个 token，1000 字符
  就是 3000 token。所以 embedding worker（用模型自己的分词器）拒绝某一批时，
  这一批改为逐片重试，只把被拒的切片对半切开再嵌入，向量取各片均值后归一化
  （`Ingestor._embed_fitted` / `_pool_pieces`）。普通文本永远是一批一次请求，不经过这段。
* **用 seq512 短文本档时这段会经常触发**，属于预期：1000 字的切片通常超过 512 token，
  所以被切开汇聚。`.157` 实测一份中文语料里 **3.1%** 的切片（1000 字符、605 token 的
  整块无标点 CJK）需要切分，其余仍是一片一次前向，单条成本只有长档的约 1/3。长文档为主的
  库建议留在默认的 seq2048 档（`docs/aux-models.md`）。
* 切片**不跨页**，所以 `page` 总有唯一答案。
* 每片记录 `page`（txt/md 为 `null`）、`source`（`text` / `ocr`）、`char_start/char_end`
  （该页文本中的位置）、以及 OCR 切片覆盖的行的 `boxes`（预览图坐标，四点）。

## 5. BM25

纯 Python，k1=1.5、b=0.75，IDF 用 Lucene 形式 `log(1 + (N-n+0.5)/(n+0.5))`。

分词（`app/apps/kb/bm25.py`）：

* CJK 连续串取**字二元组**（单字串取单字）—— 中文没有空格，unigram 会在几乎无意义的单字上检索；
* 拉丁字母/数字串取小写单词；
* 其余是分隔符；不做停用词、不做词干。

故意**不用**模型的分词器：BM25 是"没有任何模型时也要能用"的那一级，依赖 `tokenizer.json`
就把关键词检索绑在了 embedding 模型上。

索引按库缓存在内存（`app.state.kb_bm25`），签名为 `(切片数, 最后一个切片 id)` ——
上传、删除、重试都会改其中之一，所以不需要额外的失效通知。命中不了就重建，20 000 切片是
几十毫秒。

## 6. 向量

* 切片用 embedding 模型批量编码，**每批 ≤ 64 条**（接口上限）。
* 查询用 Qwen3-Embedding 的检索指令，逐字符固定：

  ```
  Instruct: Given a web search query, retrieve relevant passages that answer the query
  Query: 
  ```

  切片**不加**指令（见 `docs/aux-models.md`：改一个词参考相似度就会跑出容差）。
* 检索时若加载的模型与 `kb.json` 记录的**不在同一个向量族**，或没有可用模型 → `vector`
  阶段 `skipped`，原因写明。同族的不同档（seq2048 / seq512）不算不一致，照常检索。
* `POST /reindex` 用当前模型重建**整库**向量。之所以是一个整库任务而不是每文档一个：
  `vectors.npy` 是单矩阵，逐文档重建会让还没轮到的行在一段时间里指向错误的切片。
  前提只是**库里有切片**：重整失败或重整中重启之后每个文档都是 `failed`，那时它既是唯一的
  恢复手段，也必须能跑起来（详见 §10.2）。也用于**同族换档**：只加载 seq512 时重建，库就
  改记为 seq512，向量由它重写，之后两档照样可以继续互相入库。
* 重建期间的增删改返回 409；删除最后一个文档会连 `embedding_model`、`dims`、`needs_reindex`
  一起清空 —— 库回到了新建时的状态。

## 7. 融合与精排

* BM25 与向量各取前 `candidates`（默认 20）；RRF `score = Σ 1/(60 + rank)`；
* 并列时按首次出现顺序（BM25 在前），所以两次相同请求的结果一致；
* reranker 对融合后的前 `candidates` 条精排（query + 切片文本），取前 `top_k`（默认 5）；
* 没有向量时 RRF 只用 BM25（`fusion.reason` 说明退化了）；没有 reranker 时按 RRF 排序。

`GET /{kb}/search` 的响应把每个阶段的 `status / reason / ms / hits` 和每条结果的
`scores.{bm25,bm25_rank,vector,vector_rank,rrf,rrf_rank,rerank}` 都返回；未参与的阶段为 `null`。

## 8. 生成

`POST /{kb}/answer` 取指定的 `chunk_ids`，编号 `[1]…[n]` 放进 system prompt，要求
「只依据资料作答、用 [n] 标注出处、资料不足时说明」。

SSE 帧与 `/api/test/chat/completions` 相同（OpenAI delta）。**在起始处**先发一帧

```json
{"type": "citations", "items": [{"n": 1, "chunk_id": "…", "doc_name": "…", "page": 3}]}
```

再流式输出 delta，最后 `finish_reason` 帧 + usage 帧 + `data: [DONE]`。

引用帧放在**流的起始处**而不是 `done` 之前：前端在回答还在流式输出时就要显示来源面板，而中途
放弃的客户端否则永远拿不到"这段文字依据了哪几片"—— 恰恰是解释这个回答需要的那一条信息。
设计文本写的是"在 `done` 之前额外发一帧"，起始位置同样满足"在 `done` 之前"这个约束，
并且对前端更友好。

引擎是贪心的，`temperature` 等参数无效；默认 `enable_thinking=false`、`max_tokens=1024`。
客户端断开即取消 worker 上的请求（否则 35B 会继续往没人读的 socket 里解码几分钟）。

## 9. 建库任务

**单个全局串行队列**。解析 300 页 PDF、编码 20 000 个切片都是长时间操作；并发两个文档会让
OCR 与 embedding 在只有一块 NPU 的设备上互相插队，进度条也各自以不可预测的比例前进。
串行还让"库的 `kb.json` 模型就是每一行向量的来源模型"成立：同时只有一个建库在跑。

状态：`queued → parsing → ocr → embedding → ready | failed`，`progress={stage, done, total}`。
`ocr` 只在真有页面需要它时出现。

服务重启后未完成的文档置 `failed`（「服务重启，处理中断」），可用 `POST /docs/{doc}/retry` 重试；
重试用磁盘上已有的原文件，所以不依赖浏览器还留着那份上传。

## 10. 接口

字段名是前端的契约（前端按此开发），增加字段可以，改名不行。

```
GET    /api/apps/kb                          -> {kbs:[{id,name,created_at,docs,chunks,embedding_model,dims}]}
POST   /api/apps/kb            {name}        -> {kb}
DELETE /api/apps/kb/{kb}
POST   /api/apps/kb/{kb}/reindex             -> {ok, job:{documents,chunks,model}}
GET    /api/apps/kb/{kb}/docs                -> {docs:[{id,name,type,bytes,pages,status,
                                                 progress,error,warnings,chunks,text_pages,
                                                 ocr_pages,created_at}]}
POST   /api/apps/kb/{kb}/docs  multipart file(+) -> {docs:[...]}
DELETE /api/apps/kb/{kb}/docs/{doc}
POST   /api/apps/kb/{kb}/docs/{doc}/retry
GET    /api/apps/kb/{kb}/docs/{doc}/chunks   -> {chunks:[{id,page,source,text,char_start,
                                                 char_end,boxes}]}
GET    /api/apps/kb/{kb}/docs/{doc}/pages/{n}.png
GET    /api/apps/kb/{kb}/docs/{doc}/file
POST   /api/apps/kb/{kb}/search  {query, top_k=5, candidates=20, use_bm25, use_vector, use_rerank}
POST   /api/apps/kb/{kb}/answer  {query, chunk_ids, model?, max_tokens?}  -> SSE
```

鉴权与控制台其他接口一致：admin 会话 cookie（不是 API key），与 `/api/test/*` 相同。
推理记录的 `source` 是被调用的路径，`actor` 为控制台 + `kb`。

`chunk_id` 形如 `<doc_id>:<序号>`，库内唯一且稳定。

`/{kb}/search` 会对 `top_k > candidates` 返回 400：管道最多只能返回 `candidates` 条，
更大的 `top_k` 会静默地少给结果，说清楚比返回 3 条强。`candidates` 上限 **100**：rerank 接口
本身拒绝超过 256 对，而板上一次 20 对的精排已经要 6.5 s，再大这个演示就不在"一次点击"的耐心
之内了，所以上限写在接口上而不是留给超时去发现。

上传是**整体接受或整体拒绝**的：一次提交多个文件时先全部校验（类型、单文件上限），
任何一个不合格就 400，不会出现"前两个已入队、第三个报错"的半完成状态。

## 10.1 与设计的偏差（已与负责人确认，保留）

| 偏差 | 原因 |
|---|---|
| `citations` 帧放在**流的开头**（设计写"`done` 之前"） | 前端在回答还在流式输出时就要显示来源面板；中途放弃的客户端否则永远拿不到引用。起始位置同样满足"在 `done` 之前"。帧里**不带 `choices`**。 |
| `top_k > candidates` 返回 400 | 管道最多只能返回 `candidates` 条，静默少给不如说清楚。 |
| `reindex` 是**整库**任务（不是每文档一个） | `vectors.npy` 是单矩阵，逐文档重建会让还没轮到的行指向错误的切片。 |
| 建库**必须**有 embedding 模型，否则文档 `failed` | 允许"无向量 ready"会让矩阵出现空洞，而矩阵之外没有任何地方记录哪几行是空的。 |
| 查询指令 `Query: ` 后面**带一个空格** | 与 `docs/aux-models.md` 里参考相似度的取法逐字符一致；改一个词参考值就出容差。 |

## 10.2 并发与一致性（第一轮验收修复）

聚合索引（`chunks.jsonl` + `vectors.npy`）是整个应用唯一的不变式来源，下面几条都是围绕它：

* **`needs_reindex` 标志**。两个文件行数对不上时（断电落在两次写之间、旧版本留下的半成品），
  切片文件为准，矩阵删除，`kb.json` 置 `needs_reindex: true`。标志是**持久**的：
  `GET /kb` 返回它，向量阶段 `skipped` 并说明原因，**在重建之前不会往矩阵里追加任何行** ——
  否则下一次上传会自信地往一个已知错位的矩阵后面接行，错位从此永久且无声。
* **重建索引期间该库的增删改返回 409**。`POST /reindex` 在**提交时**就占住该库
  （不是 worker 取到任务时），一直到任务结束。任务内部还在锁内重读一次切片集合并比对 id 序列，
  不一致就放弃这次重建。两条防线：一条挡住新请求，一条挡住已经排队的。
* **重建只改切片文件里有的文档**。判定依据是 `chunks.jsonl`，不是文档当时的状态：
  有切片的文档被本次任务接管、结束时置 `ready`；没有切片的（解析就失败了）保持 `failed`，
  它唯一的修复手段是「重试」，不能被标成 `ready`。这条也是**重建失败或重建中重启之后的恢复路径** ——
  那两种情况下每个文档都是 `failed`、库是 flag 状态，按旧规则（只接管 `ready`）重建等于无事可做。
* **`POST /reindex` 的前提是"库里有切片"**，不再要求必须有 `ready` 文档。旧规则把最需要重建的
  状态挡在门外：重建失败后全部 `failed`，重建接口回 409、重试又因为 `kb.embedding_model` 还是旧模型
  而失败，用户只能删库。
* **原文件在上传返回前落盘**。任务只带 id，不带字节。这既让重启时 `queued` 的文档仍可重试
  （以前"原始文件不存在"），也让 50 MiB 的上传不会在内存里排到队尾。
* **删除会让在处理的文档停下，并等它确认**。解析器每页前查一次停止标志；删除接口在
  `request_stop` 之后 `await ingestor.await_stop(...)`（上限 30 s），确认解析线程真的退出了才动目录。
  光置标志不够：标志要到**下一页**才被看到，这中间线程还在往 `pages/` 里写预览图，`rmtree` 可能
  先列目录再发现新文件，报 ENOTEMPTY（接口 500）。第二道防线在 store 层：文档目录不存在时
  `write_doc_meta` / `write_preview` **不再自动创建父目录**，写入变 no-op，已删除的文档不会被重新写出来。
  嵌入阶段同理，在**下一批之前**停下，不是跑完整个嵌入。
* **`Ingestor.stop()` 等解析线程退出**（上限 30 s），不是只 cancel asyncio 任务。`to_thread` 里的
  线程不会被 cancel 掉；数据目录搬迁时它会继续写，而 `Ingestor.store` 已经指向新根目录，
  于是 `recover()` 刚写的 `failed` 被改回 `ocr`，重试永远 409。现在两道锁：标志 + 等待，
  以及**任务在提交时钉住宿主 store**（`Job.store`），旧任务的写入不会落到新 store 上。
* **停止标志活过 `stop()` 本身**（`_halted`，按文档记录）。只等 30 s 是不够的：`task.cancel()`
  会让 worker 的 `finally` 立刻跑，而那里以前正是清停止标志的地方 —— 于是等待期一过、
  `_stopping` 又被置回 `False`，`should_stop()` 重新返回 `False`，一页 OCR 超过 30 s 的解析
  会继续把剩下的页写进旧根目录。搬迁正在复制那个目录，校验就对不上、搬迁失败。
  现在只有解析线程**自己的** `finally` 清这个标志，任何 `stop()` 返回路径都撤销不了它。
* **`stop()` 连带清空队列**。以前只 cancel 在飞的那个任务，后面排队的任务留在队里，
  搬迁后被新 worker 用旧 store 捡起来：白跑 NPU，甚至通过 `save_chunks` 把搬迁已经删掉的
  目录重新创建出来。现在就地丢弃，`recover()` 会在新根目录把它们标成 `failed`（可重试）。
  遍历 `_parsing` 用 `list(...)`：工作线程正在同一个集合里 `discard`，直接迭代会
  "Set changed size during iteration"。
* **删除是幂等的，并且按文档串行**。同一个文档的两个删除请求可能都过了"存在吗"的检查、
  都等过 30 s，然后一起 `rmtree`：一个删掉，另一个对着已经不存在的路径报错 —— 500。
  `store.delete_doc` 现在把"目录已经不在"当作成功（ENOTEMPTY 仍照报，那是真问题），
  接口层用按文档的锁把两个请求排开，后到的发现记录已消失就直接 200（删除两次都是成功）。
* **数据目录搬迁后重启队列**。`stop_everything` 在复制前停了 worker，搬迁完成后重新启动，
  并把被中断的文档置 `failed`（可重试）。之前没有任何地方重启它，搬迁后所有上传永远停在 `queued`。
* **`mark_needs_reindex` 先置标志再删矩阵**。反过来的话两步之间失败（正是崩溃会落进去的窗口）
  会留下"有切片、没有矩阵、也没有标志"的状态：缺失文件被读成"从没建过"，下一次上传就只写自己那几行。
  另外**有切片而没有 `vectors.npy`** 现在也判定为需要重建（0 切片 + 无矩阵仍是正常的"新库"）。
* **删除最后一个文档时连 `needs_reindex` 一起清**。只清 `embedding_model` 的话，库会一直显示
  "需要重建"、向量阶段一直 `skipped`，而重建又因为没有切片回 409。
* **往 flag 状态的库上传直接 409**。`_replace_rows` 在这种库上只写切片、不写矩阵，所以文档会被
  嵌入几分钟、再被标成 `ready` 却没有向量。拒绝更便宜也更诚实，提示先重建。
* **旧版本建的库补算计数**。`kb.json` 里没有 `doc_count`/`chunk_count`（字段是随缓存一起加的）
  时从文件重算一次并写回，否则 `GET /kb` 对一个装满切片的库报 0/0。
* **便宜的检查在上传时返回 400**：txt/md 的编码、PDF 能否打开与页数、图片能否解码与像素数
  （上限 40 Mpx）。20000 切片的上限做不到（要切完才知道），保留为 `failed`，但判在 **embed 之前**。
* **辅助模型调用写推理记录**。`embedding` / `rerank` / `ocr` 都走 `retrieval` 里的
  `embed_passages` / `rerank_documents` / `ocr_image`，用 `build_context` 记录，
  `source=/api/apps/kb`、actor=`kb`，上限取自 `/v1` 接口自己的常量（64 / 256）。
* **OCR 框与切片同一份文本**。`char_start/char_end` 按**规范化后**的页面文本计算，
  行偏移也从那份文本里按顺序 `find`（OCR 行首尾有空格、表格行会重复）。一致，框才画在对的句子上。
* **预览图逐页写盘**，不在内存里攒 300 张；图片送 OCR 前按长边 2048 px 缩放，与 PDF 页一致。
* **`GET /kb` 不解析 `chunks.jsonl`**：计数缓存在 `kb.json`，由 `store.save_chunks` 同步维护。

## 11. 代码结构

| 文件 | 职责 |
|---|---|
| `app/apps/kb/store.py` | 目录布局、原子写、聚合索引的读写 |
| `app/apps/kb/parse.py` | txt/md/PDF/图片 → 每页文本 + 预览图（pypdfium2、Pillow） |
| `app/apps/kb/chunker.py` | 分句与 400/60 切片 |
| `app/apps/kb/bm25.py` | 分词与 BM25 |
| `app/apps/kb/retrieval.py` | 四阶段流水线、RRF、余弦检索 |
| `app/apps/kb/models.py` | "现在能用哪个模型"，不抛异常 |
| `app/apps/kb/ingest.py` | 串行建库队列、重启恢复、整库重建 |
| `app/apps/kb/answer.py` | 带引用的 SSE 生成 |
| `app/api/apps_api.py` | `APIRouter`，`app/main.py` 以 `prefix="/api/apps/kb"` 注册 |
| `tools/kb_smoke.py` | 标准库冒烟脚本（建库 → 四文件 → 检索 → 回答） |
| `tools/kb/make_pdf_fixtures.py` | 生成测试用 PDF（需要 LibreOffice + CJK 字体，只在开发机跑） |

## 12. 依赖

新增两个轮子，都由 `scripts/package.sh` 以 aarch64 / cp310 装进 `vendor/`，**版本固定**：

| 包 | 版本 | 许可 | 用途 |
|---|---|---|---|
| `pypdfium2` | `5.14.0` | Apache-2.0 / BSD-3 | PDF 文字层 + 光栅化（`manylinux_2_17_aarch64` 轮子） |
| `Pillow` | `12.2.0` | HPND | 图片解码与缩放（预览图、OCR 输入） |

固定而不是浮动，是因为不固定的 `pip install pillow` 在构建时取最新版：同一 commit 两次构建会
产出不同的二进制，而板子上没有编译器，新版本一旦不再提供 aarch64/cp310 轮子就只能原地失败。
`pypdfium2 5.14.0` 自带的 libpdfium 是 PDF 路径实测用的那一份，`Pillow 12.2.0` 是 `.151` 上
实测过的版本。两个一起升级时要在真机上重跑一次建库（§14）。

`numpy` 已经在 vendor 里（OCR 路径用），向量运算复用它。

## 13. 已知边界

* **不缓存解析结果**：改切分参数后必须删文档重传。
* **重试用原文件**，所以修好模型后重试是完整重来一遍，不做增量。
* **`candidates` 上限没有单独限制**，受单库 20 000 切片约束；rerank 一次最多 256 对
  （`/v1/rerank` 的上限），所以 `candidates` 超过 256 时精排会被接口拒绝并降级为 RRF 顺序。
* 预览图只对 PDF 与图片存在；txt/md 没有可画的东西，路由返回 404。
