# 管理 API 文档

本文件由 `tools/gen_admin_api_doc.py` 从服务的 OpenAPI 文档生成（当前服务版本
`0.6.37`），**不要手改**：改接口后重新生成，`tests/test_admin_api_docs.py` 会检查
两者是否一致。手写的几节（本节的约定、错误码、分页与时间格式、`/v1` 的文档）写在生成
脚本里，其余全部来自 `app/api/*.py` 的注解与 `app/api/admin_schemas.py` 的模型。

交互式文档（离线可用，不依赖任何 CDN）：服务启动后打开 `/api/docs`（Swagger）或
`/api/redoc`（ReDoc）。两者都需要管理员会话 cookie 或 admin key。

## 认证

两套凭据，按调用方选一种：

| 调用方 | 凭据 | 说明 |
|---|---|---|
| 脚本 / CI | `Authorization: Bearer <admin key>` | 推荐。key 的 `scope` 必须是 `admin`。 |
| 控制台（浏览器） | 会话 cookie `cv84x6_admin` | `POST /api/login` 换取，12 小时有效。 |

```bash
# 1. 用控制台会话签发一把 admin key（只需一次）
curl -s -c jar -X POST http://<板子>:8000/api/login \
     -H 'Content-Type: application/json' -d '{"password":"admin"}' >/dev/null
curl -s -b jar -X POST http://<板子>:8000/api/keys \
     -H 'Content-Type: application/json' \
     -d '{"name":"ci","scope":"admin"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["key"])'

# 2. 之后所有管理调用都用它
export CV84X6_KEY=sk-...
curl -s -H "Authorization: Bearer $CV84X6_KEY" http://<板子>:8000/api/models
```

规则：

- key 的权限范围（`scope`）分两种：`inference`（默认，只能调 `/v1`）和 `admin`
  （还能调 `/api/*`）。**用 `inference` key 调 `/api/*` 返回 403，`code` 是
  `forbidden_scope`** —— 这是为了给 agent 发推理 key 时不会顺带交出管理权。
- 本功能之前创建的 key 没有 `scope` 字段，读取时一律按 `inference` 处理（不需要迁移）。
- 用 Bearer 认证的请求**不需要 CSRF 防护**：浏览器不会自动带上它，没有可伪造的东西。
- 用 cookie 认证的写请求（`POST`/`PUT`/`PATCH`/`DELETE`）会校验 `Origin`：缺失放行，
  存在则必须是本机回环、`CV84X6_MCP_ORIGINS` 里声明的地址，或与本次请求的 `Host`
  完全一致，否则 403（防止别的页面用操作者的浏览器改这台板子）。
- 审计记录里的操作者显示 key 的**名字**（`actor_type: api_key`，`actor_name: <名字>`）。

## 错误格式

所有 `/api/*` 的错误都是同一个形状：

```json
{"detail": "模型 qwen3-4b 正在加载中，请等待加载完成后再请求", "code": "model_busy"}
```

- `detail`：中文说明，控制台直接显示。**保持原有约定不变**（老的控制台读的就是它）。
- `code`：稳定的英文错误码。脚本应据此分支，而不是解析 `detail` 的文字。
- `422` 校验错误也转成这个格式，`detail` 里的字段名和原因用中文，`code` 是
  `validation_error`。
- `/v1/*` 不受影响：那里仍是 OpenAI 的错误体，已有 SDK 依赖它。

## 错误码

`code` 是稳定的：这里的取值不会改名，新增会追加在表尾。

| `code` | HTTP | 含义 |
|---|---|---|
| `bad_request` | 400 | 请求本身不合法：业务校验未通过，说明见 detail |
| `model_kind_mismatch` | 400 | 模型类型与接口不符（例如拿 embedding 模型调用对话接口） |
| `unauthorized` | 401 | 缺少凭据，或会话 cookie / admin key 无效、已过期 |
| `forbidden_scope` | 403 | 凭据有效但权限范围不足：inference key 不能调用 /api，需要 admin key；或 cookie 请求来自别的站点 |
| `not_found` | 404 | 目标资源不存在（模型、key、记录、日志源、知识库、agent 等） |
| `method_not_allowed` | 405 | 该路径不支持此 HTTP 方法 |
| `conflict` | 409 | 与当前状态冲突，但无法归入下面更具体的码 |
| `device_memory_insufficient` | 409 | NPU / VPP 设备内存不足，或单块连续内存放不下，请先卸载其他模型 |
| `download_busy` | 409 | 该模型正在下载中，请等待完成或先取消 |
| `load_failed` | 409 | 加载失败，原因见 detail 与 worker 日志 |
| `model_busy` | 409 | 模型正在加载、卸载或下载，请等待当前操作结束后重试 |
| `model_conflict` | 409 | 已有一个无法确认归属的同名模型进程占用该模型，需人工确认 |
| `model_mem_limit_exceeded` | 409 | 模型静态占用超过它自己的内存上限，请调大该模型的上限 |
| `model_not_loaded` | 409 | 模型未加载（或上次加载失败），请先加载 |
| `storage_busy` | 409 | 已有数据目录搬迁任务在进行 |
| `system_memory_insufficient` | 409 | 系统内存不足，请先停止占用内存的进程（如 agent） |
| `payload_too_large` | 413 | 请求体超过上限 |
| `unsupported_media_type` | 415 | 上传的文件类型或音频容器无法解析 |
| `validation_error` | 422 | 请求体或查询参数不符合接口定义（字段类型、取值范围、必填项） |
| `queue_full` | 429 | 模型请求队列已满，响应头 Retry-After 给出建议间隔 |
| `client_closed` | 499 | 客户端在服务端完成前断开了连接 |
| `internal_error` | 500 | 服务内部错误（磁盘、数据库等），说明见 detail |
| `model_unavailable` | 503 | 模型进程已退出：它加载过，现在没了，重新加载即可恢复 |
| `service_unavailable` | 503 | 依赖的子系统暂不可用（审计库不可读等） |

状态码与 `code` 的对应关系不是一一的：`409` 覆盖了「状态不对」的一整类拒绝，具体是哪一种由 `code` 说明——这正是一个脚本需要区分的（等一会儿重试 / 先卸载 / 改设置 / 人工确认）。


## 分页与时间格式

- **分页**：列表类接口用 `limit` + `offset`，响应用
  `{"items": [...], "total": N, "limit": N, "offset": N}`（推理记录、审计）；日志用
  **字节游标**：响应给 `cursor`，取更旧的一页时原样传回；`has_more` 说明还有没有。
- **时间**：响应里的时间统一是 **epoch 秒（浮点）**；同时给 `*_iso` 字段的地方是
  本地时区带偏移的 ISO8601（给人和 Excel 用）。请求里的 `since` / `until`
  （只有日志与审计接口有）接受三种写法：epoch 秒、ISO8601、相对时间（`-30m`、`-2h`、`-7d`）。
- **大小**：一律字节数，字段名以 `_bytes` 结尾。
- **布尔**：真布尔，不用 0/1。

## /v1 的文档

`/v1/*` 的 OpenAPI **单独提供**，在 `/v1/openapi.json`，不在本文件里。理由：

1. **凭据不同。** `/api` 用 admin key 或会话 cookie，`/v1` 用 inference key。混在一份
   文档里，Swagger 的「Authorize」只能表达一个凭据，另一种总要靠文字补充说明。
2. **错误体不同。** `/v1` 是 OpenAI 的错误封装，`/api` 是 `{detail, code}`。同一份文档
   里每个接口都要写「本接口的错误体是另一种」，读者反而更容易记错。
3. **读者不同。** 读 `/api` 的是要写运维脚本的人，读 `/v1` 的是要接 OpenAI SDK 的人；
   后者的第一手材料是 OpenAI 的规范，本服务的 `/v1` 只是它的一个实现。
4. **暴露面不同。** `/v1` 的 key 会发给板子上的 agent，而枚举整个管理面不该是这些 key
   的能力；分成两份文档后，`/v1/openapi.json` 也能要求管理凭据才能读。

两份文档由同一个 app 生成、只做路径过滤，所以 schema 定义不会互相漂移。

## 约定

- 所有路径都以服务根为基准（默认 `http://<板子>:8000`）。
- 模型 id 就是 `models/` 下的目录名；路径参数里的 id 不做转义假设，含特殊字符的目录名
  请用 URL 编码。
- 本服务不改版本号本文件就更新；接口字段只增不改——新增字段是兼容的，控制台已读的字段
  不会被改名（`docs/console-design.md` 的契约）。

## 接口一览

按模块分组；每条给出方法、路径和一句话说明。详细字段见后面的章节。

### auth

登录、退出、会话状态、修改口令。脚本通常不需要这些：用 admin key 直接调用即可。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | 管理员登录（换会话 cookie） |
| POST | `/api/logout` | 退出登录（清除会话 cookie） |
| POST | `/api/password` | 修改管理员口令 |
| GET | `/api/session` | 查询当前请求是否已登录 |

### stats

总览页的读数：设备（CPU / 内存 / 温度 / NPU+VPP 内存）、累计用量、前缀缓存、磁盘。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stats` | 总览：设备读数、累计用量、每个模型的状态 |

### models

模型列表、加载、卸载、删除、单模型设置、worker 日志。「模型」页的全部接口。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/models` | 列出 models/ 下的全部模型及其状态 |
| DELETE | `/api/models/{model_id}` | 从磁盘删除一个模型 |
| POST | `/api/models/{model_id}/load` | 加载一个模型 |
| GET | `/api/models/{model_id}/log` | 读一个模型的 worker 日志尾部 |
| GET | `/api/models/{model_id}/settings` | 读一个模型的按模型设置 |
| PUT | `/api/models/{model_id}/settings` | 改一个模型的按模型设置（空闲卸载阈值 / 自动加载 / 内存上限） |
| POST | `/api/models/{model_id}/unload` | 卸载一个模型 |

### downloads

模型下载：启动、进度、取消、更新到 dfss 标签指向的最新版本，以及本版本支持的模型目录。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/catalog` | 本版本支持的模型目录（含「有新版本」判定） |
| GET | `/api/downloads` | 列出下载任务与磁盘残留 |
| POST | `/api/downloads` | 启动一个模型下载任务 |
| POST | `/api/downloads/{job_id}/cancel` | 取消一个下载任务 |
| POST | `/api/models/{model_id}/update` | 把模型更新到 dfss 标签指向的最新版本 |

### settings

全局设置、数据目录占用与搬迁。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings` | 读全局设置（含各项的边界） |
| POST | `/api/settings` | 保存全局设置并立即应用到已加载的模型 |
| GET | `/api/storage` | 数据目录的占用与所在文件系统 |
| GET | `/api/storage/move` | 搬迁任务的进度 |
| POST | `/api/storage/move` | 把数据目录搬到另一个位置（异步） |

### keys

API key 的增删查与吊销。key 分 `inference`（只能调 `/v1`）和 `admin`（还能调 `/api`）两种权限范围。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/keys` | 列出全部 API key |
| POST | `/api/keys` | 创建 API key |
| DELETE | `/api/keys/{key_id}` | 删除一个 API key |
| POST | `/api/keys/{key_id}/revoke` | 吊销一个 API key（保留记录） |

### records

推理记录：每次推理一条，用于事后解释一次错误回答。列表不含对话正文，正文在详情里。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/inference-records` | 推理记录列表（不含对话正文） |
| GET | `/api/inference-records-export` | 导出全部推理记录（NDJSON） |
| POST | `/api/inference-records/clear` | 清空推理记录并把磁盘空间还给系统 |
| GET | `/api/inference-records/status` | 记录库自身的状态（可读性、大小、最近一次写入失败） |
| GET | `/api/inference-records/{record_id}` | 一条推理记录的完整内容（含消息与输出原文） |

### console

控制台自己的对话与测试代理：用 cookie 或 admin key 驱动模型，不必先申请 key。字段与 `/v1` 对应接口一致。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 控制台的对话（非流式） |
| POST | `/api/chat/stream` | 控制台的对话（SSE 流式） |
| POST | `/api/test/audio/transcriptions` | 控制台测试面板：语音转写 |
| POST | `/api/test/chat/completions` | 控制台测试面板：OpenAI 对话（含视觉） |
| POST | `/api/test/embeddings` | 控制台测试面板：embedding |
| POST | `/api/test/ocr` | 控制台测试面板：OCR |
| POST | `/api/test/rerank` | 控制台测试面板：rerank |

### logs

平台 / worker / agent 三类日志的读取与下载，以及管理审计。审计只记写操作，读日志不产生审计行。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit` | 管理审计：谁在什么时候改了什么 |
| GET | `/api/audit/export` | 导出审计为 CSV |
| GET | `/api/logs/sources` | 列出可读的日志源 |
| GET | `/api/logs/{source}` | 读一页日志 |
| GET | `/api/logs/{source}/download` | 下载日志（过滤后的文本，或含轮转的 zip） |

### agents

内置 agent（opencode / OpenClaw / DSH）的安装、启停、配置、日志。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agents` | 列出内置 agent 的状态 |
| GET | `/api/agents/{agent_id}` | 读一个 agent 的状态 |
| PATCH | `/api/agents/{agent_id}` | 改一个 agent 的配置（端口 / 自启 / 模型 / 思考模式） |
| POST | `/api/agents/{agent_id}/install` | 安装一个 agent（下载在后台进行） |
| GET | `/api/agents/{agent_id}/job` | 读一个 agent 的安装任务 |
| GET | `/api/agents/{agent_id}/logs` | 读一个 agent 的日志尾部 |
| POST | `/api/agents/{agent_id}/{action}` | 对一个 agent 执行操作（start / stop / restart / reset / uninstall / sync） |

### apps

「应用演示」的接口：知识库问答与语音转写流。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/apps/asr/transcriptions/stream` | 语音转写（按段流式） |
| GET | `/api/apps/kb` | 列出知识库 |
| POST | `/api/apps/kb` | 新建知识库 |
| DELETE | `/api/apps/kb/{kb_id}` | 删除知识库 |
| POST | `/api/apps/kb/{kb_id}/answer` | 基于检索到的片段流式生成带引用的回答 |
| GET | `/api/apps/kb/{kb_id}/docs` | 列出库里的文档及其索引状态 |
| POST | `/api/apps/kb/{kb_id}/docs` | 上传一个或多个文档，排进建库队列 |
| DELETE | `/api/apps/kb/{kb_id}/docs/{doc_id}` | 删除一个文档 |
| GET | `/api/apps/kb/{kb_id}/docs/{doc_id}/chunks` | 读一个文档切出的全部片段 |
| GET | `/api/apps/kb/{kb_id}/docs/{doc_id}/file` | 下载文档的原始文件 |
| GET | `/api/apps/kb/{kb_id}/docs/{doc_id}/pages/{page}.png` | 读文档某一页的预览图（PNG） |
| POST | `/api/apps/kb/{kb_id}/docs/{doc_id}/retry` | 重试一个失败的文档 |
| POST | `/api/apps/kb/{kb_id}/reindex` | 用当前加载的 embedding 模型重建整个库的向量 |
| POST | `/api/apps/kb/{kb_id}/search` | 检索：BM25 + 向量 → RRF → 精排 |

## 接口详情

### auth

#### `POST /api/login`

**管理员登录（换会话 cookie）**

用管理员口令换取签名会话 cookie，有效期 12 小时。控制台用它；脚本应改用 `Authorization: Bearer <admin key>`，不必登录。口令错误时固定延迟 0.4 秒，避免成为暴力破解的计时旁路。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `password` | string | 必填 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `422`（错误体见「错误格式」）

```bash
curl -s -c jar -X POST http://<板子>:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"<管理员口令>"}'
```

#### `POST /api/logout`

**退出登录（清除会话 cookie）**

删除浏览器里的会话 cookie。服务端不保留会话表，因此不需要别的动作。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/logout \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/password`

**修改管理员口令**

新口令至少 6 个字符。改完之后旧 cookie 仍然有效（会话密钥没变），下次登录用新口令。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `password` | string | 必填 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`400`, `401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/password \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/session`

**查询当前请求是否已登录**

控制台启动时用它决定显示登录页还是主界面。始终返回 200，未登录时 `authenticated: false`。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `authenticated` | bool | 必填 | 当前请求是否带着有效的管理员会话 cookie |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/session \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### stats

#### `GET /api/stats`

**总览：设备读数、累计用量、每个模型的状态**

控制台总览页每几秒轮询一次。一次请求返回四组数据：`device` 是主板读数（读数来源见 `device.device_mem.source`，mock 后端为 `mock`）；`usage` 是累计用量与decode 速度采样；`models` 与 `GET /api/models` 同形；`kv_cache` / `workers` 是各 worker 自报的统计。设备内存口径见 `docs/device-memory.md`。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `device` | object | 必填 | 设备读数 |
| `vpp_reserve` | object | 可选 | 服务为多媒体栈预留的 VPP 块（会计入 device_mem 的已用） |
| `usage` | object | 必填 | 累计用量 |
| `models` | object[] | 必填 | 每个模型的完整状态（同 GET /api/models） |
| `max_loaded_models` | int | 必填 | 同时加载的对话模型上限；0 = 不限 |
| `kv_cache` | object | 必填 | 每个已加载模型的前缀缓存用量，按模型 id |
| `workers` | object | 必填 | 每个已加载 worker 自己报告的统计，按模型 id |
| `disk` | object | 必填 | models/ 的磁盘占用 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/stats \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### models

#### `GET /api/models`

**列出 models/ 下的全部模型及其状态**

含未加载的模型。`loaded` / `operation` / `load_error` 是控制台判断按钮可用性的依据；`settings` 是操作者保存的原样值（可能为 null，表示跟随默认），`effective` 是当前生效值，`mem_*_bytes` 是上限与占用的账。为了少一次 RPC，已加载且空闲的模型会顺带取一次 worker 统计，因此本接口在 worker 无响应时最多慢 3 秒。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `models` | object[] | 必填 | models/ 下的全部模型，含未加载的 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/models \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `DELETE /api/models/{model_id}`

**从磁盘删除一个模型**

已加载、正在加载/卸载、正在下载的模型都拒绝删除（409）。删除时连同它的按模型设置一起清掉，避免同名模型下次被下载时继承旧的限制。

路径参数：`model_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X DELETE http://<板子>:8000/api/models/{model_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/models/{model_id}/load`

**加载一个模型**

加载完成才返回（`loaded: true`），35B 需几十秒。重复调用是幂等的：已加载时直接返回当前状态。设备内存不足、静态占用超过本模型上限、或已有无法确认归属的同名进程时返回 409，`code` 分别是 `device_memory_insufficient` / `model_mem_limit_exceeded` / `model_conflict`。

路径参数：`model_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |
| `model` | object | 必填 | 操作完成后的模型状态 |

可能的状态码：`401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/models/{model_id}/load \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/models/{model_id}/log`

**读一个模型的 worker 日志尾部**

`tail` 是行数（默认 200）。日志文件不存在时返回空串而不是 404：「这个模型自启动以来没跑过」是信息，不是错误。

路径参数：`model_id`

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `lines` | int | `200` |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `log` | string | 必填 | 日志尾部文本；没有日志时为空串 |

可能的状态码：`401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/models/{model_id}/log \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: lines
```

#### `GET /api/models/{model_id}/settings`

**读一个模型的按模型设置**

返回保存的设置、当前生效值、内存上限的推算默认值与各项边界。`limits` 里的数字就是 `PUT` 接受的取值范围，控制台的输入框直接用它。

路径参数：`model_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id |
| `kind` | string | 必填 | 模型类型 |
| `settings` | object | 必填 | 保存的设置，原样返回 |
| `effective` | object | 必填 | 当前生效的值 |
| `mem_limit_default_bytes` | int | 必填 | 推算的默认上限（字节） |
| `mem_static_bytes` | int | 必填 | 静态占用（字节） |
| `mem_used_bytes` | int | 可选 | 运行期占用（字节） |
| `limits` | map[string, int] | 必填 | 本路由接受的取值范围，供控制台的输入框直接使用 |
| `auto_load_note` | string | 必填 | 给操作者的提示：自动加载大模型要几十秒 |
| `applied` | object | 可选 | 新上限推送到运行中 worker 的结果；模型未加载或没有 client 时为 null |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/models/{model_id}/settings \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `PUT /api/models/{model_id}/settings`

**改一个模型的按模型设置（空闲卸载阈值 / 自动加载 / 内存上限）**

字段语义是「省略不改、`null` 恢复默认」，两者不同：控制台只发送操作者动过的那一个字段。拒绝有四处：字段越界（400）、模型正在加载或卸载（409，`model_busy`）、内存上限低于模型当前占用（400）、**运行中增额后 NPU 剩余量低于安全下限**（409，`device_memory_insufficient`）。增额与模型加载共用同一份设备预算准入：扣掉**所有**已加载大模型的运行期预算（含本模型自己原来的预算）、尚未完成的承诺和 1 GiB 保护下限。所以 free=1624 MiB、原预算 400、调到 1000 会被拒绝 —— 只剩 624 MiB，边界是 2024 MiB；缓存/会话较多时也可能拒绝物理上放得下的增额，需要更大额度请先卸载其他模型。`native` 后端读不到设备余量时不放行（503）。拒绝时原设置与 worker 额度都不变。改完立即生效，不需要重新加载模型。**答复丢失时的收尾**：`configure` 超时、连接断开、本地写失败或读到 EOF 后，本接口会读一次 worker 的实际额度再决定 —— 确实已应用则保存并按成功返回（`applied.settled_after_lost_reply`），确认未应用是 409，无法确认则保留这部分额度并按 503 报告，该额度继续按已占用记账（后续加载与增额都用不到它）。**恢复有三条路径，都不需要重启服务**：① 重试同一次保存 —— 会先核对 worker 的实际额度再收敛，已应用就补写设置并返回 200；② 改不同的额度 —— 核对完成前 409 `model_busy`；③ 卸载该模型 —— worker 进程确认退出后对应未确认额度清零（卸载失败或进程仍在则保留）。取消请求时同样先标记未确认，并在同一次请求内做有界核对，不遗留脱离锁写设置的后台任务。

路径参数：`model_id`

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `idle_unload_min` | int | 可选 |  |
| `auto_load` | bool | 可选 |  |
| `mem_limit_mb` | int | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id |
| `kind` | string | 必填 | 模型类型 |
| `settings` | object | 必填 | 保存的设置，原样返回 |
| `effective` | object | 必填 | 当前生效的值 |
| `mem_limit_default_bytes` | int | 必填 | 推算的默认上限（字节） |
| `mem_static_bytes` | int | 必填 | 静态占用（字节） |
| `mem_used_bytes` | int | 可选 | 运行期占用（字节） |
| `limits` | map[string, int] | 必填 | 本路由接受的取值范围，供控制台的输入框直接使用 |
| `auto_load_note` | string | 必填 | 给操作者的提示：自动加载大模型要几十秒 |
| `applied` | object | 可选 | 新上限推送到运行中 worker 的结果；模型未加载或没有 client 时为 null |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`, `503`（错误体见「错误格式」）

```bash
curl -s -X PUT http://<板子>:8000/api/models/{model_id}/settings \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/models/{model_id}/unload`

**卸载一个模型**

先拒绝（409）再动手：卸载过程中的模型不会被改坏。worker 正忙时返回 `model_busy`。

路径参数：`model_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |
| `model` | object | 必填 | 操作完成后的模型状态 |

可能的状态码：`401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/models/{model_id}/unload \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### downloads

#### `GET /api/catalog`

**本版本支持的模型目录（含「有新版本」判定）**

每张卡片带 `installed` / `downloading`，已安装且登记了 dfss 标签的还带 `latest_file` / `update_available`。标签索引要一次 dfss 下载，因此缓存 10 分钟并在后台刷新：本接口只读缓存，离线设备拿不到更新信息，但页面照常打开。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `models` | object[] | 必填 | 本版本支持的模型 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/catalog \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/downloads`

**列出下载任务与磁盘残留**

`jobs` 是全部任务（最新的在前）；`orphans` 是上次失败留下的 `.part`/`.bak`，其中 `recoverable` 里的 `.bak` 是唯一副本，不要删。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `jobs` | object[] | 必填 | 全部下载任务，最新的在前 |
| `orphans` | object | 必填 | 磁盘上的残留文件 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/downloads \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/downloads`

**启动一个模型下载任务**

`kind: "dfss"` 走 dfss，`kind: "url"` 走 http(s)。多文件模型（OCR 是四个 bmodel）用 `files` 给出清单；`kind: dfss` 且省略时用本版本登记的清单展开，这样「一键下载」不会只装一个碎片。目标模型正在运行、正在加载或已在下载时返回 409。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `url` | string | 必填 |  |
| `name` | string | 必填 |  |
| `kind` | string | 可选 |  |
| `expected_bytes` | int | 可选 |  |
| `files` | object[] | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 必填 | 刚创建的任务 |

可能的状态码：`400`, `401`, `403`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/downloads \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/downloads/{job_id}/cancel`

**取消一个下载任务**

等传输真的停下来才返回，因此模型锁的释放时机是确定的。

路径参数：`job_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/downloads/{job_id}/cancel \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/models/{model_id}/update`

**把模型更新到 dfss 标签指向的最新版本**

会占用该模型 id 的下载锁；模型正在运行、加载、卸载或下载时返回 409。失败时磁盘上的旧版本不受影响。

路径参数：`model_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 必填 | 刚创建的任务 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/models/{model_id}/update \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### settings

#### `GET /api/settings`

**读全局设置（含各项的边界）**

`*_limit*` / `*_min` / `*_max` 字段是同一个字段的取值范围，发布出来是为了让控制台的输入框不必再写一遍常量。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `max_concurrent_per_model` | int | 必填 | 每个模型同时处理的请求数上限（1-3） |
| `max_concurrency_limit` | int | 必填 | 上面这个字段的硬上限 |
| `prefix_cache_entries` | int | 必填 | 前缀缓存条目上限 |
| `prefix_cache_ttl_min` | int | 必填 | 未被使用的前缀缓存保留分钟数 |
| `max_queue` | int | 必填 | 排队请求上限；超出的直接 429 |
| `prefill_exact_tail` | int | 必填 | 长 prompt 尾部走 decode 图的 token 数；0 = 关闭 |
| `require_api_key` | bool | 必填 | `/v1` 是否要求 API key |
| `inference_logging_enabled` | bool | 必填 | 是否记录推理记录 |
| `inference_log_retention_count` | int | 必填 | 推理记录保留条数上限 |
| `inference_log_retention_days` | int | 必填 | 推理记录保留天数上限 |
| `aux_idle_unload_min` | int | 必填 | 辅助模型的默认空闲卸载阈值（分钟），0 = 不卸载 |
| `aux_idle_unload_limit_min` | int | 必填 | 这个字段的硬上限 |
| `aux_auto_load` | bool | 必填 | 是否默认按需自动加载辅助模型 |
| `audit_retention_days` | int | 必填 | 管理审计保留天数 |
| `audit_retention_days_min` | int | 必填 | 审计保留下限 |
| `audit_retention_days_max` | int | 必填 | 审计保留上限 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/settings \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/settings`

**保存全局设置并立即应用到已加载的模型**

字段全部可选；**越界值会被夹到边界而不是报错**（设置页的输入框可能送来一个过期的数字，不该因此存不进去；需要严格校验的是按模型的内存上限，那条路由拒绝越界）。`applied` 汇总每个已加载 worker 的应答，推送失败的带一个 `error` 键——设置已经保存，只是某个 worker 没收到。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `max_concurrent_per_model` | int | 可选 |  |
| `prefix_cache_entries` | int | 可选 |  |
| `prefix_cache_max_mb` | int | 可选 | 自 v0.6.34 起无效（总上限已删除）：接受但忽略，每个模型的前缀缓存改由该模型自己的内存上限约束 |
| `prefix_cache_ttl_min` | int | 可选 |  |
| `max_queue` | int | 可选 |  |
| `prefill_exact_tail` | int | 可选 |  |
| `inference_logging_enabled` | bool | 可选 |  |
| `inference_log_retention_count` | int | 可选 |  |
| `inference_log_retention_days` | int | 可选 |  |
| `aux_idle_unload_min` | int | 可选 |  |
| `aux_auto_load` | bool | 可选 |  |
| `audit_retention_days` | int | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `settings` | object | 必填 | 保存后（夹紧之后）的设置 |
| `applied` | object | 必填 | 每个已加载模型推送新设置的返回值；推送失败的模型带一个 `error` 键 |

可能的状态码：`400`, `401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/settings \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/storage`

**数据目录的占用与所在文件系统**

`refresh=true` 跳过 30 秒的大小缓存。`parts` 按子目录拆开，`dir_bytes` 是它们的和。

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `refresh` | bool | `False` |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `data_dir` | string | 必填 | 当前数据目录 |
| `fs_total_bytes` | int | 必填 | 所在文件系统总大小 |
| `fs_used_bytes` | int | 必填 | 所在文件系统已用 |
| `fs_free_bytes` | int | 必填 | 所在文件系统可用 |
| `dir_bytes` | int | 必填 | 数据目录占用（等于 parts 之和） |
| `parts` | map[string, int] | 必填 | 按子目录拆开：models / state / agents / downloads / apps / inbox |

可能的状态码：`401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/storage \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: refresh
```

#### `GET /api/storage/move`

**搬迁任务的进度**

没有任务时返回 `state: "idle"` 的空任务，而不是 404：设置页始终能画出这一块。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 任务 id；空闲时为 "" |
| `state` | `idle` \| `checking` \| `copying` \| `verifying` \| `switching` \| `done` \| `failed` | 必填 | 搬到哪一步了 |
| `copied_bytes` | int | 必填 | 已复制字节数 |
| `total_bytes` | int | 必填 | 需要复制的总字节数 |
| `message` | string | 必填 | 进度说明或失败原因 |
| `old` | string | 必填 | 原数据目录 |
| `new` | string | 必填 | 目标数据目录；空闲时为 "" |
| `started_at` | float | 必填 | 开始时间（epoch 秒） |
| `finished_at` | float | 可选 | 结束时间（epoch 秒） |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/storage/move \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/storage/move`

**把数据目录搬到另一个位置（异步）**

**先在请求里校验，再在后台搬**：校验会走一遍当前数据树来估大小，因此在本请求里同步执行；搬运用 `GET /api/storage/move` 轮询。已有任务在进行时 409（`storage_busy`）。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `path` | string | 必填 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | string | 必填 | 搬迁任务 id；进度用 GET /api/storage/move 查 |

可能的状态码：`400`, `401`, `403`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/storage/move \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### keys

#### `GET /api/keys`

**列出全部 API key**

只返回元数据：明文 key 只在创建时返回一次，服务端只存 SHA-256 哈希。`scope` 字段说明这把 key 能不能调 `/api`。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `keys` | object[] | 必填 | 全部 key，含已吊销的 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/keys \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/keys`

**创建 API key**

`scope` 默认 `inference`（只能调 `/v1`）。需要脚本管理服务时创建 `scope: admin` 的 key，然后用 `Authorization: Bearer <key>` 调用 `/api/*`。明文 key 只在本响应里出现一次。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `name` | string | 可选 |  |
| `scope` | string | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `key` | string | 必填 | **明文 key，只在这里返回一次**；服务端只存哈希 |
| `meta` | object | 必填 | 这条 key 的元数据（同 `GET /api/keys` 的元素） |

可能的状态码：`400`, `401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/keys \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `DELETE /api/keys/{key_id}`

**删除一个 API key**

与吊销不同：删除后这把 key 从列表里消失。两者都立即生效。

路径参数：`key_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X DELETE http://<板子>:8000/api/keys/{key_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/keys/{key_id}/revoke`

**吊销一个 API key（保留记录）**

吊销后这把 key 不能再认证，但仍在列表里可见，便于审计回溯。

路径参数：`key_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/keys/{key_id}/revoke \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### records

#### `GET /api/inference-records`

**推理记录列表（不含对话正文）**

最新的在前。重字段（消息、输出原文）只在详情里：一页 200 条、每条都带 128k 对话会是几十 MB。`limit` 1-200；`before` 是排他的时间上界，用于在持续写入时向后翻页。

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int | `50` |  |
| `offset` | int | `0` |  |
| `before` | float |  |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `items` | object[] | 必填 | 这一页，最新的在前 |
| `total` | int | 必填 | 总条数 |
| `limit` | int | 必填 | 本页最多多少条 |
| `offset` | int | 必填 | 本页起点 |

可能的状态码：`400`, `401`, `403`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/inference-records \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: limit, offset, before
```

#### `GET /api/inference-records-export`

**导出全部推理记录（NDJSON）**

一行一条完整记录，最新的在前，流式输出（读表时分页，10 万条也不会变成一个字符串）。用 `responses` 声明的内容类型是 `application/x-ndjson`，并带 `Content-Disposition` 附件名。

响应内容类型 `application/x-ndjson`，流式输出。

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/inference-records-export \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/inference-records/clear`

**清空推理记录并把磁盘空间还给系统**

不可撤销。`deleted` 是被删掉的条数。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 成功 |
| `deleted` | int | 必填 | 删掉了多少条 |

可能的状态码：`401`, `403`, `500`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/inference-records/clear \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/inference-records/status`

**记录库自身的状态（可读性、大小、最近一次写入失败）**

「列表为什么是空的」的答案在这里：库不可写时 `readable: false` 且 `last_error` 有原因。搬迁期间 `moving: true`，写入是暂停而不是坏了。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `path` | string | 必填 | 记录库文件路径 |
| `enabled` | bool | 必填 | 是否在记录 |
| `total` | int | 必填 | 库里有多少条 |
| `bytes` | int | 可选 | 库文件占用的字节数 |
| `schema_version` | int | 必填 | 记录库结构版本 |
| `retention_count` | int | 必填 | 保留条数上限 |
| `retention_days` | int | 必填 | 保留天数上限 |
| `readable` | bool | 必填 | 库是否可读；false 时列表会 500，服务其余部分照常 |
| `moving` | bool | 必填 | 是否正在随数据目录迁移（此时记录暂停） |
| `last_error` | string | 可选 | 最近一次写入失败的原因 |
| `last_error_at` | float | 可选 | 最近一次失败的时间 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/inference-records/status \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/inference-records/{record_id}`

**一条推理记录的完整内容（含消息与输出原文）**

控制台的记录页点开一行时调用。响应在列表字段之外还带 `messages`（原始请求）、`output_text` / `raw_output`（输出正文）与 `error`，这是唯一能读到对话内容的接口。

路径参数：`record_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 记录 id |
| `started_at` | float | 必填 | 开始时间（epoch 秒） |
| `finished_at` | float | 可选 | 结束时间（epoch 秒） |
| `source` | string | 必填 | 请求路径，区分控制台与 API 流量 |
| `model` | string | 必填 | 模型 id |
| `actor_type` | string | 必填 | 操作者类型 |
| `actor_name` | string | 可选 | 操作者名字 |
| `status` | string | 必填 | ok / error / cancelled |
| `finish_reason` | string | 可选 | stop / length / tool_calls |
| `prompt_tokens` | int | 可选 | 输入 token |
| `completion_tokens` | int | 可选 | 输出 token |
| `cached_tokens` | int | 可选 | 命中缓存的 token |
| `first_token_latency_s` | float | 可选 | 首 token 延迟（秒） |
| `decode_tps` | float | 可选 | decode 速度（tok/s） |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/inference-records/{record_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### console

#### `POST /api/chat`

**控制台的对话（非流式）**

与 `/v1/chat/completions` 走同一条推理路径，但用控制台凭据而不是 API key，因此操作者不必先申请 key 才能在界面上试一句话。只服务 chat / ocr_vl 两类模型；别的类型请用 `/api/test/*`。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `prompt` | string | 可选 |  |
| `max_tokens` | int | 可选 |  |
| `temperature` | float | 可选 |  |
| `images` | string[] | 可选 |  |
| `enable_thinking` | bool | 可选 |  |
| `messages` | object[] | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `text` | string | 必填 | 模型输出（思考内容已剥离） |
| `prompt_tokens` | int | 必填 | 输入 token |
| `completion_tokens` | int | 必填 | 输出 token |
| `cached_tokens` | int | 必填 | 命中前缀缓存的 token |
| `first_token_latency_s` | float | 可选 | 首 token 延迟（秒） |
| `decode_tps` | float | 可选 | decode 速度（tok/s） |
| `finish_reason` | string | 可选 | stop / length |

可能的状态码：`400`, `401`, `403`, `409`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/chat \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/chat/stream`

**控制台的对话（SSE 流式）**

同一请求，逐 token 返回 `data: {"text": ...}`，最后 `data: {"done": true, ...}` 与 `data: [DONE]`。模型拒绝时以 `data: {"error": ...}` 收尾再发 `[DONE]`。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `prompt` | string | 可选 |  |
| `max_tokens` | int | 可选 |  |
| `temperature` | float | 可选 |  |
| `images` | string[] | 可选 |  |
| `enable_thinking` | bool | 可选 |  |
| `messages` | object[] | 可选 |  |

响应内容类型 `text/event-stream`，流式输出。

可能的状态码：`400`, `401`, `403`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/chat/stream \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/test/audio/transcriptions`

**控制台测试面板：语音转写**

`multipart/form-data`（`model`、`file`、可选 `language` / `prompt`），由 `/v1/audio/transcriptions` 的处理函数读取，字段与错误码一致。

响应 `200 application/json`：

（无字段）

可能的状态码：`400`, `401`, `403`, `409`, `415`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/test/audio/transcriptions \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/test/chat/completions`

**控制台测试面板：OpenAI 对话（含视觉）**

直接调用 `/v1/chat/completions` 的处理函数，因此拿到与官方客户端完全相同的类型规则与响应。请求体见 `app/schemas.py` 的 `ChatCompletionRequest`。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `messages` | object[] | 必填 |  |
| `max_tokens` | int | 可选 |  |
| `max_completion_tokens` | int | 可选 |  |
| `temperature` | float | 可选 |  |
| `top_p` | float | 可选 |  |
| `n` | int | 可选 |  |
| `stream` | bool | 可选 |  |
| `stop` | string | 可选 |  |
| `presence_penalty` | float | 可选 |  |
| `frequency_penalty` | float | 可选 |  |
| `seed` | int | 可选 |  |
| `top_k` | int | 可选 |  |
| `repetition_penalty` | float | 可选 |  |
| `enable_thinking` | bool | 可选 |  |
| `chat_template_kwargs` | object | 可选 |  |
| `tools` | any[] | 可选 |  |
| `tool_choice` | string | 可选 |  |
| `parallel_tool_calls` | bool | 可选 |  |

响应 `200 application/json`：

（无字段）

可能的状态码：`400`, `401`, `403`, `409`, `422`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/test/chat/completions \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/test/embeddings`

**控制台测试面板：embedding**

直接调用 `/v1/embeddings` 的处理函数，字段与错误码完全一致，只是调用者是管理端、不必持有 inference key。请求体与响应见 `/v1/openapi.json` 的 `POST /v1/embeddings`。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `input` | any | 必填 | 字符串或字符串数组，最多 64 条。Qwen3-VL-Embedding / WeMM-Embedding 还接受 {text?: string, image?: JPEG/PNG base64 data URL} 及混合数组；每条一张图片，单张最多 4 MiB，每批最多 16 张、合计 16 MiB。 |
| `encoding_format` | `float` \| `base64` | 可选 |  |
| `dimensions` | int | 可选 | 截断后重新 L2 归一化；Qwen3-Embedding 为 32–1024，Qwen3-VL-Embedding / WeMM-Embedding-2B 为 64–2048。 |
| `instruction` | string | 可选 | 可选任务指令。文本 embedding 拼在输入前；多模态 embedding 使用系统指令；Qwen3-VL 默认 Represent the user's input.，WeMM 默认不加系统指令。 |

响应 `200 application/json`：

（无字段）

可能的状态码：`400`, `401`, `403`, `409`, `422`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/test/embeddings \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/test/ocr`

**控制台测试面板：OCR**

`multipart/form-data`（`file` + `model`）或 JSON（`{"model", "image"}`），由 `/v1/ocr` 的处理函数读取，含 `mode=vl` 的两模型编排。

响应 `200 application/json`：

（无字段）

可能的状态码：`400`, `401`, `403`, `409`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/test/ocr \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/test/rerank`

**控制台测试面板：rerank**

直接调用 `/v1/rerank` 的处理函数。请求体与响应见 `/v1/openapi.json` 的 `POST /v1/rerank`。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `query` | string | 必填 |  |
| `documents` | any[] | 必填 |  |
| `top_n` | int | 可选 |  |
| `return_documents` | bool | 可选 |  |

响应 `200 application/json`：

（无字段）

可能的状态码：`400`, `401`, `403`, `409`, `422`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/test/rerank \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### logs

#### `GET /api/audit`

**管理审计：谁在什么时候改了什么**

只记写操作（POST/PUT/PATCH/DELETE）与登录，读操作不记。`action` 是 `"方法 路径前缀"`，例如 `POST /api/models` 也匹配 `/api/models/x/load`。`dropped` 非零表示审计链有缺口。审计库不可读时返回 503 而不是空表。

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `since` | string |  |  |
| `until` | string |  |  |
| `actor` | string |  |  |
| `action` | string |  |  |
| `status` | string |  |  |
| `q` | string |  |  |
| `limit` | int | `50` |  |
| `offset` | int | `0` |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `items` | object[] | 必填 | 这一页，最新的在前 |
| `total` | int | 必填 | 符合条件的总行数 |
| `limit` | int | 必填 | 本页最多多少行 |
| `offset` | int | 必填 | 本页起点 |
| `retention_days` | int | 必填 | 当前保留天数 |
| `dropped` | int | 必填 | 非零表示审计链有缺口（搬迁或写入失败丢了行） |
| `last_error` | string | 可选 | 最近一次写入失败的原因 |

可能的状态码：`400`, `401`, `403`, `422`, `503`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/audit \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: since, until, actor, action, status, q, limit, offset
```

#### `GET /api/audit/export`

**导出审计为 CSV**

UTF-8 **带 BOM**（否则中文 Windows 的 Excel 会把表头读成乱码），列顺序固定，流式输出。

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `since` | string |  |  |
| `until` | string |  |  |
| `actor` | string |  |  |
| `action` | string |  |  |
| `status` | string |  |  |
| `q` | string |  |  |

响应内容类型 `text/csv; charset=utf-8`，流式输出。

可能的状态码：`400`, `401`, `403`, `422`, `503`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/audit/export \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: since, until, actor, action, status, q
```

#### `GET /api/logs/sources`

**列出可读的日志源**

从未写过的日志也会出现，`size_bytes: 0`：`kind` 区分平台 / worker / agent 三类。**这些接口不写审计**：日志页在轮询，一次轮询一行审计会把真正的变更埋掉。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `sources` | object[] | 必填 | 全部日志源，含空的 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/logs/sources \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/logs/{source}`

**读一页日志**

不带 `cursor` 时是「最新的 N 行」，从文件尾往回读，因此读 50 MB 的日志也不会卡住；带 `cursor` 时接着上一页往更旧的方向翻。返回的行**从旧到新**，便于页面自上而下渲染。`since` / `until` 接受 epoch 秒、ISO8601 或相对时间（`-30m` / `-2h` / `-7d`）。

路径参数：`source`

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `since` | string |  |  |
| `until` | string |  |  |
| `level` | string |  |  |
| `q` | string |  |  |
| `limit` | int | `200` |  |
| `cursor` | string |  |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `source` | string | 必填 | 日志源 id |
| `label` | string | 必填 | 日志源名字 |
| `lines` | object[] | 必填 | 这一页的行，**从旧到新** |
| `cursor` | string | 可选 | 取下一页（更旧的一页）时原样传回 `cursor`；null = 没有更旧的了 |
| `has_more` | bool | 必填 | 是否还有更旧的行 |
| `limit` | int | 必填 | 本页最多多少行 |
| `size_bytes` | int | 必填 | 日志源当前大小 |

可能的状态码：`400`, `401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/logs/{source} \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: since, until, level, q, limit, cursor
```

#### `GET /api/logs/{source}/download`

**下载日志（过滤后的文本，或含轮转的 zip）**

带过滤条件时是纯文本（`text/plain; charset=utf-8`）；不带条件时是包含所有轮转代际的 zip （`application/zip`）——只给当前文件会漏掉正要排查的那次事故。两者都是流式的。

路径参数：`source`

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `since` | string |  |  |
| `until` | string |  |  |
| `level` | string |  |  |
| `q` | string |  |  |

响应内容类型 `text/plain; charset=utf-8`，流式输出。

可能的状态码：`400`, `401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/logs/{source}/download \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: since, until, level, q
```

### agents

#### `GET /api/agents`

**列出内置 agent 的状态**

`status` 是四态摘要（running / stopped / failed / not_installed），`operation` 表达四态表达不了的部分（starting 不算 running）。`web_url` 与 `web` 是它自己界面的地址与登录凭据。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `agents` | object[] | 必填 | 三个内置 agent 的状态 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/agents \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/agents/{agent_id}`

**读一个 agent 的状态**

与列表里的元素同形，但 `web_url` 用本次请求的 Host 拼，因此从别的机器访问也打得开。

路径参数：`agent_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | agent id |
| `name` | string | 必填 | 显示名 |
| `version` | string | 必填 | 已安装的版本；未安装为空 |
| `latest_version` | string | 必填 | 本版本支持的最新版本 |
| `default_port` | int | 必填 | 默认端口 |
| `port` | int | 必填 | 当前端口 |
| `installed` | bool | 必填 | 是否已安装 |
| `status` | `running` \| `stopped` \| `failed` \| `not_installed` | 必填 | 四态摘要 |
| `operation` | string | 可选 | 正在进行的操作 |
| `operation_since` | float | 可选 | 该操作的开始时间 |
| `busy` | bool | 必填 | 是否有操作在进行 |
| `operation_label` | string | 必填 | 该操作的中文名 |
| `running` | bool | 必填 | 是否健康运行（启动中不算） |
| `pid` | int | 可选 | 进程号 |
| `health` | bool | 必填 | 本次健康检查是否通过 |
| `adopted` | bool | 必填 | 是否为重启后接管的进程 |
| `orphan_pid` | int | 可选 | 占着端口但不健康的进程号 |
| `rss_bytes` | int | 必填 | 常驻内存（字节） |
| `disk_bytes` | int | 必填 | 安装占用（字节） |
| `autostart` | bool | 必填 | 是否开机自启 |
| `default_model` | string | 必填 | 配置里给它用的模型 |
| `thinking` | bool | 必填 | 是否给它打开思考模式 |
| `embeddable` | bool | 必填 | 能否嵌在控制台里显示 |
| `proxied` | bool | 必填 | 是否由本服务反代它的界面 |
| `card_note` | string | 必填 | 卡片上的补充说明 |
| `memory_floor_bytes` | int | 必填 | 启动它至少需要的内存 |
| `web_url` | string | 必填 | 它的界面地址；未安装为空 |
| `web` | object | 必填 | 它的界面的登录凭据 |
| `models` | object[] | 必填 | 可以配给它的模型 |
| `child_ports` | int[] | 必填 | 它自己再开出来的端口 |
| `started_at` | float | 可选 | 启动时间（epoch 秒） |
| `uptime_s` | float | 可选 | 已运行秒数 |
| `exit_code` | int | 可选 | 上次退出码 |
| `last_error` | string | 可选 | 最近一次错误 |
| `job` | object | 可选 | 安装任务的进度 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/agents/{agent_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `PATCH /api/agents/{agent_id}`

**改一个 agent 的配置（端口 / 自启 / 模型 / 思考模式）**

只发送要改的字段。改运行中 agent 的端口会重启它。其他字段在下次启动时生效。

路径参数：`agent_id`

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `port` | int | 可选 |  |
| `autostart` | bool | 可选 |  |
| `default_model` | string | 可选 |  |
| `thinking` | bool | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | agent id |
| `name` | string | 必填 | 显示名 |
| `version` | string | 必填 | 已安装的版本；未安装为空 |
| `latest_version` | string | 必填 | 本版本支持的最新版本 |
| `default_port` | int | 必填 | 默认端口 |
| `port` | int | 必填 | 当前端口 |
| `installed` | bool | 必填 | 是否已安装 |
| `status` | `running` \| `stopped` \| `failed` \| `not_installed` | 必填 | 四态摘要 |
| `operation` | string | 可选 | 正在进行的操作 |
| `operation_since` | float | 可选 | 该操作的开始时间 |
| `busy` | bool | 必填 | 是否有操作在进行 |
| `operation_label` | string | 必填 | 该操作的中文名 |
| `running` | bool | 必填 | 是否健康运行（启动中不算） |
| `pid` | int | 可选 | 进程号 |
| `health` | bool | 必填 | 本次健康检查是否通过 |
| `adopted` | bool | 必填 | 是否为重启后接管的进程 |
| `orphan_pid` | int | 可选 | 占着端口但不健康的进程号 |
| `rss_bytes` | int | 必填 | 常驻内存（字节） |
| `disk_bytes` | int | 必填 | 安装占用（字节） |
| `autostart` | bool | 必填 | 是否开机自启 |
| `default_model` | string | 必填 | 配置里给它用的模型 |
| `thinking` | bool | 必填 | 是否给它打开思考模式 |
| `embeddable` | bool | 必填 | 能否嵌在控制台里显示 |
| `proxied` | bool | 必填 | 是否由本服务反代它的界面 |
| `card_note` | string | 必填 | 卡片上的补充说明 |
| `memory_floor_bytes` | int | 必填 | 启动它至少需要的内存 |
| `web_url` | string | 必填 | 它的界面地址；未安装为空 |
| `web` | object | 必填 | 它的界面的登录凭据 |
| `models` | object[] | 必填 | 可以配给它的模型 |
| `child_ports` | int[] | 必填 | 它自己再开出来的端口 |
| `started_at` | float | 可选 | 启动时间（epoch 秒） |
| `uptime_s` | float | 可选 | 已运行秒数 |
| `exit_code` | int | 可选 | 上次退出码 |
| `last_error` | string | 可选 | 最近一次错误 |
| `job` | object | 可选 | 安装任务的进度 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X PATCH http://<板子>:8000/api/agents/{agent_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/agents/{agent_id}/install`

**安装一个 agent（下载在后台进行）**

返回安装任务，进度用 `GET /api/agents/{id}/job` 或状态里的 `job` 字段查。

路径参数：`agent_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 可选 | 安装任务；没有任务时 null |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/agents/{agent_id}/install \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/agents/{agent_id}/job`

**读一个 agent 的安装任务**

安装是异步的（下载一个真实的发布包），控制台用它画进度条。没有任务时 `job: null`，而不是 404。

路径参数：`agent_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 可选 | 安装任务；没有任务时 null |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/agents/{agent_id}/job \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/agents/{agent_id}/logs`

**读一个 agent 的日志尾部**

`tail` 是行数（默认 200，上限 5000）。

路径参数：`agent_id`

| 查询参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `tail` | int | `200` |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `log` | string | 必填 | 日志尾部文本；没有日志时为空串 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/agents/{agent_id}/logs \
  -H "Authorization: Bearer $CV84X6_KEY" \
  # 可选查询参数: tail
```

#### `POST /api/agents/{agent_id}/{action}`

**对一个 agent 执行操作（start / stop / restart / reset / uninstall / sync）**

返回操作后的状态。`install` 是单独的路径。未知 action 返回 404；内存不够、端口被占、已安装等情况返回 409 并在 `detail` 里说明怎么办。

路径参数：`agent_id, action`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | agent id |
| `name` | string | 必填 | 显示名 |
| `version` | string | 必填 | 已安装的版本；未安装为空 |
| `latest_version` | string | 必填 | 本版本支持的最新版本 |
| `default_port` | int | 必填 | 默认端口 |
| `port` | int | 必填 | 当前端口 |
| `installed` | bool | 必填 | 是否已安装 |
| `status` | `running` \| `stopped` \| `failed` \| `not_installed` | 必填 | 四态摘要 |
| `operation` | string | 可选 | 正在进行的操作 |
| `operation_since` | float | 可选 | 该操作的开始时间 |
| `busy` | bool | 必填 | 是否有操作在进行 |
| `operation_label` | string | 必填 | 该操作的中文名 |
| `running` | bool | 必填 | 是否健康运行（启动中不算） |
| `pid` | int | 可选 | 进程号 |
| `health` | bool | 必填 | 本次健康检查是否通过 |
| `adopted` | bool | 必填 | 是否为重启后接管的进程 |
| `orphan_pid` | int | 可选 | 占着端口但不健康的进程号 |
| `rss_bytes` | int | 必填 | 常驻内存（字节） |
| `disk_bytes` | int | 必填 | 安装占用（字节） |
| `autostart` | bool | 必填 | 是否开机自启 |
| `default_model` | string | 必填 | 配置里给它用的模型 |
| `thinking` | bool | 必填 | 是否给它打开思考模式 |
| `embeddable` | bool | 必填 | 能否嵌在控制台里显示 |
| `proxied` | bool | 必填 | 是否由本服务反代它的界面 |
| `card_note` | string | 必填 | 卡片上的补充说明 |
| `memory_floor_bytes` | int | 必填 | 启动它至少需要的内存 |
| `web_url` | string | 必填 | 它的界面地址；未安装为空 |
| `web` | object | 必填 | 它的界面的登录凭据 |
| `models` | object[] | 必填 | 可以配给它的模型 |
| `child_ports` | int[] | 必填 | 它自己再开出来的端口 |
| `started_at` | float | 可选 | 启动时间（epoch 秒） |
| `uptime_s` | float | 可选 | 已运行秒数 |
| `exit_code` | int | 可选 | 上次退出码 |
| `last_error` | string | 可选 | 最近一次错误 |
| `job` | object | 可选 | 安装任务的进度 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/agents/{agent_id}/{action} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

### apps

#### `POST /api/apps/asr/transcriptions/stream`

**语音转写（按段流式）**

`multipart/form-data`（`model`、`file`、可选 `language` / `prompt`），每段一帧 SSE：先 `meta`，再若干 `segment`，最后 `done`（正文与 `/v1/audio/transcriptions` 逐字一致）。能在 NPU 开始跑之前判定完的拒绝都是状态码而不是帧：415 容器无法解码，400 音频超过 30 分钟，429 队列已满。

响应内容类型 `text/event-stream`，流式输出。

可能的状态码：`400`, `401`, `403`, `415`, `429`, `503`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/asr/transcriptions/stream \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/apps/kb`

**列出知识库**

`doc_count` / `chunk_count` 来自缓存在 `kb.json` 里的计数：2 万片段的库每次刷新都重新解析一遍不现实。缺这两个字段的老库会重算一次并写回。

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `kbs` | object[] | 必填 | 全部知识库，最新创建的在前 |

可能的状态码：`401`, `403`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/apps/kb \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb`

**新建知识库**

名字可为空（界面上就是「未命名」）。新建的库是空的：下一步用 `POST /api/apps/kb/{kb_id}/docs` 上传文档，等 `status` 变成 `ready` 才能检索。

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `name` | string | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `kb` | object | 必填 | 新建的知识库 |

可能的状态码：`400`, `401`, `403`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `DELETE /api/apps/kb/{kb_id}`

**删除知识库**

连同它的文档、切片、向量一起删；队列里属于它的任务会被丢弃。

路径参数：`kb_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`, `404`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X DELETE http://<板子>:8000/api/apps/kb/{kb_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb/{kb_id}/answer`

**基于检索到的片段流式生成带引用的回答**

先把 `/search` 的命中 id 传进来，再用本接口生成。SSE，帧格式见 `docs/kb-app.md`。

路径参数：`kb_id`

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 |  |
| `chunk_ids` | string[] | 必填 |  |
| `model` | string | 可选 |  |
| `max_tokens` | int | 可选 |  |

响应内容类型 `text/event-stream`，流式输出。

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb/{kb_id}/answer \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/apps/kb/{kb_id}/docs`

**列出库里的文档及其索引状态**

`status` / `progress` 是建库队列的实时进度；`error` 是失败原因，可配合 retry 重试。

路径参数：`kb_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `docs` | object[] | 必填 | 知识库里的文档，最新的在前 |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/apps/kb/{kb_id}/docs \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb/{kb_id}/docs`

**上传一个或多个文档，排进建库队列**

`multipart/form-data`，字段名 `file`（可重复）。**整批校验通过才收**：一个坏文件会让整次上传被拒，避免「界面报错但有两个文档在索引」。单文件上限与支持的格式见 `docs/kb-app.md`。

路径参数：`kb_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `docs` | object[] | 必填 | 刚排进队列的文档。**解析是异步的**：用 `GET .../docs` 轮询 `status`，`ready` 之后才可检索 |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb/{kb_id}/docs \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `DELETE /api/apps/kb/{kb_id}/docs/{doc_id}`

**删除一个文档**

会等在解析中的任务停下并确认后再删，因此删除是确定的。重复删除返回成功。

路径参数：`kb_id, doc_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

可能的状态码：`401`, `403`, `404`, `409`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X DELETE http://<板子>:8000/api/apps/kb/{kb_id}/docs/{doc_id} \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/apps/kb/{kb_id}/docs/{doc_id}/chunks`

**读一个文档切出的全部片段**

含版面框坐标（`boxes`），文档识别页用它把片段框在页面上。

路径参数：`kb_id, doc_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `chunks` | object[] | 必填 | 该文档的切片，按原文顺序 |

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/apps/kb/{kb_id}/docs/{doc_id}/chunks \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/apps/kb/{kb_id}/docs/{doc_id}/file`

**下载文档的原始文件**

按原名返回（`Content-Disposition: attachment`）。

路径参数：`kb_id, doc_id`

响应内容类型 `application/octet-stream`，流式输出。

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/apps/kb/{kb_id}/docs/{doc_id}/file \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `GET /api/apps/kb/{kb_id}/docs/{doc_id}/pages/{page}.png`

**读文档某一页的预览图（PNG）**

扫描件、图片与 PDF 的每一页在解析时都会渲染一张预览图，文档识别页用它显示版面框。`page` 从 1 开始；没有这一页时 404。

路径参数：`kb_id, doc_id`

响应内容类型 `image/png`，流式输出。

可能的状态码：`401`, `403`, `404`, `422`（错误体见「错误格式」）

```bash
curl -s -X GET http://<板子>:8000/api/apps/kb/{kb_id}/docs/{doc_id}/pages/{page}.png \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb/{kb_id}/docs/{doc_id}/retry`

**重试一个失败的文档**

只有 `failed` 的文档可以重试；仍在队列或解析中、原始文件已丢失时返回 409。

路径参数：`kb_id, doc_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 已重新排队 |
| `doc` | object | 必填 | 重试后的文档状态（`queued`） |

可能的状态码：`401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb/{kb_id}/docs/{doc_id}/retry \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb/{kb_id}/reindex`

**用当前加载的 embedding 模型重建整个库的向量**

用于「建库时的模型已经换掉」：旧向量与新模型的查询向量不在同一空间，检索阶段会跳过它们。没有可用模型、库是空的、或已在重建时返回 409（立即拒绝，而不是排一个注定失败的队）。

路径参数：`kb_id`

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 任务已排入队列 |
| `job` | object | 必填 | `documents`（参与重建的文档数）、`chunks`（切片数）、`model`（用的模型） |

可能的状态码：`400`, `401`, `403`, `404`, `409`, `422`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb/{kb_id}/reindex \
  -H "Authorization: Bearer $CV84X6_KEY"
```

#### `POST /api/apps/kb/{kb_id}/search`

**检索：BM25 + 向量 → RRF → 精排**

各阶段按已加载的模型自动降级，跳过的阶段与原因在 `skipped` 里，不是静默降级。`candidates` 上限 100（一次检索在板上约 6.5 秒），`top_k` 不能大于 `candidates`。

路径参数：`kb_id`

请求体 `application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 |  |
| `top_k` | int | 可选 |  |
| `candidates` | int | 可选 |  |
| `use_bm25` | bool | 可选 |  |
| `use_vector` | bool | 可选 |  |
| `use_rerank` | bool | 可选 |  |

响应 `200 application/json`：

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 | 原查询 |
| `hits` | object[] | 必填 | 排序后的命中，最相关的在前 |
| `skipped` | map[string, string] | 可选 | 被跳过的阶段及原因，例如 `{"vector": "模型未加载"}`。**降级会说明，不会静默** |

可能的状态码：`400`, `401`, `403`, `404`, `422`, `500`（错误体见「错误格式」）

```bash
curl -s -X POST http://<板子>:8000/api/apps/kb/{kb_id}/search \
  -H "Authorization: Bearer $CV84X6_KEY"
```

## 数据模型

各接口的响应模型。字段说明与接口里的表格相同，这里按类型集中列一次，便于写客户端时照着建结构体。

#### `AgentJobOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 可选 | 安装任务；没有任务时 null |

#### `AgentListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `agents` | object[] | 必填 | 三个内置 agent 的状态 |

#### `AgentLogsOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `log` | string | 必填 | 日志尾部文本；没有日志时为空串 |

#### `AgentModelChoice`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id |
| `context` | int | 必填 | 上下文长度 |
| `vision` | bool | 必填 | 是否支持视觉 |

#### `AgentOut`

One agent's card: install/run state, its ports, and its own UI's login.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | agent id |
| `name` | string | 必填 | 显示名 |
| `version` | string | 必填 | 已安装的版本；未安装为空 |
| `latest_version` | string | 必填 | 本版本支持的最新版本 |
| `default_port` | int | 必填 | 默认端口 |
| `port` | int | 必填 | 当前端口 |
| `installed` | bool | 必填 | 是否已安装 |
| `status` | `running` \| `stopped` \| `failed` \| `not_installed` | 必填 | 四态摘要 |
| `operation` | string | 可选 | 正在进行的操作 |
| `operation_since` | float | 可选 | 该操作的开始时间 |
| `busy` | bool | 必填 | 是否有操作在进行 |
| `operation_label` | string | 必填 | 该操作的中文名 |
| `running` | bool | 必填 | 是否健康运行（启动中不算） |
| `pid` | int | 可选 | 进程号 |
| `health` | bool | 必填 | 本次健康检查是否通过 |
| `adopted` | bool | 必填 | 是否为重启后接管的进程 |
| `orphan_pid` | int | 可选 | 占着端口但不健康的进程号 |
| `rss_bytes` | int | 必填 | 常驻内存（字节） |
| `disk_bytes` | int | 必填 | 安装占用（字节） |
| `autostart` | bool | 必填 | 是否开机自启 |
| `default_model` | string | 必填 | 配置里给它用的模型 |
| `thinking` | bool | 必填 | 是否给它打开思考模式 |
| `embeddable` | bool | 必填 | 能否嵌在控制台里显示 |
| `proxied` | bool | 必填 | 是否由本服务反代它的界面 |
| `card_note` | string | 必填 | 卡片上的补充说明 |
| `memory_floor_bytes` | int | 必填 | 启动它至少需要的内存 |
| `web_url` | string | 必填 | 它的界面地址；未安装为空 |
| `web` | object | 必填 | 它的界面的登录凭据 |
| `models` | object[] | 必填 | 可以配给它的模型 |
| `child_ports` | int[] | 必填 | 它自己再开出来的端口 |
| `started_at` | float | 可选 | 启动时间（epoch 秒） |
| `uptime_s` | float | 可选 | 已运行秒数 |
| `exit_code` | int | 可选 | 上次退出码 |
| `last_error` | string | 可选 | 最近一次错误 |
| `job` | object | 可选 | 安装任务的进度 |

#### `AgentWebOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `username` | string | 必填 | agent 自带界面的用户名 |
| `password` | string | 必填 | agent 自带界面的口令（安装时生成） |

#### `AgentPatch`

Only the settings the console exposes; anything absent is left alone.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `port` | int | 可选 |  |
| `autostart` | bool | 可选 |  |
| `default_model` | string | 可选 |  |
| `thinking` | bool | 可选 |  |

#### `AnswerBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 |  |
| `chunk_ids` | string[] | 必填 |  |
| `model` | string | 可选 |  |
| `max_tokens` | int | 可选 |  |

#### `AuditPageOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `items` | object[] | 必填 | 这一页，最新的在前 |
| `total` | int | 必填 | 符合条件的总行数 |
| `limit` | int | 必填 | 本页最多多少行 |
| `offset` | int | 必填 | 本页起点 |
| `retention_days` | int | 必填 | 当前保留天数 |
| `dropped` | int | 必填 | 非零表示审计链有缺口（搬迁或写入失败丢了行） |
| `last_error` | string | 可选 | 最近一次写入失败的原因 |

#### `AuditRowOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | int | 必填 | 自增主键，翻页的稳定排序依据 |
| `ts` | float | 必填 | 操作时间（epoch 秒） |
| `ts_iso` | string | 必填 | 同上，本地时区 ISO8601 |
| `actor_type` | `console` \| `api_key` \| `anonymous` | 必填 | 操作者类型 |
| `actor_id` | string | 可选 | API key 的 id；控制台会话为 null |
| `actor_name` | string | 可选 | API key 的名字，或 admin |
| `ip` | string | 可选 | TCP 对端地址（不信任 X-Forwarded-For） |
| `user_agent` | string | 可选 | User-Agent，截断到 256 字符 |
| `method` | string | 必填 | HTTP 方法 |
| `path` | string | 必填 | 请求路径 |
| `target` | string | 可选 | 路径参数里的目标，如模型 id |
| `status` | int | 必填 | HTTP 状态码 |
| `ok` | bool | 必填 | 状态码是否 < 400 |
| `result` | `success` \| `failure` | 必填 | `ok` 的单词形式 |
| `duration_ms` | float | 必填 | 耗时（毫秒） |
| `summary` | string | 可选 | 白名单字段拼出的摘要，绝不含口令/密钥 |

#### `CatalogEntryOut`

One card of the download catalogue, with its update state.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id |
| `kind` | string | 必填 | 模型类型 |
| `title` | string | 必填 | 卡片标题 |
| `dfss` | string | 必填 | dfss 路径 |
| `size_bytes` | int | 必填 | 文件大小（字节） |
| `context` | int | 可选 | 上下文长度 |
| `vision` | bool | 可选 | 是否支持视觉 |
| `dflag` | string | 可选 | dfss 下载标签名，用于检测「有新版本」 |
| `md5` | string | 可选 | 本版本登记的 md5 |
| `installed` | bool | 必填 | 是否已安装到 models/ |
| `downloading` | bool | 必填 | 是否正在下载 |
| `latest_file` | string | 可选 | 标签当前指向的文件名；null = 离线或未取到标签 |
| `update_available` | bool | 可选 | 磁盘上的文件是否已落后于标签；null = 未知 |

#### `CatalogOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `models` | object[] | 必填 | 本版本支持的模型 |

#### `ChatBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `prompt` | string | 可选 |  |
| `max_tokens` | int | 可选 |  |
| `temperature` | float | 可选 |  |
| `images` | string[] | 可选 |  |
| `enable_thinking` | bool | 可选 |  |
| `messages` | object[] | 可选 |  |

#### `ChatCompletionRequest`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `messages` | object[] | 必填 |  |
| `max_tokens` | int | 可选 |  |
| `max_completion_tokens` | int | 可选 |  |
| `temperature` | float | 可选 |  |
| `top_p` | float | 可选 |  |
| `n` | int | 可选 |  |
| `stream` | bool | 可选 |  |
| `stop` | string | 可选 |  |
| `presence_penalty` | float | 可选 |  |
| `frequency_penalty` | float | 可选 |  |
| `seed` | int | 可选 |  |
| `top_k` | int | 可选 |  |
| `repetition_penalty` | float | 可选 |  |
| `enable_thinking` | bool | 可选 |  |
| `chat_template_kwargs` | object | 可选 |  |
| `tools` | any[] | 可选 |  |
| `tool_choice` | string | 可选 |  |
| `parallel_tool_calls` | bool | 可选 |  |

#### `ChatMessage`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `role` | `system` \| `user` \| `assistant` \| `tool` | 必填 |  |
| `content` | string | 可选 |  |
| `name` | string | 可选 |  |
| `tool_calls` | object[] | 可选 |  |
| `tool_call_id` | string | 可选 |  |
| `reasoning_content` | string | 可选 |  |

#### `ChatOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `text` | string | 必填 | 模型输出（思考内容已剥离） |
| `prompt_tokens` | int | 必填 | 输入 token |
| `completion_tokens` | int | 必填 | 输出 token |
| `cached_tokens` | int | 必填 | 命中前缀缓存的 token |
| `first_token_latency_s` | float | 可选 | 首 token 延迟（秒） |
| `decode_tps` | float | 可选 | decode 速度（tok/s） |
| `finish_reason` | string | 可选 | stop / length |

#### `ChunkListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `chunks` | object[] | 必填 | 该文档的切片，按原文顺序 |

#### `ChunkOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 切片 id |
| `page` | int | 可选 | 所在页（从 1 开始） |
| `source` | string | 可选 | 来源标签，如 `页 3` |
| `text` | string | 必填 | 切片正文 |
| `char_start` | int | 可选 | 在原文中的起始字符下标 |
| `char_end` | int | 可选 | 在原文中的结束字符下标 |
| `boxes` | float[][] | 可选 | 版面框 `[[x0,y0,x1,y1], ...]`，像素坐标；文档识别页用它把片段框在预览图上 |

#### `ClearRecordsOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 成功 |
| `deleted` | int | 必填 | 删掉了多少条 |

#### `ContentPart`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `type` | string | 必填 |  |
| `text` | string | 可选 |  |
| `image_url` | object | 可选 |  |

#### `CreateKbBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `name` | string | 可选 |  |

#### `CreateKbOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `kb` | object | 必填 | 新建的知识库 |

#### `KbOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 知识库 id |
| `name` | string | 必填 | 名字 |
| `created_at` | float | 必填 | 创建时间（epoch 秒） |
| `created_at_iso` | string | 可选 | 同上，本地时区 ISO8601 |
| `doc_count` | int | 必填 | 文档数 |
| `chunk_count` | int | 必填 | 切片数 |
| `embedding_model` | string | 可选 | 建库用的 embedding 模型 id；空库为 null |
| `dims` | int | 可选 | 向量维度 |
| `needs_reindex` | bool | 可选 | 向量与切片已不一致，需要点「重建索引」 |

#### `CreateKeyBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `name` | string | 可选 |  |
| `scope` | string | 可选 |  |

#### `CreateKeyOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `key` | string | 必填 | **明文 key，只在这里返回一次**；服务端只存哈希 |
| `meta` | object | 必填 | 这条 key 的元数据（同 `GET /api/keys` 的元素） |

#### `KeyOut`

One API key as the console and a script see it. Never the key itself.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | key 的 id，用于吊销/删除 |
| `name` | string | 必填 | 创建时给的名字；审计里也显示它 |
| `prefix` | string | 必填 | 前 10 个字符，供人辨认 |
| `created_at` | float | 必填 | 创建时间（epoch 秒） |
| `revoked` | bool | 必填 | 是否已吊销 |
| `scope` | `inference` \| `admin` | 可选 | 权限范围：`inference` 只能调 `/v1`；`admin` 还能调 `/api`。本字段之前创建的 key 一律是 `inference`。 |
| `prompt_tokens` | int | 可选 | 累计输入 token |
| `completion_tokens` | int | 可选 | 累计输出 token |
| `cached_tokens` | int | 可选 | 累计命中前缀缓存的 token |
| `requests` | int | 可选 | 累计请求数 |

#### `DeviceHeapOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `name` | string | 必填 | 堆名：`npu` 或 `vpp` |
| `total_bytes` | int | 必填 | 该堆总大小 |
| `used_bytes` | int | 必填 | 该堆已用 |
| `free_bytes` | int | 必填 | 该堆空闲 |

#### `DeviceMemoryOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `total_bytes` | int | 必填 | 设备内存总量（NPU + VPP 两个堆） |
| `used_bytes` | int | 必填 | 已用 |
| `free_bytes` | int | 必填 | 空闲 |
| `max_block_bytes` | int | 必填 | 单个堆里最大的连续空闲块；单次分配不能跨堆 |
| `heaps` | object[] | 必填 | 按堆拆开 |
| `source` | string | 必填 | 读数来源：`bm-smi` 或 `mock` |

#### `DeviceOut`

One reading of the board. On the mock backend the numbers are simulated.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ts` | float | 必填 | 采样时间（epoch 秒） |
| `cpu_percent` | float | 必填 | CPU 使用率（0-100） |
| `load_average` | float[] | 必填 | 1/5/15 分钟负载 |
| `memory` | object | 必填 | 系统内存 |
| `temperatures` | object[] | 必填 | 温度传感器 |
| `device_mem` | object | 必填 | NPU + VPP 设备内存 |

#### `MemoryOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `total_bytes` | int | 必填 | 系统内存总量 |
| `available_bytes` | int | 必填 | 系统可用内存 |
| `used_bytes` | int | 必填 | 系统已用内存 |

#### `DocListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `docs` | object[] | 必填 | 知识库里的文档，最新的在前 |

#### `DocOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 文档 id |
| `name` | string | 必填 | 原文件名 |
| `type` | `txt` \| `md` \| `pdf` \| `image` | 必填 | 解析类型 |
| `bytes` | int | 必填 | 文件大小（字节） |
| `pages` | int | 必填 | 页数；图片与纯文本为 1 |
| `status` | `queued` \| `parsing` \| `embedding` \| `ready` \| `failed` | 必填 | 索引进度状态 |
| `progress` | object | 可选 | 进度：`stage` / `done` / `total` |
| `error` | string | 可选 | 失败原因；只有 `failed` 时有值 |
| `warnings` | string[] | 可选 | 解析告警（不阻断入库），如某页没有文本层 |
| `chunks` | int | 必填 | 切出的片段数 |
| `text_pages` | int | 必填 | 走文本层解析的页数 |
| `ocr_pages` | int | 必填 | 走 OCR 的页数 |
| `created_at` | float | 必填 | 上传时间（epoch 秒） |

#### `DownloadBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `url` | string | 必填 |  |
| `name` | string | 必填 |  |
| `kind` | string | 可选 |  |
| `expected_bytes` | int | 可选 |  |
| `files` | object[] | 可选 |  |

#### `DownloadJobOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 任务 id，用于取消 |
| `kind` | string | 必填 | 下载方式 |
| `target` | string | 必填 | 安装目标目录 |
| `name` | string | 必填 | 模型名 |
| `state` | `pending` \| `running` \| `done` \| `failed` \| `cancelled` | 必填 | 任务状态 |
| `total_bytes` | int | 必填 | 总字节数 |
| `done_bytes` | int | 必填 | 已完成字节数 |
| `percent` | float | 必填 | 完成百分比 |
| `message` | string | 必填 | 进度说明或失败原因 |
| `started_at` | float | 必填 | 开始时间（epoch 秒） |
| `finished_at` | float | 可选 | 结束时间（epoch 秒） |
| `file_count` | int | 可选 | 这个模型由几个文件组成 |
| `files_done` | int | 可选 | 已完成几个文件 |

#### `DownloadListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `jobs` | object[] | 必填 | 全部下载任务，最新的在前 |
| `orphans` | object | 必填 | 磁盘上的残留文件 |

#### `OrphanFreeSpace`

Leftover ``.part``/``.bak`` files a failed pull left behind.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `files` | string[] | 必填 | 可以安全删除的残留文件 |
| `bytes` | int | 必填 | 这些文件占用的字节数 |
| `recoverable` | string[] | 必填 | 唯一副本的 `.bak`（安装中断），**不要删**；重启时会自动放回 |

#### `EmbeddingRequest`

OpenAI's shape, plus instruction and a multimodal input extension.

``input`` is typed loosely on purpose: OpenAI accepts a string, a list of
strings, or a list of token ids, and the last one must be refused with a
*helpful* 400 rather than a 422 from pydantic -- so the discrimination
happens in the endpoint, where the message can say why.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `input` | any | 必填 | 字符串或字符串数组，最多 64 条。Qwen3-VL-Embedding / WeMM-Embedding 还接受 {text?: string, image?: JPEG/PNG base64 data URL} 及混合数组；每条一张图片，单张最多 4 MiB，每批最多 16 张、合计 16 MiB。 |
| `encoding_format` | `float` \| `base64` | 可选 |  |
| `dimensions` | int | 可选 | 截断后重新 L2 归一化；Qwen3-Embedding 为 32–1024，Qwen3-VL-Embedding / WeMM-Embedding-2B 为 64–2048。 |
| `instruction` | string | 可选 | 可选任务指令。文本 embedding 拼在输入前；多模态 embedding 使用系统指令；Qwen3-VL 默认 Represent the user's input.，WeMM 默认不加系统指令。 |

#### `ErrorOut`

The one error shape of the management API (MYS-2676).

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `detail` | any | 必填 | 中文说明。控制台直接显示它；`/v1` 的 `detail` 仍是 OpenAI 的错误对象，不受影响。 |
| `code` | string | 必填 | 稳定的英文错误码，见「错误码」一节。脚本应据此分支，而不是解析 detail。 |

#### `HTTPValidationError`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `detail` | object[] | 可选 |  |

#### `KbListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `kbs` | object[] | 必填 | 全部知识库，最新创建的在前 |

#### `KeyListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `keys` | object[] | 必填 | 全部 key，含已吊销的 |

#### `LogLineOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ts` | string | 可选 | 行首时间戳，原样保留 |
| `level` | string | 可选 | 日志级别 |
| `logger` | string | 可选 | logger 名 |
| `message` | string | 必填 | 正文（敏感字段已打码） |

#### `LogPageOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `source` | string | 必填 | 日志源 id |
| `label` | string | 必填 | 日志源名字 |
| `lines` | object[] | 必填 | 这一页的行，**从旧到新** |
| `cursor` | string | 可选 | 取下一页（更旧的一页）时原样传回 `cursor`；null = 没有更旧的了 |
| `has_more` | bool | 必填 | 是否还有更旧的行 |
| `limit` | int | 必填 | 本页最多多少行 |
| `size_bytes` | int | 必填 | 日志源当前大小 |

#### `LogSourceOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 日志源 id，用作 GET /api/logs/{source} 的路径参数 |
| `label` | string | 必填 | 给人看的名字 |
| `size_bytes` | int | 必填 | 当前大小；从未写过是 0 |
| `updated_at` | float | 可选 | 最后写入时间（epoch 秒） |
| `updated_at_iso` | string | 可选 | 同上，本地时区 ISO8601 |
| `kind` | `platform` \| `worker` \| `agent` | 必填 | 日志类别 |

#### `LogSourcesOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `sources` | object[] | 必填 | 全部日志源，含空的 |

#### `LoginBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `password` | string | 必填 |  |

#### `ModelActionOut`

``POST /api/models/{id}/load`` and ``/unload``.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |
| `model` | object | 必填 | 操作完成后的模型状态 |

#### `ModelOut`

One model on disk, with its live state and its memory accounting.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id，即 models/ 下的目录名 |
| `display_name` | string | 必填 | 给人看的名字 |
| `path` | string | 必填 | 模型目录的绝对路径 |
| `kind` | `chat` \| `embedding` \| `rerank` \| `asr` \| `ocr` \| `ocr_vl` | 必填 | 模型类型，决定它能服务哪个接口 |
| `size_bytes` | int | 必填 | 目录总大小（字节） |
| `bmodel_files` | string[] | 必填 | 目录里的 .bmodel 文件 |
| `has_config` | bool | 必填 | 目录里是否有 tokenizer/processor 配置 |
| `context_length` | int | 必填 | 上下文长度（token） |
| `supports_vision` | bool | 必填 | 是否接受图片输入 |
| `hidden_size` | int | 必填 | hidden size，用于推算 embedding 维度 |
| `supports_sampling` | bool | 必填 | bmodel 的 lm_head 是否支持采样；false 表示只能返回 argmax |
| `loaded` | bool | 必填 | 是否已加载并可以服务请求 |
| `port` | int | 可选 | worker 的 RPC 端口（未加载时为 null） |
| `pid` | int | 可选 | worker 进程号（未加载时为 null） |
| `load_error` | string | 可选 | 上次加载失败的原因 |
| `load_seconds` | float | 可选 | 上次加载耗时（秒） |
| `loaded_at` | float | 可选 | 加载完成时间（epoch 秒） |
| `operation` | `loading` \| `unloading` | 可选 | 正在进行的操作；null 表示空闲 |
| `operation_since` | float | 可选 | 该操作的开始时间（epoch 秒） |
| `conflict` | string | 可选 | 有无法确认归属的同名进程占用该模型时的说明 |
| `adopted` | bool | 可选 | 是否为重启后接管的前一次运行的进程 |
| `downloading` | bool | 可选 | 是否正在下载 |
| `last_used_at` | float | 可选 | 最后一次被使用的时间（epoch 秒） |
| `idle_unload_at` | float | 可选 | 按当前阈值预计的自动卸载时间（epoch 秒）；null = 不会自动卸载 |
| `settings` | object | 必填 | 操作者保存的设置，原样返回，含 null |
| `effective` | object | 必填 | 当前生效的值 |
| `mem_limit_default_bytes` | int | 必填 | 按模型自身占用推算的默认上限（字节） |
| `mem_static_bytes` | int | 必填 | 模型的静态占用（字节） |
| `mem_used_bytes` | int | 可选 | 运行期实测占用（字节）；只有已加载的模型才有 |
| `inflight` | int | 可选 | worker 正在处理的请求数 |

#### `ModelSettingsView`

What an operator configured for one model; ``null`` means "follow the default".

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `idle_unload_min` | int | 可选 | 空闲多少分钟自动卸载；0 = 不自动卸载；null = 跟随全局设置 |
| `auto_load` | bool | 可选 | 是否按需自动加载；null = 跟随全局设置 |
| `mem_limit_mb` | int | 可选 | 该模型的内存上限（MiB）；null = 用推算的默认值 |

#### `ModelEffective`

The values in force right now (the fallbacks already resolved).

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `idle_unload_min` | int | 必填 | 当前生效的空闲卸载阈值（分钟），0 = 不自动卸载 |
| `auto_load` | bool | 必填 | 当前生效的按需自动加载开关 |
| `mem_limit_bytes` | int | 必填 | 当前生效的内存上限（字节） |

#### `ModelCard`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 |  |
| `object` | string | 可选 |  |
| `created` | int | 必填 |  |
| `owned_by` | string | 可选 |  |
| `kind` | string | 可选 |  |

#### `ModelList`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `object` | string | 可选 |  |
| `data` | object[] | 必填 |  |

#### `ModelListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `models` | object[] | 必填 | models/ 下的全部模型，含未加载的 |

#### `ModelSettingsBody`

What ``PUT /api/models/{id}/settings`` accepts.

Every field is optional **and nullable**, and the two mean different things,
which is why they cannot share FastAPI's usual "absent leaves it alone":

  * absent -- leave this field alone (a console that sends only the switch
    the operator moved patches exactly that field);
  * ``null`` -- reset this field to its default (the global setting for the
    two idle switches, the derived figure for the memory limit).

pydantic v2 distinguishes the two through ``model_fields_set``, which is what
``update_model_settings`` reads; a plain ``None`` default cannot tell them
apart and would make resetting a field impossible.

Bounds are **refused**, not clamped, unlike ``/api/settings``: there the
value comes from a spinner and a stale number should not fail the save, but
here a memory limit is the thing an operator uses to protect a board, and
silently accepting 0 for "32 MiB" would defeat it. ``null`` is how you ask
for the default; an out-of-range number is a mistake worth reporting.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `idle_unload_min` | int | 可选 |  |
| `auto_load` | bool | 可选 |  |
| `mem_limit_mb` | int | 可选 |  |

#### `ModelSettingsOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 模型 id |
| `kind` | string | 必填 | 模型类型 |
| `settings` | object | 必填 | 保存的设置，原样返回 |
| `effective` | object | 必填 | 当前生效的值 |
| `mem_limit_default_bytes` | int | 必填 | 推算的默认上限（字节） |
| `mem_static_bytes` | int | 必填 | 静态占用（字节） |
| `mem_used_bytes` | int | 可选 | 运行期占用（字节） |
| `limits` | map[string, int] | 必填 | 本路由接受的取值范围，供控制台的输入框直接使用 |
| `auto_load_note` | string | 必填 | 给操作者的提示：自动加载大模型要几十秒 |
| `applied` | object | 可选 | 新上限推送到运行中 worker 的结果；模型未加载或没有 client 时为 null |

#### `MoveBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `path` | string | 必填 |  |

#### `MoveJobOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 任务 id；空闲时为 "" |
| `state` | `idle` \| `checking` \| `copying` \| `verifying` \| `switching` \| `done` \| `failed` | 必填 | 搬到哪一步了 |
| `copied_bytes` | int | 必填 | 已复制字节数 |
| `total_bytes` | int | 必填 | 需要复制的总字节数 |
| `message` | string | 必填 | 进度说明或失败原因 |
| `old` | string | 必填 | 原数据目录 |
| `new` | string | 必填 | 目标数据目录；空闲时为 "" |
| `started_at` | float | 必填 | 开始时间（epoch 秒） |
| `finished_at` | float | 可选 | 结束时间（epoch 秒） |

#### `MoveStartedOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | string | 必填 | 搬迁任务 id；进度用 GET /api/storage/move 查 |

#### `OkOut`

``{"ok": true}`` -- the answer to a request that has nothing else to say.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 操作成功 |

#### `RecordListOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `items` | object[] | 必填 | 这一页，最新的在前 |
| `total` | int | 必填 | 总条数 |
| `limit` | int | 必填 | 本页最多多少条 |
| `offset` | int | 必填 | 本页起点 |

#### `RecordStatusOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `path` | string | 必填 | 记录库文件路径 |
| `enabled` | bool | 必填 | 是否在记录 |
| `total` | int | 必填 | 库里有多少条 |
| `bytes` | int | 可选 | 库文件占用的字节数 |
| `schema_version` | int | 必填 | 记录库结构版本 |
| `retention_count` | int | 必填 | 保留条数上限 |
| `retention_days` | int | 必填 | 保留天数上限 |
| `readable` | bool | 必填 | 库是否可读；false 时列表会 500，服务其余部分照常 |
| `moving` | bool | 必填 | 是否正在随数据目录迁移（此时记录暂停） |
| `last_error` | string | 可选 | 最近一次写入失败的原因 |
| `last_error_at` | float | 可选 | 最近一次失败的时间 |

#### `RecordSummaryOut`

One row of the records list: no conversation text, which is in the detail.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `id` | string | 必填 | 记录 id |
| `started_at` | float | 必填 | 开始时间（epoch 秒） |
| `finished_at` | float | 可选 | 结束时间（epoch 秒） |
| `source` | string | 必填 | 请求路径，区分控制台与 API 流量 |
| `model` | string | 必填 | 模型 id |
| `actor_type` | string | 必填 | 操作者类型 |
| `actor_name` | string | 可选 | 操作者名字 |
| `status` | string | 必填 | ok / error / cancelled |
| `finish_reason` | string | 可选 | stop / length / tool_calls |
| `prompt_tokens` | int | 可选 | 输入 token |
| `completion_tokens` | int | 可选 | 输出 token |
| `cached_tokens` | int | 可选 | 命中缓存的 token |
| `first_token_latency_s` | float | 可选 | 首 token 延迟（秒） |
| `decode_tps` | float | 可选 | decode 速度（tok/s） |

#### `ReindexJobOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 任务已排入队列 |
| `job` | object | 必填 | `documents`（参与重建的文档数）、`chunks`（切片数）、`model`（用的模型） |

#### `RerankRequest`

Jina/Cohere rerank shape (OpenAI has no rerank endpoint).

``documents`` accepts both forms the ecosystem uses -- bare strings, and
``{"text": ...}`` objects -- because Dify and LangChain send the first while
Cohere's own clients send the second.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `model` | string | 必填 |  |
| `query` | string | 必填 |  |
| `documents` | any[] | 必填 |  |
| `top_n` | int | 可选 |  |
| `return_documents` | bool | 可选 |  |

#### `RetryDocOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `ok` | bool | 可选 | 已重新排队 |
| `doc` | object | 必填 | 重试后的文档状态（`queued`） |

#### `SearchBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 |  |
| `top_k` | int | 可选 |  |
| `candidates` | int | 可选 |  |
| `use_bm25` | bool | 可选 |  |
| `use_vector` | bool | 可选 |  |
| `use_rerank` | bool | 可选 |  |

#### `SearchHitOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `chunk_id` | string | 必填 | 切片 id，可直接传给 `/answer` |
| `doc_id` | string | 可选 | 所属文档 id |
| `doc_name` | string | 可选 | 所属文档名 |
| `page` | int | 可选 | 页码 |
| `text` | string | 必填 | 切片正文 |
| `score` | float | 必填 | 最终得分（精排后的相关度） |
| `stages` | object | 可选 | 各阶段得分（bm25 / vector / rrf / rerank），用于解释排序 |

#### `SearchOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `query` | string | 必填 | 原查询 |
| `hits` | object[] | 必填 | 排序后的命中，最相关的在前 |
| `skipped` | map[string, string] | 可选 | 被跳过的阶段及原因，例如 `{"vector": "模型未加载"}`。**降级会说明，不会静默** |

#### `SessionOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `authenticated` | bool | 必填 | 当前请求是否带着有效的管理员会话 cookie |

#### `SettingsBody`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `max_concurrent_per_model` | int | 可选 |  |
| `prefix_cache_entries` | int | 可选 |  |
| `prefix_cache_max_mb` | int | 可选 | 自 v0.6.34 起无效（总上限已删除）：接受但忽略，每个模型的前缀缓存改由该模型自己的内存上限约束 |
| `prefix_cache_ttl_min` | int | 可选 |  |
| `max_queue` | int | 可选 |  |
| `prefill_exact_tail` | int | 可选 |  |
| `inference_logging_enabled` | bool | 可选 |  |
| `inference_log_retention_count` | int | 可选 |  |
| `inference_log_retention_days` | int | 可选 |  |
| `aux_idle_unload_min` | int | 可选 |  |
| `aux_auto_load` | bool | 可选 |  |
| `audit_retention_days` | int | 可选 |  |

#### `SettingsOut`

Every server-side setting, plus the bounds the console renders fields with.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `max_concurrent_per_model` | int | 必填 | 每个模型同时处理的请求数上限（1-3） |
| `max_concurrency_limit` | int | 必填 | 上面这个字段的硬上限 |
| `prefix_cache_entries` | int | 必填 | 前缀缓存条目上限 |
| `prefix_cache_ttl_min` | int | 必填 | 未被使用的前缀缓存保留分钟数 |
| `max_queue` | int | 必填 | 排队请求上限；超出的直接 429 |
| `prefill_exact_tail` | int | 必填 | 长 prompt 尾部走 decode 图的 token 数；0 = 关闭 |
| `require_api_key` | bool | 必填 | `/v1` 是否要求 API key |
| `inference_logging_enabled` | bool | 必填 | 是否记录推理记录 |
| `inference_log_retention_count` | int | 必填 | 推理记录保留条数上限 |
| `inference_log_retention_days` | int | 必填 | 推理记录保留天数上限 |
| `aux_idle_unload_min` | int | 必填 | 辅助模型的默认空闲卸载阈值（分钟），0 = 不卸载 |
| `aux_idle_unload_limit_min` | int | 必填 | 这个字段的硬上限 |
| `aux_auto_load` | bool | 必填 | 是否默认按需自动加载辅助模型 |
| `audit_retention_days` | int | 必填 | 管理审计保留天数 |
| `audit_retention_days_min` | int | 必填 | 审计保留下限 |
| `audit_retention_days_max` | int | 必填 | 审计保留上限 |

#### `SettingsSaveOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `settings` | object | 必填 | 保存后（夹紧之后）的设置 |
| `applied` | object | 必填 | 每个已加载模型推送新设置的返回值；推送失败的模型带一个 `error` 键 |

#### `StartDownloadOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `job` | object | 必填 | 刚创建的任务 |

#### `StatsOut`

Everything the overview page polls, in one request.

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `device` | object | 必填 | 设备读数 |
| `vpp_reserve` | object | 可选 | 服务为多媒体栈预留的 VPP 块（会计入 device_mem 的已用） |
| `usage` | object | 必填 | 累计用量 |
| `models` | object[] | 必填 | 每个模型的完整状态（同 GET /api/models） |
| `max_loaded_models` | int | 必填 | 同时加载的对话模型上限；0 = 不限 |
| `kv_cache` | object | 必填 | 每个已加载模型的前缀缓存用量，按模型 id |
| `workers` | object | 必填 | 每个已加载 worker 自己报告的统计，按模型 id |
| `disk` | object | 必填 | models/ 的磁盘占用 |

#### `UsageOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `prompt_tokens` | int | 必填 | 累计输入 token |
| `completion_tokens` | int | 必填 | 累计输出 token |
| `cached_tokens` | int | 必填 | 累计命中前缀缓存的 token |
| `requests` | int | 必填 | 累计请求数 |
| `cache_hit_rate` | float | 必填 | 缓存命中率（0-1） |
| `tps_history` | float[][] | 必填 | 最近 120 个 (epoch 秒, decode tok/s) 采样，供曲线图使用 |

#### `StorageOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `data_dir` | string | 必填 | 当前数据目录 |
| `fs_total_bytes` | int | 必填 | 所在文件系统总大小 |
| `fs_used_bytes` | int | 必填 | 所在文件系统已用 |
| `fs_free_bytes` | int | 必填 | 所在文件系统可用 |
| `dir_bytes` | int | 必填 | 数据目录占用（等于 parts 之和） |
| `parts` | map[string, int] | 必填 | 按子目录拆开：models / state / agents / downloads / apps / inbox |

#### `TemperatureOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `zone` | string | 必填 | thermal zone 名 |
| `name` | string | 必填 | 传感器名 |
| `celsius` | float | 必填 | 摄氏温度 |

#### `UploadDocsOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `docs` | object[] | 必填 | 刚排进队列的文档。**解析是异步的**：用 `GET .../docs` 轮询 `status`，`ready` 之后才可检索 |

#### `ValidationError`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `loc` | string[] | 必填 |  |
| `msg` | string | 必填 |  |
| `type` | string | 必填 |  |
| `input` | any | 可选 |  |
| `ctx` | object | 可选 |  |

#### `VppReserveOut`

| 字段 | 类型 | | 说明 |
|---|---|---|---|
| `acquired` | bool | 必填 | 是否已占住多媒体保留块 |
| `bytes` | int | 必填 | 保留的字节数 |
| `reason` | string | 可选 | 没占住时的原因 |
