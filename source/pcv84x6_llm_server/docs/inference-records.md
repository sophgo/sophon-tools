# 推理记录（inference records）

每次真正发起的模型推理落一条记录，用于事后定位「输出不对」的现场问题。本文是这套机制的当前契约：
存了什么、不存什么、怎么读、怎么清、坏了会怎样。

起因见 issue MYS-2496：现场出现一次结果异常的推理，服务当时只保留累计计数，回复内容没有任何留痕，
事后无法回溯。本模块补的就是这份证据。

## 1. 记录什么算「一次推理」

记录在**请求已经确定会跑到模型上**之后才创建：模型解析成功、prompt 渲染成功、请求校验全部通过。
因此下面这些**不产生记录**——它们没有在 NPU 上跑任何东西：

- 400：`messages` 为空、`n != 1`、`max_tokens < 1`、stop 过多、图片格式不支持/远端 URL、tool 定义非法
- 401/403：鉴权失败
- 404：模型不存在；409：模型未加载 / 正在卸载
- 413：请求体过大
- 控制台 `/api/chat*` 的同类校验错误

覆盖的入口（`source` 字段就是实际被调用的路径）：

| `source` | 说明 |
|---|---|
| `/v1/chat/completions` | OpenAI 兼容接口，stream 与 non-stream |
| `/api/chat/stream` | 控制台「对话测试」的流式接口 |
| `/api/chat` | 控制台的整段返回接口（若调用） |

**每次推理恰好一条**。终结路径有且只有这几条，每条都 `await`/同步写入，不依赖后台 task：

| 路径 | `status` | `finish_reason` | `error` |
|---|---|---|---|
| 正常结束 | `ok` | API 语义值（`stop`/`length`/`tool_calls`） | `null` |
| worker 报错（`WorkerError`） | `error` | `null` | `{type: "WorkerError:<kind>", message}` |
| 后端连接中断（`ConnectionError`/`OSError`） | `error` | `null` | `{type: "ConnectionResetError", message}` 等 |
| 客户端断开（`CancelledError`/`GeneratorExit`） | `cancelled` | `null` | `{type: "ClientDisconnected", message}` |

`RecordContext.finish()` 是幂等的：第二次调用不写第二行。这一点在流式路径上很关键——正常结束、
取消与异常可能都走到收尾，重复写入会让「一次推理一条记录」在最需要看记录的时候失效。

断开与出错时**保留已生成的部分输出**：半句话往往足以看出错误答案往哪个方向偏。

### 流式收尾与 `[DONE]`

`[DONE]` 只在**连接还在**的终结路径上发送：正常结束、`WorkerError`、后端
`ConnectionError`/`OSError`（各恰好一次，且都在错误帧之后）。客户端断开 / 取消的路径
（`CancelledError`、`GeneratorExit`）**一个字节都不再写**：

- 此时 Starlette 正在关闭生成器，关闭期间的 `yield` 会抛
  `RuntimeError: async generator ignored GeneratorExit`，把一次干净断开变成一条 traceback；
- 对端已经不在了，写进去的 `[DONE]` 也没有任何读者。

所以控制台的 SSE 生成器（`app/api/admin_api.py:_console_stream`）没有「统一在 `finally` 里发
DONE」的写法，每个终结路径各自决定；记录与 `record_usage` 仍然在所有路径上恰好执行一次。

## 2. 字段语义

完整字段见 `app/core/inference_log.py` 的 schema 与 `GET /api/inference-records/{id}` 的返回。

### 两个输出字段的区别

| 字段 | 含义 |
|---|---|
| `output_text` | **模型实际生成并按 API 语义截断后的文本**。命中 stop string 时不含 stop 本身及其之后的内容，与客户端收到的回复一致；思考标签与 `<tool_call>` 块原样保留 |
| `raw_output_chars` / `output_chars` | 截断前后的字符数。两者不等即为「被 stop 截断」，否则是模型自己停的 |
| `stop_hit` | 命中的那个 stop string（多个 stop 时能看出是哪一个），未命中为 `null` |
| `response_content` | 客户端拿到的 `content`（`parse_completion` 的结果：无 thinking 时为全文，有 thinking 时为 `</think>` 之后的部分） |
| `reasoning_content` | 客户端拿到的 reasoning |
| `tool_calls` | 客户端拿到的 tool_calls（没有则 `null`） |

`output_text` 与 `response_content` 可能不同，这不是 bug：前者是模型的原始语气，后者是解析后的展示
语义（例如 thinking 打开时 `output_text` 含 `<think>…</think>`）。两者都保留，定位时才能分清「模型
没生成」和「被解析/截断了」。

### 其它关键字段

- `id`：即请求 id（也等于 `chatcmpl-` 之后那一段），与 worker 收到的 `req_id` 一致；并发下唯一，不会串。
- `started_at` / `finished_at`：epoch 秒（排序与保留策略用）；`started_iso` / `finished_iso`：UTC
  ISO8601（毫秒 + `Z`），便于与 `journalctl --since` 对齐。
- `params`：**实际生效的采样参数**，默认值已合并（`max_tokens=512`、`temperature=0.8`、
  `top_p=0.8`、`top_k=50`、`repetition_penalty=1.1`），外加 `stop` 列表、`seed` 与 `enable_thinking`。
  「客户端没传」与「客户端传了 0.8」在记录里是同一件事，因为对模型而言确实如此。
- `tools` / `tool_choice`：请求里原始的工具定义与选择（非凭证）。
- `messages`：完整的角色与文本，assistant 历史里的 `reasoning_content`、`tool_calls`、`tool_call_id`
  一并保留。图片部分被替换为 `{"type":"image","index","width","height"}`，位置不变。
- `images`：按出现顺序的 `{count, width, height}` 汇总（相邻同样尺寸合并为一条）。
- `message_images`：逐条消息的图片元数据，可对应回具体哪一轮。
- `first_token_latency_s` / `decode_tps` / `prompt_tokens` / `completion_tokens` / `cached_tokens`：
  全部来自 worker 的 `done`（或 `meta`）事件，与 `record_usage` 同源，不自行估算。
- `actor_type` / `actor_id` / `actor_name`：`api_key` 时是 key 的 id 与备注名；控制台调用为
  `admin` / `admin`。

## 3. 绝不入库的内容

| 不存 | 原因 / 替代 |
|---|---|
| API key 明文与其 SHA-256 | 只存 `actor_id` 与 `actor_name`；key 材料留在 `state.json` |
| `Authorization` 头、`api-key` 头 | 请求头从不进入记录 |
| 会话 cookie / `session.key` token | 同上；控制台来源记为 `admin` |
| 图片 base64 / data URL / 原图字节 | 只存数量与 `{width, height}`；未知格式宽度高度为 `null`，数量照记 |
| 渲染后的完整 prompt 字符串 | `messages` 已能重建，不重复存；`prompt` 只在内存里用于比较 |

图片尺寸用**标准库**解析（PNG 的 IHDR、JPEG 的 SOF、GIF 的逻辑屏幕描述符），板上没有 Pillow。
用户文本里长得像 `data:image/...` 的内容**原样保留**——从用户输入里正则剥离图片会让记录撒谎。

## 4. 存储

- 单文件 SQLite，WAL 模式，默认 `<数据目录>/state/inference_records.sqlite3`。
- `meta.schema_version` 当前为 `1`；列或语义变化时递增。
- 结构：`inference_records` 一张表，长 JSON 用 JSON 文本列存（`params`/`tools`/`messages`/`images`/
  `tool_calls` 等）；`started_at` 上有降序索引供列表使用。
- 写入：`BEGIN IMMEDIATE` + `COMMIT`（清理与插入同一事务），一个连接 + 线程锁
  （`check_same_thread=False`），`busy_timeout=10s`。读只取共享锁，因此「列表」与「写入」不会互相
  `database is locked`。
- 读完列表不返回重字段（`messages`/`output_text` 等），详情才返回全部——否则 200 条 128k 上下文的
  对话一次就是几十 MB。
- 导出 NDJSON 按每页 200 条流式读取，不构造一个巨大的 JSON 数组。
- 「全部清空」后 `VACUUM`，把页真正还给文件系统。

## 5. 配置

「设置」页 → 「推理记录」卡片（`GET/POST /api/settings`，无平行入口）：

| 字段 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `inference_logging_enabled` | `true` | bool | 关闭后新推理不落盘，已有记录保留；保存后下一请求即生效 |
| `inference_log_retention_count` | `1000` | 1–100000 | 只保留最新 N 条 |
| `inference_log_retention_days` | `30` | 1–3650 | 同时按天清理 |

两条保留规则**同时生效**，保留更少的那一条说了算（即「最新 1000 条里超过 30 天的也删」）。清理在
每次写入的同一事务里做，不需要额外定时任务。

旧版本（≤ v0.6.12）的 `state.json` 里没有这三个字段：升级后按默认值生效（**默认开启**），其余字段
原样保留。

## 6. 管理 API（全部 `require_admin`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/inference-records?limit&offset&before` | `{items,total,limit,offset}`，新到旧；`limit` 1–200，`offset` ≥ 0，非法值 400 |
| GET | `/api/inference-records/status` | 记录库自身状态：路径、条数、字节数、`readable`、`moving`、`last_error`/`last_error_at` |
| GET | `/api/inference-records/{id}` | 完整记录；不存在 404 |
| GET | `/api/inference-records-export` | NDJSON 附件，每行一条完整记录，新到旧，UTF-8 不转义中文 |
| POST | `/api/inference-records/clear` | 删除全部并 VACUUM，返回 `{ok, deleted}` |

导出路由是 `-export` 同级路径而不是 `/inference-records/export`：后者会被 `{id}` 抢走（记
录 id 恰好为 `export` 时更糟）。

未登录一律 401，且不泄露记录内容。

## 7. 数据目录迁移与开关

- 启动顺序：`StateStore`（读设置）→ `InferenceLogStore`（用设置里的开关与保留策略）→ 其余组件。
- 迁移（`--storage move` / 设置页「迁移」）：`stop_everything()` 在**卸载模型之前**关闭记录库连接，
  复制期间没有任何写入；`rebind(new_root)` 把库重绑到新 `state/` 目录并按新读到的设置重新配置。
  记录文件由 StorageManager 的整树复制带走，不需要单独的复制器。
- 关闭到重绑之间的窗口里，写入被**丢弃**（不会偷偷重开旧路径再往一棵即将被删除的树里写），
  这是刻意的取舍：宁可少一条，也不在新旧两棵树里各写一份。
- 丢弃不是静默的：`record()` 在丢弃时把 `InferenceLogMoving: 数据目录正在迁移…` 写进
  `last_error`/`last_error_at`，`GET /api/inference-records/status` 同时给出 `moving: true`，
  控制台「推理记录」页据此显示「记录暂停：…」。这样「迁移期间记录不完整」是可见事实，而不是页面上
  看起来一切正常的 0 条。
- 迁移成功后 `rebind()` 重绑到新库、首条记录写入成功即清除这条提示；迁移在切换前失败时，旧目录仍是
  活动目录，下一次写入会自动恢复并清除提示。

## 8. 故障行为

记录是证据，不是依赖：**记录失败绝不改变 API 响应，也不会吞掉原异常**。

- **写入失败**（文件损坏、目录不可写、磁盘满）：异常被捕获并记在 `last_error`（带时间戳），推理
  照常返回。`GET /api/inference-records/status` 把它暴露出来，控制台用红字显示——「一条记录都没有」
  和「记录正在丢失」必须能区分。
- **迁移期间丢弃记录**：同样记进 `last_error`，但类型是 `InferenceLogMoving`、`moving: true`，
  页面按「记录暂停」而不是故障显示。两者的区别是有意的：一个是数据库坏了，一个是数据库好好的、
  只是正在搬家。
- `last_error` 只在**下一次成功写入**时清除，因此它表示「最近一次没能存下来的原因」，不代表当前
  一定还在失败；`last_error_at` 给出时间，`moving`/`readable` 给出当前状态。
- 同一条错误只写一次 WARNING 日志，不会每个 token 刷屏。
- `readable: false` 只表示「库打不开」（损坏、磁盘满），不表示「刚才有记录没存下来」——后者看
  `last_error`。迁移期间 `readable` 仍为 true，行数通过一个临时只读连接读取，页面上不会把一次
  正常的搬家显示成数据库损坏。
- 写入失败后连接被丢弃，下一个请求用新连接重试，不继承已坏的状态。
- `record_usage`（累计用量）路径完全不变：记录库的问题不影响 token 统计与 `tps_history`。

## 9. 隐私

记录里是**客户真实对话明文**。

- 位置：`<数据目录>/state/inference_records.sqlite3`（默认 `/data/cv84x6_llm_server/state/`），
  随数据目录一起迁移，不会自动上传任何地方。
- 访问：只有管理员（cookie 会话）能通过管理 API 与「推理记录」页读取；`/v1/*` 的 API key 无法读取。
- 导出：NDJSON 文件同样是敏感数据，导出后由操作者自行保管；服务端不留导出副本。
- 清理：按保留策略自动过期，或在「推理记录」页「全部清空」（中文二次确认，不可恢复）。
- 关闭：在「设置」页关掉开关，新推理不再落盘；已有记录需要手动清空。
- 计算环境风险：数据目录是普通文件，`root`（或同用户）能读。需要更强保护时应落在全盘加密的分区上，
  本服务不做额外加密。

## 10. 控制台

「推理记录」页（`web/src/pages/Records.tsx`）：

- 列表：时间（本地时区，悬停显示 UTC）、来源、模型、调用方（key 名 / admin）、状态与 `finish_reason`、
  输入/输出 token、TTFT、TPS，分页（每页 20/50/100）+ 上一页/下一页。
- 详情：请求 id、起止时间、采样参数、工具定义、逐条输入消息（图片显示为 `#序号 宽×高`）、
  `reasoning_content`、`output_text`、`response_content`、`tool_calls`、错误信息。
- 记录库状态：路径、占用、条数、保留策略；`last_error` 非空时按类型显示——数据库故障是红字
  「最近一次写入失败」，迁移期间则是「记录暂停：…」。
- 页首固定隐私说明（明文位置、仅管理员、导出同样敏感、两种清理方式）。
- 「导出 NDJSON」直接下载；「全部清空」需二次确认。
