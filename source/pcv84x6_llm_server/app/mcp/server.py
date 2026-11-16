"""MCP over Streamable HTTP: a JSON-RPC 2.0 dispatcher and nothing else.

The protocol version this serves is ``2025-06-18``; a client that asks for
``2025-03-26`` (or anything else it knows) is answered with its own version,
which is what the spec requires -- the two differ in ways that do not touch this
surface.

**Why not the ``mcp`` Python SDK.** The release vendors a small, pinned wheel set
built for the board's Python 3.10 and its aarch64 libc (``scripts/package.sh``).
The SDK pulls in ``sse-starlette``, ``httpx-sse``, ``python-multipart`` and their
transitive pins, and a resolver disagreement there is a release that will not
import on the device. What this service actually needs is five methods over
``POST`` returning ``application/json`` -- roughly a hundred lines -- so that is
what it implements, and ``tests/test_mcp_protocol.py`` uses the real SDK as its
client to prove the result is not merely self-consistent.

**Stateless.** No ``Mcp-Session-Id`` is issued: the spec allows a server to omit
it, and this service has nothing per-session to keep -- every tool call is
authenticated by its own key. ``GET /mcp`` answers 405 because this server has no
server-initiated stream to offer; the three clients measured for MYS-2611
(opencode 1.19.4, PicoClaw 0.3.1, OpenClaw 2026.10.7) all treat that as "no
stream" and carry on, which is recorded in ``docs/mcp.md``.

**Origin is checked, even when the API key is not.** A browser page can POST to
``http://127.0.0.1:8000/mcp`` from any origin, and with ``require_api_key`` off
-- the console's default for a trusted single-board deployment -- that request
would be authenticated by nothing at all. The spec's protection is the ``Origin``
header: a request that carries one and is not this service's own origin is
refused with 403 before the body is read. That is what keeps a malicious page on
the operator's laptop from driving the board's NPU and, through
``kb_add_document``, from reading files out of the agents' workspaces.

**Errors.** Two layers, kept apart on purpose:

* a *protocol* error (bad JSON, unknown method, malformed params) is a JSON-RPC
  ``error`` object, and the model cannot act on it;
* a *tool* failure (no such knowledge base, path refused) is a normal result with
  ``isError: true`` and a message the model can read and retry from.

Error text never carries an exception class name or a server path: a client that
learns the shapes of this box's internals has learned something no tool call
needs, and the detail is in the service log where the operator can read it.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from ..core.auth import require_api_key
from . import tools as mcp_tools

logger = logging.getLogger(__name__)

router = APIRouter()

#: The version this implementation speaks, and the one it falls back to when a
#: client asks for something unrecognised.
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26")

SERVER_NAME = "cv84x6-llm-server"

# JSON-RPC 2.0's own codes, plus the two the MCP lifecycle needs.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: Methods a client may call. ``notifications/*`` are one-way: answered with 202
#: and no body (the spec's "the server MUST return 202 Accepted with no body").
NOTIFICATIONS = frozenset({"notifications/initialized", "notifications/cancelled"})

#: Hosts an ``Origin`` header may name. Loopback only: this endpoint is meant for
#: the agents on the board itself, and every one of them dials
#: ``http://127.0.0.1:<port>/mcp``.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Extra origins an operator may declare, ``;``-separated (``app/mcp/paths`` uses
#: ``:`` for a path list, and a colon would split ``http://`` in two).
ORIGINS_ENV = "CV84X6_MCP_ORIGINS"


class RpcError(Exception):
    """A JSON-RPC error, as opposed to a tool that failed."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _error(rid, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _result(rid, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _negotiate(params: dict) -> str:
    """The version to answer with: the client's if supported, else ours.

    Returning the client's own version when it is one this server also speaks is
    what makes a 2025-03-26 client work; the fallback is for a client asking for
    something neither of us has heard of, which the spec says to answer with the
    newest version the server supports.
    """
    asked = str((params or {}).get("protocolVersion") or "")
    return asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION


async def _dispatch(request: Request, message: dict, key_name: str) -> dict | None:
    """One JSON-RPC message in, one response object out (or None for no reply)."""
    if not isinstance(message, dict):
        raise RpcError(INVALID_REQUEST, "请求必须是 JSON 对象")
    if message.get("jsonrpc") != "2.0":
        raise RpcError(INVALID_REQUEST, "jsonrpc 必须是 \"2.0\"")
    method = message.get("method")
    rid = message.get("id")
    params = message.get("params")

    if method is None and rid is not None:
        # A *response* from the client: ``{"jsonrpc":"2.0","id":…,"result"|"error"}``.
        # This server never sends a request, so there is nothing to match it to,
        # but per the spec it is a valid message and the answer is 202 Accepted
        # with no body -- not a -32600, which would tell a client its perfectly
        # legal message was malformed.
        logger.debug("ignoring a client response for id %r", rid)
        return None
    if not isinstance(method, str) or not method:
        raise RpcError(INVALID_REQUEST, "缺少 method")
    if rid is None and method in NOTIFICATIONS:
        return None
    if rid is None:
        # A request without an id is a notification this server does not
        # implement; per JSON-RPC there is nothing to reply to.
        logger.debug("ignoring unknown MCP notification %s", method)
        return None
    if method in NOTIFICATIONS:
        return None
    if params is not None and not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params 必须是对象")

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": _negotiate(params or {}),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": _version()},
            # No ``instructions`` key: nothing here needs saying before the
            # model reads the tool descriptions, which already say when to call
            # what.
        })
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": mcp_tools.tool_specs()})
    if method == "tools/call":
        name = (params or {}).get("name")
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "tools/call 需要 name")
        arguments = (params or {}).get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments 必须是对象")
        try:
            return _result(rid, await mcp_tools.call_tool(
                request, name, arguments, key_name=key_name))
        except KeyError:
            # An unknown tool is a protocol-level "no such method" per the spec's
            # own treatment of tools/call, not an isError result: there is no
            # tool to have failed.
            raise RpcError(INVALID_PARAMS, f"没有名为 {name} 的工具") from None
    raise RpcError(METHOD_NOT_FOUND, f"不支持的方法：{method}")


def _version() -> str:
    from .. import __version__

    return __version__


def _key_name(request: Request, key_id: str) -> str:
    """The calling key's name, for the inference record's actor."""
    store = getattr(request.app.state, "store", None)
    if not key_id or store is None:
        return ""
    for key in getattr(store, "keys", []):
        if key.id == key_id:
            return key.name or ""
    return ""


def _has_no_reply(payload) -> bool:
    """Whether this message is one the spec says to answer with 202 and no body.

    Two shapes qualify: a **notification** (a ``method`` and no ``id``) and a
    **response from the client** (an ``id`` and no ``method``). Neither is a
    request, so even a malformed one of them gets the 202 rather than a JSON-RPC
    error nobody would match to anything.

    An object with *neither* -- ``{"jsonrpc":"2.0"}`` -- is neither shape: it is a
    malformed request, and a client that sent it is waiting for an explanation.
    """
    if not isinstance(payload, dict):
        return False
    has_method = payload.get("method") is not None
    has_id = payload.get("id") is not None
    return (has_method and not has_id) or (has_id and not has_method)


def _origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """Whether a request's ``Origin`` may drive this endpoint.

    A missing ``Origin`` is allowed: non-browser clients (all three bundled
    agents, the stdio bridge, curl, the ``mcp`` SDK) do not send one, and the
    spec only asks the server to validate the header when it is present.

    When it is present, the rule is "loopback, or this service's own host". The
    first covers the three agents, which dial ``127.0.0.1``; the second covers an
    operator who reaches the console through the board's LAN address and whose
    browser then posts from that same origin. Anything else -- a page on
    ``evil.example`` -- is refused, because otherwise that page could drive the
    NPU and, through ``kb_add_document``, read files out of the agents'
    workspaces.
    """
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:  # pragma: no cover - urlsplit is very permissive
        return False
    if parts.scheme not in ("http", "https"):
        # ``file://``, ``null`` (a sandboxed frame) and anything else opaque.
        return False
    hostname = (parts.hostname or "").lower()
    if hostname in LOOPBACK_HOSTS:
        return True
    declared = {
        item.strip().rstrip("/")
        for item in (os.environ.get(ORIGINS_ENV) or "").split(";")
        if item.strip()
    }
    if origin.rstrip("/") in declared:
        return True
    if host_header:
        # Same-origin in the browser's sense: the Origin's host:port is the Host
        # the request was addressed to.
        served = host_header.strip().lower()
        if parts.netloc.lower() == served:
            return True
    return False


@router.post("/mcp")
async def mcp_endpoint(request: Request, key_id: str = Depends(require_api_key)):
    """The whole MCP surface: one POST, one JSON object, no session."""
    # Before the body: a cross-origin page must not even get its JSON parsed,
    # and this check has to hold when ``require_api_key`` is off (the default on
    # a trusted deployment), where it is the *only* thing between a browser and
    # the board.
    if not _origin_allowed(request.headers.get("origin"), request.headers.get("host")):
        logger.warning("MCP request refused: Origin %r is not this service",
                       request.headers.get("origin"))
        return JSONResponse(
            _error(None, INVALID_REQUEST,
                   "跨源请求被拒绝：/mcp 只接受本机或同源请求"),
            status_code=403)

    raw = await request.body()
    if not raw.strip():
        return JSONResponse(_error(None, INVALID_REQUEST, "请求体为空"), status_code=400)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        # The decoder's own message quotes the offending document, which for a
        # large body is a log of somebody's request in an error string. The
        # position is the useful part and is not a path or a type name.
        return JSONResponse(_error(None, PARSE_ERROR, "JSON 解析失败：请求体不是合法 JSON"),
                            status_code=400)

    request.state.mcp_key_id = key_id or None
    name = _key_name(request, key_id)

    # A batch was in 2025-03-26 and removed in 2025-06-18. The card asks for
    # -32600 or spec-compliant handling; -32600 is the honest answer for the
    # version this endpoint speaks, and the message says so rather than leaving
    # a client to guess why an array was rejected.
    if isinstance(payload, list):
        if not payload:
            return JSONResponse(_error(None, INVALID_REQUEST, "空的批量请求"),
                                status_code=400)
        return JSONResponse(
            _error(None, INVALID_REQUEST,
                   f"MCP {PROTOCOL_VERSION} 已取消批量请求，请一次发送一个 JSON-RPC 对象"),
            status_code=400)

    try:
        response = await _dispatch(request, payload, name)
    except RpcError as exc:
        # A notification (a method, no id) and a client response (an id, no
        # method) both have no reply of their own, so 202 is the answer even when
        # the message was wrong. Anything else is a request, and a malformed
        # request gets its error back.
        if _has_no_reply(payload):
            return Response(status_code=202)
        return JSONResponse(_error(payload.get("id") if isinstance(payload, dict) else None,
                                   exc.code, exc.message, exc.data),
                            status_code=200)
    except Exception:  # noqa: BLE001 - a protocol layer must not 500 silently
        # The traceback goes to the log, where the operator can act on it. The
        # client gets a code and a sentence: an exception class and its message
        # leak this box's internals into a chat transcript.
        logger.exception("MCP request failed")
        return JSONResponse(
            _error(payload.get("id") if isinstance(payload, dict) else None,
                   INTERNAL_ERROR, "服务内部错误，详情见服务日志"),
            status_code=200)

    if response is None:
        # A notification or a client response: accepted, nothing to say.
        return Response(status_code=202)
    return JSONResponse(response, status_code=200)


@router.get("/mcp")
async def mcp_no_stream():
    """No server-initiated SSE stream: this endpoint is stateless.

    The spec allows a server that offers no stream to answer 405. Clients that
    open one anyway treat the refusal as "there is none" -- measured with
    opencode 1.19.4 and OpenClaw 2026.10.7, which both proceed to ``tools/list``
    over POST after their GET is refused.
    """
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def mcp_no_session():
    """No session to delete; the spec's answer when sessions are not used."""
    return Response(status_code=405, headers={"Allow": "POST"})
