"""The ``/api`` surface's documentation metadata (MYS-2676).

Every management route carries a tag (which module the page is about), a Chinese
summary and description, its request and response models, and the error codes it
can answer. Writing that inline in ``admin_api.py`` would double the length of a
1300-line file whose handler bodies are already commented at length, and the
metadata is pure data -- so it lives here, keyed by ``(method, path)``, and
``app.api.docs.apply`` attaches it at import time.

**Why keyed by path rather than applied at each decorator:** the key is exactly
what ``/api/openapi.json`` publishes, so a route that is renamed and not updated
here fails ``tests/test_admin_api_docs.py`` loudly instead of silently shipping
an undescribed endpoint. The test also refuses an entry for a route that does not
exist, which is what keeps this table from rotting into a description of an API
that used to be.

The error codes are the *documented* set for a route, not every code its
exception handlers could conceivably produce: the shared ones (401/403 from the
auth dependency, 500 from an unhandled error) are declared once on every route by
``apply`` and do not need repeating per entry.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import admin_schemas as s
from . import kb_schemas as k

#: The tag vocabulary, in the order the document prints it. ``description`` is
#: the section's introduction in Swagger and in ``docs/admin-api.md``.
TAGS: list[dict] = [
    {"name": "auth", "description": "登录、退出、会话状态、修改口令。脚本通常不需要这些："
                                    "用 admin key 直接调用即可。"},
    {"name": "stats", "description": "总览页的读数：设备（CPU / 内存 / 温度 / NPU+VPP 内存）、"
                                     "累计用量、前缀缓存、磁盘。"},
    {"name": "models", "description": "模型列表、加载、卸载、删除、单模型设置、worker 日志。"
                                      "「模型」页的全部接口。"},
    {"name": "downloads", "description": "模型下载：启动、进度、取消、更新到 dfss 标签指向的最新版本，"
                                         "以及本版本支持的模型目录。"},
    {"name": "settings", "description": "全局设置、数据目录占用与搬迁。"},
    {"name": "keys", "description": "API key 的增删查与吊销。key 分 `inference`（只能调 `/v1`）"
                                    "和 `admin`（还能调 `/api`）两种权限范围。"},
    {"name": "records", "description": "推理记录：每次推理一条，用于事后解释一次错误回答。"
                                       "列表不含对话正文，正文在详情里。"},
    {"name": "console", "description": "控制台自己的对话与测试代理：用 cookie 或 admin key 驱动模型，"
                                       "不必先申请 key。字段与 `/v1` 对应接口一致。"},
    {"name": "logs", "description": "平台 / worker / agent 三类日志的读取与下载，以及管理审计。"
                                    "审计只记写操作，读日志不产生审计行。"},
    {"name": "agents", "description": "内置 agent（opencode / OpenClaw / DSH）的安装、启停、配置、日志。"},
    {"name": "apps", "description": "「应用演示」的接口：知识库问答与语音转写流。"},
]

#: Methods that change state. Declared on every route so a client author can see
#: which calls the audit trail records (it records exactly these, plus login).
_AUDITED = ("POST", "PUT", "PATCH", "DELETE")


def _entry(tag: str, summary: str, description: str, *,
           body=None, response=None, errors: tuple[int, ...] = (),
           status: int = 200, content: str | None = None, auth: bool = True,
           extra_responses: dict | None = None) -> dict:
    """One route's documentation, in the shape :func:`app.docs.apply` consumes.

    ``auth=False`` is only for ``/api/login``, the one route a caller reaches
    without a credential (and which therefore cannot answer 401 for a missing
    one -- it answers 401 for a *wrong* one, which the entry states explicitly).
    """
    return {"tag": tag, "summary": summary, "description": description,
            "body": body, "response": response, "errors": errors,
            "status": status, "content": content, "auth": auth,
            "extra_responses": extra_responses or {}}


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------
#: ``(METHOD, path)`` -> documentation. The path is the one FastAPI registers,
#: without the router's own prefix being repeated (``/api`` is added when the
#: document is built, so these read as the console's URLs).
DOCS: dict[tuple[str, str], dict] = {
    # -- auth ------------------------------------------------------------
    ("POST", "/api/login"): _entry(
        "auth", "管理员登录（换会话 cookie）",
        "用管理员口令换取签名会话 cookie，有效期 12 小时。控制台用它；脚本应改用 "
        "`Authorization: Bearer <admin key>`，不必登录。口令错误时固定延迟 0.4 秒，"
        "避免成为暴力破解的计时旁路。",
        body=s.LoginBody, response=s.OkOut, errors=(401,), auth=False),
    ("POST", "/api/logout"): _entry(
        "auth", "退出登录（清除会话 cookie）",
        "删除浏览器里的会话 cookie。服务端不保留会话表，因此不需要别的动作。",
        response=s.OkOut),
    ("GET", "/api/session"): _entry(
        "auth", "查询当前请求是否已登录",
        "控制台启动时用它决定显示登录页还是主界面。始终返回 200，"
        "未登录时 `authenticated: false`。",
        response=s.SessionOut),
    ("POST", "/api/password"): _entry(
        "auth", "修改管理员口令",
        "新口令至少 6 个字符。改完之后旧 cookie 仍然有效（会话密钥没变），"
        "下次登录用新口令。",
        body=s.LoginBody, response=s.OkOut, errors=(400, 401)),
    # -- stats -----------------------------------------------------------
    ("GET", "/api/stats"): _entry(
        "stats", "总览：设备读数、累计用量、每个模型的状态",
        "控制台总览页每几秒轮询一次。一次请求返回四组数据：`device` 是主板读数"
        "（读数来源见 `device.device_mem.source`，mock 后端为 `mock`）；`usage` 是累计用量与"
        "decode 速度采样；`models` 与 `GET /api/models` 同形；`kv_cache` / `workers` 是"
        "各 worker 自报的统计。设备内存口径见 `docs/device-memory.md`。",
        response=s.StatsOut),
    # -- models ----------------------------------------------------------
    ("GET", "/api/models"): _entry(
        "models", "列出 models/ 下的全部模型及其状态",
        "含未加载的模型。`loaded` / `operation` / `load_error` 是控制台判断按钮可用性的依据；"
        "`settings` 是操作者保存的原样值（可能为 null，表示跟随默认），`effective` 是当前"
        "生效值，`mem_*_bytes` 是上限与占用的账。为了少一次 RPC，已加载且空闲的模型会顺带"
        "取一次 worker 统计，因此本接口在 worker 无响应时最多慢 3 秒。",
        response=s.ModelListOut),
    ("GET", "/api/models/{model_id}/settings"): _entry(
        "models", "读一个模型的按模型设置",
        "返回保存的设置、当前生效值、内存上限的推算默认值与各项边界。"
        "`limits` 里的数字就是 `PUT` 接受的取值范围，控制台的输入框直接用它。",
        response=s.ModelSettingsOut, errors=(404,)),
    ("PUT", "/api/models/{model_id}/settings"): _entry(
        "models", "改一个模型的按模型设置（空闲卸载阈值 / 自动加载 / 内存上限）",
        "字段语义是「省略不改、`null` 恢复默认」，两者不同：控制台只发送操作者动过的那一个"
        "字段。拒绝有四处：字段越界（400）、模型正在加载或卸载（409，`model_busy`）、"
        "内存上限低于模型当前占用（400）、**运行中增额后 NPU 剩余量低于安全下限**"
        "（409，`device_memory_insufficient`）。增额与模型加载共用同一份设备预算准入："
        "扣掉**所有**已加载大模型的运行期预算（含本模型自己原来的预算）、尚未完成的承诺和 "
        "1 GiB 保护下限。所以 free=1624 MiB、原预算 400、调到 1000 会被拒绝 —— 只剩 624 MiB，"
        "边界是 2024 MiB；缓存/会话较多时也可能拒绝物理上放得下的增额，需要更大额度请先卸载"
        "其他模型。`native` 后端读不到设备余量时不放行（503）。"
        "拒绝时原设置与 worker 额度都不变。改完立即生效，不需要重新加载模型。"
        "**答复丢失时的收尾**：`configure` 超时、连接断开、本地写失败或读到 EOF 后，"
        "本接口会读一次 worker 的实际额度再决定 —— 确实已应用则保存并按成功返回"
        "（`applied.settled_after_lost_reply`），确认未应用是 409，无法确认则保留这部分额度"
        "并按 503 报告，该额度继续按已占用记账（后续加载与增额都用不到它）。"
        "**恢复有三条路径，都不需要重启服务**：① 重试同一次保存 —— 会先核对 worker 的实际"
        "额度再收敛，已应用就补写设置并返回 200；② 改不同的额度 —— 核对完成前 409 "
        "`model_busy`；③ 卸载该模型 —— worker 进程确认退出后对应未确认额度清零"
        "（卸载失败或进程仍在则保留）。取消请求时同样先标记未确认，并在同一次请求内做有界"
        "核对，不遗留脱离锁写设置的后台任务。",
        body=s.ModelSettingsBody, response=s.ModelSettingsOut,
        errors=(400, 404, 409, 503)),
    ("POST", "/api/models/{model_id}/load"): _entry(
        "models", "加载一个模型",
        "加载完成才返回（`loaded: true`），35B 需几十秒。重复调用是幂等的：已加载时直接"
        "返回当前状态。设备内存不足、静态占用超过本模型上限、或已有无法确认归属的同名进程时"
        "返回 409，`code` 分别是 `device_memory_insufficient` / `model_mem_limit_exceeded` / "
        "`model_conflict`。",
        response=s.ModelActionOut,
        errors=(404, 409)),
    ("POST", "/api/models/{model_id}/unload"): _entry(
        "models", "卸载一个模型",
        "先拒绝（409）再动手：卸载过程中的模型不会被改坏。worker 正忙时返回 `model_busy`。",
        response=s.ModelActionOut, errors=(404, 409)),
    ("GET", "/api/models/{model_id}/log"): _entry(
        "models", "读一个模型的 worker 日志尾部",
        "`tail` 是行数（默认 200）。日志文件不存在时返回空串而不是 404："
        "「这个模型自启动以来没跑过」是信息，不是错误。",
        response=s.AgentLogsOut),
    ("DELETE", "/api/models/{model_id}"): _entry(
        "models", "从磁盘删除一个模型",
        "已加载、正在加载/卸载、正在下载的模型都拒绝删除（409）。删除时连同它的"
        "按模型设置一起清掉，避免同名模型下次被下载时继承旧的限制。",
        response=s.OkOut, errors=(400, 404, 409)),
    # -- downloads -------------------------------------------------------
    ("POST", "/api/downloads"): _entry(
        "downloads", "启动一个模型下载任务",
        "`kind: \"dfss\"` 走 dfss，`kind: \"url\"` 走 http(s)。多文件模型（OCR 是四个 "
        "bmodel）用 `files` 给出清单；`kind: dfss` 且省略时用本版本登记的清单展开，"
        "这样「一键下载」不会只装一个碎片。目标模型正在运行、正在加载或已在下载时返回 409。",
        body=s.DownloadBody, response=s.StartDownloadOut, errors=(400, 409)),
    ("GET", "/api/downloads"): _entry(
        "downloads", "列出下载任务与磁盘残留",
        "`jobs` 是全部任务（最新的在前）；`orphans` 是上次失败留下的 `.part`/`.bak`，"
        "其中 `recoverable` 里的 `.bak` 是唯一副本，不要删。",
        response=s.DownloadListOut),
    ("POST", "/api/downloads/{job_id}/cancel"): _entry(
        "downloads", "取消一个下载任务",
        "等传输真的停下来才返回，因此模型锁的释放时机是确定的。",
        response=s.OkOut, errors=(404,)),
    ("GET", "/api/catalog"): _entry(
        "downloads", "本版本支持的模型目录（含「有新版本」判定）",
        "每张卡片带 `installed` / `downloading`，已安装且登记了 dfss 标签的还带 "
        "`latest_file` / `update_available`。标签索引要一次 dfss 下载，因此缓存 10 分钟并在"
        "后台刷新：本接口只读缓存，离线设备拿不到更新信息，但页面照常打开。",
        response=s.CatalogOut),
    ("POST", "/api/models/{model_id}/update"): _entry(
        "downloads", "把模型更新到 dfss 标签指向的最新版本",
        "会占用该模型 id 的下载锁；模型正在运行、加载、卸载或下载时返回 409。"
        "失败时磁盘上的旧版本不受影响。",
        response=s.StartDownloadOut, errors=(400, 404, 409)),
    # -- keys ------------------------------------------------------------
    ("GET", "/api/keys"): _entry(
        "keys", "列出全部 API key",
        "只返回元数据：明文 key 只在创建时返回一次，服务端只存 SHA-256 哈希。"
        "`scope` 字段说明这把 key 能不能调 `/api`。",
        response=s.KeyListOut),
    ("POST", "/api/keys"): _entry(
        "keys", "创建 API key",
        "`scope` 默认 `inference`（只能调 `/v1`）。需要脚本管理服务时创建 `scope: admin` 的 key，"
        "然后用 `Authorization: Bearer <key>` 调用 `/api/*`。明文 key 只在本响应里出现一次。",
        body=s.CreateKeyBody, response=s.CreateKeyOut, errors=(400,)),
    ("DELETE", "/api/keys/{key_id}"): _entry(
        "keys", "删除一个 API key",
        "与吊销不同：删除后这把 key 从列表里消失。两者都立即生效。",
        response=s.OkOut, errors=(404,)),
    ("POST", "/api/keys/{key_id}/revoke"): _entry(
        "keys", "吊销一个 API key（保留记录）",
        "吊销后这把 key 不能再认证，但仍在列表里可见，便于审计回溯。",
        response=s.OkOut, errors=(404,)),
    # -- settings --------------------------------------------------------
    ("GET", "/api/settings"): _entry(
        "settings", "读全局设置（含各项的边界）",
        "`*_limit*` / `*_min` / `*_max` 字段是同一个字段的取值范围，发布出来是为了让控制台的"
        "输入框不必再写一遍常量。",
        response=s.SettingsOut),
    ("POST", "/api/settings"): _entry(
        "settings", "保存全局设置并立即应用到已加载的模型",
        "字段全部可选；**越界值会被夹到边界而不是报错**（设置页的输入框可能送来一个过期的数字，"
        "不该因此存不进去；需要严格校验的是按模型的内存上限，那条路由拒绝越界）。"
        "`applied` 汇总每个已加载 worker 的应答，推送失败的带一个 `error` 键——"
        "设置已经保存，只是某个 worker 没收到。",
        body=s.SettingsBody, response=s.SettingsSaveOut, errors=(400,)),
    ("GET", "/api/storage"): _entry(
        "settings", "数据目录的占用与所在文件系统",
        "`refresh=true` 跳过 30 秒的大小缓存。`parts` 按子目录拆开，`dir_bytes` 是它们的和。",
        response=s.StorageOut),
    ("POST", "/api/storage/move"): _entry(
        "settings", "把数据目录搬到另一个位置（异步）",
        "**先在请求里校验，再在后台搬**：校验会走一遍当前数据树来估大小，因此在本请求里同步执行；"
        "搬运用 `GET /api/storage/move` 轮询。已有任务在进行时 409（`storage_busy`）。",
        body=s.MoveBody, response=s.MoveStartedOut, status=202, errors=(400, 409)),
    ("GET", "/api/storage/move"): _entry(
        "settings", "搬迁任务的进度",
        "没有任务时返回 `state: \"idle\"` 的空任务，而不是 404：设置页始终能画出这一块。",
        response=s.MoveJobOut),
    # -- records ---------------------------------------------------------
    ("GET", "/api/inference-records"): _entry(
        "records", "推理记录列表（不含对话正文）",
        "最新的在前。重字段（消息、输出原文）只在详情里：一页 200 条、每条都带 128k 对话"
        "会是几十 MB。`limit` 1-200；`before` 是排他的时间上界，用于在持续写入时向后翻页。",
        response=s.RecordListOut, errors=(400, 500)),
    ("GET", "/api/inference-records/status"): _entry(
        "records", "记录库自身的状态（可读性、大小、最近一次写入失败）",
        "「列表为什么是空的」的答案在这里：库不可写时 `readable: false` 且 `last_error` 有原因。"
        "搬迁期间 `moving: true`，写入是暂停而不是坏了。",
        response=s.RecordStatusOut),
    ("GET", "/api/inference-records-export"): _entry(
        "records", "导出全部推理记录（NDJSON）",
        "一行一条完整记录，最新的在前，流式输出（读表时分页，10 万条也不会变成一个字符串）。"
        "用 `responses` 声明的内容类型是 `application/x-ndjson`，并带 `Content-Disposition` 附件名。",
        content="application/x-ndjson"),
    ("POST", "/api/inference-records/clear"): _entry(
        "records", "清空推理记录并把磁盘空间还给系统",
        "不可撤销。`deleted` 是被删掉的条数。",
        response=s.ClearRecordsOut, errors=(500,)),
    ("GET", "/api/inference-records/{record_id}"): _entry(
        "records", "一条推理记录的完整内容（含消息与输出原文）",
        "控制台的记录页点开一行时调用。响应在列表字段之外还带 `messages`（原始请求）、"
        "`output_text` / `raw_output`（输出正文）与 `error`，这是唯一能读到对话内容的接口。",
        response=s.RecordSummaryOut, errors=(404,)),
    # -- console chat ----------------------------------------------------
    ("POST", "/api/chat"): _entry(
        "console", "控制台的对话（非流式）",
        "与 `/v1/chat/completions` 走同一条推理路径，但用控制台凭据而不是 API key，"
        "因此操作者不必先申请 key 才能在界面上试一句话。只服务 chat / ocr_vl 两类模型；"
        "别的类型请用 `/api/test/*`。",
        body=s.ChatBody, response=s.ChatOut, errors=(400, 409, 500)),
    ("POST", "/api/chat/stream"): _entry(
        "console", "控制台的对话（SSE 流式）",
        "同一请求，逐 token 返回 `data: {\"text\": ...}`，最后 `data: {\"done\": true, ...}` "
        "与 `data: [DONE]`。模型拒绝时以 `data: {\"error\": ...}` 收尾再发 `[DONE]`。",
        body=s.ChatBody, content="text/event-stream", errors=(400, 409)),
    ("POST", "/api/test/embeddings"): _entry(
        "console", "控制台测试面板：embedding",
        "直接调用 `/v1/embeddings` 的处理函数，字段与错误码完全一致，只是调用者是管理端、"
        "不必持有 inference key。请求体与响应见 `/v1/openapi.json` 的 `POST /v1/embeddings`。",
        content="application/json", errors=(400, 409, 429, 503)),
    ("POST", "/api/test/rerank"): _entry(
        "console", "控制台测试面板：rerank",
        "直接调用 `/v1/rerank` 的处理函数。请求体与响应见 `/v1/openapi.json` 的 "
        "`POST /v1/rerank`。",
        content="application/json", errors=(400, 409, 429, 503)),
    ("POST", "/api/test/audio/transcriptions"): _entry(
        "console", "控制台测试面板：语音转写",
        "`multipart/form-data`（`model`、`file`、可选 `language` / `prompt`），"
        "由 `/v1/audio/transcriptions` 的处理函数读取，字段与错误码一致。",
        content="application/json", errors=(400, 409, 415, 429, 503)),
    ("POST", "/api/test/ocr"): _entry(
        "console", "控制台测试面板：OCR",
        "`multipart/form-data`（`file` + `model`）或 JSON（`{\"model\", \"image\"}`），"
        "由 `/v1/ocr` 的处理函数读取，含 `mode=vl` 的两模型编排。",
        content="application/json", errors=(400, 409, 429, 503)),
    ("POST", "/api/test/chat/completions"): _entry(
        "console", "控制台测试面板：OpenAI 对话（含视觉）",
        "直接调用 `/v1/chat/completions` 的处理函数，因此拿到与官方客户端完全相同的"
        "类型规则与响应。请求体见 `app/schemas.py` 的 `ChatCompletionRequest`。",
        content="application/json", errors=(400, 409, 429, 503)),
    # -- logs / audit ----------------------------------------------------
    ("GET", "/api/logs/sources"): _entry(
        "logs", "列出可读的日志源",
        "从未写过的日志也会出现，`size_bytes: 0`：`kind` 区分平台 / worker / agent 三类。"
        "**这些接口不写审计**：日志页在轮询，一次轮询一行审计会把真正的变更埋掉。",
        response=s.LogSourcesOut),
    ("GET", "/api/logs/{source}"): _entry(
        "logs", "读一页日志",
        "不带 `cursor` 时是「最新的 N 行」，从文件尾往回读，因此读 50 MB 的日志也不会卡住；"
        "带 `cursor` 时接着上一页往更旧的方向翻。返回的行**从旧到新**，便于页面自上而下渲染。"
        "`since` / `until` 接受 epoch 秒、ISO8601 或相对时间（`-30m` / `-2h` / `-7d`）。",
        response=s.LogPageOut, errors=(400, 404)),
    ("GET", "/api/logs/{source}/download"): _entry(
        "logs", "下载日志（过滤后的文本，或含轮转的 zip）",
        "带过滤条件时是纯文本（`text/plain; charset=utf-8`）；不带条件时是包含所有轮转代际的 zip "
        "（`application/zip`）——只给当前文件会漏掉正要排查的那次事故。两者都是流式的。",
        content="text/plain; charset=utf-8", errors=(400, 404)),
    ("GET", "/api/audit"): _entry(
        "logs", "管理审计：谁在什么时候改了什么",
        "只记写操作（POST/PUT/PATCH/DELETE）与登录，读操作不记。`action` 是 `\"方法 路径前缀\"`，"
        "例如 `POST /api/models` 也匹配 `/api/models/x/load`。`dropped` 非零表示审计链有缺口。"
        "审计库不可读时返回 503 而不是空表。",
        response=s.AuditPageOut, errors=(400, 503)),
    ("GET", "/api/audit/export"): _entry(
        "logs", "导出审计为 CSV",
        "UTF-8 **带 BOM**（否则中文 Windows 的 Excel 会把表头读成乱码），列顺序固定，流式输出。",
        content="text/csv; charset=utf-8", errors=(400, 503)),
    # -- agents ----------------------------------------------------------
    ("GET", "/api/agents"): _entry(
        "agents", "列出内置 agent 的状态",
        "`status` 是四态摘要（running / stopped / failed / not_installed），`operation` 表达"
        "四态表达不了的部分（starting 不算 running）。`web_url` 与 `web` 是它自己界面的地址与登录凭据。",
        response=s.AgentListOut),
    ("GET", "/api/agents/{agent_id}"): _entry(
        "agents", "读一个 agent 的状态",
        "与列表里的元素同形，但 `web_url` 用本次请求的 Host 拼，因此从别的机器访问也打得开。",
        response=s.AgentOut, errors=(400, 404, 409, 500)),
    ("PATCH", "/api/agents/{agent_id}"): _entry(
        "agents", "改一个 agent 的配置（端口 / 自启 / 模型 / 思考模式）",
        "只发送要改的字段。改运行中 agent 的端口会重启它。其他字段在下次启动时生效。",
        body=s.AgentPatchBody, response=s.AgentOut, errors=(400, 404, 409, 500)),
    ("POST", "/api/agents/{agent_id}/{action}"): _entry(
        "agents", "对一个 agent 执行操作（start / stop / restart / reset / uninstall / sync）",
        "返回操作后的状态。`install` 是单独的路径。未知 action 返回 404；"
        "内存不够、端口被占、已安装等情况返回 409 并在 `detail` 里说明怎么办。",
        response=s.AgentOut, status=202, errors=(400, 404, 409, 500)),
    ("POST", "/api/agents/{agent_id}/install"): _entry(
        "agents", "安装一个 agent（下载在后台进行）",
        "返回安装任务，进度用 `GET /api/agents/{id}/job` 或状态里的 `job` 字段查。",
        response=s.AgentJobOut, status=202, errors=(400, 404, 409)),
    ("GET", "/api/agents/{agent_id}/job"): _entry(
        "agents", "读一个 agent 的安装任务",
        "安装是异步的（下载一个真实的发布包），控制台用它画进度条。没有任务时 "
        "`job: null`，而不是 404。",
        response=s.AgentJobOut, errors=(400, 404, 409)),
    ("GET", "/api/agents/{agent_id}/logs"): _entry(
        "agents", "读一个 agent 的日志尾部",
        "`tail` 是行数（默认 200，上限 5000）。",
        response=s.AgentLogsOut, errors=(400, 404, 409)),
    # -- apps: kb --------------------------------------------------------
    ("GET", "/api/apps/kb"): _entry(
        "apps", "列出知识库",
        "`doc_count` / `chunk_count` 来自缓存在 `kb.json` 里的计数：2 万片段的库每次刷新都重新"
        "解析一遍不现实。缺这两个字段的老库会重算一次并写回。",
        response=k.KbListOut),
    ("POST", "/api/apps/kb"): _entry(
        "apps", "新建知识库",
        "名字可为空（界面上就是「未命名」）。新建的库是空的：下一步用 "
        "`POST /api/apps/kb/{kb_id}/docs` 上传文档，等 `status` 变成 `ready` 才能检索。",
        body=k.CreateKbBody, response=k.CreateKbOut, errors=(400,)),
    ("DELETE", "/api/apps/kb/{kb_id}"): _entry(
        "apps", "删除知识库",
        "连同它的文档、切片、向量一起删；队列里属于它的任务会被丢弃。",
        response=s.OkOut, errors=(404, 500)),
    ("POST", "/api/apps/kb/{kb_id}/reindex"): _entry(
        "apps", "用当前加载的 embedding 模型重建整个库的向量",
        "用于「建库时的模型已经换掉」：旧向量与新模型的查询向量不在同一空间，检索阶段会跳过它们。"
        "没有可用模型、库是空的、或已在重建时返回 409（立即拒绝，而不是排一个注定失败的队）。",
        response=k.ReindexJobOut, errors=(400, 404, 409)),
    ("GET", "/api/apps/kb/{kb_id}/docs"): _entry(
        "apps", "列出库里的文档及其索引状态",
        "`status` / `progress` 是建库队列的实时进度；`error` 是失败原因，可配合 retry 重试。",
        response=k.DocListOut, errors=(404,)),
    ("POST", "/api/apps/kb/{kb_id}/docs"): _entry(
        "apps", "上传一个或多个文档，排进建库队列",
        "`multipart/form-data`，字段名 `file`（可重复）。**整批校验通过才收**：一个坏文件会让"
        "整次上传被拒，避免「界面报错但有两个文档在索引」。单文件上限与支持的格式见 "
        "`docs/kb-app.md`。",
        response=k.UploadDocsOut, errors=(400, 404, 409)),
    ("DELETE", "/api/apps/kb/{kb_id}/docs/{doc_id}"): _entry(
        "apps", "删除一个文档",
        "会等在解析中的任务停下并确认后再删，因此删除是确定的。重复删除返回成功。",
        response=s.OkOut, errors=(404, 409, 500)),
    ("POST", "/api/apps/kb/{kb_id}/docs/{doc_id}/retry"): _entry(
        "apps", "重试一个失败的文档",
        "只有 `failed` 的文档可以重试；仍在队列或解析中、原始文件已丢失时返回 409。",
        response=k.RetryDocOut, errors=(404, 409)),
    ("GET", "/api/apps/kb/{kb_id}/docs/{doc_id}/chunks"): _entry(
        "apps", "读一个文档切出的全部片段",
        "含版面框坐标（`boxes`），文档识别页用它把片段框在页面上。",
        response=k.ChunkListOut, errors=(404,)),
    ("GET", "/api/apps/kb/{kb_id}/docs/{doc_id}/pages/{page}.png"): _entry(
        "apps", "读文档某一页的预览图（PNG）",
        "扫描件、图片与 PDF 的每一页在解析时都会渲染一张预览图，文档识别页用它显示"
        "版面框。`page` 从 1 开始；没有这一页时 404。",
        content="image/png", errors=(404,)),
    ("GET", "/api/apps/kb/{kb_id}/docs/{doc_id}/file"): _entry(
        "apps", "下载文档的原始文件",
        "按原名返回（`Content-Disposition: attachment`）。",
        content="application/octet-stream", errors=(404,)),
    ("POST", "/api/apps/kb/{kb_id}/search"): _entry(
        "apps", "检索：BM25 + 向量 → RRF → 精排",
        "各阶段按已加载的模型自动降级，跳过的阶段与原因在 `skipped` 里，不是静默降级。"
        "`candidates` 上限 100（一次检索在板上约 6.5 秒），`top_k` 不能大于 `candidates`。",
        body=k.SearchBody, response=k.SearchOut, errors=(400, 404, 500)),
    ("POST", "/api/apps/kb/{kb_id}/answer"): _entry(
        "apps", "基于检索到的片段流式生成带引用的回答",
        "先把 `/search` 的命中 id 传进来，再用本接口生成。SSE，帧格式见 `docs/kb-app.md`。",
        body=k.AnswerBody, content="text/event-stream", errors=(400, 404, 409)),
    ("POST", "/api/apps/asr/transcriptions/stream"): _entry(
        "apps", "语音转写（按段流式）",
        "`multipart/form-data`（`model`、`file`、可选 `language` / `prompt`），每段一帧 SSE："
        "先 `meta`，再若干 `segment`，最后 `done`（正文与 `/v1/audio/transcriptions` "
        "逐字一致）。能在 NPU 开始跑之前判定完的拒绝都是状态码而不是帧：415 容器无法解码，"
        "400 音频超过 30 分钟，429 队列已满。",
        content="text/event-stream", errors=(400, 415, 429, 503)),
}


#: Shared by every route: the auth dependency can refuse before the handler runs.
COMMON_ERRORS = (401, 403)
