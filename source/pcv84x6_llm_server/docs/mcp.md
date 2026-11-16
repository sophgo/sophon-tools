# MCP 服务：知识库、OCR 与语音转写以 MCP tools 对外

推理服务本身在**同一端口**挂载 `POST /mcp`，把知识库（除依赖主 LLM 的问答）、OCR 和
语音转写以 MCP tools 的形式提供给 agent。三个内置 agent（PicoClaw / opencode /
OpenClaw）在安装、重置、同步配置时都会写入这个服务，开箱即可在对话里检索知识库、往
知识库添加文档、识别图片和 PDF 中的文字、把录音转成文字。

- 端点：`POST http://<设备>:<服务端口>/mcp`
- 协议：MCP **Streamable HTTP**，协议版本 `2025-06-18`（同时接受客户端声明 `2025-03-26`）
- 鉴权：与 `/v1` 相同的 API Key，`Authorization: Bearer <key>`
- **Origin 校验**：请求带 `Origin` 头且不是本机 / 同源时返回 `403`（见第 9 节）
- 无状态：不返回 `Mcp-Session-Id`，`GET /mcp` 与 `DELETE /mcp` 返回 `405`

## 1. 为什么不是官方 SDK

`app/mcp/server.py` 自己实现 JSON-RPC 2.0 分发，只处理
`initialize` / `notifications/initialized` / `ping` / `tools/list` / `tools/call`。
release 的 `vendor/` 是为板子（aarch64 / Python 3.10）钉死的一套小轮子，而 `mcp`
Python SDK 会拉进 `sse-starlette`、`httpx-sse`、`python-multipart` 等一整套依赖，
解析结果和现有钉版本冲突一次就是"装到设备上 import 不起来"。这个服务真正需要的只是
五个方法 + `application/json` 响应。

这条选择由 `tests/test_mcp_sdk_client.py` 兜底：**用官方 `mcp` SDK 作为客户端**驱动
这个端点（SDK 只在构建机的测试 venv 里，不进 vendor），握手、`tools/list`、
`tools/call` 都要通过。实现只和自己写的客户端对得上，等于没有验证。

## 2. 工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `kb_list` | — | 知识库列表：id、名称、文档数、片段数、embedding 模型、是否需要重建 |
| `kb_create` | `name` | 新建知识库 |
| `kb_search` | `query`、`kb`、`top_k`=5（≤20） | 混合检索 + 精排，按已加载模型降级。结果每条形如 `[n] 文档名 第 p 页（相关度 x）` + 片段原文，并说明本次执行/跳过了哪些步骤 |
| `kb_read` | `chunk_id`、`neighbors`=1（≤3） | 返回该片段及前后相邻片段 |
| `kb_list_documents` | `kb` | 文档列表与状态 |
| `kb_add_document` | `kb` + (`path` \| `text`+`name`) | 复用建库流程，立即返回 doc id 与 `queued` |
| `kb_document_status` | `kb`、`doc_id` | 状态、进度、错误 |
| `ocr_read` | `path`、`mode`、`pages` | 图片走 PP-OCR；PDF 逐页：有文字层直接取，扫描页走 OCR，标明每页来源。`mode="layout"` 时扫描页按版面分区输出整页 Markdown。不写入知识库 |
| `transcribe_audio` | `path`、`language`、`prompt` | 音频转写：先给全文，再列 `[mm:ss–mm:ss] 文字` 分段；≤ 50 MB、≤ 30 分钟 |

`kb` 参数在 `kb_search` 里可以省略：只有一个库就用它，多个库则搜全部并在结果里标明
来源库。其余工具必须显式指定目标库。

**不提供删除类工具**：删除文档/知识库只能在控制台做，避免 agent 误删。
**不提供问答工具**：回答由 agent 自己的模型生成。

工具失败（库不存在、路径被拒、参数越界）返回 `isError: true` 的**正常结果**，模型能读到
原因并改参数重试；只有 JSON-RPC 层面的问题（未知方法、`arguments` 不是对象）才是
`error` 对象。错误信息里不带异常类名和服务器绝对路径 —— 那些进服务日志。

### `ocr_read` 的页范围

`pages` 支持 `"1-5"`、`"3"`、`"1-5,8"`。默认读前 20 页，单次最多 50 页。**区间先裁剪
再展开**：`pages="1-2000000000"` 不会生成 20 亿个整数，而是与「文档总页数」和「本次预算」
求交之后只物化最多 50 个页码；预算按调用方书写的顺序消耗，所以 `"40-100,1-3"` 返回
40–89 而不是"最小的 50 页"。被上限截断时回复里写明「本次按单次上限取了前 50 页」——
但只在文档确实还有未读页时才写，`pages="1-2000000000"` 打在一个 30 页文件上不算被截断。

图片和 PDF 都走 `kb_parse.validate_upload` —— 与上传同一套检查：大小、类型、PDF 页数、
**图片像素上限 40 Mpx**。`ocr_read` 曾经绕过这套检查，一张 50 MiB 的 PNG 可以是
170 Mpx，解码后超过 500 MB。

### `ocr_read` 的 `mode`

| `mode` | 输出 | 什么时候用 | 代价 |
|---|---|---|---|
| `"lines"`（默认） | 每页的行文本，按阅读顺序；图片是纯文本，PDF 每页带 `source` | 截图、裁剪图、单列表单 | 一次 det + 每行一次 rec |
| `"layout"` | 扫描页按版面分区（标题/段落/表格/图片…）后输出整页 **Markdown**，每页多一个 `markdown` 字段 | 整页文档、双栏排版、要保留标题与段落结构时 | 多一次 ~3 ms 的版面前向 |
| `"vl"` | 与 `layout` 同结构，但每个区域交给 **PaddleOCR-VL** 识别：**表格输出 HTML（含合并单元格）**，公式输出 LaTeX，正文更准 | 含表格、公式的文档；扫描质量差的页 | 每区域一次 VL 推理，整页通常几十秒；需要两个模型都加载 |

- **有文字层的页在三种模式下都直接取文字层。** 文字层是精确的，重跑 OCR 只会把更好的
  答案换成更差的；所以 `layout`/`vl` 对纯数字 PDF **不产生任何变化**，回复开头会写明这一点，
  免得调用方以为自己用错了参数。
- 扫描页走版面模式。`layout` 的表格区域只输出文字、不还原结构（原因见
  [`ocr.md`](ocr.md) 的「Markdown 规则」）；`vl` 的表格是 HTML，`rowspan`/`colspan`
  都在（见 [`ocr-vl.md`](ocr-vl.md) §11）。
- `mode` 有枚举约束（`enum: ["lines", "layout", "vl"]`），非法值返回 `isError: true`，
  在花任何 NPU 时间之前就拒掉。
- `vl` 需要 **PaddleOCR-VL-1.5 已加载**。它不会被自动加载（3.3 GB 常驻，和聊天模型一样
  由操作员显式加载），没加载时工具直接返回错误并说明要加载哪个模型、以及可以退回
  `layout`。**不会静默降级**：要表格结构的人拿到的是没有结构的文字，那是在回答另一个问题。

工具描述里写清了选择依据（"整页文档、双栏、需要标题与段落结构时用 layout；含表格、
公式、扫描质量差的文档用 vl，比 layout 慢、更准"），因为 agent 只看描述，不看这份文档。

### `transcribe_audio`

复用 /v1/audio/transcriptions 背后的逐段转写路径（`iter_transcribe`，非流式收集），
限制完全一致：≤ 50 MB（`audio_upload.MAX_UPLOAD_BYTES`）、≤ 30 分钟（worker 自己会在
第一帧之前拒绝更长的音频）。返回的文本先给全文，再按 `[mm:ss–mm:ss] 文字` 列分段；
`structuredContent` 带 `segments`、`duration`、`language`、`usage`。

没有加载 ASR 模型时返回工具错误，提示去控制台加载 `qwen3-asr-0.6b` 或 `qwen3-asr-1.7b`。
两个都加载时用**最近加载的那个**（`kb_models.resolve` 的既有规则）—— 想要 1.7B 就最后
加载 1.7B。推理记录的 `source` 为 `/mcp`。

**`language` 的 `"None"` 陷阱**（真机实测发现）：worker 读的是模型自己回的
`language <Name><asr_text>` 前导，而模型在**没有人声**的音频上会照字面回一个 `None`，
于是 `/v1/audio/transcriptions` 的 `verbose_json` 里 `language` 是**字符串** `"None"`。
MCP 侧把这个值规范成 `None`（`("none", "null", "unknown", "n/a", "")` 同理），
不然对话里会写着"语言：None"——那比不写更糟。`/v1` 的行为没有改（那不是本分支的范围）。

### 两个重活工具的并发上限

`ocr_read` 与 `transcribe_audio` 共用一个 **2 路**的准入池（`tools.HEAVY`）。超出的调用
立即返回工具错误「正在处理其他请求（同时最多 2 个），请稍后重试」，而不是排队 ——
排队会让每次调用都攥着自己解码后的图片或音频内存，而 2.6 GB 的板子上这正是耗尽的
方式。池是计数器而不是信号量：判断与占用之间没有 `await`，两个调用不可能同时看到最后
一个空位。

### 推理记录

工具触发的 embedding / rerank / OCR / ASR 推理照常写推理记录：`source` 为 `/mcp`，
actor 是调用方 API Key 的名称。实现上不改 `app/apps/kb/*`（那些模块服务控制台），
而是给它们一个"转写"的推理日志代理 —— 记录点仍在原处、每条推理仍是一行，只是
`source` 与 actor 被改写成 MCP 的。`transcribe_audio` 不是知识库的阶段，它直接写自己
那一行（同样带 MCP 身份）。

### 不阻塞事件循环

读 50 MiB 文件、打开 PDF 数页数、读图片头、建 20 000 片段的 BM25 索引、原子写一篇文档，
全部走 `asyncio.to_thread`。BM25 索引复用控制台已有的缓存（同一个 `app.state.kb_bm25`、
同一个签名），所以第二次检索只付 `load_chunks` 的钱 —— 和控制台路由付的一样。

## 3. 本地路径白名单

`path` 参数（`ocr_read`、`kb_add_document`、`transcribe_audio`）只能落在这些目录下：

| 目录 | 用途 |
|---|---|
| `<数据目录>/agents/**` | 各 agent 自己的工作区、`data/`、下载的媒体文件 |
| `<数据目录>/inbox/` | 通用投放目录：把文件放这里再让 agent 处理 |
| `server.env` 里 `CV84X6_MCP_PATHS` 列出的目录 | 操作员额外声明的目录，`:` 分隔 |

规则是**先 `realpath` 再判断**：`..` 无法越界，白名单目录里的符号链接指向外部同样被拒
（先解析再比较，而不是"前缀匹配通过、然后打开时才发现跟过去了"）。单文件 ≤ 50 MiB，
与知识库上传一致。

**检查、打开、读取是同一个动作，对同一个文件描述符完成**（`paths.read_local_file`）：

1. `realpath` 之后比对允许的根目录，按**整个路径分量**比较（`/data/agents-old` 不是
   `/data/agents` 的子目录）；
2. 用 `O_NOFOLLOW | O_NONBLOCK` 打开**解析后的真实路径** —— `O_NOFOLLOW` 拒绝在检查与
   打开之间被换成符号链接的名字，`O_NONBLOCK` 保证打开一个 FIFO 不会先把检查挂住；
3. `fstat` 确认是普通文件、大小 ≤ 上限（FIFO、设备文件在这里被拒）；
4. 再读一次 `/proc/self/fd/<fd>` 指向的真实路径，与白名单复查一遍 —— 中间任何一级目录
   被换掉都会在这里露出来；
5. 从这个 fd **最多读「上限 + 1」字节**，多一个字节就是拒绝。"测了大小再按名字读"是
   TOCTOU；"测了大小但读的时候不限量"则让 50 MiB 的上限只约束 `stat` 不约束内存。

<数据目录> 默认 `/data/cv84x6_llm_server`（`server.env` 的 `CV84X6_DATA_DIR`），
`inbox/` 由 `ensure_layout` 创建，并作为数据目录迁移的一个 part 一起搬走。

三个 agent 都把用户给它们的文件放在自己树内，因此 `agents/**` 覆盖了它们：

| agent | 存放位置 |
|---|---|
| PicoClaw | 工作区 `<agent>/workspace`；渠道下载的媒体在 `$TMPDIR/picoclaw_media`，而 `TMPDIR` 已被管理器指到 `<agent>/tmp`（见 `app/agents/spec.py` 的 `env()`） |
| opencode | 工作区 `<agent>/workspace`；`XDG_DATA_HOME` 指到 `<agent>/data`，附件与 session 数据都在下面 |
| OpenClaw | 工作区由 `OPENCLAW_WORKSPACE_DIR` 指到 `<agent>/workspace`；`OPENCLAW_STATE_DIR`/`OPENCLAW_HOME` 都在 `<agent>/` 内 |

白名单外的路径被拒时，错误信息只写**相对名称**（`agents/`、`inbox/`）和
`CV84X6_MCP_PATHS` 里的目录名，不写服务器的绝对路径：模型需要知道能去哪找，不需要知道
这个 box 怎么摆的。

## 4. 三个 agent 的接入

三个 agent 的配置里都会出现一个名为 **`cv84x6`** 的 MCP server，URL 是
`http://127.0.0.1:<服务端口>/mcp`，鉴权头用与 provider 相同的 API Key。安装、重置、
同步配置时都会写入；**用户自己加的其他 MCP server 不会被覆盖**（配置块按名字合并，
只替换 `cv84x6` 这一项）。

### 各 agent 的格式与证据

**PicoClaw 0.3.1** —— `tools.mcp`

```json
{
  "tools": {
    "mcp": {
      "enabled": true,
      "servers": {
        "cv84x6": {
          "enabled": true,
          "type": "streamable-http",
          "url": "http://127.0.0.1:8000/mcp",
          "headers": {"Authorization": "Bearer sk-..."}
        }
      }
    }
  }
}
```

两个字段缺一不可，都来自 PicoClaw 自己的 Go 结构体（`pkg/config/config.go` 的
`ToolsConfig` / `MCPConfig` / `MCPServerConfig`，以及 `pkg/config/defaults.go`、
`pkg/config/mcp_transport.go`）：

- **`enabled: true`** —— `MCPConfig` 内嵌 `ToolConfig`，`DefaultConfig()` 把它设成
  **false**；不写就等于"MCP integration is disabled"，下面的 `servers` 根本不会被读。
- **`type: "streamable-http"`** —— 不写时 `EffectiveMCPTransportType` 会按"有 url"
  推断成 **sse**，而本端点没有 SSE 流。`streamable-http` 是它 `http` 传输的别名。

实测（0.3.1 x64 二进制 + 一个只实现这五个方法的 mock `/mcp`）：

```
$ picoclaw mcp test cv84x6
INF mcp > Connecting to MCP server server=cv84x6
INF mcp > Connected to MCP server protocol=2025-06-18 server=cv84x6 serverName=mock serverVersion=0.0.1
INF mcp > Listed tools from MCP server server=cv84x6 toolCount=3
✓ MCP server "cv84x6" reachable (3 tools).
```

**opencode 1.19.4** —— `mcp`

```json
{
  "mcp": {
    "cv84x6": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {"Authorization": "Bearer sk-..."},
      "enabled": true
    }
  }
}
```

格式来自二进制里的 zod 定义（`ConfigV2.MCP.Remote`：
`{type: literal("remote"), url, headers, enabled}`）。`type: "remote"` + plain http URL
就是它的 Streamable HTTP 客户端。

实测：`opencode mcp list` 对 mock 端点报 `✓ cv84x6 connected`；抓到的请求依次是
`POST /mcp initialize` → `POST /mcp notifications/initialized` →
`GET /mcp`（被 405 拒绝，不影响）→ `POST /mcp tools/list`，头里带
`Accept: application/json, text/event-stream` 和我们的 `Authorization`。

**OpenClaw 2026.10.7** —— `mcp.servers`

```json
{
  "mcp": {
    "servers": {
      "cv84x6": {
        "url": "http://127.0.0.1:8000/mcp",
        "transport": "streamable-http",
        "headers": {"Authorization": "Bearer sk-..."},
        "enabled": true
      }
    }
  }
}
```

**它原生支持远程 MCP，不需要 stdio 桥接。** 格式来自包里的 zod schema
（`McpServerSchema`，`dist/zod-schema.root-support-*.mjs`）：
`transport` 接受 `stdio` / `sse` / `streamable-http`。`transport` 必须显式写：只给
`url` 时它按 SSE 处理，而本端点没有 SSE 流。

实测（私有 Node 24.22.1 + `openclaw@2026.10.7`）：

```
$ openclaw mcp probe
MCP check (openclaw.json):
- cv84x6: 3 tools, Codex approval auto
  i tools have no safety annotations; calls require approval in prompting session postures
```

`openclaw config validate` 对上面这份配置报 `Config valid`；把 `transport` 改成非法值
会报 `Invalid input (allowed: "stdio", "sse", "streamable-http")`，说明这个字段确实被校验。

### 用户自己加的 server

三个 agent 的配置块都是"读旧文件 → 只替换 `cv84x6` 这一项 → 写回"，所以从 agent 自己的
UI 里加的 server 会在同步后保留。`tests/test_mcp_agent_config.py` 对三个 agent 各测一遍
（安装后加一个 `operator-server`，再 sync，确认它还在）。

### Key 写在两处

API Key 同时出现在 provider 块和 MCP 的 header 里。`existing_key` 两处都读：没有加载模型
时 provider 块是空的（PicoClaw 那边则可能已经把 `api_keys` 搬进 `.security.yml`），此时
MCP header 是唯一能找到的副本 —— 否则每次同步都会吊销并重发一次 key，等于每次刷新控制台
就让 agent 手里的凭据失效一次。

## 5. 外部客户端怎么接

任何支持 Streamable HTTP 的 MCP 客户端都可以直接用：

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H 'Authorization: Bearer sk-...' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
```

`mcp` Python SDK（**只在别的机器/venv 里用，不进 release**）：

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client  # 1.x；2.x 叫 streamable_http_client
import httpx

async with streamablehttp_client("http://<设备>:8000/mcp",
                                 headers={"Authorization": "Bearer sk-..."}) as (r, w, _):
    async with ClientSession(r, w) as s:
        await s.initialize()
        for tool in (await s.list_tools()).tools:
            print(tool.name)
        print(await s.call_tool("kb_search", {"query": "盘点", "top_k": 3}))
```

只支持 stdio 的客户端用随包的桥接：

```bash
bin/cv84x6-mcp-stdio --url http://127.0.0.1:8000/mcp --api-key sk-...
# 或 CV84X6_MCP_URL / CV84X6_API_KEY 环境变量
```

它逐行读 stdin 的 JSON-RPC，转发到 `/mcp`，把响应写回 stdout；通知类消息不产生输出。
纯标准库（`urllib`），不依赖服务的 venv。三个内置 agent 都不需要它。

## 6. 实现位置

| 文件 | 内容 |
|---|---|
| `app/mcp/server.py` | JSON-RPC 2.0 分发、版本协商、Origin 校验、错误分层 |
| `app/mcp/tools.py` | 九个工具；对 `app/apps/kb/*` 的薄封装、推理记录转写、重活并发池 |
| `app/mcp/paths.py` | 本地路径白名单（realpath + 分量比较 + `O_NOFOLLOW` 单描述符读） |
| `app/api/mcp_api.py` | `POST /mcp` 路由（在 `app/main.py` 注册，且在 SPA 兜底之前） |
| `bin/cv84x6-mcp-stdio` | stdio 桥接 |
| `app/agents/{picoclaw,opencode,openclaw}.py` | 各自的 MCP 配置写入 |

测试：`tests/test_mcp_protocol.py`（协议、鉴权、Origin、202 语义）、
`tests/test_mcp_tools.py`（每个工具的正常/错误路径 + 推理记录归属 + 资源上限）、
`tests/test_mcp_paths.py`（白名单、TOCTOU、有界读取）、
`tests/test_mcp_agent_config.py`（三个 agent 的安装/重置/同步）、
`tests/test_mcp_stdio.py`（桥接往返）、`tests/test_mcp_sdk_client.py`（官方 SDK 客户端）。

## 7. 资源上限一览

| 约束 | 值 | 在哪 |
|---|---|---|
| 单个文件 | ≤ 50 MiB | `paths.read_local_file`（读的上限，不只是 `stat`） |
| 图片像素 | ≤ 40 Mpx | `kb_parse.validate_upload`，`ocr_read` 也走 |
| PDF 页数 | ≤ 300（上传）/ 单次读 ≤ 50 页 | `kb_parse.MAX_PDF_PAGES` / `MAX_PDF_PAGES_PER_CALL` |
| 音频 | ≤ 50 MB、≤ 30 分钟 | `audio_upload.MAX_UPLOAD_BYTES` / worker 的 `MAX_AUDIO_SECONDS` |
| `top_k` | ≤ 20 | `tools.MAX_TOP_K` |
| `neighbors` | ≤ 3 | `tools.MAX_NEIGHBORS` |
| 并发的 OCR / 转写 | 2 | `tools.MAX_HEAVY_CALLS` |

## 8. 一个必须知道的现场行为：MCP 连不上会中断 PicoClaw 的整轮对话

实测（PicoClaw 0.3.1）：MCP server 连不上时，`LoadFromMCPConfig` 只是 `WRN`，但
`agent_mcp.go` 的 `Failed to load MCP servers` 会让 `picoclaw agent -m` 直接以
`failed to load MCP servers: ...` 结束，**整轮对话不执行**：

```
ERR mcp > Failed to connect to MCP server error="... connection refused" server=cv84x6
WRN agent > Failed to load MCP servers, MCP tools will not be available ...
Error: error processing message: failed to load MCP servers: failed to connect to server cv84x6: ...
```

正常运维下不会遇到：MCP 端点就在 agent 自己进程连的 `127.0.0.1:<服务端口>` 上，而 agent
本来就是这个服务的客户端 —— 服务不在了，对话模型也不在了。但两种情况会撞上：

- 服务正在重启的窗口里恰好有一次对话；
- 操作员手工改坏了 `tools.mcp.servers.cv84x6` 的 URL。

排障时先看 `agent.log` 里这一行。临时绕过是把该 server 的 `enabled` 置 `false`（或删掉），
agent 就能在没有 MCP 的情况下工作。

## 9. Origin 校验

浏览器可以对 `http://127.0.0.1:8000/mcp` 发起跨源 POST。默认部署下
`require_api_key` 可能是关的（单机可信部署），那时 Origin 就是浏览器与板子之间**唯一**
的关卡 —— 没有它，操作员笔记本上任何一个网页都能驱动这块板子的 NPU，并通过
`kb_add_document` 读取 agent 工作区里的文件。

按 MCP 规范的做法：

- **没有 `Origin` 头** → 放行。三个内置 agent、stdio 桥接、curl、`mcp` SDK 都不发这个头。
- `Origin` 是本机（`127.0.0.1` / `localhost` / `::1`）→ 放行。
- `Origin` 与请求的 `Host` 相同（浏览器意义上的同源，板子的 LAN 地址访问控制台就是这种）
  → 放行。
- `CV84X6_MCP_ORIGINS`（分号分隔）里声明过的 → 放行。
- 其他，包括 `Origin: null`（沙箱 frame / `file://`）→ **403**，在读请求体之前。

```bash
# 操作员要允许另一个前端时：
CV84X6_MCP_ORIGINS=https://console.example;https://ops.example
```

分号而不是冒号：冒号会把 `http://` 劈成两半。

## 10. 与设计的偏差

- **`GET /mcp` 的鉴权**：路由本身不挂 `require_api_key`，所以无 key 的 GET 拿到的是
  405 而不是 401。它不触碰任何工具或数据，泄露的只是"这个路径存在且只说 POST"。
- **`app/api/apps_api.py` 没有对外的"添加一篇文档"函数**（上传路由把步骤写在处理函数里），
  所以 `kb_add_document` 在 `app/mcp/tools.py` 里按同样的顺序重做了那几步（先原子写源文件，
  再入队）。其余工具都直接调用既有函数。
- **`inbox/` 进入了 `storage.SUBDIRS`**，因此它会被 `/api/storage` 列为一个 part 并随
  数据目录迁移一起搬走。
- **没有加入 agent 使用提示**（"处理用户提供的文档、PDF、截图里的大量文字时优先调用
  `ocr_read`；需要查资料时先用 `kb_search`"）。设计里写的是"在已有写入 agent 默认提示词或
  说明的地方（如果有）加一句；没有这种入口就不加，不要为此造新机制"—— 三个 agent 的
  配置里都没有这个入口（`app/agents/*.py` 只写 provider、gateway、workspace 等字段，
  没有任何提示词/instructions 写入点），所以按设计不加。这条提示目前由工具描述承担：
  `ocr_read`、`kb_search` 与 `transcribe_audio` 的 description 里已写明"何时该用它"。
- **`transcribe_audio` 用 `iter_transcribe` 而不是 `transcribe`**：两者产出的文本是同一
  个拼接器给的（worker 里只有一份），但前者是分段流式端点
  `/api/apps/asr/transcriptions/stream` 走的那条路径，复用它意味着 MCP 和控制台不可能对
  同一段音频给出不同的分段。
- **空消息（`{"jsonrpc":"2.0"}`）回 `-32600`，客户端发来的响应回 202**：两种形态要分开。
  前者既没有 `method` 也没有 `id`，是畸形请求；后者有 `id` 而没有 `method`，按 JSON-RPC
  是合法消息，规范要求"202 无 body"。按 `id is None or method is None` 一刀切会把前者也
  变成 202，让一个等回话的客户端永远等下去。
- **`_parse_pages` 的截断提示只在真的截断时才写**：真机复测时发现，`pages="1-2000000000"`
  打在一个 30 页的文件上会写"本次按单次上限取了前 50 页；其余页请再调用一次"——那句话是
  假的，50 页上限并没有限制这次读取，文件本来就只有 30 页。现在的判据是「请求超过上限
  **且** 文档确有你没读到的页」。

## 11. 真机复测记录（10.43.0.157，CV84X6，2.3 GB 内存）

板上一开始是 0.6.16，按 §注释（BSP-NOTES §94）的办法在 `/data/mcp-2611` 搭了一个**旁挂
实例**（8011 端口、独立数据根，安装好的服务一行没动），补上带 aux 符号的
`libcv84x6_llm.so`、0.6.23 的 vendor、`model-config/{ppocr_v6,qwen3_embedding,qwen3_asr}`，
用 dfss 下了 ASR 0.6B（1588723712 B）、embedding 0.6B（1356795904 B）与 PP-OCR 四件，
**大小与 `app/core/downloader.py` 的 CATALOG 逐个相符**。

加载：ASR 7.5 s、embedding 6.5 s、PP-OCR 1.5 s（三个同时加载，内存 699 MB）。

```
initialize -> protocolVersion=2025-06-18 serverInfo=cv84x6-llm-server 0.6.23
tools/list -> 9 tools

transcribe_audio long95.wav   isError=False 4.0s
  long95.wav（音频，Chinese，01:36，4 段，模型 qwen3-asr-0.6b）：
  [00:00–00:30] 甚至出现交易几乎停滞的情况。…
  [01:30–01:36] 情况，甚至出现交易几乎。
  duration=95.5 language=Chinese usage={prompt_tokens:1308, completion_tokens:131}

ocr_read text60.pdf pages="1-2000000000"   isError=False 3.6s
  text60.pdf：共 60 页，本次读取 1–50 页。（本次按单次上限取了前 50 页；其余页请再调用一次并指定 pages）
  50 页整，每页标了「文字层」

ocr_read text60.pdf pages="51-60"          isError=False 0.7s  -> [51..60]
ocr_read cn_notice.png                     isError=False 1.2s  -> 17 行完整中文（真实 PP-OCR）
ocr_read /etc/passwd                       isError=True       -> 不允许读取 passwd：… agents/、inbox/
```

`transcribe_audio` 用的是**已知正确的中文语音**（`asr-golden/long95.wav`，此前在本板
-v1 端点转写过，结果存在 `asr-golden/long95_board.json`），分段文本与那份记录逐字一致。

**复测中发现并修掉的两个问题**（都是真机才暴露的）：

1. `language` 回的是**字符串** `"None"`。模型在没有人声的音频上照字面回 `language None`，
   worker 读前导时原样返回；MCP 层现在把它规范成 `null`（详见 §2）。
2. 截断提示在"文件本来就不够 50 页"时也说被截断了（详见 §10 最后一条）。

**没有复测的**：三个 agent 的对话内触发。板上内存 2.3 GB，35B 放不下，本来就只能验工具
链路；而且这块板在长 prompt 下有 watchdog 重启的既有问题（BSP-NOTES §94「板子跑 35B 会
重启」）。工具链路改用官方 SDK 与三个 agent 自己的二进制验证：`picoclaw mcp test` 报
`✓ cv84x6 reachable (9 tools)`、`opencode mcp list` 报 `✓ cv84x6 connected`、
`openclaw mcp probe` 报 `cv84x6: 9 tools`（都对着本次代码真实的 9 工具目录）。

**另一次现场观察**（与本次改动无关，供记录）：用一张 200 页 PDF 做 `ocr_read` 压测时，
板子在第 90 秒左右**整机重启**（`journalctl --list-boots` 看得到 boot 边界，`dmesg` 里
没有 OOM、没有 panic，`/dev/watchdog` 存在）。同一份代码跑 60 页文本 PDF 稳定在 3.6 s。
这条与 BSP-NOTES 里记的「35B 长 prompt 下重启」可能是同一个看门狗问题的另一面，值得单独
开卡。
