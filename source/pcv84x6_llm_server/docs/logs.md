# 日志与操作审计（`/api/logs`、`/api/audit`）

控制台「日志」页的后端：三类日志的统一查询与下载，以及管理端每一次变更操作的审计。
控制台界面由负责人开发，本文只描述后端保证什么。

- 代码：`app/core/logs.py`（文件日志）、`app/core/audit.py`（审计库与中间件）、`app/api/logs_api.py`（接口）
- 配置：`/api/settings` 的 `audit_retention_days`

## 1. 三类日志，一条读取路径

| source id | 位置 | 谁写 |
|---|---|---|
| `platform` | `<数据目录>/state/logs/platform.log`（+ `.1`…`.5`） | 本服务自己的 `logging` |
| `worker:<模型 id>` | `<数据目录>/state/logs/worker-<模型 id>.log`（+ `.1`…`.3`） | 每个模型的 worker 进程 |
| `agent:<agent id>` | `<数据目录>/agents/<agent id>/logs/agent.log` | agent 自己的进程 |

三条路径**都在数据目录下**，随数据目录迁移一起走。worker 与 agent 日志不搬家：它们本来就写在
那里，只是现在有了一个能翻页的读取入口。

`source` 是唯一的用户输入，也是唯一会变成路径的东西：它只在
`LogRegistry.sources()` 从文件系统现扫出来的 id 集合里查表（`LogRegistry.resolve`），
查不到就是 404。`../`、绝对路径、软链名都不会进入任何 `open()`——`resolve` 的实现没有把
输入拼进路径的那一步。这条规则由 `tests/test_logs_api.py` 的路径穿越用例逐个钉住。

## 2. 平台日志：从 stderr 到文件

`app/main.py` 原来只 `basicConfig` 到 stderr（systemd journal 收集）。现在**同时**写
`state/logs/platform.log`：

- 保留 stderr：磁盘满、数据目录被搬走时 journal 是operator 的安全网，两者不竞争。
- 轮转：10 MiB × 5 份（`RotatingFileHandler`）。
- 格式固定为 `时间(ISO8601 本地时区带偏移) 级别 logger: 消息`，例如
  `2026-11-07T10:27:46.123+08:00 INFO cv84x6: CV84X6 LLM service v0.6.28 starting`。
  本地时区是刻意的：操作员拿它和 `journalctl` 对照；偏移量保证文件被拷到别的机器（或板子时钟被
  NTP 跳过）之后仍不含糊。
- `create_app` 在一个进程里可能被调用多次（测试），handler 是**替换**而不是叠加，一个文件一个写者。

解析是宽容的：本服务格式、带时区的 ISO8601、以及**任何别的行**。解析不出来的行不丢——`message`
放原文、`level` 为 `null`。worker 的 traceback、native 库的 `bm_alloc_gmem failed`、mock worker
的 `{"event": "ready"}` 横幅都属于这一类，而它们恰好是排查时最需要看的。

worker 日志原本没有轮转，一个被反复加载卸载的模型会写出一个无上界文件。轮转加在
`ModelManager._load` 打开日志**之前**那一处（`app/core/models.py`，唯一改动点）：
那一刻没有任何 fd 持着这个文件，是唯一安全的 rename 时机。策略 10 MiB × 3 定义在
`app/core/logs.py`，与读它的代码同处，避免"写的人和读的人对 `.1` 的理解不一致"。

## 3. 接口

全部只允许控制台登录（`require_admin`，与 `/api/*` 其余接口同一套权限）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/logs/sources` | `[{id, label, kind, size_bytes, updated_at, updated_at_iso}]`，平台日志在首位 |
| GET | `/api/logs/{source}` | 一页结构化行 `{ts, level, logger, message}`，见下 |
| GET | `/api/logs/{source}/download` | 过滤后纯文本；无过滤时把轮转文件一起打成 zip |
| GET | `/api/audit` | 审计分页查询 |
| GET | `/api/audit/export` | 审计 CSV（UTF-8 BOM） |

### `GET /api/logs/{source}`

参数：`since`、`until`、`level`、`q`、`limit`（1–5000，默认 200）、`cursor`。

- `since`/`until`：epoch 秒、ISO8601、或相对窗口（`-30m`、`-2h`、`-7d`）。无时区的 ISO 按**本地
  时间**解析，和日志行本身同一条规则。
- `level`：阈值语义（`warning` = warning 及以上），不是精确匹配——操作员问的是"什么出错了"。
  接受 `warn`/`err`/`fatal` 别名。非法值返回 400，不是空页。
- `q`：子串，大小写不敏感。
- 不带 `cursor` = **最新 N 行**。
- 响应按**旧→新**排列，便于控制台自上而下渲染；`cursor` 指向"返回的第一行之前那一行"，
  `has_more` 与 `cursor is not None` 完全一致——"加载更早"按钮只在它真能取到东西时出现。

### 最新 N 行怎么读

从文件尾**反向按 64 KiB 块**读，凑够 N 行就停（`iter_lines_backwards`）。50 MiB 日志取 200 行
只碰最后几个块：`tests/test_logs_api.py` 用 50 MiB 文件实测，断言内存峰值 < 4 MiB（实测远低于此）
且耗时 < 2 s。正着读完整文件在这里是 50 MiB 的 I/O 和同样大小的行列表。

单次请求还有 `SCAN_BUDGET_BYTES`（16 MiB）的读取上限：过滤条件一个都不匹配时，扫描到上限就
停下并返回游标，而不是把一个大日志走到底。`Budget.stopped` 区分"没读完"和"读到头了"，
所以 `has_more` 在两种情况下都诚实。

### 翻页为什么是字节游标

`cursor` 是 `{source, 文件名, 字节偏移}` 的 base64。用行号翻页在追加写的文件上必然错位——
新行落在尾部，行号窗口整体平移；字节偏移不会。文件名（而不是代数索引）让轮转后游标不会
悄悄指向另一代文件。游标只在签发它的 source 上有效，跨 source 或伪造返回 400；它指向的那一代
已经被轮转掉时，走查结束（返回空页 + `cursor: null`），而不是从头再返回一遍最新行——那会让
"加载更早"变成一个死循环。

## 4. 下载

- **带过滤**（`since`/`until`/`level`/`q` 任一）：匹配行拼成纯文本，`text/plain`，旧→新。
- **不带过滤**：整段历史，**包括轮转出来的旧文件**，打成 zip（`platform.log.2` → `.1` → `platform.log`
  的顺序，读起来像一份连续的日志）。操作员下载 `platform.log` 想要的是包含事发那一刻的完整文件，
  只给当前那一代等于给了一份缺页的证据。
- 两者都流式：50 MiB 日志不会变成一个内存字符串。zip 用非 seek 流（`_ZipStream`）产出，
  每写完一个条目就把缓冲交出去。

## 5. 审计

### 记什么

用中间件（`AuditMiddleware`，纯 ASGI）记录 `/api/*` 中**所有改变状态的请求**（POST/PUT/PATCH/
DELETE），以及登录成功、登录失败、登出。`/v1/*` 不进审计——那是推理记录的职责
（[`inference-records.md`](inference-records.md)）；GET 也不进，尤其是 `/api/logs/*` 自己：
日志页会轮询，一次轮询一条记录会把审计真正要显示的变更埋掉。

| 字段 | 含义 |
|---|---|
| `ts` / `ts_iso` | epoch 秒 + 本地 ISO8601（带偏移），排序键 |
| `actor_type` / `actor_id` / `actor_name` | `console`（控制台会话，记作 `admin`）/ `api_key`（id + 名字）/ `anonymous` |
| `ip` | socket 对端地址，**不读 `X-Forwarded-For`**——客户端能设的头不是来源证据 |
| `user_agent` | 截断到 256 字符 |
| `method` / `path` | 实际请求 |
| `target` | 路由参数（`model_id` / `key_id` / `agent_id` / `job_id` / `record_id`），例如模型 id |
| `status` / `ok` | 客户端拿到的 HTTP 状态，以及成功/失败的布尔形式 |
| `duration_ms` | 处理耗时 |
| `summary` | 白名单提取的简短摘要 |

### 不记什么

- **请求体不进库。** 中间件只看请求体前 64 KiB（`receive` 的旁路拷贝，48 MiB 上传不会被缓冲），
  而且只按**白名单**取字段：设置项（取自 `_SETTING_FIELDS`，新增字段自动包含）、`/api/keys` 的
  `name` 与 `scope`（MYS-2676：签一把 admin key 和签一把 inference key 是不同量级的事，
  「建了个 key」不足以说明）、`/api/downloads` 的 `name`/`kind`。这张表没有列出的路径**没有摘要**，
  默认是"什么都不记"而不是"全记"。
- 字段名命中 `password|secret|token|api[_-]?key|authorization|cookie|credential|...` 的，
  一律不贡献值（白名单之外的第二道防线）。
- 登录体是密码、`/api/password` 体是新密码：这两条路径的摘要是一个固定句子，连长度都不记。
- API key 只记 id 与名字，**从不记 key 本身或它的哈希**；控制台会话只记 `admin`，不记 cookie。
- 值超过 300 字符的摘要整体截断；body 前缀不是合法 JSON 时不给摘要（半个文档推不出真值，
  猜出来的值出现在审计里比没有更糟）。

`tests/test_audit.py` 的断言对象是**数据库文件本身**（含 WAL 与 SHM）：密码和刚签发的 key 的
字节串不能出现在文件里。只看列的断言会在密钥躺在 WAL 帧或索引页里时通过。

### 存储与保留

- `<数据目录>/state/audit.db`，独立 SQLite（WAL），不与推理记录同库：两者的保留期、写入频率、
  读者都不同，一份损坏的审计不该把推理历史一起带走。
- 保留期只有**天**一个维度，默认 180 天，范围 30–3650，配置项 `audit_retention_days`。
  没有条数上限："最近 1000 条变更"在安静板子上是一年、在忙的板子上是一个下午，都不是操作员
  要的策略。
- 每次写入都在同一事务里按**当前时间**裁剪。锚点是 `now` 而不是这一行自己的时间戳：一条带着
  回退时间戳写入的行否则会永远留在表里（每次后来的插入都在一个已经越过它的时间上裁剪）。
- 缩短保留期时立即裁剪（`prune_now`），不用等下一次管理操作。
- 写入失败、迁移期间被丢弃的行记在 `dropped` 里，随 `/api/audit` 一起返回。审计页读起来"完整"
  而实际有洞，比没有这一页更糟。

### 查询与导出

`GET /api/audit`：`since`、`until`、`actor`（名字模糊或 key id 精确）、`action`（"方法 + 路径前缀"，
`POST /api/models`、`POST`、`/api/settings` 都接受）、`status`（`success`/`failure`，也接受
`成功`/`失败`）、`q`、`limit`（1–500，默认 50）、`offset`。

`GET /api/audit/export`：同样的过滤条件，CSV。**UTF-8 BOM** 开头——没有它，中文 Windows 上的
Excel 会按 GBK 读，表头和摘要全是乱码。表头是中文，行是流式产出的（500 行一批），一年的审计
不会变成一个字符串。

## 6. 数据目录迁移

平台日志、worker 日志、审计库都在 `state/` 下，迁移由 `StorageManager` 一并处理：

1. `stop_everything`（复制之前）：`detach_platform_log()` 关掉文件 handler，`audit.close()`
   关掉数据库连接。复制期间没有写者，于是"校验文件数与字节数"不会因为一条迟到的记录而判成
   副本不一致，也不会有人写进一棵即将被删除的树。
2. `rebind`（切换之后）：`rebind_platform_log` 在新的 `state/logs/` 重新装上 handler，
   `audit.rebind()` 指向新库并按新读到的设置重新配置，日志源的尺寸/时间缓存清空。

不这样做，平台日志和审计会在进程剩下的生命里继续静默——这正是推理记录的 `rebind` 存在的原因，
三者同一条规则。

## 7. 边界

- **worker 日志轮转**改了 `app/core/models.py` 的一处（打开日志前调用
  `rotate_log_file`）。这是任务卡允许的唯一一处改动，除此之外 `models.py` 只被读 `log_dir`。
- agent 日志离开进程前经过该 agent 自己的 `public_log`：DSH 打印的启动 token 在这一层被抹掉，
  与 `GET /api/agents/<id>/logs` 一致。多一条不脱敏的读路径等于让那条路径的努力白做。
- 日志接口本身不写审计（见 §5）。
- mock 后端下同样工作：mock worker 也写 `worker-<id>.log`，平台日志与审计与真机无差别。
