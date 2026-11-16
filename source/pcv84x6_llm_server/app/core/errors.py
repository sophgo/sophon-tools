"""The management API's error contract: one body shape, one code per situation.

Every refusal under ``/api/`` answers with

    {"detail": "<中文说明>", "code": "<stable english code>"}

``detail`` is unchanged -- the console prints it verbatim (``web/src/api.ts``
reads ``detail`` when it is a string), so a script and the UI read the same
sentence. ``code`` is the machine-readable half: the console's Chinese wording
may be improved at any time, but a script that branches on ``code`` keeps
working. The table below is the whole vocabulary, and ``docs/admin-api.md`` is
generated from it -- adding a code without documenting it is a test failure.

Why one handler rather than an explicit code at each of the forty-odd
``raise HTTPException`` sites: a trail of codes that depends on every handler
remembering to pass one has holes in it, and the holes are exactly the sites
nobody revisited. So the mapping is *derived* -- from the status, plus the
exception class where the class already carries the meaning (``ModelBusy``,
``DeviceMemoryError``) -- and only the handful of cases the derivation cannot
tell apart set a code explicitly with :func:`api_error`.

``/v1`` is deliberately untouched: those bodies mirror OpenAI's error shape,
existing SDKs parse them, and ``mcp_api`` speaks JSON-RPC codes. The handlers
here rewrite a response only when the request path starts with ``/api/``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


@dataclass(frozen=True)
class ErrorCode:
    """One row of the published table."""

    code: str
    status: int
    description: str


#: The complete vocabulary, in the order ``docs/admin-api.md`` prints it.
#: Several rows may share a status: ``409`` is where this service reports every
#: "the state of the world says no" refusal, and which *kind* of no it is matters
#: to a script (retry in a moment vs unload something first vs change a setting).
ERROR_CODES: tuple[ErrorCode, ...] = (
    ErrorCode("validation_error", 422,
              "请求体或查询参数不符合接口定义（字段类型、取值范围、必填项）"),
    ErrorCode("bad_request", 400, "请求本身不合法：业务校验未通过，说明见 detail"),
    ErrorCode("unauthorized", 401, "缺少凭据，或会话 cookie / admin key 无效、已过期"),
    ErrorCode("forbidden_scope", 403,
              "凭据有效但权限范围不足：inference key 不能调用 /api，需要 admin key；"
              "或 cookie 请求来自别的站点"),
    ErrorCode("not_found", 404, "目标资源不存在（模型、key、记录、日志源、知识库、agent 等）"),
    ErrorCode("method_not_allowed", 405, "该路径不支持此 HTTP 方法"),
    ErrorCode("conflict", 409, "与当前状态冲突，但无法归入下面更具体的码"),
    ErrorCode("model_busy", 409, "模型正在加载、卸载或下载，请等待当前操作结束后重试"),
    ErrorCode("model_not_loaded", 409, "模型未加载（或上次加载失败），请先加载"),
    ErrorCode("model_conflict", 409,
              "已有一个无法确认归属的同名模型进程占用该模型，需人工确认"),
    ErrorCode("load_failed", 409, "加载失败，原因见 detail 与 worker 日志"),
    ErrorCode("device_memory_insufficient", 409,
              "NPU / VPP 设备内存不足，或单块连续内存放不下，请先卸载其他模型"),
    ErrorCode("system_memory_insufficient", 409,
              "系统内存不足，请先停止占用内存的进程（如 agent）"),
    ErrorCode("model_mem_limit_exceeded", 409,
              "模型静态占用超过它自己的内存上限，请调大该模型的上限"),
    ErrorCode("model_kind_mismatch", 400,
              "模型类型与接口不符（例如拿 embedding 模型调用对话接口）"),
    ErrorCode("queue_full", 429, "模型请求队列已满，响应头 Retry-After 给出建议间隔"),
    ErrorCode("storage_busy", 409, "已有数据目录搬迁任务在进行"),
    ErrorCode("download_busy", 409, "该模型正在下载中，请等待完成或先取消"),
    ErrorCode("payload_too_large", 413, "请求体超过上限"),
    ErrorCode("unsupported_media_type", 415, "上传的文件类型或音频容器无法解析"),
    ErrorCode("client_closed", 499, "客户端在服务端完成前断开了连接"),
    ErrorCode("internal_error", 500, "服务内部错误（磁盘、数据库等），说明见 detail"),
    ErrorCode("service_unavailable", 503, "依赖的子系统暂不可用（审计库不可读等）"),
    ErrorCode("model_unavailable", 503,
              "模型进程已退出：它加载过，现在没了，重新加载即可恢复"),
)

#: status -> the code used when nothing more specific applies. A status outside
#: this table still gets a code: ``error_<status>``, which keeps the contract
#: ("there is always a code") true even for a status nobody anticipated.
DEFAULT_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden_scope",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "queue_full",
    499: "client_closed",
    500: "internal_error",
    503: "service_unavailable",
}

#: The documented code for each status, for the generated document's header.
CODE_STATUS: dict[str, int] = {row.code: row.status for row in ERROR_CODES}
CODE_DESCRIPTION: dict[str, str] = {row.code: row.description for row in ERROR_CODES}


def code_for_status(status: int) -> str:
    """The code a bare status means (``error_<status>`` past the table)."""
    return DEFAULT_CODES.get(status, f"error_{status}")


def api_error(status_code: int, code: str, detail: str, *,
              headers: dict[str, str] | None = None) -> HTTPException:
    """An ``HTTPException`` carrying an explicit ``code``.

    An ``HTTPException`` subclass would be cleaner, but handlers already raise
    the plain class everywhere and the handler below only needs to read the
    attribute -- so this sets it and returns the exception for ``raise
    api_error(...)``. ``code`` must be in :data:`ERROR_CODES`; that is checked
    here rather than only in the test suite, because a typo would otherwise ship
    as a code no client can find in the document.
    """
    if code not in CODE_STATUS:
        raise ValueError(f"unknown error code {code!r}; add it to ERROR_CODES first")
    exc = HTTPException(status_code=status_code, detail=detail, headers=headers)
    exc.code = code  # type: ignore[attr-defined]
    return exc


def jsonable(obj):
    """pydantic's error list can carry non-JSON values (``ctx`` exceptions)."""
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(obj)


def error_body(detail, code: str) -> dict:
    return {"detail": detail, "code": code}


def is_api_path(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def is_openai_path(request: Request) -> bool:
    return request.url.path.startswith("/v1/")


#: OpenAI's ``error.type`` for a status. The SDKs map status to their own
#: exception classes and read ``error.message`` for the text; ``type`` is what a
#: client that branches on the body (not the status) looks at.
_OPENAI_TYPES = {400: "invalid_request_error", 401: "authentication_error",
                 403: "permission_error", 404: "not_found_error", 409: "invalid_request_error",
                 413: "invalid_request_error", 415: "invalid_request_error",
                 422: "invalid_request_error", 429: "rate_limit_error"}


def openai_error_body(detail, status: int) -> dict:
    """``/v1`` errors in OpenAI's shape: a top-level ``error`` object.

    Every OpenAI SDK reads ``body["error"]["message"]``; a body that only had
    FastAPI's ``{"detail": ...}`` surfaced to callers as an opaque string of the
    whole JSON (found in the v0.6.29 E2E run, MYS-2682). ``detail`` is kept
    alongside, unchanged, so a caller that already read it keeps working.
    """
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        err = {"param": None, "code": None, **detail["error"]}
    else:
        err = {"message": detail if isinstance(detail, str) else str(detail),
               "type": _OPENAI_TYPES.get(status, "server_error" if status >= 500 else "invalid_request_error"),
               "param": None,
               "code": classify(detail, status)}
    return {"error": err, "detail": detail}


def _code_for_exception(exc: StarletteHTTPException) -> str:
    """The code a raised ``HTTPException`` means (kept for callers that want it)."""
    explicit = getattr(exc, "code", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    return classify(exc.detail, exc.status_code)


#: What a *state* refusal at one status actually means, decided by the message the
#: manager raised. This is the only place a Chinese sentence is matched, and it is
#: deliberately narrow: four phrases that come from exactly one ``raise`` each
#: (``app/core/models.py``), so a reworded message makes the code fall back to the
#: generic one for its status -- degraded, never wrong. The alternative, threading
#: a code through every ``RuntimeError`` in the manager, would have meant touching
#: the loading path this task is forbidden to change behaviour of.
_STATE_CODES: tuple[tuple[str, str], ...] = (
    ("设备内存不足", "device_memory_insufficient"),
    # A separate phrase from the line above on purpose: the two refusals mean
    # different things to an operator. "设备内存不足" is "this model does not
    # fit"; this one is "it fits, but loading it would leave the NPU heap too
    # empty to stay alive" (MYS-2703). Same status, different remedy.
    ("NPU 显存余量不足", "device_memory_insufficient"),
    ("系统可用内存仅", "system_memory_insufficient"),
    ("超过本模型内存上限", "model_mem_limit_exceeded"),
    ("正在加载", "model_busy"),
    ("正在卸载", "model_busy"),
    ("正在下载", "model_busy"),
    ("在下载中", "download_busy"),
    ("同时在线的大语言模型上限", "model_busy"),
    ("无法安全判断哪个持有 NPU 内存", "model_conflict"),
    ("已在搬迁任务", "storage_busy"),
    ("已有搬迁任务", "storage_busy"),
)

#: 503 bodies that mean "the worker died" rather than "the log store is unreadable".
_UNAVAILABLE_MARKERS = ("模型进程", "worker", "重新加载", "模型未就绪")


def classify(detail, status: int) -> str:
    """The ``code`` for a handler's ``detail`` at this status.

    Used where the status alone cannot say which of several situations it is. A
    non-string ``detail`` (a ``/v1``-shaped error object that reached here) gets
    the status's default: guessing from a dict would be invention.
    """
    text = detail if isinstance(detail, str) else ""
    if status == 409:
        for needle, code in _STATE_CODES:
            if needle in text:
                return code
    if status == 503 and any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return "model_unavailable"
    return code_for_status(status)


# -- validation --------------------------------------------------------------
#: FastAPI's own field messages are English and shaped for a developer reading
#: the OpenAPI page, e.g. "Input should be a valid integer". Each is mapped to a
#: Chinese phrase; a message not in this table passes through verbatim, which is
#: the honest outcome for a constraint pydantic phrased in a way we have not
#: seen yet -- inventing a translation would be worse than the original.
_FIELD_MESSAGES: tuple[tuple[str, str], ...] = (
    ("Field required", "是必填项"),
    ("Input should be a valid integer", "必须是整数"),
    ("Input should be a valid number", "必须是数字"),
    ("Input should be a valid string", "必须是字符串"),
    ("Input should be a valid boolean", "必须是布尔值"),
    ("Input should be a valid list", "必须是数组"),
    ("Input should be a valid dictionary", "必须是对象"),
    ("Input should be '", "取值不在允许范围内"),
    ("String should have at least", "长度不足"),
    ("String should have at most", "长度超出上限"),
    ("Input should be greater than or equal to", "小于允许的最小值"),
    ("Input should be less than or equal to", "大于允许的最大值"),
    ("Input should be greater than", "必须大于给定值"),
    ("Input should be less than", "必须小于给定值"),
    ("Extra inputs are not permitted", "包含未定义的字段"),
)


def _chinese_field_error(error: dict) -> str:
    location = [str(part) for part in error.get("loc") or ()]
    # loc[0] is "body"/"query"/"path"; the rest names the field.
    where = ".".join(location[1:]) or (location[0] if location else "请求")
    message = str(error.get("msg") or "").strip()
    for needle, phrase in _FIELD_MESSAGES:
        if needle in message:
            if needle == "Input should be '":
                allowed = message.split("'")[1] if message.count("'") >= 2 else ""
                return f"{where} 取值不在允许范围内" + (f"（可选：{allowed}）" if allowed else "")
            return f"{where} {phrase}"
    return f"{where} {message}" if message else where


def validation_detail(exc: RequestValidationError) -> str:
    """One Chinese sentence from pydantic's error list.

    The first error is quoted, and a count of the rest is appended: a 422 for a
    settings body usually has one real mistake, and a message that concatenates
    five field errors is one an operator skims past. Everything is in the
    response's ``detail``, so nothing is lost -- ``errors`` is not part of the
    documented contract, and the console shows ``detail`` whole.
    """
    errors = list(exc.errors() or ())
    if not errors:
        return "请求参数校验失败"
    first = _chinese_field_error(errors[0])
    if len(errors) == 1:
        return f"请求参数校验失败：{first}"
    return f"请求参数校验失败：{first}（另有 {len(errors) - 1} 处问题）"


# -- handlers ----------------------------------------------------------------
async def _api_http_error(request: Request, exc: StarletteHTTPException):
    """``/api/*`` HTTPException -> the documented body (other paths untouched).

    Returning ``None`` is not an option -- a handler must answer -- so ``/v1``
    and every other path get the stock ``http_exception_handler``'s output,
    reproduced here. That keeps this module the only place a status is turned
    into a body, instead of two handlers racing to be the one that answers.
    """
    if is_openai_path(request):
        return JSONResponse(openai_error_body(exc.detail, exc.status_code),
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if not is_api_path(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))
    code = getattr(exc, "code", None)
    if not (isinstance(code, str) and code):
        code = classify(exc.detail, exc.status_code)
    return JSONResponse(error_body(exc.detail, code),
                        status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


async def _api_validation_error(request: Request, exc: RequestValidationError):
    if is_openai_path(request):
        body = openai_error_body(validation_detail(exc), 422)
        body["detail"] = exc.errors()
        return JSONResponse(jsonable(body), status_code=422)
    if not is_api_path(request):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return JSONResponse(error_body(validation_detail(exc), "validation_error"),
                        status_code=422)


async def _api_unhandled_error(request: Request, exc: Exception):
    """A 500 from an unhandled exception, in the same shape for ``/api``."""
    import logging

    import asyncio

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        # A worker that does not answer within its call budget: on this chip
        # that is what a wedged TPU looks like (v0.6.29 E2E, MYS-2682). It is a
        # 503 the caller can act on -- retry later, or reload the model -- not a
        # bare 500 with an empty message.
        logging.getLogger("cv84x6").warning("worker timed out on %s", request.url.path)
        detail = ("模型进程在规定时间内没有响应（可能正忙或已卡住）；请稍后重试，"
                  "若持续出现请在控制台查看该模型的日志并重新加载")
        if is_openai_path(request):
            return JSONResponse(openai_error_body(detail, 503), status_code=503)
        if is_api_path(request):
            return JSONResponse(error_body(detail, "model_unavailable"), status_code=503)
        return JSONResponse({"detail": detail}, status_code=503)
    logging.getLogger("cv84x6").exception("unhandled error on %s", request.url.path)
    if is_openai_path(request):
        return JSONResponse(openai_error_body(str(exc), 500), status_code=500)
    if not is_api_path(request):
        return JSONResponse({"detail": str(exc)}, status_code=500)
    return JSONResponse(error_body(str(exc), "internal_error"), status_code=500)


def install_error_handlers(app) -> None:
    """Register the three handlers on ``app`` (called from ``create_app``)."""
    app.add_exception_handler(StarletteHTTPException, _api_http_error)
    app.add_exception_handler(RequestValidationError, _api_validation_error)
    app.add_exception_handler(Exception, _api_unhandled_error)
