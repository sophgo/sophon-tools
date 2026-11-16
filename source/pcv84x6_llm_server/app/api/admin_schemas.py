"""Wire models for the management API (``/api/*``), for the OpenAPI document.

Two jobs, and the second is the reason this file exists at all:

1. **Documentation.** Every ``/api`` route declares ``response_model`` (or a
   ``responses`` entry) pointing at one of these, so ``/api/openapi.json`` -- and
   therefore the offline Swagger page and the generated ``docs/admin-api.md`` --
   describes what actually comes back, with real types and an example.
2. **A contract that is checked, not trusted.** The handlers still return the
   same plain dicts they always did (``tests/test_admin_api_docs.py`` compares
   the models against real responses). Modelling was deliberately *not* made a
   runtime validator for the existing routes: FastAPI would then re-serialise
   every payload through pydantic, and a field the model forgot would silently
   disappear from the console's response. ``response_model`` is used only where
   the payload is small and fully known.

Naming: ``XxxOut`` for a response body, ``XxxBody`` for a request body. A route
whose body is a passthrough to ``/v1`` reuses ``app/schemas.py``.

**Optional-ness is honest.** A field is ``| None`` when the handler really can
return ``null`` (a worker that is not loaded has no ``mem_used_bytes``), and
required when it always returns a value -- a client that branches on ``null``
should be able to trust the model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Every model here documents a payload it does not validate, so unknown keys are
#: allowed: the document lists what the console reads, not an exhaustive set. A
#: ``state``/``stats`` payload gains fields over time (device memory, TPU usage,
#: per-model settings), and a client written against an older document must keep
#: working.
_DOC = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------------------
# errors -- the response body of every 4xx/5xx under /api
# ---------------------------------------------------------------------------
class ErrorOut(BaseModel):
    """The one error shape of the management API (MYS-2676)."""

    model_config = ConfigDict(extra="forbid")
    detail: Any = Field(
        description="中文说明。控制台直接显示它；`/v1` 的 `detail` 仍是 OpenAI "
                    "的错误对象，不受影响。",
        examples=["模型 qwen3-4b 正在加载中，请等待加载完成后再请求"],
    )
    code: str = Field(
        description="稳定的英文错误码，见「错误码」一节。脚本应据此分支，而不是解析 detail。",
        examples=["model_busy"],
    )


# ---------------------------------------------------------------------------
# auth / session
# ---------------------------------------------------------------------------
class LoginBody(BaseModel):
    password: str = Field(description="管理员口令（首次启动的默认值是 admin）",
                          examples=["admin"])


class OkOut(BaseModel):
    """``{"ok": true}`` -- the answer to a request that has nothing else to say."""

    model_config = _DOC
    ok: bool = Field(default=True, description="操作成功", examples=[True])


class SessionOut(BaseModel):
    model_config = _DOC
    authenticated: bool = Field(description="当前请求是否带着有效的管理员会话 cookie",
                               examples=[True])


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------
class KeyOut(BaseModel):
    """One API key as the console and a script see it. Never the key itself."""

    model_config = _DOC
    id: str = Field(description="key 的 id，用于吊销/删除", examples=["9f2c1ab34de5f607"])
    name: str = Field(description="创建时给的名字；审计里也显示它", examples=["laptop"])
    prefix: str = Field(description="前 10 个字符，供人辨认", examples=["sk-AbCdEfGh…"])
    created_at: float = Field(description="创建时间（epoch 秒）", examples=[1794053545.41])
    revoked: bool = Field(description="是否已吊销", examples=[False])
    scope: Literal["inference", "admin"] = Field(
        default="inference",
        description="权限范围：`inference` 只能调 `/v1`；`admin` 还能调 `/api`。"
                    "本字段之前创建的 key 一律是 `inference`。",
        examples=["admin"])
    prompt_tokens: int = Field(default=0, description="累计输入 token")
    completion_tokens: int = Field(default=0, description="累计输出 token")
    cached_tokens: int = Field(default=0, description="累计命中前缀缓存的 token")
    requests: int = Field(default=0, description="累计请求数")


class KeyListOut(BaseModel):
    model_config = _DOC
    keys: list[KeyOut] = Field(description="全部 key，含已吊销的")


class CreateKeyBody(BaseModel):
    name: str = Field(default="", description="备注名，会出现在审计和列表里",
                      examples=["ci-deploy"])
    scope: Literal["inference", "admin"] = Field(
        default="inference",
        description="权限范围。`inference`（默认）只能调 `/v1`；"
                    "`admin` 才能用 `Authorization: Bearer <key>` 调 `/api`。",
        examples=["admin"])


class CreateKeyOut(BaseModel):
    model_config = _DOC
    key: str = Field(description="**明文 key，只在这里返回一次**；服务端只存哈希",
                     examples=["sk-3Jk9xQ..."])
    meta: KeyOut = Field(description="这条 key 的元数据（同 `GET /api/keys` 的元素）")


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------
class ModelSettingsView(BaseModel):
    """What an operator configured for one model; ``null`` means "follow the default"."""

    model_config = _DOC
    idle_unload_min: int | None = Field(
        default=None, description="空闲多少分钟自动卸载；0 = 不自动卸载；null = 跟随全局设置")
    auto_load: bool | None = Field(
        default=None, description="是否按需自动加载；null = 跟随全局设置")
    mem_limit_mb: int | None = Field(
        default=None, description="该模型的内存上限（MiB）；null = 用推算的默认值")


class ModelEffective(BaseModel):
    """The values in force right now (the fallbacks already resolved)."""

    model_config = _DOC
    idle_unload_min: int = Field(description="当前生效的空闲卸载阈值（分钟），0 = 不自动卸载",
                                examples=[10])
    auto_load: bool = Field(description="当前生效的按需自动加载开关", examples=[False])
    mem_limit_bytes: int = Field(description="当前生效的内存上限（字节）",
                                 examples=[3221225472])


class ModelOut(BaseModel):
    """One model on disk, with its live state and its memory accounting."""

    model_config = _DOC
    id: str = Field(description="模型 id，即 models/ 下的目录名", examples=["qwen3.6-35b-a3b-128k"])
    display_name: str = Field(description="给人看的名字")
    path: str = Field(description="模型目录的绝对路径")
    kind: Literal["chat", "embedding", "rerank", "asr", "ocr", "ocr_vl"] = Field(
        description="模型类型，决定它能服务哪个接口", examples=["chat"])
    size_bytes: int = Field(description="目录总大小（字节）")
    bmodel_files: list[str] = Field(description="目录里的 .bmodel 文件")
    has_config: bool = Field(description="目录里是否有 tokenizer/processor 配置")
    context_length: int = Field(description="上下文长度（token）", examples=[131072])
    supports_vision: bool = Field(description="是否接受图片输入")
    hidden_size: int = Field(description="hidden size，用于推算 embedding 维度")
    supports_sampling: bool = Field(
        description="bmodel 的 lm_head 是否支持采样；false 表示只能返回 argmax")
    loaded: bool = Field(description="是否已加载并可以服务请求")
    port: int | None = Field(default=None, description="worker 的 RPC 端口（未加载时为 null）")
    pid: int | None = Field(default=None, description="worker 进程号（未加载时为 null）")
    load_error: str | None = Field(default=None, description="上次加载失败的原因")
    load_seconds: float | None = Field(default=None, description="上次加载耗时（秒）")
    loaded_at: float | None = Field(default=None, description="加载完成时间（epoch 秒）")
    operation: Literal["loading", "unloading"] | None = Field(
        default=None, description="正在进行的操作；null 表示空闲")
    operation_since: float | None = Field(default=None, description="该操作的开始时间（epoch 秒）")
    conflict: str | None = Field(
        default=None, description="有无法确认归属的同名进程占用该模型时的说明")
    adopted: bool = Field(default=False, description="是否为重启后接管的前一次运行的进程")
    downloading: bool = Field(default=False, description="是否正在下载")
    last_used_at: float | None = Field(default=None, description="最后一次被使用的时间（epoch 秒）")
    idle_unload_at: float | None = Field(
        default=None, description="按当前阈值预计的自动卸载时间（epoch 秒）；null = 不会自动卸载")
    settings: ModelSettingsView = Field(description="操作者保存的设置，原样返回，含 null")
    effective: ModelEffective = Field(description="当前生效的值")
    mem_limit_default_bytes: int = Field(description="按模型自身占用推算的默认上限（字节）")
    mem_static_bytes: int = Field(description="模型的静态占用（字节）")
    mem_used_bytes: int | None = Field(
        default=None, description="运行期实测占用（字节）；只有已加载的模型才有")
    inflight: int | None = Field(default=None, description="worker 正在处理的请求数")


class ModelListOut(BaseModel):
    model_config = _DOC
    models: list[ModelOut] = Field(description="models/ 下的全部模型，含未加载的")


class ModelSettingsBody(BaseModel):
    """``PUT /api/models/{id}/settings``.

    Every field is optional **and** nullable, and the two mean different things:
    absent leaves it alone, ``null`` resets it to the default.
    """

    model_config = _DOC
    idle_unload_min: int | None = Field(
        default=None, description="0-1440。**省略=不改**；`null`=恢复跟随全局设置",
        examples=[10])
    auto_load: bool | None = Field(
        default=None, description="**省略=不改**；`null`=恢复跟随全局设置", examples=[True])
    mem_limit_mb: int | None = Field(
        default=None, description="64-1048576。**省略=不改**；`null`=恢复推算的默认值",
        examples=[4096])


class ModelSettingsOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="模型 id")
    kind: str = Field(description="模型类型")
    settings: ModelSettingsView = Field(description="保存的设置，原样返回")
    effective: ModelEffective = Field(description="当前生效的值")
    mem_limit_default_bytes: int = Field(description="推算的默认上限（字节）")
    mem_static_bytes: int = Field(description="静态占用（字节）")
    mem_used_bytes: int | None = Field(default=None, description="运行期占用（字节）")
    limits: dict[str, int] = Field(
        description="本路由接受的取值范围，供控制台的输入框直接使用",
        examples=[{"idle_unload_min_max": 1440, "mem_limit_mb_min": 64,
                   "mem_limit_mb_max": 1048576}])
    auto_load_note: str = Field(description="给操作者的提示：自动加载大模型要几十秒")
    applied: dict | None = Field(
        default=None,
        description="新上限推送到运行中 worker 的结果；模型未加载或没有 client 时为 null")


class ModelActionOut(BaseModel):
    """``POST /api/models/{id}/load`` and ``/unload``."""

    model_config = _DOC
    ok: bool = Field(default=True, description="操作成功", examples=[True])
    model: ModelOut = Field(description="操作完成后的模型状态")


# ---------------------------------------------------------------------------
# downloads
# ---------------------------------------------------------------------------
class DownloadFileSpec(BaseModel):
    """One bmodel of a multi-file model (the OCR model is four)."""

    model_config = _DOC
    dfss: str = Field(description="dfss 路径或 URL", examples=["open@sophgo.com:/tools/x.bmodel"])
    md5: str | None = Field(default=None, description="期望的 md5")
    size_bytes: int | None = Field(default=None, description="期望的文件大小")


class DownloadBody(BaseModel):
    model_config = _DOC
    url: str = Field(description="下载源：dfss 路径（kind=dfss）或 http(s) URL（kind=url）")
    name: str = Field(description="安装成 models/<name>/；会被规范化（非法字符替换）",
                      examples=["qwen3.6-35b-a3b-128k"])
    kind: Literal["url", "dfss"] = Field(default="url", description="下载方式")
    expected_bytes: int | None = Field(default=None, description="期望大小，用于显示进度和校验")
    files: list[DownloadFileSpec] | None = Field(
        default=None,
        description="多文件模型的清单；省略时按 url 单文件下载。kind=dfss 且省略时，"
                    "会用本版本目录里登记的清单展开")


class DownloadJobOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="任务 id，用于取消", examples=["7f3a1c"])
    kind: str = Field(description="下载方式", examples=["dfss"])
    target: str = Field(description="安装目标目录")
    name: str = Field(description="模型名")
    state: Literal["pending", "running", "done", "failed", "cancelled"] = Field(
        description="任务状态", examples=["running"])
    total_bytes: int = Field(description="总字节数")
    done_bytes: int = Field(description="已完成字节数")
    percent: float = Field(description="完成百分比", examples=[42.7])
    message: str = Field(description="进度说明或失败原因")
    started_at: float = Field(description="开始时间（epoch 秒）")
    finished_at: float | None = Field(default=None, description="结束时间（epoch 秒）")
    file_count: int = Field(default=1, description="这个模型由几个文件组成")
    files_done: int = Field(default=0, description="已完成几个文件")


class StartDownloadOut(BaseModel):
    model_config = _DOC
    job: DownloadJobOut = Field(description="刚创建的任务")


class OrphanFreeSpace(BaseModel):
    """Leftover ``.part``/``.bak`` files a failed pull left behind."""

    model_config = _DOC
    files: list[str] = Field(description="可以安全删除的残留文件")
    bytes: int = Field(description="这些文件占用的字节数")
    recoverable: list[str] = Field(
        description="唯一副本的 `.bak`（安装中断），**不要删**；重启时会自动放回")


class DownloadListOut(BaseModel):
    model_config = _DOC
    jobs: list[DownloadJobOut] = Field(description="全部下载任务，最新的在前")
    orphans: OrphanFreeSpace = Field(description="磁盘上的残留文件")


class CatalogEntryOut(BaseModel):
    """One card of the download catalogue, with its update state."""

    model_config = _DOC
    id: str = Field(description="模型 id", examples=["qwen3.6-35b-a3b-128k"])
    kind: str = Field(description="模型类型", examples=["chat"])
    title: str = Field(description="卡片标题")
    dfss: str = Field(description="dfss 路径")
    size_bytes: int = Field(description="文件大小（字节）")
    context: int | None = Field(default=None, description="上下文长度")
    vision: bool | None = Field(default=None, description="是否支持视觉")
    dflag: str | None = Field(default=None, description="dfss 下载标签名，用于检测「有新版本」")
    md5: str | None = Field(default=None, description="本版本登记的 md5")
    installed: bool = Field(description="是否已安装到 models/")
    downloading: bool = Field(description="是否正在下载")
    latest_file: str | None = Field(
        default=None, description="标签当前指向的文件名；null = 离线或未取到标签")
    update_available: bool | None = Field(
        default=None, description="磁盘上的文件是否已落后于标签；null = 未知")


class CatalogOut(BaseModel):
    model_config = _DOC
    models: list[CatalogEntryOut] = Field(description="本版本支持的模型")


# ---------------------------------------------------------------------------
# settings / stats
# ---------------------------------------------------------------------------
class SettingsOut(BaseModel):
    """Every server-side setting, plus the bounds the console renders fields with."""

    model_config = _DOC
    max_concurrent_per_model: int = Field(description="每个模型同时处理的请求数上限（1-3）",
                                          examples=[2])
    max_concurrency_limit: int = Field(description="上面这个字段的硬上限", examples=[3])
    prefix_cache_entries: int = Field(description="前缀缓存条目上限")
    prefix_cache_ttl_min: int = Field(description="未被使用的前缀缓存保留分钟数")
    max_queue: int = Field(description="排队请求上限；超出的直接 429")
    prefill_exact_tail: int = Field(description="长 prompt 尾部走 decode 图的 token 数；0 = 关闭")
    require_api_key: bool = Field(description="`/v1` 是否要求 API key")
    inference_logging_enabled: bool = Field(description="是否记录推理记录")
    inference_log_retention_count: int = Field(description="推理记录保留条数上限")
    inference_log_retention_days: int = Field(description="推理记录保留天数上限")
    aux_idle_unload_min: int = Field(description="辅助模型的默认空闲卸载阈值（分钟），0 = 不卸载")
    aux_idle_unload_limit_min: int = Field(description="这个字段的硬上限", examples=[1440])
    aux_auto_load: bool = Field(description="是否默认按需自动加载辅助模型")
    audit_retention_days: int = Field(description="管理审计保留天数")
    audit_retention_days_min: int = Field(description="审计保留下限", examples=[30])
    audit_retention_days_max: int = Field(description="审计保留上限", examples=[3650])


class SettingsBody(BaseModel):
    """``POST /api/settings`` -- every field optional, out-of-range values clamped."""

    model_config = _DOC
    max_concurrent_per_model: int | None = Field(default=None, ge=1, le=3,
                                                 description="1-3，超出会被夹到边界")
    prefix_cache_entries: int | None = Field(default=None, ge=1, le=256)
    prefix_cache_max_mb: int | None = Field(
        default=None, ge=0, le=16384, deprecated=True,
        description="自 v0.6.34 起无效（总上限已删除）：接受但忽略，"
                    "每个模型的前缀缓存由该模型自己的内存上限约束")
    prefix_cache_ttl_min: int | None = Field(default=None, ge=0, le=10080)
    max_queue: int | None = Field(default=None, ge=0, le=256)
    prefill_exact_tail: int | None = Field(default=None, ge=0, le=1024)
    inference_logging_enabled: bool | None = None
    inference_log_retention_count: int | None = Field(default=None, ge=1, le=100000)
    inference_log_retention_days: int | None = Field(default=None, ge=1, le=3650)
    aux_idle_unload_min: int | None = Field(default=None, ge=0, le=1440,
                                            description="0 = 不自动卸载")
    aux_auto_load: bool | None = None
    audit_retention_days: int | None = Field(default=None, ge=30, le=3650)


class SettingsSaveOut(BaseModel):
    model_config = _DOC
    settings: SettingsOut = Field(description="保存后（夹紧之后）的设置")
    applied: dict[str, Any] = Field(
        description="每个已加载模型推送新设置的返回值；推送失败的模型带一个 `error` 键",
        examples=[{"qwen3.6-35b-a3b-128k": {"ok": True}}])


class UsageOut(BaseModel):
    model_config = _DOC
    prompt_tokens: int = Field(description="累计输入 token")
    completion_tokens: int = Field(description="累计输出 token")
    cached_tokens: int = Field(description="累计命中前缀缓存的 token")
    requests: int = Field(description="累计请求数")
    cache_hit_rate: float = Field(description="缓存命中率（0-1）", examples=[0.42])
    tps_history: list[list[float]] = Field(
        description="最近 120 个 (epoch 秒, decode tok/s) 采样，供曲线图使用")


class DeviceHeapOut(BaseModel):
    model_config = _DOC
    name: str = Field(description="堆名：`npu` 或 `vpp`", examples=["npu"])
    total_bytes: int = Field(description="该堆总大小")
    used_bytes: int = Field(description="该堆已用")
    free_bytes: int = Field(description="该堆空闲")


class DeviceMemoryOut(BaseModel):
    model_config = _DOC
    total_bytes: int = Field(description="设备内存总量（NPU + VPP 两个堆）")
    used_bytes: int = Field(description="已用")
    free_bytes: int = Field(description="空闲")
    max_block_bytes: int = Field(description="单个堆里最大的连续空闲块；单次分配不能跨堆")
    heaps: list[DeviceHeapOut] = Field(description="按堆拆开")
    source: str = Field(description="读数来源：`bm-smi` 或 `mock`", examples=["bm-smi"])


class MemoryOut(BaseModel):
    model_config = _DOC
    total_bytes: int = Field(description="系统内存总量")
    available_bytes: int = Field(description="系统可用内存")
    used_bytes: int = Field(description="系统已用内存")


class TemperatureOut(BaseModel):
    model_config = _DOC
    zone: str = Field(description="thermal zone 名", examples=["thermal_zone0"])
    name: str = Field(description="传感器名", examples=["soc_thermal"])
    celsius: float = Field(description="摄氏温度", examples=[61.5])


class DeviceOut(BaseModel):
    """One reading of the board. On the mock backend the numbers are simulated."""

    model_config = _DOC
    ts: float = Field(description="采样时间（epoch 秒）")
    cpu_percent: float = Field(description="CPU 使用率（0-100）")
    load_average: list[float] = Field(description="1/5/15 分钟负载")
    memory: MemoryOut = Field(description="系统内存")
    temperatures: list[TemperatureOut] = Field(description="温度传感器")
    device_mem: DeviceMemoryOut = Field(description="NPU + VPP 设备内存")


class VppReserveOut(BaseModel):
    model_config = _DOC
    acquired: bool = Field(description="是否已占住多媒体保留块")
    bytes: int = Field(description="保留的字节数")
    reason: str | None = Field(default=None, description="没占住时的原因")


class StatsOut(BaseModel):
    """Everything the overview page polls, in one request."""

    model_config = _DOC
    device: DeviceOut = Field(description="设备读数")
    vpp_reserve: VppReserveOut | None = Field(
        default=None, description="服务为多媒体栈预留的 VPP 块（会计入 device_mem 的已用）")
    usage: UsageOut = Field(description="累计用量")
    models: list[ModelOut] = Field(description="每个模型的完整状态（同 GET /api/models）")
    max_loaded_models: int = Field(description="同时加载的对话模型上限；0 = 不限")
    kv_cache: dict[str, Any] = Field(description="每个已加载模型的前缀缓存用量，按模型 id")
    workers: dict[str, Any] = Field(description="每个已加载 worker 自己报告的统计，按模型 id")
    disk: dict[str, Any] = Field(description="models/ 的磁盘占用")


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
class StorageOut(BaseModel):
    model_config = _DOC
    data_dir: str = Field(description="当前数据目录")
    fs_total_bytes: int = Field(description="所在文件系统总大小")
    fs_used_bytes: int = Field(description="所在文件系统已用")
    fs_free_bytes: int = Field(description="所在文件系统可用")
    dir_bytes: int = Field(description="数据目录占用（等于 parts 之和）")
    parts: dict[str, int] = Field(
        description="按子目录拆开：models / state / agents / downloads / apps / inbox",
        examples=[{"models": 20681019392, "state": 193304, "agents": 0,
                   "downloads": 0, "apps": 0, "inbox": 0}])


class MoveBody(BaseModel):
    model_config = _DOC
    path: str = Field(description="目标数据目录的**绝对路径**，必须为空或不存在",
                      examples=["/data/cv84x6"])


class MoveStartedOut(BaseModel):
    model_config = _DOC
    job: str = Field(description="搬迁任务 id；进度用 GET /api/storage/move 查",
                     examples=["5c1e0a"])


class MoveJobOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="任务 id；空闲时为 \"\"")
    state: Literal["idle", "checking", "copying", "verifying", "switching",
                   "done", "failed"] = Field(description="搬到哪一步了", examples=["copying"])
    copied_bytes: int = Field(description="已复制字节数")
    total_bytes: int = Field(description="需要复制的总字节数")
    message: str = Field(description="进度说明或失败原因")
    old: str = Field(description="原数据目录")
    new: str = Field(description="目标数据目录；空闲时为 \"\"")
    started_at: float = Field(description="开始时间（epoch 秒）")
    finished_at: float | None = Field(default=None, description="结束时间（epoch 秒）")


# ---------------------------------------------------------------------------
# logs / audit
# ---------------------------------------------------------------------------
class LogSourceOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="日志源 id，用作 GET /api/logs/{source} 的路径参数",
                    examples=["platform"])
    label: str = Field(description="给人看的名字", examples=["平台日志"])
    size_bytes: int = Field(description="当前大小；从未写过是 0")
    updated_at: float | None = Field(default=None, description="最后写入时间（epoch 秒）")
    updated_at_iso: str | None = Field(default=None, description="同上，本地时区 ISO8601")
    kind: Literal["platform", "worker", "agent"] = Field(description="日志类别",
                                                         examples=["platform"])


class LogSourcesOut(BaseModel):
    model_config = _DOC
    sources: list[LogSourceOut] = Field(description="全部日志源，含空的")


class LogLineOut(BaseModel):
    model_config = _DOC
    ts: str | None = Field(default=None, description="行首时间戳，原样保留")
    level: str | None = Field(default=None, description="日志级别", examples=["INFO"])
    logger: str | None = Field(default=None, description="logger 名")
    message: str = Field(description="正文（敏感字段已打码）")


class LogPageOut(BaseModel):
    model_config = _DOC
    source: str = Field(description="日志源 id")
    label: str = Field(description="日志源名字")
    lines: list[LogLineOut] = Field(description="这一页的行，**从旧到新**")
    cursor: str | None = Field(
        default=None, description="取下一页（更旧的一页）时原样传回 `cursor`；null = 没有更旧的了")
    has_more: bool = Field(description="是否还有更旧的行")
    limit: int = Field(description="本页最多多少行")
    size_bytes: int = Field(description="日志源当前大小")


class AuditRowOut(BaseModel):
    model_config = _DOC
    id: int = Field(description="自增主键，翻页的稳定排序依据")
    ts: float = Field(description="操作时间（epoch 秒）")
    ts_iso: str = Field(description="同上，本地时区 ISO8601")
    actor_type: Literal["console", "api_key", "anonymous"] = Field(
        description="操作者类型", examples=["api_key"])
    actor_id: str | None = Field(default=None, description="API key 的 id；控制台会话为 null")
    actor_name: str | None = Field(default=None, description="API key 的名字，或 admin")
    ip: str | None = Field(default=None, description="TCP 对端地址（不信任 X-Forwarded-For）")
    user_agent: str | None = Field(default=None, description="User-Agent，截断到 256 字符")
    method: str = Field(description="HTTP 方法", examples=["POST"])
    path: str = Field(description="请求路径", examples=["/api/settings"])
    target: str | None = Field(default=None, description="路径参数里的目标，如模型 id")
    status: int = Field(description="HTTP 状态码", examples=[200])
    ok: bool = Field(description="状态码是否 < 400")
    result: Literal["success", "failure"] = Field(description="`ok` 的单词形式")
    duration_ms: float = Field(description="耗时（毫秒）")
    summary: str | None = Field(default=None, description="白名单字段拼出的摘要，绝不含口令/密钥")


class AuditPageOut(BaseModel):
    model_config = _DOC
    items: list[AuditRowOut] = Field(description="这一页，最新的在前")
    total: int = Field(description="符合条件的总行数")
    limit: int = Field(description="本页最多多少行")
    offset: int = Field(description="本页起点")
    retention_days: int = Field(description="当前保留天数")
    dropped: int = Field(description="非零表示审计链有缺口（搬迁或写入失败丢了行）")
    last_error: str | None = Field(default=None, description="最近一次写入失败的原因")


# ---------------------------------------------------------------------------
# inference records
# ---------------------------------------------------------------------------
class RecordSummaryOut(BaseModel):
    """One row of the records list: no conversation text, which is in the detail."""

    model_config = _DOC
    id: str = Field(description="记录 id")
    started_at: float = Field(description="开始时间（epoch 秒）")
    finished_at: float | None = Field(default=None, description="结束时间（epoch 秒）")
    source: str = Field(description="请求路径，区分控制台与 API 流量")
    model: str = Field(description="模型 id")
    actor_type: str = Field(description="操作者类型")
    actor_name: str | None = Field(default=None, description="操作者名字")
    status: str = Field(description="ok / error / cancelled", examples=["ok"])
    finish_reason: str | None = Field(default=None, description="stop / length / tool_calls")
    prompt_tokens: int | None = Field(default=None, description="输入 token")
    completion_tokens: int | None = Field(default=None, description="输出 token")
    cached_tokens: int | None = Field(default=None, description="命中缓存的 token")
    first_token_latency_s: float | None = Field(default=None, description="首 token 延迟（秒）")
    decode_tps: float | None = Field(default=None, description="decode 速度（tok/s）")


class RecordListOut(BaseModel):
    model_config = _DOC
    items: list[RecordSummaryOut] = Field(description="这一页，最新的在前")
    total: int = Field(description="总条数")
    limit: int = Field(description="本页最多多少条")
    offset: int = Field(description="本页起点")


class RecordStatusOut(BaseModel):
    model_config = _DOC
    path: str = Field(description="记录库文件路径")
    enabled: bool = Field(description="是否在记录")
    total: int = Field(description="库里有多少条")
    bytes: int | None = Field(default=None, description="库文件占用的字节数")
    schema_version: int = Field(description="记录库结构版本")
    retention_count: int = Field(description="保留条数上限")
    retention_days: int = Field(description="保留天数上限")
    readable: bool = Field(description="库是否可读；false 时列表会 500，服务其余部分照常")
    moving: bool = Field(description="是否正在随数据目录迁移（此时记录暂停）")
    last_error: str | None = Field(default=None, description="最近一次写入失败的原因")
    last_error_at: float | None = Field(default=None, description="最近一次失败的时间")


class ClearRecordsOut(BaseModel):
    model_config = _DOC
    ok: bool = Field(default=True, description="成功", examples=[True])
    deleted: int = Field(description="删掉了多少条", examples=[128])


# ---------------------------------------------------------------------------
# chat playground
# ---------------------------------------------------------------------------
class ChatBody(BaseModel):
    """The console's own chat request (``/api/chat`` and ``/api/chat/stream``)."""

    model_config = _DOC
    model: str = Field(description="模型 id", examples=["qwen3.6-35b-a3b-128k"])
    prompt: str = Field(default="", description="单轮文本；给了 `messages` 时忽略")
    max_tokens: int = Field(default=256, description="最多生成多少 token")
    temperature: float = Field(default=0.8, description="采样温度")
    images: list[str] = Field(default_factory=list,
                              description="base64 图片，按顺序放在文本之前")
    enable_thinking: bool = Field(default=False, description="是否打开 Qwen 的思考模式")
    messages: list[dict] | None = Field(
        default=None,
        description="完整对话（OpenAI 消息形状，图片用 data URL）；给了它就替换 prompt/images")


class ChatOut(BaseModel):
    model_config = _DOC
    text: str = Field(description="模型输出（思考内容已剥离）")
    prompt_tokens: int = Field(description="输入 token")
    completion_tokens: int = Field(description="输出 token")
    cached_tokens: int = Field(description="命中前缀缓存的 token")
    first_token_latency_s: float | None = Field(default=None, description="首 token 延迟（秒）")
    decode_tps: float | None = Field(default=None, description="decode 速度（tok/s）")
    finish_reason: str | None = Field(default=None, description="stop / length")


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------
class AgentWebOut(BaseModel):
    model_config = _DOC
    username: str = Field(description="agent 自带界面的用户名")
    password: str = Field(description="agent 自带界面的口令（安装时生成）")


class AgentModelChoice(BaseModel):
    model_config = _DOC
    id: str = Field(description="模型 id")
    context: int = Field(description="上下文长度")
    vision: bool = Field(description="是否支持视觉")


class AgentOut(BaseModel):
    """One agent's card: install/run state, its ports, and its own UI's login."""

    model_config = _DOC
    id: str = Field(description="agent id", examples=["opencode"])
    name: str = Field(description="显示名")
    version: str = Field(description="已安装的版本；未安装为空")
    latest_version: str = Field(description="本版本支持的最新版本")
    default_port: int = Field(description="默认端口", examples=[14096])
    port: int = Field(description="当前端口")
    installed: bool = Field(description="是否已安装")
    status: Literal["running", "stopped", "failed", "not_installed"] = Field(
        description="四态摘要", examples=["running"])
    operation: str | None = Field(default=None, description="正在进行的操作")
    operation_since: float | None = Field(default=None, description="该操作的开始时间")
    busy: bool = Field(description="是否有操作在进行")
    operation_label: str = Field(description="该操作的中文名")
    running: bool = Field(description="是否健康运行（启动中不算）")
    pid: int | None = Field(default=None, description="进程号")
    health: bool = Field(description="本次健康检查是否通过")
    adopted: bool = Field(description="是否为重启后接管的进程")
    orphan_pid: int | None = Field(default=None, description="占着端口但不健康的进程号")
    rss_bytes: int = Field(description="常驻内存（字节）")
    disk_bytes: int = Field(description="安装占用（字节）")
    autostart: bool = Field(description="是否开机自启")
    default_model: str = Field(description="配置里给它用的模型")
    thinking: bool = Field(description="是否给它打开思考模式")
    embeddable: bool = Field(description="能否嵌在控制台里显示")
    proxied: bool = Field(description="是否由本服务反代它的界面")
    card_note: str = Field(description="卡片上的补充说明")
    memory_floor_bytes: int = Field(description="启动它至少需要的内存")
    web_url: str = Field(description="它的界面地址；未安装为空")
    web: AgentWebOut = Field(description="它的界面的登录凭据")
    models: list[AgentModelChoice] = Field(description="可以配给它的模型")
    child_ports: list[int] = Field(description="它自己再开出来的端口")
    started_at: float | None = Field(default=None, description="启动时间（epoch 秒）")
    uptime_s: float | None = Field(default=None, description="已运行秒数")
    exit_code: int | None = Field(default=None, description="上次退出码")
    last_error: str | None = Field(default=None, description="最近一次错误")
    job: DownloadJobOut | None = Field(default=None, description="安装任务的进度")


class AgentListOut(BaseModel):
    model_config = _DOC
    agents: list[AgentOut] = Field(description="三个内置 agent 的状态")


class AgentJobOut(BaseModel):
    model_config = _DOC
    job: DownloadJobOut | None = Field(default=None, description="安装任务；没有任务时 null")


class AgentPatchBody(BaseModel):
    """``PATCH /api/agents/{id}`` -- only what the console exposes."""

    model_config = _DOC
    port: int | None = Field(default=None, description="新端口；改运行中的 agent 会重启它")
    autostart: bool | None = Field(default=None, description="是否开机自启")
    default_model: str | None = Field(default=None, description="配给它的模型 id")
    thinking: bool | None = Field(default=None, description="是否打开思考模式")


class AgentLogsOut(BaseModel):
    model_config = _DOC
    log: str = Field(description="日志尾部文本；没有日志时为空串")


# ---------------------------------------------------------------------------
# misc responses reused by several routes
# ---------------------------------------------------------------------------
class OkDeletedOut(BaseModel):
    model_config = _DOC
    ok: bool = Field(default=True, description="成功")
    deleted: int = Field(description="删掉了多少条/多少项")


class IdJobOut(BaseModel):
    model_config = _DOC
    ok: bool = Field(default=True, description="成功")
    job: dict[str, Any] = Field(description="任务的关键字段（文档数、切片数、所用模型）")
